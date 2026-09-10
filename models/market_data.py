from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MarketData:
    set_num: str | None = None
    marketplace: str | None = None
    condition: str | None = None
    currency: str | None = None
    observed_at: datetime | None = None
    active_listing_count: int | None = None
    asking_price_min: float | None = None
    asking_price_median: float | None = None
    asking_price_p25: float | None = None
    sales_6m: int | None = None
    monthly_sales: float | None = None
    sold_price_min: float | None = None
    sold_price_median: float | None = None
    sold_price_p25: float | None = None
    sold_price_weighted_avg: float | None = None
    expected_days_to_sell: float | None = None
    confidence: float | None = None
    raw_data: Any | None = None


@dataclass(frozen=True)
class DerivedMetrics:
    monthly_sales: float | None = None
    expected_days_to_sell: float | None = None
    demand_supply_ratio: float | None = None
    conservative_value: float | None = None
    max_buy_price: float | None = None
    expected_profit: float | None = None
    expected_roi: float | None = None
    capital_efficiency: float | None = None
    score: float | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    confidence_reasons: list[str] = field(default_factory=list)
    confidence_factors: dict[str, float | None] = field(default_factory=dict)
    decision: str = "PENDING MARKET DATA"
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AggregatedMarketData:
    set_num: str
    identity_data: dict[str, Any] | None
    bricklink_data: MarketData | None
    ebay_data: MarketData | None
    derived_metrics: DerivedMetrics
