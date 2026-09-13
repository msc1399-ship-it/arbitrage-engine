from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import load_dotenv

from collectors.ebay import EbayClient
from services.http import ConnectorError, request_with_backoff

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
PUBLIC_KEY_CACHE_SECONDS = 3600


@dataclass(frozen=True)
class AccountDeletionSettings:
    endpoint: str
    verification_token: str

    @classmethod
    def from_environment(cls):
        load_dotenv()
        return cls(
            endpoint=os.getenv("EBAY_ACCOUNT_DELETION_ENDPOINT", ""),
            verification_token=os.getenv("EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN", ""),
        ).validated()

    def validated(self):
        if not TOKEN_PATTERN.fullmatch(self.verification_token):
            raise ValueError(
                "EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN must contain 32-80 "
                "letters, digits, underscores, or hyphens"
            )
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("EBAY_ACCOUNT_DELETION_ENDPOINT must be a public HTTPS URL")
        if parsed.hostname.casefold() == "localhost":
            raise ValueError("EBAY_ACCOUNT_DELETION_ENDPOINT cannot use localhost")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError("EBAY_ACCOUNT_DELETION_ENDPOINT must use a public host")
        return self


def challenge_response(challenge_code: str, settings: AccountDeletionSettings) -> str:
    value = challenge_code + settings.verification_token + settings.endpoint
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignatureVerification:
    status: str
    valid: bool | None


class EbayNotificationSignatureVerifier:
    def __init__(self, ebay_client=None, *, cache_seconds=PUBLIC_KEY_CACHE_SECONDS):
        self.ebay_client = ebay_client
        self.cache_seconds = cache_seconds
        self._public_keys = {}

    @classmethod
    def from_environment(cls):
        try:
            client = EbayClient()
        except ConnectorError:
            client = None
        return cls(client)

    def _get_public_key(self, key_id):
        cached = self._public_keys.get(key_id)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        if self.ebay_client is None:
            raise ConnectorError("eBay credentials are not configured for public-key retrieval")

        host = (
            "api.sandbox.ebay.com"
            if self.ebay_client.environment == "sandbox"
            else "api.ebay.com"
        )
        token = self.ebay_client.get_application_token()
        response = request_with_backoff(
            "GET",
            f"https://{host}/commerce/notification/v1/public_key/{quote(key_id, safe='')}",
            session=self.ebay_client.session,
            headers={"Authorization": f"Bearer {token}"},
            max_retries=self.ebay_client.max_retries,
            sleep=self.ebay_client.sleep,
        )
        public_key = response.json().get("key")
        if not public_key:
            raise ConnectorError("eBay public-key response did not contain a key")
        self._public_keys[key_id] = (public_key, time.monotonic() + self.cache_seconds)
        return public_key

    def verify(self, payload, signature_header):
        if not signature_header:
            return SignatureVerification("MISSING", False)
        try:
            header = json.loads(base64.b64decode(signature_header, validate=True))
            key_id = header["kid"]
            signature = base64.b64decode(header["signature"], validate=True)
            public_key_pem = self._get_public_key(key_id)
            public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            message = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA1()))
        except (InvalidSignature, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return SignatureVerification("INVALID", False)
        except ConnectorError:
            return SignatureVerification("PENDING_IMPLEMENTATION", None)
        return SignatureVerification("VERIFIED", True)
