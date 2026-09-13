from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from pathlib import Path

from services.ebay_listing_classifier import normalized_condition
from services.ebay_quality_gate import evaluate_ebay_quality
from services.ebay_query_engine import (
    EbayQueryEngine,
    deterministic_full_set_sample,
    full_set_price_stats,
)

DEFAULT_SEED = 20260913

_GROUPS = (
    ("Star Wars", r"star wars|millennium|x-wing|tie fighter|r2-d2|mandalorian|death star|at-at|ahsoka"),
    ("Architecture", r"architecture|skyline|eiffel|taj mahal|statue of liberty|colosseum|pyramid|empire state"),
    ("Harry Potter", r"harry potter|hogwarts|diagon alley|hedwig|gringotts|hagrid"),
    ("Marvel / DC", r"marvel|avengers|spider|batman|gotham|superman|guardians|thor|iron man"),
    ("Ideas", r"tree house|central perk|globe|lighthouse|jazz quartet|tales of the space age|typewriter"),
    ("Icons / Creator", r"icons|modular|bouquet|bonsai|titanic|concorde|ornithopter|creator expert"),
    ("Technic", r"technic|bugatti|lamborghini|ferrari|mclaren|porsche|formula 1|f1 car"),
    ("Vehicles", r"\bcar\b|\bvehicle\b|\bford\b|\bchevrolet\b|\bmercedes\b|\bbmw\b|\baudi\b|\bnascar\b|\bmotorcycle\b|land rover|\bcamaro\b|\bmustang\b|\bsenna\b"),
    ("Other licensed", r"\bdisney\b|sonic the hedgehog|\bmario\b|\bminecraft\b|\bzelda\b|\bjurassic\b|\btransformers\b|\bsimpsons\b|stranger things"),
    ("Non-licensed / ambiguous", r"castle|house|ship|train|space|city|police|fire|museum|garden|station|tower"),
)

_GROUP_THEME_IDS = {
    "Star Wars": {"158", "209"},
    "Architecture": {"252"},
    "Harry Potter": {"246", "710"},
    "Marvel / DC": {"697", "702", "705"},
    "Ideas": {"576"},
    "Icons / Creator": {"721", "769"},
    "Technic": {"1"},
    "Vehicles": {"601"},
    "Non-licensed / ambiguous": {"52", "53", "61", "435", "672"},
}

SUMMARY_FIELDS = (
    "selection_group", "set_num", "name", "year", "theme_id", "num_parts",
    "queries_used", "api_calls", "unique_results", "duplicates_removed",
    "full_set_count", "incomplete_count", "accessory_count", "parts_count",
    "instructions_count", "box_only_count", "compatible_count", "other_count",
    "uncertain_count", "retrieval_yield", "uncertain_rate",
    "new_count", "new_min", "new_p25", "new_median", "new_p75", "new_max", "new_mean",
    "used_count", "used_min", "used_p25", "used_median", "used_p75", "used_max", "used_mean",
    "unknown_count", "price_stability", "sample_quality", "status", "error",
)

REVIEW_FIELDS = (
    "set_num", "title", "price", "condition", "classification", "item_id", "review_status",
)


def _stable_rank(seed: int, set_num: str) -> str:
    return hashlib.sha256(f"{seed}:{set_num}".encode()).hexdigest()


def _bucket(row):
    year = int(row["year"])
    parts = int(row["num_parts"])
    year_band = 0 if year <= 2015 else 1 if year <= 2020 else 2
    part_band = 0 if parts < 500 else 1 if parts <= 1200 else 2
    return year_band, part_band


def _pick_stratified(candidates, count, seed):
    buckets = {}
    for row in candidates:
        buckets.setdefault(_bucket(row), []).append(row)
    for rows in buckets.values():
        rows.sort(key=lambda row: _stable_rank(seed, row["set_num"]))

    picked = []
    keys = sorted(buckets)
    while len(picked) < count and keys:
        next_keys = []
        for key in keys:
            rows = buckets[key]
            if rows and len(picked) < count:
                picked.append(rows.pop(0))
            if rows:
                next_keys.append(key)
        keys = next_keys
    return picked


def _matches_group(row, group, pattern):
    theme_match = row["theme_id"] in _GROUP_THEME_IDS.get(group, set())
    name_match = bool(re.search(pattern, row["name"], re.IGNORECASE))
    if group in {
        "Architecture", "Ideas", "Icons / Creator", "Technic",
        "Non-licensed / ambiguous",
    }:
        return theme_match
    return theme_match or name_match


