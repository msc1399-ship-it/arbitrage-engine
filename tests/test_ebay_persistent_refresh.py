import json

import pytest

from services.ebay_quality_gate import evaluate_ebay_quality
from services.ebay_refresh import EbayRefreshPipeline
from services.market_store import MarketStore


def summary(set_num="TEST-1", status="GOOD_EBAY_DATA", **overrides):
    values = {
        "set_num": set_num,
        "status": status,
        "full_set_count": 40,
        "retrieval_yield": 0.5,
        "uncertain_rate": 0.05,
        "price_stability": "STABLE",
        "new_count": 20,
        "new_min": 80.0,
        "new_p25": 90.0,
        "new_median": 100.0,
        "new_p75": 110.0,
        "new_max": 120.0,
        "used_count": 20,
        "used_min": 40.0,
        "used_p25": 50.0,
        "used_median": 60.0,
        "used_p75": 70.0,
        "used_max": 80.0,
        "api_calls": 2,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("full,uncertain,stability,status,persisted", [
    (40, 0.05, "STABLE", "GOOD_EBAY_DATA", True),
    (10, 0.05, "STABLE", "PARTIAL_EBAY_DATA", True),
    (40, 0.11, "STABLE", "REVIEW_REQUIRED", False),
    (4, 0.05, "STABLE", "INSUFFICIENT_EBAY_DATA", False),
])
def test_quality_gate(full, uncertain, stability, status, persisted):
    result = evaluate_ebay_quality(
        full_set_count=full, uncertain_rate=uncertain, price_stability=stability
    )
    assert result.quality_status == status
    assert result.persist_market_data is persisted


def test_ebay_snapshot_history_is_append_only_and_feeds_radar(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.start_run("one", ["TEST-1"])
    store.save_ebay_snapshot("one", summary(new_p25=90), usable_for_radar=True)
    store.start_run("two", ["TEST-1"])
    store.save_ebay_snapshot("two", summary(new_p25=95), usable_for_radar=True)

    history = store.ebay_history_for_set("TEST-1")
    radar = store.latest_radar_rows()[0]
    assert len(history) == 2
    assert [row["new_p25"] for row in history] == [90, 95]
    assert radar["ebay_asking_reference_new"] == 95
    assert radar["ebay_status"] == "GOOD"
    assert radar["decision"] == "PENDING MARKET DATA"
    status = store.ebay_status_summary()
    assert status["good"] == 1
    assert status["partial"] == 0


def test_review_snapshot_keeps_diagnostic_but_not_prices(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.start_run("review", ["TEST-1"])
    record = summary(status="REVIEW_REQUIRED", seller="must-not-persist")
    store.save_ebay_snapshot("review", record, usable_for_radar=False)

    stored = store.ebay_history_for_set("TEST-1")[0]
    radar = store.latest_radar_rows()[0]
    assert stored["quality_status"] == "REVIEW_REQUIRED"
    assert stored["new_p25"] is None
    assert radar["ebay_status"] == "REVIEW"
    assert radar["ebay_new_p25"] is None
    assert "seller" not in json.dumps(stored).casefold()
    assert "must-not-persist" not in json.dumps(stored)


def test_none_price_is_preserved_for_usable_snapshot(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.start_run("none", ["TEST-1"])
    store.save_ebay_snapshot(
        "none", summary(used_p25=None, used_median=None), usable_for_radar=True
    )
    row = store.latest_radar_rows()[0]
    assert row["ebay_used_p25"] is None
    assert row["ebay_used_median"] is None


def test_monitored_sets_use_only_latest_good_or_partial_status(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.start_run("first", ["A-1", "B-1", "C-1"])
    store.save_ebay_snapshot("first", summary("A-1"), usable_for_radar=True)
    store.save_ebay_snapshot(
        "first", summary("B-1", status="PARTIAL_EBAY_DATA"), usable_for_radar=True
    )
    store.save_ebay_snapshot("first", summary("C-1"), usable_for_radar=True)
    store.start_run("second", ["A-1"])
    store.save_ebay_snapshot(
        "second", summary("A-1", status="REVIEW_REQUIRED"), usable_for_radar=False
    )

    assert store.monitored_ebay_set_nums() == ["B-1", "C-1"]


def test_historical_changes_and_time_windows(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    for run_id in ["one", "two", "three"]:
        store.start_run(run_id, ["TEST-1"])
    store.save_ebay_snapshot(
        "one", summary(new_p25=100, used_p25=50, full_set_count=20),
        usable_for_radar=True, timestamp="2026-01-01T00:00:00+00:00",
    )
    store.save_ebay_snapshot(
        "two", summary(new_p25=110, used_p25=55, full_set_count=22),
        usable_for_radar=True, timestamp="2026-01-24T00:00:00+00:00",
    )
    store.save_ebay_snapshot(
        "three", summary(new_p25=121, used_p25=44, full_set_count=11),
        usable_for_radar=True, timestamp="2026-02-02T00:00:00+00:00",
    )

    history = store.ebay_history_for_set("TEST-1")
    first_metrics = json.loads(history[0]["historical_metrics"])
    latest_metrics = json.loads(history[-1]["historical_metrics"])
    radar = store.latest_radar_rows()[0]
    assert first_metrics["new_p25_change_pct"] is None
    assert first_metrics["7d_change"] is None
    assert latest_metrics["new_p25_change_pct"] == 10
    assert latest_metrics["used_p25_change_pct"] == -20
    assert latest_metrics["listing_count_change_pct"] == -50
    assert latest_metrics["7d_change"]["new_p25_change_pct"] == 10
    assert latest_metrics["30d_change"]["new_p25_change_pct"] == 21
    assert radar["ebay_new_p25_7d_change_pct"] == 10
    assert radar["ebay_new_p25_30d_change_pct"] == 21
    assert len(history) == 3


def test_historical_change_preserves_none_and_zero_baseline(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    store.start_run("one", ["TEST-1"])
    store.save_ebay_snapshot(
        "one", summary(new_p25=None, used_p25=0), usable_for_radar=True,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    store.start_run("two", ["TEST-1"])
    store.save_ebay_snapshot(
        "two", summary(new_p25=100, used_p25=20), usable_for_radar=True,
        timestamp="2026-01-02T00:00:00+00:00",
    )

    metrics = json.loads(store.ebay_history_for_set("TEST-1")[-1]["historical_metrics"])
    assert metrics["new_p25_change_pct"] is None
    assert metrics["used_p25_change_pct"] is None
    assert metrics["7d_change"] is None


class FakeEbay:
    environment = "production"
    rate_limit_retries = 0


class FakeRebrickable:
    def get_set(self, set_num):
        return {"set_num": set_num, "name": f"Set {set_num}"}


def test_ebay_pipeline_checkpoint_resume(tmp_path, monkeypatch):
    store = MarketStore(tmp_path / "market.sqlite3")
    calls = []

    def interrupted(row, *, identity, engine):
        calls.append(identity["set_num"])
        if identity["set_num"] == "B-1":
            raise KeyboardInterrupt()
        return summary(identity["set_num"]), [], []

    monkeypatch.setattr("services.ebay_refresh.benchmark_set", interrupted)
    pipeline = EbayRefreshPipeline(
        store=store, rebrickable_client=FakeRebrickable(), ebay_client=FakeEbay(),
        pause_seconds=0, checkpoint_every=1, sleep=lambda _: None,
    )
    with pytest.raises(KeyboardInterrupt):
        pipeline.refresh_sets(["A-1", "B-1", "C-1"], run_id="resume")
    assert store.processed_sets("resume") == {"A-1"}

    monkeypatch.setattr(
        "services.ebay_refresh.benchmark_set",
        lambda row, *, identity, engine: (summary(identity["set_num"]), [], []),
    )
    resumed = pipeline.refresh_sets(
        ["A-1", "B-1", "C-1"], run_id="resume", resume=True
    )
    assert resumed.skipped == ["A-1"]
    assert store.processed_sets("resume") == {"A-1", "B-1", "C-1"}


def test_set_error_does_not_abort_batch_or_log_secret(tmp_path, monkeypatch, caplog):
    secret = "seller-secret-value"
    store = MarketStore(tmp_path / "market.sqlite3")

    def one_error(row, *, identity, engine):
        if identity["set_num"] == "B-1":
            raise RuntimeError(secret)
        return summary(identity["set_num"]), [], []

    monkeypatch.setattr("services.ebay_refresh.benchmark_set", one_error)
    pipeline = EbayRefreshPipeline(
        store=store, rebrickable_client=FakeRebrickable(), ebay_client=FakeEbay(),
        pause_seconds=0, sleep=lambda _: None,
    )
    batch = pipeline.refresh_sets(["A-1", "B-1", "C-1"], run_id="errors")
    assert [item.quality_status for item in batch.results] == [
        "GOOD_EBAY_DATA", "ERROR", "GOOD_EBAY_DATA"
    ]
    assert secret not in caplog.text
    assert secret not in str(store.processed_sets("errors"))
