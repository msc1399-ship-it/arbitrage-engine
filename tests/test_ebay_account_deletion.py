import base64
import hashlib
import json
import logging
import sqlite3

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from notification_server.app import create_app
from notification_server.ebay_account_deletion import (
    AccountDeletionSettings,
    EbayNotificationSignatureVerifier,
    SignatureVerification,
    challenge_response,
)
from services.ebay_data_deletion import (
    process_account_deletion,
    sanitize_ebay_data_for_storage,
)

ENDPOINT = "https://notifications.example.com/ebay/account-deletion"
TOKEN = "account_deletion_verification_token_12345"


def notification(notification_id="notification-1", username="private-seller"):
    return {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
        "notification": {
            "notificationId": notification_id,
            "eventDate": "2026-09-13T10:00:00Z",
            "publishDate": "2026-09-13T10:01:00Z",
            "data": {
                "userId": "private-user-id",
                "username": username,
                "eiasToken": "private-eias-token",
            },
        },
    }


class VerifiedSignature:
    def verify(self, payload, signature_header):
        return SignatureVerification("VERIFIED", True)


class PendingSignature:
    def verify(self, payload, signature_header):
        return SignatureVerification("PENDING_IMPLEMENTATION", None)


def client(tmp_path, **kwargs):
    settings = AccountDeletionSettings(ENDPOINT, TOKEN)
    app = create_app(
        settings=settings,
        database_path=tmp_path / "deletion.sqlite3",
        signature_verifier=kwargs.pop("signature_verifier", VerifiedSignature()),
        **kwargs,
    )
    return TestClient(app)


def test_challenge_uses_required_concatenation_order(tmp_path):
    challenge = "challenge-abc"
    expected = hashlib.sha256((challenge + TOKEN + ENDPOINT).encode()).hexdigest()
    with client(tmp_path) as test_client:
        response = test_client.get(
            "/ebay/account-deletion", params={"challenge_code": challenge}
        )
    assert response.status_code == 200
    assert response.json() == {"challengeResponse": expected}


def test_challenge_wrong_order_does_not_match():
    settings = AccountDeletionSettings(ENDPOINT, TOKEN)
    wrong = hashlib.sha256((TOKEN + "abc" + ENDPOINT).encode()).hexdigest()
    assert challenge_response("abc", settings) != wrong


def test_missing_challenge_returns_400(tmp_path):
    with client(tmp_path) as test_client:
        response = test_client.get("/ebay/account-deletion")
    assert response.status_code == 400


def test_challenge_is_json_without_bom(tmp_path):
    with client(tmp_path) as test_client:
        response = test_client.get(
            "/ebay/account-deletion", params={"challenge_code": "abc"}
        )
    assert response.headers["content-type"].startswith("application/json")
    assert not response.content.startswith(b"\xef\xbb\xbf")


def test_valid_notification_is_processed_and_audited(tmp_path):
    calls = []

    def processor(payload, database_path):
        calls.append(payload)
        return "NO_MATCH"

    with client(tmp_path, deletion_processor=processor) as test_client:
        response = test_client.post(
            "/ebay/account-deletion",
            json=notification(),
            headers={"X-EBAY-SIGNATURE": "verified-by-test-double"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"
    assert len(calls) == 1
    connection = sqlite3.connect(tmp_path / "deletion.sqlite3")
    try:
        row = connection.execute(
            "SELECT notification_id, processed_at, result "
            "FROM ebay_account_deletion_notifications"
        ).fetchone()
    finally:
        connection.close()
    assert row[0] == "notification-1"
    assert row[1]
    assert row[2] == "NO_MATCH"


def test_duplicate_notification_is_idempotent(tmp_path):
    calls = []

    def processor(payload, database_path):
        calls.append(payload)
        return "NO_MATCH"

    with client(tmp_path, deletion_processor=processor) as test_client:
        first = test_client.post("/ebay/account-deletion", json=notification())
        second = test_client.post("/ebay/account-deletion", json=notification())
    assert first.status_code == second.status_code == 200
    assert second.json()["duplicate"] is True
    assert len(calls) == 1


def test_missing_signature_is_rejected(tmp_path):
    verifier = EbayNotificationSignatureVerifier()
    with client(tmp_path, signature_verifier=verifier) as test_client:
        response = test_client.post("/ebay/account-deletion", json=notification())
    assert response.status_code == 412
    assert response.json()["signature_status"] == "MISSING"


def test_unavailable_signature_verification_is_explicit(tmp_path):
    with client(tmp_path, signature_verifier=PendingSignature()) as test_client:
        response = test_client.post("/ebay/account-deletion", json=notification())
    assert response.status_code == 503
    assert response.json()["signature_status"] == "PENDING_IMPLEMENTATION"


def test_official_signature_shape_verifies_with_ecc_key():
    payload = notification()
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA1()))
    encoded_header = base64.b64encode(json.dumps({
        "kid": "test-key",
        "signature": base64.b64encode(signature).decode(),
    }).encode()).decode()
    verifier = EbayNotificationSignatureVerifier()
    verifier._public_keys["test-key"] = (public_pem, float("inf"))
    result = verifier.verify(payload, encoded_header)
    assert result == SignatureVerification("VERIFIED", True)


