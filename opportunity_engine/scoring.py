from dataclasses import dataclass
from math import isfinite
from config import CONFIG

@dataclass
class Opportunity:
    purchase_price: float
    expected_sale_price: float
    selling_fees: float
    shipping: float
    packaging: float
    other_costs: float
    expected_profit: float
    expected_roi: float
    monthly_sales: float
    expected_days_to_sell: float
    capital_efficiency: float
    profit_per_30_days: float
    liquidity_score: float
    rotation_label: str
    score: float
    decision: str
    reasons: list[str]

def rotation_label_for_monthly_sales(monthly_sales: float) -> str:
    if monthly_sales < 1:
        return "MUY BAJA"
    if monthly_sales < 2:
        return "BAJA"
    if monthly_sales < 5:
        return "ACEPTABLE"
    if monthly_sales <= 10:
        return "ALTA"
    return "MUY ALTA"

def evaluate(purchase_price, expected_sale_price, confidence, sales_6m,
             active_listings=None, shipping=None, packaging=None, other_costs=None):
    selling_fees = expected_sale_price * (
        CONFIG.assumed_selling_fee_rate + CONFIG.assumed_payment_fee_rate
    )
    shipping = CONFIG.default_shipping_eur if shipping is None else shipping
    packaging = CONFIG.default_packaging_eur if packaging is None else packaging
    other_costs = CONFIG.default_other_costs_eur if other_costs is None else other_costs
    values = [purchase_price, expected_sale_price, confidence, sales_6m, shipping, packaging, other_costs]
    if active_listings is not None:
        values.append(active_listings)
    if any(not isfinite(v) or v < 0 for v in values) or purchase_price <= 0 or confidence > 1:
        raise ValueError("Precios y costes validos, compra positiva y confianza entre 0 y 1 requeridos")
    if sales_6m != int(sales_6m):
        raise ValueError("Ventas 6m debe ser un entero")

    profit = expected_sale_price - purchase_price - selling_fees - shipping - packaging - other_costs
    roi = profit / purchase_price if purchase_price > 0 else -1

    monthly_sales = sales_6m / 6.0
    expected_days_to_sell = 30.0 / monthly_sales if monthly_sales > 0 else 9999.0

    if active_listings is not None and active_listings > 0:
        demand_supply = monthly_sales / active_listings
        expected_days_to_sell *= max(min(1 / max(demand_supply, 0.05), 3.0), 0.5)

    capital_efficiency = 0.0
    if purchase_price > 0 and expected_days_to_sell > 0:
        capital_efficiency = (profit / purchase_price) * (30.0 / expected_days_to_sell) * 100

    profit_per_30_days = 0.0
    if expected_days_to_sell > 0:
        profit_per_30_days = profit * (30.0 / expected_days_to_sell)

    if monthly_sales > 10: liquidity_score = 1.0
    elif monthly_sales >= 5: liquidity_score = 0.85
    elif monthly_sales >= 2: liquidity_score = 0.65
    elif monthly_sales >= 1: liquidity_score = 0.35
    else: liquidity_score = 0.10

    roi_score = min(max(roi / 0.40, 0), 1.0)
    profit_score = min(max(profit / 100, 0), 1.0)
    efficiency_score = min(max(capital_efficiency / 40, 0), 1.0)

    score = 100 * (
        0.25 * roi_score +
        0.20 * profit_score +
        0.25 * liquidity_score +
        0.15 * confidence +
        0.10 * efficiency_score +
        0.05 * min(max(1 - purchase_price / max(CONFIG.starting_capital_eur, 1), 0), 1)
    )

    reasons = []
    hard_reject = []
    if purchase_price > CONFIG.max_purchase_price_eur: hard_reject.append("ticket_exceeds_limit")
    if monthly_sales < 2: hard_reject.append("rotation_below_2_sales_month")
    if expected_days_to_sell > 45: hard_reject.append("expected_days_to_sell_above_45")
    if confidence < CONFIG.min_confidence: hard_reject.append("confidence_below_minimum")

    if profit < CONFIG.min_expected_profit_eur: reasons.append("profit_below_minimum")
    if roi < CONFIG.min_expected_roi: reasons.append("roi_below_minimum")
    reasons = hard_reject + reasons

    decision = "REJECT"
    if not reasons:
        decision = "PAPER_BUY"
    elif not hard_reject:
        near_profit = profit >= CONFIG.min_expected_profit_eur * 0.9
        near_roi = roi >= CONFIG.min_expected_roi * 0.9
        has_rotation = monthly_sales >= 2 and expected_days_to_sell <= 45
        has_confidence = confidence >= CONFIG.min_confidence
        if has_rotation and has_confidence and near_profit and near_roi:
            decision = "WATCH"

    return Opportunity(
        round(purchase_price, 2), round(expected_sale_price, 2), round(selling_fees, 2),
        round(shipping, 2), round(packaging, 2), round(other_costs, 2),
        round(profit, 2), round(roi, 4), round(monthly_sales, 2),
        round(expected_days_to_sell, 1), round(capital_efficiency, 2),
        round(profit_per_30_days, 2), round(liquidity_score, 4),
        rotation_label_for_monthly_sales(monthly_sales), round(score, 1),
        decision, reasons
    )
