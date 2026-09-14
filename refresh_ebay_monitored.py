from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone

from services.ebay_refresh import EbayRefreshPipeline
from services.market_store import MarketStore


def main():
    parser = argparse.ArgumentParser(
        description="Append a daily eBay snapshot for monitored GOOD/PARTIAL sets"
    )
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args()

    store = MarketStore()
    set_nums = store.monitored_ebay_set_nums()
    run_id = args.run_id or f"ebay-monitored-{datetime.now(timezone.utc).date().isoformat()}"
    print(json.dumps({
        "run_id": run_id,
        "monitored_sets": len(set_nums),
        "estimated_api_calls": round(len(set_nums) * 2.06),
    }))
    if args.select_only or not set_nums:
        return

    started = time.monotonic()
    pipeline = EbayRefreshPipeline.from_environment(store=store, checkpoint_every=25)
    result = pipeline.refresh_sets(set_nums, run_id=run_id, resume=True)
    counts = Counter(item.quality_status for item in result.results)
    print(json.dumps({
        "run_id": result.run_id,
        "sets_selected": len(set_nums),
        "sets_attempted": len(result.results),
        "sets_updated": sum(item.error is None for item in result.results),
        "sets_skipped_as_completed": len(result.skipped),
        "errors": sum(item.error is not None for item in result.results),
        "api_calls": sum(item.api_calls for item in result.results),
        "rate_limit_retries": result.rate_limit_retries,
        "good": counts["GOOD_EBAY_DATA"],
        "partial": counts["PARTIAL_EBAY_DATA"],
        "review": counts["REVIEW_REQUIRED"],
        "insufficient": counts["INSUFFICIENT_EBAY_DATA"],
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }))


if __name__ == "__main__":
    main()
