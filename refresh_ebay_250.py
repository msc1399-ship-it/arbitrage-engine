from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from services.ebay_refresh import EbayRefreshPipeline
from services.ebay_scale_benchmark import DEFAULT_SEED, select_refresh_sets


def main():
    parser = argparse.ArgumentParser(description="Refresh a reproducible eBay radar batch")
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-id", default=f"ebay-v07-{DEFAULT_SEED}-250")
    args = parser.parse_args()
    selected = select_refresh_sets(
        "lego_universe_v0.csv", count=args.count,
        benchmark_report="reports/ebay_50_benchmark.csv",
    )
    set_nums = [row["set_num"] for row in selected]
    print(json.dumps({
        "sets": len(set_nums),
        "estimated_api_calls": round(len(set_nums) * 2.06),
        "set_nums": set_nums,
    }))
    if args.select_only:
        return

    started = time.monotonic()
    pipeline = EbayRefreshPipeline.from_environment(checkpoint_every=25)
    result = pipeline.refresh_sets(set_nums, run_id=args.run_id, resume=args.resume)
    counts = Counter(item.quality_status for item in result.results)
    print(json.dumps({
        "run_id": result.run_id,
        "processed": len(result.results),
        "skipped": len(result.skipped),
        "quality": counts,
        "api_calls": sum(item.api_calls for item in result.results),
        "persisted": sum(item.persisted for item in result.results),
        "errors": sum(item.error is not None for item in result.results),
        "rate_limit_retries": result.rate_limit_retries,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }, default=dict))


if __name__ == "__main__":
    main()
