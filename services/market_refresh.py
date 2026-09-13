from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from collectors.bricklink import BrickLinkClient
from collectors.ebay import EbayClient
from collectors.rebrickable import RebrickableClient
from models.market_data import AggregatedMarketData
from services.market_aggregator import aggregate_market_data
from services.market_store import MarketStore
from services.system_status import connector_statuses

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefreshItemResult:
    set_num: str
    timestamp: str
    market_status: str
    aggregate: AggregatedMarketData
    error_message: str | None = None


@dataclass(frozen=True)
class RefreshBatchResult:
    run_id: str
    results: list[RefreshItemResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class MarketRefreshPipeline:
    def __init__(self, *, store=None, rebrickable_client=None, bricklink_client=None,
                 ebay_client=None, pause_seconds=0.5, checkpoint_every=10,
                 sleep=time.sleep, logger=LOGGER):
        if pause_seconds < 0 or checkpoint_every < 1:
            raise ValueError("pause_seconds must be >= 0 and checkpoint_every >= 1")
        self.store = store or MarketStore()
        self.rebrickable_client = rebrickable_client
        self.bricklink_client = bricklink_client
        self.ebay_client = ebay_client
        self.pause_seconds = pause_seconds
        self.checkpoint_every = checkpoint_every
        self.sleep = sleep
        self.logger = logger

    @classmethod
    def from_environment(cls, *, include_ebay=False, **kwargs):
        statuses = connector_statuses()
        rebrickable = RebrickableClient() if statuses["Rebrickable"] == "ACTIVE" else None
        bricklink = BrickLinkClient() if statuses["BrickLink"] == "ACTIVE" else None
        ebay = EbayClient() if include_ebay and statuses["eBay"] == "ACTIVE" else None
        pause = float(os.getenv("MARKET_REFRESH_PAUSE_SECONDS", "0.5"))
        checkpoint = int(os.getenv("MARKET_REFRESH_CHECKPOINT_EVERY", "10"))
        return cls(rebrickable_client=rebrickable, bricklink_client=bricklink,
                   ebay_client=ebay, pause_seconds=pause,
                   checkpoint_every=checkpoint, **kwargs)

    def _call(self, connector_name, set_num, function, errors):
        try:
            return function()
        except Exception as exc:
            error = f"{connector_name}: {type(exc).__name__}"
            errors.append(error)
            self.logger.warning("refresh_error connector=%s set_num=%s error_type=%s",
                                connector_name, set_num, type(exc).__name__)
            return None

    def _refresh_one(self, set_num):
        errors = []
        identity = None
        bricklink = None
        ebay = None
        if self.rebrickable_client is not None:
            identity = self._call("rebrickable", set_num,
                                  lambda: self.rebrickable_client.get_set(set_num), errors)
        if self.bricklink_client is not None:
            bricklink = self._call("bricklink", set_num,
                                   lambda: self.bricklink_client.get_market_data(set_num), errors)
        if self.ebay_client is not None:
            ebay = self._call("ebay", set_num,
                              lambda: self.ebay_client.get_market_data(set_num), errors)

        configured = sum(client is not None for client in
                         (self.bricklink_client, self.ebay_client))
        succeeded = sum(data is not None for data in (bricklink, ebay))
        if configured == 0:
            status = "PENDING"
        elif succeeded == 0:
            status = "ERROR"
        elif configured == 2 and succeeded == 2:
            status = "OK"
        else:
            status = "PARTIAL"
        timestamp = datetime.now(timezone.utc).isoformat()
        aggregate = aggregate_market_data(
            set_num=set_num, identity_data=identity,
            bricklink_data=bricklink, ebay_data=ebay,
        )
        return RefreshItemResult(
            set_num=set_num, timestamp=timestamp, market_status=status,
            aggregate=aggregate,
            error_message="; ".join(errors) if errors else None,
        )

    def refresh_sets(self, set_nums, *, resume=False, run_id=None):
        normalized = list(dict.fromkeys(str(value).strip() for value in set_nums
                                        if value is not None and str(value).strip()))
        run_id = run_id or uuid4().hex
        self.store.start_run(run_id, normalized)
        processed = self.store.processed_sets(run_id) if resume else set()
        results = []
        skipped = []
        pending = [value for value in normalized if value not in processed]
        skipped.extend(value for value in normalized if value in processed)
        for index, set_num in enumerate(pending, start=1):
            try:
                result = self._refresh_one(set_num)
            except Exception as exc:
                self.logger.warning("refresh_error connector=pipeline set_num=%s error_type=%s",
                                    set_num, type(exc).__name__)
                aggregate = aggregate_market_data(set_num=set_num)
                result = RefreshItemResult(
                    set_num=set_num, timestamp=datetime.now(timezone.utc).isoformat(),
                    market_status="ERROR", aggregate=aggregate,
                    error_message=f"pipeline: {type(exc).__name__}",
                )
            self.store.save_result(run_id, result)
            results.append(result)
            if index % self.checkpoint_every == 0:
                self.store.checkpoint(run_id)
            if index < len(pending) and self.pause_seconds:
                self.sleep(self.pause_seconds)
        self.store.finish_run(run_id)
        return RefreshBatchResult(run_id=run_id, results=results, skipped=skipped)

    def refresh_set(self, set_num):
        return self.refresh_sets([set_num]).results[0]
