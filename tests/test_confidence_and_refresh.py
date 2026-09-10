from datetime import datetime, timezone
import logging

import pytest

from models.market_data import MarketData
from services.confidence_engine import ConfidenceResult, FACTOR_WEIGHTS, calculate_confidence
from services.market_aggregator import PENDING, aggregate_market_data
from services.market_refresh import MarketRefreshPipeline
from services.market_store import MarketStore
from tests.fixtures.market_samples import bricklink_sales

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def sold_data(*, sales=60, p25=100, median=102, weighted=101,
              observed_at=NOW, set_num="TEST-1"):
    return MarketData(
        set_num=set_num, marketplace="BRICKLINK", observed_at=observed_at,
        sales_6m=sales, sold_price_p25=p25, sold_price_median=median,
        sold_price_weighted_avg=weighted,
    )


def listing_data(*, p25=100, median=105, minimum=80,
                 observed_at=NOW, set_num="TEST-1"):
    return MarketData(
        set_num=set_num, marketplace="EBAY", observed_at=observed_at,
        active_listing_count=5, asking_price_min=minimum,
        asking_price_p25=p25, asking_price_median=median,
    )


def test_high_confidence_large_sample_low_dispersion():
    result = calculate_confidence(
        set_num="TEST-1", bricklink_data=sold_data(),
        ebay_data=listing_data(), now=NOW,
    )
    assert result.confidence_score >= .9
    assert result.confidence_label == "VERY_HIGH"


def test_low_confidence_small_sample_high_dispersion():
    result = calculate_confidence(
        set_num="TEST-1",
        bricklink_data=sold_data(sales=2, p25=20, median=100, weighted=200),
        ebay_data=listing_data(p25=300, median=400),
        exact_identification=False, now=NOW,
    )
    assert result.confidence_score < .4
    assert result.confidence_label in {"VERY_LOW", "LOW"}


def test_missing_factors_remain_none_and_weights_are_renormalized():
    data = MarketData(sales_6m=60)
    result = calculate_confidence(
        set_num="TEST-1", bricklink_data=data,
        exact_identification=False, now=NOW,
    )
    assert result.confidence_factors["price_dispersion"] is None
    assert result.confidence_factors["source_agreement"] is None
    assert result.confidence_factors["data_freshness"] is None
    expected = (FACTOR_WEIGHTS["sales_sample"] +
                FACTOR_WEIGHTS["exact_identification"] * .35) / (
                    FACTOR_WEIGHTS["sales_sample"] +
                    FACTOR_WEIGHTS["exact_identification"])
    assert result.confidence_score == pytest.approx(expected, abs=1e-4)


def test_no_observable_factors_means_pending():
    confidence = calculate_confidence(set_num="TEST-1", now=NOW)
    assert confidence.confidence_score is None
    assert all(value is None for value in confidence.confidence_factors.values())
    result = aggregate_market_data(set_num="TEST-1", now=NOW)
    assert result.derived_metrics.confidence_score is None
    assert result.derived_metrics.decision == PENDING


@pytest.mark.parametrize("score,decision", [(.54, "REJECT"), (.60, "WATCH"), (.70, "PAPER_BUY")])
def test_confidence_decision_thresholds(monkeypatch, score, decision):
    confidence = ConfidenceResult(score, "MEDIUM", [], {})
    monkeypatch.setattr("services.market_aggregator.calculate_confidence", lambda **_: confidence)
    result = aggregate_market_data(
        set_num="TEST-1", bricklink_data=sold_data(sales=60, p25=200, median=205, weighted=202),
        ebay_data=listing_data(p25=100, median=110, minimum=100), now=NOW,
    )
    assert result.derived_metrics.expected_roi > .2
    assert result.derived_metrics.monthly_sales >= 2
    assert result.derived_metrics.decision == decision


class FakeBrickLink:
    def __init__(self, behavior=None):
        self.behavior = behavior or {}
        self.calls = []

    def get_market_data(self, set_num):
        self.calls.append(set_num)
        outcome = self.behavior.get(set_num)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome or bricklink_sales(set_num=set_num)


def test_batch_continues_after_set_error(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    client = FakeBrickLink({"B": RuntimeError("request failed")})
    pipeline = MarketRefreshPipeline(
        store=store, bricklink_client=client, pause_seconds=0,
        checkpoint_every=2, sleep=lambda _: None,
    )
    batch = pipeline.refresh_sets(["A", "B", "C"], run_id="batch")
    assert [item.set_num for item in batch.results] == ["A", "B", "C"]
    assert [item.market_status for item in batch.results] == ["PARTIAL", "ERROR", "PARTIAL"]
    assert len(store.latest_records()) == 3


def test_checkpoint_resume_skips_completed_sets(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    interrupted = FakeBrickLink({"B": KeyboardInterrupt()})
    first = MarketRefreshPipeline(
        store=store, bricklink_client=interrupted, pause_seconds=0,
        checkpoint_every=1, sleep=lambda _: None,
    )
    with pytest.raises(KeyboardInterrupt):
        first.refresh_sets(["A", "B", "C"], run_id="resume-me")
    assert store.processed_sets("resume-me") == {"A"}

    resumed_client = FakeBrickLink()
    resumed = MarketRefreshPipeline(
        store=store, bricklink_client=resumed_client, pause_seconds=0,
        checkpoint_every=1, sleep=lambda _: None,
    ).refresh_sets(["A", "B", "C"], run_id="resume-me", resume=True)
    assert resumed.skipped == ["A"]
    assert resumed_client.calls == ["B", "C"]
    assert store.processed_sets("resume-me") == {"A", "B", "C"}


def test_logs_and_stored_errors_do_not_include_secrets(tmp_path, caplog):
    secret = "client-secret-must-not-leak"
    store = MarketStore(tmp_path / "market.sqlite3")
    pipeline = MarketRefreshPipeline(
        store=store, bricklink_client=FakeBrickLink({"A": RuntimeError(secret)}),
        pause_seconds=0, sleep=lambda _: None,
    )
    with caplog.at_level(logging.WARNING):
        pipeline.refresh_sets(["A"], run_id="safe-log")
    assert secret not in caplog.text
    assert secret not in str(store.latest_records())


def test_no_connectors_records_pending_without_network(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    result = MarketRefreshPipeline(
        store=store, pause_seconds=0, sleep=lambda _: None,
    ).refresh_sets(["A"]).results[0]
    assert result.market_status == "PENDING"
    assert result.aggregate.derived_metrics.decision == PENDING


def test_refresh_history_is_append_only(tmp_path):
    store = MarketStore(tmp_path / "market.sqlite3")
    pipeline = MarketRefreshPipeline(
        store=store, bricklink_client=FakeBrickLink(),
        pause_seconds=0, sleep=lambda _: None,
    )
    pipeline.refresh_sets(["A"], run_id="first")
    pipeline.refresh_sets(["A"], run_id="second")
    history = store.history_for_set("A")
    assert len(history) == 2
    assert [row["run_id"] for row in history] == ["first", "second"]
