from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
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
from services.http import ConnectorAuthenticationError, ConnectorError, request_with_backoff

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
PUBLIC_KEY_CACHE_SECONDS = 3600
PRODUCTION_PUBLIC_KEY_URL = "https://api.ebay.com/commerce/notification/v1/public_key"
SANDBOX_PUBLIC_KEY_URL = "https://api.sandbox.ebay.com/commerce/notification/v1/public_key"
LOGGER = logging.getLogger(__name__)


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
    reason: str | None = None


class SignatureDependencyError(RuntimeError):
    def __init__(self, reason, *, http_status=None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


class EbayNotificationSignatureVerifier:
    def __init__(self, ebay_client=None, *, cache_seconds=PUBLIC_KEY_CACHE_SECONDS,
                 unavailable_reason=None):
        self.ebay_client = ebay_client
        self.cache_seconds = cache_seconds
        self.unavailable_reason = unavailable_reason
        self._public_keys = {}

    @classmethod
    def from_environment(cls, *, required_environment=None):
        load_dotenv()
        environment = (os.getenv("EBAY_ENVIRONMENT") or "").lower()
        missing = [
            name for name in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET")
            if not os.getenv(name)
        ]
        if missing:
            LOGGER.error(
                "ebay_signature_configuration result=unavailable "
                "reason=credentials_missing missing_variables=%s",
                ",".join(missing),
            )
            return cls(unavailable_reason="CREDENTIALS_MISSING")
        if environment not in {"sandbox", "production"}:
            LOGGER.error(
                "ebay_signature_configuration result=unavailable "
                "reason=environment_invalid configured_environment=%s",
                environment or "missing",
            )
            return cls(unavailable_reason="ENVIRONMENT_INVALID")
        if required_environment and environment != required_environment:
            LOGGER.error(
                "ebay_signature_configuration result=unavailable "
                "reason=environment_incorrect configured_environment=%s "
                "required_environment=%s",
                environment,
                required_environment,
            )
            return cls(unavailable_reason="ENVIRONMENT_INCORRECT")
        try:
            client = EbayClient()
        except ConnectorError:
            LOGGER.error(
                "ebay_signature_configuration result=unavailable "
                "reason=client_initialization_failed"
            )
            return cls(unavailable_reason="CLIENT_INITIALIZATION_FAILED")
        LOGGER.info(
            "ebay_signature_configuration result=ready environment=%s",
            client.environment,
        )
        return cls(client)

    @staticmethod
    def _key_fingerprint(key_id):
        return hashlib.sha256(key_id.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _format_public_key(public_key):
        value = public_key.strip()
        value = value.replace("-----BEGIN PUBLIC KEY-----", "-----BEGIN PUBLIC KEY-----\n", 1)
        value = value.replace("-----END PUBLIC KEY-----", "\n-----END PUBLIC KEY-----", 1)
        return value.replace("\n\n", "\n") + "\n"

    def _get_public_key(self, key_id):
        cached = self._public_keys.get(key_id)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        if self.ebay_client is None:
            raise SignatureDependencyError(
                self.unavailable_reason or "CREDENTIALS_MISSING"
            )

        base_url = (
            SANDBOX_PUBLIC_KEY_URL
            if self.ebay_client.environment == "sandbox"
            else PRODUCTION_PUBLIC_KEY_URL
        )
        fingerprint = self._key_fingerprint(key_id)
        try:
            token = self.ebay_client.get_application_token()
        except ConnectorAuthenticationError as error:
            LOGGER.error(
                "ebay_signature_oauth result=error environment=%s http_status=%s",
                self.ebay_client.environment,
                error.status_code or "unknown",
            )
            raise SignatureDependencyError(
                "OAUTH_FAILED", http_status=error.status_code
            ) from error
        except ConnectorError as error:
            LOGGER.error(
                "ebay_signature_oauth result=error environment=%s http_status=%s",
                self.ebay_client.environment,
                error.status_code or "unknown",
            )
            raise SignatureDependencyError(
                "OAUTH_FAILED", http_status=error.status_code
            ) from error
        LOGGER.info(
            "ebay_signature_oauth result=ok environment=%s",
            self.ebay_client.environment,
        )
        try:
            response = request_with_backoff(
                "GET",
                f"{base_url}/{quote(key_id, safe='')}",
                session=self.ebay_client.session,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                max_retries=self.ebay_client.max_retries,
                sleep=self.ebay_client.sleep,
            )
        except ConnectorError as error:
            reason = "PUBLIC_KEY_NOT_FOUND" if error.status_code == 404 else "PUBLIC_KEY_API_FAILED"
            LOGGER.error(
                "ebay_signature_public_key result=error environment=%s "
                "http_status=%s reason=%s key_id_fingerprint=%s",
                self.ebay_client.environment,
                error.status_code or "unknown",
                reason.lower(),
                fingerprint,
            )
            raise SignatureDependencyError(
                reason, http_status=error.status_code
            ) from error
        try:
            public_key = response.json().get("key")
        except (ValueError, AttributeError) as error:
            LOGGER.error(
                "ebay_signature_public_key result=error environment=%s "
                "http_status=%s reason=response_json_invalid key_id_fingerprint=%s",
                self.ebay_client.environment,
                response.status_code,
                fingerprint,
            )
            raise SignatureDependencyError(
                "PUBLIC_KEY_RESPONSE_INVALID", http_status=response.status_code
            ) from error
        if not isinstance(public_key, str) or not public_key:
            LOGGER.error(
                "ebay_signature_public_key result=error environment=%s "
                "http_status=%s reason=key_missing key_id_fingerprint=%s",
                self.ebay_client.environment,
                response.status_code,
                fingerprint,
            )
            raise SignatureDependencyError(
                "PUBLIC_KEY_MISSING", http_status=response.status_code
            )
        formatted_key = self._format_public_key(public_key)
        self._public_keys[key_id] = (formatted_key, time.monotonic() + self.cache_seconds)
        LOGGER.info(
            "ebay_signature_public_key result=ok environment=%s "
            "http_status=%s key_id_fingerprint=%s",
            self.ebay_client.environment,
            response.status_code,
            fingerprint,
        )
        return formatted_key

    def verify(self, payload, signature_header):
        if not signature_header:
            LOGGER.warning("ebay_signature_header result=invalid reason=missing")
            return SignatureVerification("MISSING", False, "SIGNATURE_MISSING")
        try:
            header = json.loads(base64.b64decode(signature_header, validate=True))
            key_id = header["kid"]
            encoded_signature = header["signature"]
            if not isinstance(key_id, str) or not key_id or not isinstance(encoded_signature, str):
                raise ValueError("Invalid signature header fields")
            signature = base64.b64decode(encoded_signature, validate=True)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.warning("ebay_signature_header result=invalid reason=parse_failed")
            return SignatureVerification("INVALID", False, "HEADER_PARSE_FAILED")
        try:
            public_key_pem = self._get_public_key(key_id)
            public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            message = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA1()))
        except SignatureDependencyError as error:
            return SignatureVerification("PENDING_IMPLEMENTATION", None, error.reason)
        except InvalidSignature:
            LOGGER.warning(
                "ebay_signature_crypto result=invalid key_id_fingerprint=%s",
                self._key_fingerprint(key_id),
            )
            return SignatureVerification("INVALID", False, "CRYPTOGRAPHIC_MISMATCH")
        except (TypeError, ValueError):
            LOGGER.error(
                "ebay_signature_crypto result=error reason=public_key_or_algorithm_invalid "
                "key_id_fingerprint=%s",
                self._key_fingerprint(key_id),
            )
            return SignatureVerification(
                "PENDING_IMPLEMENTATION", None, "CRYPTOGRAPHIC_ERROR"
            )
        LOGGER.info(
            "ebay_signature_crypto result=verified key_id_fingerprint=%s",
            self._key_fingerprint(key_id),
        )
        return SignatureVerification("VERIFIED", True)
