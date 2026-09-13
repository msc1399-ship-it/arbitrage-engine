from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EbayQualityGateResult:
    quality_status: str
    badge: str
    persist_market_data: bool
    diagnostic_only: bool


_BADGES = {
    "GOOD_EBAY_DATA": "GOOD",
    "PARTIAL_EBAY_DATA": "PARTIAL",
    "REVIEW_REQUIRED": "REVIEW",
    "INSUFFICIENT_EBAY_DATA": "INSUFFICIENT",
}


def evaluate_ebay_quality(*, full_set_count, uncertain_rate, price_stability):
    if uncertain_rate is not None and uncertain_rate > 0.10:
        status = "REVIEW_REQUIRED"
    elif price_stability == "UNSTABLE":
        status = "REVIEW_REQUIRED"
    elif full_set_count < 5:
        status = "INSUFFICIENT_EBAY_DATA"
    elif full_set_count >= 15 and price_stability in {"STABLE", "MODERATE"}:
        status = "GOOD_EBAY_DATA"
    else:
        status = "PARTIAL_EBAY_DATA"
    usable = status in {"GOOD_EBAY_DATA", "PARTIAL_EBAY_DATA"}
    return EbayQualityGateResult(status, _BADGES[status], usable, not usable)