def select_benchmark_sets(csv_path, *, count=50, seed=DEFAULT_SEED):
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if len(rows) < count:
        raise ValueError(f"Universe contains {len(rows)} sets; {count} requested")

    selected = []
    selected_ids = set()
    quota = max(count // len(_GROUPS), 1)
    for group, pattern in _GROUPS:
        candidates = [
            row for row in rows
            if row["set_num"] not in selected_ids
            and _matches_group(row, group, pattern)
        ]
        for row in _pick_stratified(candidates, quota, seed):
            selected.append({**row, "selection_group": group})
            selected_ids.add(row["set_num"])

    if len(selected) < count:
        remaining = [row for row in rows if row["set_num"] not in selected_ids]
        for row in _pick_stratified(remaining, count - len(selected), seed + 1):
            selected.append({**row, "selection_group": "Diversity fill"})
    return selected[:count]


def select_refresh_sets(csv_path, *, count=250, seed=DEFAULT_SEED,
                        benchmark_report=None):
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    blocked = set()
    report = Path(benchmark_report) if benchmark_report else None
    if report and report.exists():
        with report.open(encoding="utf-8-sig", newline="") as source:
            blocked = {
                row["set_num"] for row in csv.DictReader(source)
                if row.get("status") in {"REVIEW_REQUIRED", "INSUFFICIENT_EBAY_DATA"}
            }
    eligible = [
        row for row in rows
        if row["set_num"] not in blocked
        and re.fullmatch(r"\d{4,5}-1", row["set_num"])
        and int(row["year"]) >= 2016
        and int(row["num_parts"]) >= 400
        and 4 <= len(row["name"].strip()) <= 70
        and "advent calendar" not in row["name"].casefold()
    ]
    if len(eligible) < count:
        raise ValueError(f"Only {len(eligible)} reasonable eBay refresh candidates")
    return _pick_stratified(eligible, count, seed)


def sample_quality(full_set_count):
    if full_set_count >= 40:
        return "HIGH"
    if full_set_count >= 15:
        return "MEDIUM"
    if full_set_count >= 5:
        return "LOW"
    return "INSUFFICIENT"


def price_stability(first_stats, ensemble_stats):
    changes = []
    for condition in ("NEW", "USED"):
        first = first_stats[condition]["median"]
        ensemble = ensemble_stats[condition]["median"]
        if first is not None and ensemble is not None and first != 0:
            changes.append(abs(ensemble - first) / abs(first))
    if not changes:
        return "PENDING"
    largest = max(changes)
    if largest <= 0.10:
        return "STABLE"
    if largest <= 0.20:
        return "MODERATE"
    return "UNSTABLE"


def benchmark_status(full_count, uncertain_rate, stability):
    return evaluate_ebay_quality(
        full_set_count=full_count,
        uncertain_rate=uncertain_rate,
        price_stability=stability,
    ).quality_status


def _condition_count(listings, condition):
    return sum(
        item["classification"] == "FULL_SET"
        and normalized_condition(item) == condition
        for item in listings
    )


def benchmark_set(row, *, identity, engine):
    result = engine.search_product(
        identity["set_num"], identity["name"], max_queries=5,
        target_full_sets=50, min_queries=2, min_marginal_full_sets=3,
    )
    counts = Counter(item["classification"] for item in result.listings)
    first_query = result.queries_used[0]
    first_stats = {
        condition: full_set_price_stats(
            result.listings, condition, matched_query=first_query
        )
        for condition in ("NEW", "USED")
    }
    ensemble_stats = {
        condition: full_set_price_stats(result.listings, condition)
        for condition in ("NEW", "USED")
    }
    stability = price_stability(first_stats, ensemble_stats)
    status = benchmark_status(result.full_set_unique, result.review_rate, stability)
    summary = {
        "selection_group": row["selection_group"],
        "set_num": identity["set_num"],
        "name": identity["name"],
        "year": identity.get("year"),
        "theme_id": identity.get("theme_id"),
        "num_parts": identity.get("num_parts"),
        "queries_used": " | ".join(result.queries_used),
        "api_calls": result.api_calls,
        "unique_results": result.unique_results,
        "duplicates_removed": result.duplicates_removed,
        "full_set_count": counts["FULL_SET"],
        "incomplete_count": counts["INCOMPLETE_SET"],
        "accessory_count": counts["ACCESSORY"],
        "parts_count": counts["PARTS"],
        "instructions_count": counts["INSTRUCTIONS"],
        "box_only_count": counts["BOX_ONLY"],
        "compatible_count": counts["COMPATIBLE_PRODUCT"],
        "other_count": counts["OTHER"],
        "uncertain_count": counts["UNCERTAIN"],
        "retrieval_yield": result.retrieval_yield,
        "uncertain_rate": result.review_rate,
        "unknown_count": _condition_count(result.listings, "UNKNOWN"),
        "price_stability": stability,
        "sample_quality": sample_quality(result.full_set_unique),
        "status": status,
        "error": "",
    }
    for prefix, condition in (("new", "NEW"), ("used", "USED")):
        for metric, value in ensemble_stats[condition].items():
            summary[f"{prefix}_{metric}"] = value

    review_rows = []
    for item in deterministic_full_set_sample(result, 5):
        price = item.get("price") or {}
        review_rows.append({
            "set_num": identity["set_num"],
            "title": item.get("title"),
            "price": price.get("value") if price.get("currency") == "EUR" else "",
            "condition": normalized_condition(item),
            "classification": item["classification"],
            "item_id": item.get("itemId") or item.get("item_id"),
            "review_status": "PENDING",
        })
    uncertain_examples = [
        item.get("title") for item in result.listings
        if item["classification"] == "UNCERTAIN"
    ][:5]
    return summary, review_rows, uncertain_examples


def write_csv(path, rows, fields):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
