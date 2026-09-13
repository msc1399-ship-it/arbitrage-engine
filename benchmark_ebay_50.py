from __future__ import annotations

import argparse
import json

from collectors.ebay import EbayClient
from collectors.rebrickable import RebrickableClient
from services.ebay_query_engine import EbayQueryEngine
from services.ebay_scale_benchmark import (
    REVIEW_FIELDS,
    SUMMARY_FIELDS,
    benchmark_set,
    select_benchmark_sets,
    write_csv,
)


def main():
    parser = argparse.ArgumentParser(description="Run the in-memory eBay 50-set benchmark")
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()

    selected = select_benchmark_sets("lego_universe_v0.csv", count=args.count)
    print(json.dumps({"selected": selected}, ensure_ascii=False))
    if args.select_only:
        return

    ebay = EbayClient()
    if ebay.environment != "production":
        raise RuntimeError("Benchmark requires EBAY_ENVIRONMENT=production")
    rebrickable = RebrickableClient()
    engine = EbayQueryEngine(ebay)
    summaries = []
    reviews = []
    uncertain = {}
    for index, row in enumerate(selected, start=1):
        print(f"BENCHMARK {index}/{len(selected)} {row['set_num']}", flush=True)
        try:
            identity = rebrickable.get_set(row["set_num"])
            summary, review_rows, examples = benchmark_set(
                row, identity=identity, engine=engine
            )
            summaries.append(summary)
            reviews.extend(review_rows)
            if summary["uncertain_rate"] and summary["uncertain_rate"] > 0.10:
                uncertain[row["set_num"]] = examples
        except Exception as error:
            summaries.append({
                **row,
                "queries_used": "",
                "api_calls": 0,
                "status": "REVIEW_REQUIRED",
                "error": f"{type(error).__name__}: {error}",
            })
    write_csv("reports/ebay_50_benchmark.csv", summaries, SUMMARY_FIELDS)
    write_csv("reports/ebay_50_fullset_review.csv", reviews, REVIEW_FIELDS)
    print(json.dumps({
        "summaries": summaries,
        "review_rows": len(reviews),
        "high_uncertainty_examples": uncertain,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
