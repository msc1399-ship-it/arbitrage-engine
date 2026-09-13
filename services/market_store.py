from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from services.ebay_data_deletion import sanitize_ebay_data_for_storage

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "market_history.sqlite3"


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Unsupported value: {type(value).__name__}")


def _json(value):
    return json.dumps(value, default=_json_default, ensure_ascii=True, separators=(",", ":"))


class MarketStore:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS market_refresh_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    set_num TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    market_status TEXT NOT NULL,
                    bricklink_data TEXT,
                    ebay_data TEXT,
                    derived_metrics TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_market_history_set
                    ON market_refresh_history(set_num, id DESC);
                CREATE TABLE IF NOT EXISTS market_refresh_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    checkpoint_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS market_refresh_run_items (
                    run_id TEXT NOT NULL,
                    set_num TEXT NOT NULL,
                    market_status TEXT NOT NULL DEFAULT 'PENDING',
                    processed_at TEXT,
                    error_message TEXT,
                    PRIMARY KEY (run_id, set_num)
                );
                CREATE TABLE IF NOT EXISTS ebay_market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    set_num TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    marketplace TEXT NOT NULL DEFAULT 'EBAY',
                    condition TEXT NOT NULL DEFAULT 'MIXED',
                    full_set_count INTEGER,
                    retrieval_yield REAL,
                    uncertain_rate REAL,
                    price_stability TEXT,
                    quality_status TEXT NOT NULL,
                    usable_for_radar INTEGER NOT NULL,
                    new_count INTEGER,
                    new_min REAL,
                    new_p25 REAL,
                    new_median REAL,
                    new_p75 REAL,
                    new_max REAL,
                    used_count INTEGER,
                    used_min REAL,
                    used_p25 REAL,
                    used_median REAL,
                    used_p75 REAL,
                    used_max REAL,
                    api_calls INTEGER NOT NULL,
                    diagnostic TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ebay_snapshot_set
                    ON ebay_market_snapshots(set_num, id DESC);
            """)

    def start_run(self, run_id, set_nums, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO market_refresh_runs(run_id, created_at) VALUES (?, ?)",
                (run_id, timestamp),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO market_refresh_run_items(run_id, set_num) VALUES (?, ?)",
                [(run_id, set_num) for set_num in set_nums],
            )

    def processed_sets(self, run_id):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT set_num FROM market_refresh_run_items WHERE run_id=? AND processed_at IS NOT NULL",
                (run_id,),
            ).fetchall()
        return {row["set_num"] for row in rows}

    def save_result(self, run_id, result):
        aggregate = result.aggregate
        metrics = aggregate.derived_metrics
        confidence = {
            "confidence_score": metrics.confidence_score,
            "confidence_label": metrics.confidence_label,
            "confidence_reasons": metrics.confidence_reasons,
            "confidence_factors": metrics.confidence_factors,
        }
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO market_refresh_history(
                       run_id,set_num,timestamp,market_status,bricklink_data,ebay_data,
                       derived_metrics,confidence,decision,error_message
                   ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (run_id, result.set_num, result.timestamp, result.market_status,
                 _json(aggregate.bricklink_data) if aggregate.bricklink_data else None,
                 _json(sanitize_ebay_data_for_storage(asdict(aggregate.ebay_data)))
                 if aggregate.ebay_data else None,
                 _json(metrics), _json(confidence), metrics.decision,
                 result.error_message),
            )
            connection.execute(
                """UPDATE market_refresh_run_items
                   SET market_status=?, processed_at=?, error_message=?
                   WHERE run_id=? AND set_num=?""",
                (result.market_status, result.timestamp, result.error_message,
                 run_id, result.set_num),
            )

    def checkpoint(self, run_id, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE market_refresh_runs SET checkpoint_at=? WHERE run_id=?",
                (timestamp, run_id),
            )

    def save_ebay_snapshot(self, run_id, snapshot, *, usable_for_radar, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        price_fields = (
            "new_count", "new_min", "new_p25", "new_median", "new_p75", "new_max",
            "used_count", "used_min", "used_p25", "used_median", "used_p75", "used_max",
        )
        prices = {
            field: snapshot.get(field) if usable_for_radar else None
            for field in price_fields
        }
        diagnostic = {
            "full_set_count": snapshot.get("full_set_count"),
            "retrieval_yield": snapshot.get("retrieval_yield"),
            "uncertain_rate": snapshot.get("uncertain_rate"),
            "price_stability": snapshot.get("price_stability"),
        }
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO ebay_market_snapshots(
                       run_id,set_num,timestamp,marketplace,condition,full_set_count,
                       retrieval_yield,uncertain_rate,price_stability,quality_status,
                       usable_for_radar,new_count,new_min,new_p25,new_median,new_p75,new_max,
                       used_count,used_min,used_p25,used_median,used_p75,used_max,
                       api_calls,diagnostic
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, snapshot["set_num"], timestamp, "EBAY", "MIXED",
                 snapshot.get("full_set_count"), snapshot.get("retrieval_yield"),
                 snapshot.get("uncertain_rate"), snapshot.get("price_stability"),
                 snapshot["status"], int(usable_for_radar),
                 *(prices[field] for field in price_fields),
                 snapshot.get("api_calls", 0), _json(diagnostic)),
            )
            connection.execute(
                """UPDATE market_refresh_run_items
                   SET market_status=?, processed_at=?, error_message=NULL
                   WHERE run_id=? AND set_num=?""",
                (snapshot["status"], timestamp, run_id, snapshot["set_num"]),
            )

    def mark_run_error(self, run_id, set_num, error_type, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """UPDATE market_refresh_run_items
                   SET market_status='ERROR', processed_at=?, error_message=?
                   WHERE run_id=? AND set_num=?""",
                (timestamp, error_type, run_id, set_num),
            )

    def finish_run(self, run_id, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE market_refresh_runs SET checkpoint_at=?, completed_at=? WHERE run_id=?",
                (timestamp, timestamp, run_id),
            )

    def latest_records(self):
        with self._connection() as connection:
            rows = connection.execute("""
                SELECT h.* FROM market_refresh_history h
                JOIN (SELECT set_num, MAX(id) id FROM market_refresh_history GROUP BY set_num) latest
                  ON h.id=latest.id
                ORDER BY h.set_num
            """).fetchall()
        return [dict(row) for row in rows]

    def history_for_set(self, set_num):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM market_refresh_history WHERE set_num=? ORDER BY id",
                (set_num,),
            ).fetchall()
        return [dict(row) for row in rows]

    def ebay_history_for_set(self, set_num):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM ebay_market_snapshots WHERE set_num=? ORDER BY id",
                (set_num,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_ebay_snapshots(self):
        with self._connection() as connection:
            rows = connection.execute("""
                SELECT s.* FROM ebay_market_snapshots s
                JOIN (SELECT set_num, MAX(id) id FROM ebay_market_snapshots GROUP BY set_num) latest
                  ON s.id=latest.id
                ORDER BY s.set_num
            """).fetchall()
        return [dict(row) for row in rows]

    def latest_radar_rows(self):
        output = []
        for record in self.latest_records():
            bricklink = json.loads(record["bricklink_data"]) if record["bricklink_data"] else {}
            ebay = json.loads(record["ebay_data"]) if record["ebay_data"] else {}
            metrics = json.loads(record["derived_metrics"])
            confidence = json.loads(record["confidence"])
            monthly = metrics.get("monthly_sales")
            days = metrics.get("expected_days_to_sell")
            profit = metrics.get("expected_profit")
            output.append({
                "set_num": record["set_num"],
                "market_value": bricklink.get("sold_price_median"),
                "conservative_value": metrics.get("conservative_value"),
                "max_buy_price": metrics.get("max_buy_price"),
                "current_listing_price": ebay.get("asking_price_min"),
                "expected_profit": profit,
                "expected_roi": metrics.get("expected_roi"),
                "sales_6m": bricklink.get("sales_6m"),
                "monthly_sales": monthly,
                "expected_days_to_sell": days,
                "active_listings": ebay.get("active_listing_count"),
                "confidence": confidence.get("confidence_score"),
                "confidence_score": confidence.get("confidence_score"),
                "confidence_label": confidence.get("confidence_label"),
                "confidence_reasons": confidence.get("confidence_reasons"),
                "confidence_factors": confidence.get("confidence_factors"),
                "capital_efficiency": metrics.get("capital_efficiency"),
                "profit_per_30_days": profit * 30 / days if profit is not None and days else None,
                "score": metrics.get("score"),
                "decision": metrics.get("decision", "PENDING MARKET DATA"),
                "market_status": record["market_status"],
                "last_market_refresh": record["timestamp"],
                "error_message": record["error_message"],
            })
        by_set = {row["set_num"]: row for row in output}
        badges = {
            "GOOD_EBAY_DATA": "GOOD", "PARTIAL_EBAY_DATA": "PARTIAL",
            "REVIEW_REQUIRED": "REVIEW", "INSUFFICIENT_EBAY_DATA": "INSUFFICIENT",
        }
        for snapshot in self.latest_ebay_snapshots():
            row = by_set.setdefault(snapshot["set_num"], {
                "set_num": snapshot["set_num"], "decision": "PENDING MARKET DATA",
            })
            usable = bool(snapshot["usable_for_radar"])
            row.update({
                "ebay_status": badges.get(snapshot["quality_status"], snapshot["quality_status"]),
                "ebay_full_set_count": snapshot["full_set_count"],
                "ebay_new_p25": snapshot["new_p25"] if usable else None,
                "ebay_new_median": snapshot["new_median"] if usable else None,
                "ebay_used_p25": snapshot["used_p25"] if usable else None,
                "ebay_used_median": snapshot["used_median"] if usable else None,
                "ebay_asking_reference_new": snapshot["new_p25"] if usable else None,
                "ebay_asking_reference_used": snapshot["used_p25"] if usable else None,
                "ebay_retrieval_yield": snapshot["retrieval_yield"],
                "ebay_uncertain_rate": snapshot["uncertain_rate"],
                "ebay_price_stability": snapshot["price_stability"],
                "ebay_last_refresh": snapshot["timestamp"],
            })
        return list(by_set.values())

    def status_summary(self):
        records = self.latest_records()
        counts = {"OK": 0, "PARTIAL": 0, "PENDING": 0, "ERROR": 0}
        for record in records:
            counts[record["market_status"]] = counts.get(record["market_status"], 0) + 1
        return {
            "last_refresh": max((record["timestamp"] for record in records), default=None),
            "updated": counts["OK"] + counts["PARTIAL"],
            "pending": counts["PENDING"],
            "errors": counts["ERROR"],
        }

    def ebay_status_summary(self):
        records = self.latest_ebay_snapshots()
        counts = {
            "GOOD_EBAY_DATA": 0, "PARTIAL_EBAY_DATA": 0,
            "REVIEW_REQUIRED": 0, "INSUFFICIENT_EBAY_DATA": 0,
        }
        for record in records:
            status = record["quality_status"]
            counts[status] = counts.get(status, 0) + 1
        return {
            "last_refresh": max((record["timestamp"] for record in records), default=None),
            "good": counts["GOOD_EBAY_DATA"],
            "partial": counts["PARTIAL_EBAY_DATA"],
            "review": counts["REVIEW_REQUIRED"],
            "insufficient": counts["INSUFFICIENT_EBAY_DATA"],
        }