def test_account_identifiers_are_not_logged(tmp_path, caplog):
    payload = notification()
    with caplog.at_level(logging.INFO):
        result = process_account_deletion(payload, tmp_path / "empty.sqlite3")
    assert result == "NO_MATCH"
    assert "private-user-id" not in caplog.text
    assert "private-seller" not in caplog.text
    assert "private-eias-token" not in caplog.text
    assert "notification-1" in caplog.text


def test_secrets_from_processing_errors_are_not_logged(tmp_path, caplog):
    secret = "oauth-or-client-secret-must-not-leak"

    def failing_processor(payload, database_path):
        raise RuntimeError(secret)

    with caplog.at_level(logging.ERROR):
        with client(tmp_path, deletion_processor=failing_processor) as test_client:
            response = test_client.post("/ebay/account-deletion", json=notification())
    assert response.status_code == 500
    assert secret not in caplog.text
    assert TOKEN not in caplog.text
    assert "private-seller" not in caplog.text


@pytest.mark.parametrize("invalid_token", ["too-short", "x" * 81, "x" * 31 + "!"])
def test_invalid_verification_token_is_rejected_at_startup(tmp_path, invalid_token):
    app = create_app(
        settings=AccountDeletionSettings(ENDPOINT, invalid_token),
        database_path=tmp_path / "invalid.sqlite3",
        signature_verifier=VerifiedSignature(),
    )
    with pytest.raises(ValueError), TestClient(app):
        pass


def test_matching_pii_is_deleted_but_aggregate_data_is_retained(tmp_path):
    database = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE market_refresh_history "
            "(id INTEGER PRIMARY KEY, ebay_data TEXT)"
        )
        connection.execute(
            "INSERT INTO market_refresh_history VALUES (?, ?)",
            (1, json.dumps({
                "active_listing_count": 3,
                "asking_price_median": 125.0,
                "raw_data": {"items": [{
                    "title": "LEGO set",
                    "seller": {"username": "private-seller"},
                }]},
            })),
        )
        connection.commit()
    finally:
        connection.close()
    result = process_account_deletion(notification(), database)
    connection = sqlite3.connect(database)
    try:
        stored = json.loads(connection.execute(
            "SELECT ebay_data FROM market_refresh_history WHERE id=1"
        ).fetchone()[0])
    finally:
        connection.close()
    assert result == "DELETED"
    assert stored["active_listing_count"] == 3
    assert stored["asking_price_median"] == 125.0
    assert "seller" not in stored["raw_data"]["items"][0]


def test_new_ebay_data_is_sanitized_before_storage():
    source = {
        "active_listing_count": 2,
        "raw_data": {"items": [{
            "seller": {"username": "private-seller"},
            "userId": "private-user-id",
            "price": {"value": "120.00", "currency": "EUR"},
        }]},
    }
    sanitized = sanitize_ebay_data_for_storage(source)
    serialized = json.dumps(sanitized)
    assert sanitized["active_listing_count"] == 2
    assert "private-seller" not in serialized
    assert "private-user-id" not in serialized


def test_health_contains_no_sensitive_configuration(tmp_path):
    with client(tmp_path) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert TOKEN not in response.text
