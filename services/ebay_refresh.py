from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from collectors.ebay import EbayClient
from collectors.rebrickable import RebrickableClient
from services.ebay_quality_gate import evaluate_ebay_quality
from services.ebay_query_engine import EbayQueryEngine
from services.ebay_scale_benchmark import benchmark_set
from services.market_store import MarketStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EbayRefreshItemResult:
    set_num: str
    quality_status: str
    persisted: bool
    api_calls: int
    error: str | None = None


@dataclass(frozen=True)
class EbayRefreshBatchResult:
    run_id: str
    results: list[EbayRefreshItemResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rate_limit_retries: int = 0


class EbayRefreshPipeline:
    def __init__(self, *, store=None, rebrickable_client=None, ebay_client=None,
                 pause_seconds=0.5, checkpoint_every=25, sleep=time.sleep,
                 logger=LOGGER):
        if pause_seconds < 0 or checkpoint_every < 1:
            raise ValueError("Invalid eBay refresh batch settings")
        self.store = store or MarketStore()
        self.rebrickable_client = rebrickable_client or RebrickableClient()
        self.ebay_client = ebay_client or EbayClient()
        if getattr(self.ebay_client, "environment", "production") != "production":
            raise ValueError("Persistent eBay refresh requires Production")
        self.engine = EbayQueryEngine(self.ebay_client)
        self.pause_seconds = pause_seconds
        self.checkpoint_every = checkpoint_every
        self.sleep = sleep
        self.logger = logger

    @classmethod
    def from_environment(cls, **kwargs):
        return cls(**kwargs)

    def refresh_sets(self, set_nums, *, run_id=None, resume=False):
        normalized = list(dict.fromkeys(
            str(value).strip() for value in set_nums if str(value).strip()
        ))
        run_id = run_id or uuid4().hex
        self.store.start_run(run_id, normalized)
        processed = self.store.processed_sets(run_id) if resume else set()
        pending = [set_num for set_num in normalized if set_num not in processed]
        initial_rate_limits = getattr(self.ebay_client, "rate_limit_retries", 0)
        results = []
        for index, set_num in enumerate(pending, start=1):
            before_calls = 0
            try:
                identity = self.rebrickable_client.get_set(set_num)
                summary, _, _ = benchmark_set(
                    {"selection_group": "RADAR"}, identity=identity, engine=self.engine
                )
                gate = evaluate_ebay_quality(
                    full_set_count=summary["full_set_count"],
                    uncertain_rate=summary["uncertain_rate"],
                    price_stability=summary["price_stability"],
                )
                self.store.save_ebay_snapshot(
                    run_id, summary, usable_for_radar=gate.persist_market_data
                )
                results.append(EbayRefreshItemResult(
                    set_num, gate.quality_status, gate.persist_market_data,
                    summary["api_calls"],
                ))
            except Exception as error:
                error_type = type(error).__name__
                self.store.mark_run_error(run_id, set_num, error_type)
                self.logger.warning(
                    "ebay_refresh_error set_num=%s error_type=%s", set_num, error_type
                )
                results.append(EbayRefreshItemResult(
                    set_num, "ERROR", False, before_calls, error_type
                ))
            if index % self.checkpoint_every == 0:
                self.store.checkpoint(run_id)
            if index < len(pending) and self.pause_seconds:
                self.sleep(self.pause_seconds)
        self.store.finish_run(run_id)
        retries = getattr(self.ebay_client, "rate_limit_retries", 0) - initial_rate_limits
        return EbayRefreshBatchResult(
            run_id, results, [s for s in normalized if s in processed], retries
        )
