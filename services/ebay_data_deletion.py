from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "market_history.sqlite3"
PERSONAL_KEYS = {"userid", "username", "eiastoken"}


def extract_account_deletion(notification):
    metadata = notification.get("metadata") or {}
    envelope = notification.get("notification") or notification
    data = envelope.get("data") or envelope
    return {
        "topic": metadata.get("topic") or notification.get("topic"),
        "notificationId": envelope.get("notificationId") or notification.get("notificationId"),
        "eventDate": envelope.get("eventDate") or notification.get("eventDate"),
        "publishDate": envelope.get("publishDate") or notification.get("publishDate"),
        "userId": data.get("userId"),
        "username": data.get("username"),
        "eiasToken": data.get("eiasToken"),
    }


def sanitize_ebay_data_for_storage(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            normalized = key.casefold().replace("_", "")
            if normalized in PERSONAL_KEYS or normalized == "seller":
                continue
            sanitized[key] = sanitize_ebay_data_for_storage(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_ebay_data_for_storage(child) for child in value]
    return value


def _contains_identifier(value, identifiers):
    if isinstance(value, dict):
        return any(_contains_identifier(child, identifiers) for child in value.values())
    if isinstance(value, list):
        return any(_contains_identifier(child, identifiers) for child in value)
    return value is not None and str(value) in identifiers


def _remove_matching_personal_data(value, identifiers):
    removed = 0
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            normalized = key.casefold().replace("_", "")
            if normalized == "seller" and _contains_identifier(child, identifiers):
                removed += 1
                continue
            if normalized in PERSONAL_KEYS and _contains_identifier(child, identifiers):
                removed += 1
                continue
            clean_child, child_removed = _remove_matching_personal_data(child, identifiers)
            removed += child_removed
            cleaned[key] = clean_child
        return cleaned, removed
    if isinstance(value, list):
        cleaned = []
        for child in value:
            clean_child, child_removed = _remove_matching_personal_data(child, identifiers)
            removed += child_removed
            cleaned.append(clean_child)
        return cleaned, removed
    return value, 0


class EbayDeletionStore:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ebay_account_deletion_notifications (
                    notification_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    processed_at TEXT,
                    result TEXT NOT NULL
                )
            """)

    def claim(self, notification_id, received_at):
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO ebay_account_deletion_notifications(
                       notification_id, received_at, result)
                   VALUES (?, ?, 'RECEIVED')""",
                (notification_id, received_at),
            )
            if cursor.rowcount == 1:
                return True
            row = connection.execute(
                "SELECT result FROM ebay_account_deletion_notifications WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
            if row and row["result"] == "ERROR":
                connection.execute(
                    """UPDATE ebay_account_deletion_notifications
                       SET received_at=?, processed_at=NULL, result='RECEIVED'
                       WHERE notification_id=?""",
                    (received_at, notification_id),
                )
                return True
            return False

    def complete(self, notification_id, result, processed_at=None):
        processed_at = processed_at or datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """UPDATE ebay_account_deletion_notifications
                   SET processed_at=?, result=? WHERE notification_id=?""",
                (processed_at, result, notification_id),
            )

    def get(self, notification_id):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM ebay_account_deletion_notifications WHERE notification_id=?",
                (notification_id,),
            ).fetchone()
        return dict(row) if row else None


def process_account_deletion(notification, database_path=DEFAULT_DB_PATH):
    fields = extract_account_deletion(notification)
    identifiers = {str(fields[key]) for key in ("userId", "username", "eiasToken")
                   if fields.get(key)}
    removed = 0
    path = Path(database_path)
    if identifiers and path.exists():
        connection = sqlite3.connect(path, timeout=30)
        try:
            with connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_refresh_history'"
                ).fetchone()
                if table:
                    rows = connection.execute(
                        "SELECT id, ebay_data FROM market_refresh_history WHERE ebay_data IS NOT NULL"
                    ).fetchall()
                    for row_id, raw in rows:
                        try:
                            payload = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        cleaned, count = _remove_matching_personal_data(payload, identifiers)
                        if count:
                            connection.execute(
                                "UPDATE market_refresh_history SET ebay_data=? WHERE id=?",
                                (json.dumps(cleaned, ensure_ascii=True, separators=(",", ":")), row_id),
                            )
                            removed += count
        finally:
            connection.close()
    result = "DELETED" if removed else "NO_MATCH"
    timestamp = datetime.now(timezone.utc).isoformat()
    LOGGER.info("ebay_account_deletion notification_id=%s timestamp=%s deletion_result=%s",
                fields.get("notificationId"), timestamp, result)
    return result
