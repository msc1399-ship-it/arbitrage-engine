from __future__ import annotations

from dataclasses import asdict

from models.market_data import AggregatedMarketData, DerivedMetrics, MarketData
from opportunity_engine.max_buy_price import max_buy_price_for_target
from opportunity_engine.scoring import evaluate
from services.confidence_engine import calculate_confidence

PENDING = "PENDING MARKET DATA"


def _source_with_value(records, field):
    for source, record in records:
        if record is not None and getattr(record, field) is not None:
            return source, getattr(record, field)
    return None, None


def aggregate_market_data(*, set_num, identity_data=None, bricklink_data=None,
                          ebay_data=None, exact_identification=None, now=None):
    for record in (bricklink_data, ebay_data):
        if record and record.set_num and record.set_num != set_num:
            raise ValueError(f"Market data set_num {record.set_num} does not match {set_num}")

    sold_records = [("BRICKLINK", bricklink_data), ("EBAY", ebay_data)]
    listing_records = [("EBAY", ebay_data), ("BRICKLINK", bricklink_data)]
    sales_source, sales_6m = _source_with_value(sold_records, "sales_6m")
    value_source, conservative_value = _source_with_value(sold_records, "sold_price_p25")
    listing_source, active_count = _source_with_value(listing_records, "active_listing_count")
    asking_source, asking_price = _source_with_value(listing_records, "asking_price_min")
    confidence = calculate_confidence(
        set_num=set_num, bricklink_data=bricklink_data, ebay_data=ebay_data,
        exact_identification=exact_identification, now=now,
    )

    sources = {}
    for metric, source in (
        ("sales_6m", sales_source), ("conservative_value", value_source),
        ("active_listing_count", listing_source), ("asking_price", asking_source),
    ):
        if source:
            sources[metric] = source

    monthly_sales = round(sales_6m / 6, 4) if sales_6m is not None else None
    demand_supply_ratio = None
    if monthly_sales is not None and active_count is not None and active_count > 0:
        demand_supply_ratio = round(monthly_sales / active_count, 4)

    max_buy_price = None
    if conservative_value is not None:
        max_buy_price = max_buy_price_for_target(conservative_value)["max_buy_price"]

    expected_days = expected_profit = expected_roi = capital_efficiency = score = None
    decision = PENDING
    required = (asking_price, conservative_value, sales_6m, confidence.confidence_score)
    if all(value is not None for value in required):
        result = evaluate(
            purchase_price=asking_price, expected_sale_price=conservative_value,
            confidence=confidence.confidence_score, sales_6m=sales_6m,
            active_listings=active_count,
        )
        baseline = evaluate(
            purchase_price=asking_price, expected_sale_price=conservative_value,
            confidence=max(confidence.confidence_score, 0.70), sales_6m=sales_6m,
            active_listings=active_count,
        )
        expected_days = result.expected_days_to_sell
        expected_profit = result.expected_profit
        expected_roi = result.expected_roi
        capital_efficiency = result.capital_efficiency
        score = result.score
        if baseline.decision == "REJECT":
            decision = "REJECT"
        elif confidence.confidence_score < 0.55:
            decision = "REJECT"
        elif confidence.confidence_score < 0.70:
            decision = "WATCH"
        else:
            decision = baseline.decision
    elif monthly_sales is not None and monthly_sales > 0:
        expected_days = round(30 / monthly_sales, 1)

    metrics = DerivedMetrics(
        monthly_sales=monthly_sales, expected_days_to_sell=expected_days,
        demand_supply_ratio=demand_supply_ratio,
        conservative_value=conservative_value, max_buy_price=max_buy_price,
        expected_profit=expected_profit, expected_roi=expected_roi,
        capital_efficiency=capital_efficiency, score=score,
        confidence_score=confidence.confidence_score,
        confidence_label=confidence.confidence_label,
        confidence_reasons=confidence.confidence_reasons,
        confidence_factors=confidence.confidence_factors,
        decision=decision,
        sources=sources,
    )
    return AggregatedMarketData(
        set_num=set_num, identity_data=identity_data,
        bricklink_data=bricklink_data, ebay_data=ebay_data,
        derived_metrics=metrics,
    )


def aggregate_as_dict(**kwargs):
    return asdict(aggregate_market_data(**kwargs))
