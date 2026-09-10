from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from models.market_data import MarketData

FACTOR_WEIGHTS = {
    "sales_sample": 0.30,
    "price_dispersion": 0.25,
    "source_agreement": 0.20,
    "exact_identification": 0.15,
    "data_freshness": 0.10,
}


@dataclass(frozen=True)
class ConfidenceResult:
    confidence_score: float | None
    confidence_label: str | None
    confidence_reasons: list[str]
    confidence_factors: dict[str, float | None]


def _sales_sample(sales_6m):
    if sales_6m is None:
        return None
    if sales_6m <= 0:
        return 0.0
    if sales_6m <= 4:
        return 0.2
    if sales_6m <= 11:
        return 0.4
    if sales_6m <= 29:
        return 0.6
    if sales_6m <= 59:
        return 0.8
    return 1.0


def _price_dispersion(record):
    if record is None:
        return None
    values = [record.sold_price_p25, record.sold_price_median,
              record.sold_price_weighted_avg]
    if any(value is None or value <= 0 for value in values):
        return None
    center = record.sold_price_median
    relative_range = (max(values) - min(values)) / center
    return max(0.0, 1.0 - min(relative_range / 0.50, 1.0))


def _source_agreement(bricklink_data, ebay_data):
    if bricklink_data is None or ebay_data is None:
        return None
    sold = bricklink_data.sold_price_p25
    asking_p25 = ebay_data.asking_price_p25
    asking_median = ebay_data.asking_price_median
    if any(value is None or value <= 0 for value in (sold, asking_p25, asking_median)):
        return None
    lower, upper = sorted((asking_p25, asking_median))
    distance = lower - sold if sold < lower else sold - upper if sold > upper else 0.0
    return max(0.0, 1.0 - min((distance / sold) / 0.50, 1.0))


def _exact_identification(set_num, bricklink_data, ebay_data, override):
    if override is not None:
        return 1.0 if override else 0.35
    if bricklink_data is not None and bricklink_data.set_num is not None:
        return 1.0 if bricklink_data.set_num.casefold() == set_num.casefold() else 0.0
    raw = ebay_data.raw_data if ebay_data is not None else None
    identification = raw.get("identification") if isinstance(raw, dict) else None
    if not isinstance(identification, dict):
        return None
    if identification.get("exact_query"):
        ratio = identification.get("exact_match_ratio")
        return None if ratio is None else max(0.0, min(float(ratio), 1.0))
    return 0.35 if identification.get("query") else None


def _data_freshness(records, now):
    timestamps = [record.observed_at for record in records
                  if record is not None and record.observed_at is not None]
    if not timestamps:
        return None
    normalized = [stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
                  for stamp in timestamps]
    age_days = max(max((now - stamp.astimezone(timezone.utc)).total_seconds(), 0) / 86400
                   for stamp in normalized)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.9
    if age_days <= 30:
        return 0.7
    if age_days <= 90:
        return 0.4
    return 0.1


def _label(score):
    if score is None:
        return None
    if score < 0.20:
        return "VERY_LOW"
    if score < 0.40:
        return "LOW"
    if score < 0.60:
        return "MEDIUM"
    if score < 0.80:
        return "HIGH"
    return "VERY_HIGH"


def calculate_confidence(*, set_num, bricklink_data=None, ebay_data=None,
                         exact_identification=None, now=None):
    now = now or datetime.now(timezone.utc)
    sales_record = bricklink_data if bricklink_data and bricklink_data.sales_6m is not None else ebay_data
    factors = {
        "sales_sample": _sales_sample(sales_record.sales_6m if sales_record else None),
        "price_dispersion": _price_dispersion(bricklink_data),
        "source_agreement": _source_agreement(bricklink_data, ebay_data),
        "exact_identification": _exact_identification(
            set_num, bricklink_data, ebay_data, exact_identification),
        "data_freshness": _data_freshness((bricklink_data, ebay_data), now),
    }
    available_weight = sum(FACTOR_WEIGHTS[name] for name, value in factors.items()
                           if value is not None)
    score = None
    if available_weight:
        score = sum(FACTOR_WEIGHTS[name] * value for name, value in factors.items()
                    if value is not None) / available_weight
        score = round(max(0.0, min(score, 1.0)), 4)
    reasons = [f"{name}={value:.2f}" for name, value in factors.items()
               if value is not None]
    missing = [name for name, value in factors.items() if value is None]
    if missing:
        reasons.append("unavailable=" + ",".join(missing))
    return ConfidenceResult(score, _label(score), reasons, factors)
