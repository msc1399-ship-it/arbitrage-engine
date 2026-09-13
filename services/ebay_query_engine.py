from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass
from typing import Any

from collectors.ebay import MARKETPLACE_ES
from services.ebay_listing_classifier import classify_ebay_listing, normalized_condition
from services.ebay_query_planner import EbayQueryPlan, plan_ebay_queries

PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"


@dataclass(frozen=True)
class QueryQuality:
    query: str
    results_returned: int
    unique_results_added: int
    full_sets_found: int
    unique_full_sets_added: int
    retrieval_yield: float | None
    uncertain_count: int
    query_score: float | None


@dataclass(frozen=True)
class EbayQueryEnsembleResult:
    set_num: str
    name: str
    planned_queries: tuple[str, ...]
    queries_used: tuple[str, ...]
    api_calls: int
    listings: tuple[dict[str, Any], ...]
    query_quality: tuple[QueryQuality, ...]
    unique_results: int
    full_set_unique: int
    retrieval_yield: float | None
    uncertain: int
    review_rate: float | None
    duplicates_removed: int
    classifier_precision_sample: str = PENDING_HUMAN_REVIEW


def score_query(*, results_returned: int, unique_full_sets_added: int,
                uncertain_count: int) -> float | None:
    if results_returned <= 0:
        return None
    useful_yield = unique_full_sets_added / results_returned
    review_penalty = 1 - min(uncertain_count / results_returned, 1)
    return round(useful_yield * review_penalty, 6)


def _raw_items(market_data) -> list[dict[str, Any]]:
    raw = market_data.raw_data or {}
    if isinstance(raw, dict) and isinstance(raw.get("pages"), list):
        return [
            item
            for page in raw["pages"]
            for item in (page.get("itemSummaries") or [])
        ]
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return list(raw["items"])
    return []


def _listing_key(item: dict[str, Any]) -> str:
    item_id = item.get("itemId") or item.get("item_id")
    if item_id:
        return str(item_id)
    stable = repr(sorted(item.items())).encode("utf-8", "replace")
    return f"missing:{hashlib.sha256(stable).hexdigest()}"


class EbayQueryEngine:
    def __init__(self, client, *, marketplace=MARKETPLACE_ES, per_query_limit=200):
        self.client = client
        self.marketplace = marketplace
        self.per_query_limit = per_query_limit

    def search_product(
        self,
        set_num: str,
        name: str,
        aliases: tuple[str, ...] | list[str] = (),
        *,
        max_queries: int = 5,
        target_full_sets: int = 50,
        min_queries: int = 2,
        min_marginal_full_sets: int = 3,
    ) -> EbayQueryEnsembleResult:
        plan = plan_ebay_queries(set_num, name, aliases, max_queries=max_queries)
        return self.execute_plan(
            plan,
            target_full_sets=target_full_sets,
            min_queries=min_queries,
            min_marginal_full_sets=min_marginal_full_sets,
        )

    def execute_plan(
        self,
        plan: EbayQueryPlan,
        *,
        target_full_sets: int = 50,
        min_queries: int = 2,
        min_marginal_full_sets: int = 3,
    ) -> EbayQueryEnsembleResult:
        unique: dict[str, dict[str, Any]] = {}
        query_quality = []
        queries_used = []
        duplicates_removed = 0

        for query in plan.queries:
            market_data = self.client.search_keywords(
                query,
                set_num=plan.set_num,
                marketplace=self.marketplace,
                limit=self.per_query_limit,
                max_pages=1,
            )
            items = _raw_items(market_data)
            queries_used.append(query)
            unique_added = 0
            unique_full_added = 0
            full_found = 0
            uncertain_count = 0

            for original in items:
                classification = classify_ebay_listing(
                    original,
                    set_num=plan.set_num,
                    expected_terms=plan.identity_terms,
                )
                if classification.category == "FULL_SET":
                    full_found += 1
                elif classification.category == "UNCERTAIN":
                    uncertain_count += 1

                key = _listing_key(original)
                if key in unique:
                    duplicates_removed += 1
                    matched = unique[key]["matched_queries"]
                    if query not in matched:
                        matched.append(query)
                    continue

                listing = dict(original)
                listing["matched_queries"] = [query]
                listing["classification"] = classification.category
                listing["classification_reasons"] = classification.reasons
                unique[key] = listing
                unique_added += 1
                if classification.category == "FULL_SET":
                    unique_full_added += 1

            returned = len(items)
            query_quality.append(QueryQuality(
                query=query,
                results_returned=returned,
                unique_results_added=unique_added,
                full_sets_found=full_found,
                unique_full_sets_added=unique_full_added,
                retrieval_yield=(full_found / returned) if returned else None,
                uncertain_count=uncertain_count,
                query_score=score_query(
                    results_returned=returned,
                    unique_full_sets_added=unique_full_added,
                    uncertain_count=uncertain_count,
                ),
            ))

            full_total = sum(
                item["classification"] == "FULL_SET" for item in unique.values()
            )
            enough_queries = len(queries_used) >= max(min_queries, 1)
            if enough_queries and full_total >= target_full_sets:
                break
            if enough_queries and unique_full_added < min_marginal_full_sets:
                break

        listings = tuple(unique.values())
        full_total = sum(item["classification"] == "FULL_SET" for item in listings)
        uncertain = sum(item["classification"] == "UNCERTAIN" for item in listings)
        total = len(listings)
        return EbayQueryEnsembleResult(
            set_num=plan.set_num,
            name=plan.name.full_name,
            planned_queries=plan.queries,
            queries_used=tuple(queries_used),
            api_calls=len(queries_used),
            listings=listings,
            query_quality=tuple(query_quality),
            unique_results=total,
            full_set_unique=full_total,
            retrieval_yield=(full_total / total) if total else None,
            uncertain=uncertain,
            review_rate=(uncertain / total) if total else None,
            duplicates_removed=duplicates_removed,
        )


def full_set_price_summary(result: EbayQueryEnsembleResult, condition: str):
    stats = full_set_price_stats(result.listings, condition)
    return {
        "count": stats["count"],
        "median": stats["median"],
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def full_set_price_stats(
    listings,
    condition: str,
    *,
    currency: str = "EUR",
    matched_query: str | None = None,
):
    """Summarize active asking prices without mixing currencies or dropping outliers."""
    values = []
    for item in listings:
        if item["classification"] != "FULL_SET" or normalized_condition(item) != condition:
            continue
        if matched_query is not None and matched_query not in item.get("matched_queries", ()):
            continue
        price = item.get("price") or {}
        if price.get("currency") != currency:
            continue
        try:
            values.append(float(price["value"]))
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p25": _percentile(values, 0.25),
        "median": statistics.median(values) if values else None,
        "p75": _percentile(values, 0.75),
        "max": max(values) if values else None,
        "mean": statistics.mean(values) if values else None,
    }


def deterministic_full_set_sample(result: EbayQueryEnsembleResult, limit: int = 20):
    full_sets = [item for item in result.listings if item["classification"] == "FULL_SET"]
    return tuple(sorted(full_sets, key=_listing_key)[:limit])
