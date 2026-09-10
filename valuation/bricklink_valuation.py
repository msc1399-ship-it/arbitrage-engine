from dataclasses import dataclass
from statistics import median

@dataclass
class MarketValuation:
    item_no: str
    condition: str
    sales_count: int
    min_price: float
    avg_price: float
    qty_avg_price: float
    median_price: float | None
    conservative_value: float
    confidence: float

def build_valuation(item_no: str, condition: str, price_guide: dict) -> MarketValuation:
    details = price_guide.get("price_detail") or []
    prices = []
    for row in details:
        try:
            qty = max(int(row.get("quantity", 1)), 1)
            unit_price = float(row["unit_price"])
            prices.extend([unit_price] * qty)
        except (KeyError, TypeError, ValueError):
            continue

    sales_count = int(price_guide.get("unit_quantity") or 0)
    min_price = float(price_guide.get("min_price") or 0)
    avg_price = float(price_guide.get("avg_price") or 0)
    qty_avg = float(price_guide.get("qty_avg_price") or 0)
    med = median(prices) if prices else None

    # V0 intentionally conservative:
    # use the lower of weighted average and median when detail is available,
    # then haircut another 10%.
    candidates = [x for x in (qty_avg, med) if x and x > 0]
    reference = min(candidates) if candidates else avg_price
    conservative = reference * 0.90 if reference else 0.0

    # Simple V0 confidence based mostly on transaction count.
    if sales_count >= 40:
        confidence = 0.95
    elif sales_count >= 20:
        confidence = 0.90
    elif sales_count >= 10:
        confidence = 0.82
    elif sales_count >= 5:
        confidence = 0.70
    else:
        confidence = 0.45

    return MarketValuation(
        item_no=item_no,
        condition=condition,
        sales_count=sales_count,
        min_price=min_price,
        avg_price=avg_price,
        qty_avg_price=qty_avg,
        median_price=med,
        conservative_value=round(conservative, 2),
        confidence=confidence,
    )
