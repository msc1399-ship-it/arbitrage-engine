from config import CONFIG
from math import floor, isfinite

def max_buy_price_for_target(
    expected_sale_price: float,
    min_profit: float | None = None,
    min_roi: float | None = None,
    selling_fee_rate: float | None = None,
    shipping: float | None = None,
    packaging: float | None = None,
    other_costs: float | None = None,
) -> dict:
    min_profit = CONFIG.min_expected_profit_eur if min_profit is None else min_profit
    min_roi = CONFIG.min_expected_roi if min_roi is None else min_roi
    selling_fee_rate = (
        CONFIG.assumed_selling_fee_rate + CONFIG.assumed_payment_fee_rate
        if selling_fee_rate is None
        else selling_fee_rate
    )
    shipping = CONFIG.default_shipping_eur if shipping is None else shipping
    packaging = CONFIG.default_packaging_eur if packaging is None else packaging
    other_costs = CONFIG.default_other_costs_eur if other_costs is None else other_costs
    values = [expected_sale_price, min_profit, min_roi, selling_fee_rate, shipping, packaging, other_costs]
    if any(not isfinite(v) or v < 0 for v in values) or selling_fee_rate >= 1:
        raise ValueError("Valores no negativos y comision inferior a 1 requeridos")

    fixed_costs = shipping + packaging + other_costs
    sale_net_before_purchase = expected_sale_price * (1 - selling_fee_rate) - fixed_costs

    # Constraint 1: absolute profit
    by_profit = sale_net_before_purchase - min_profit

    # Constraint 2: ROI = profit / purchase >= min_roi
    # sale_net_before_purchase - purchase >= min_roi * purchase
    # purchase <= sale_net_before_purchase / (1 + min_roi)
    by_roi = sale_net_before_purchase / (1 + min_roi)

    max_buy = min(by_profit, by_roi, CONFIG.max_purchase_price_eur)
    return {
        "expected_sale_price": round(expected_sale_price, 2),
        "max_buy_price": floor(max(max_buy, 0) * 100 + 1e-9) / 100,
        "constraint_profit_price": round(max(by_profit, 0), 2),
        "constraint_roi_price": round(max(by_roi, 0), 2),
    }
