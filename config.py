from dataclasses import dataclass

@dataclass(frozen=True)
class StrategyConfig:
    currency: str = "EUR"

    # Capital rules
    starting_capital_eur: float = 1000.0
    max_purchase_price_eur: float = 300.0
    max_capital_per_trade_pct: float = 0.25

    # Opportunity rules
    min_expected_profit_eur: float = 50.0
    min_expected_roi: float = 0.20
    min_sales_6m: int = 5
    min_confidence: float = 0.70
    target_margin_of_safety: float = 0.15

    # Cost assumptions V0
    assumed_selling_fee_rate: float = 0.10
    assumed_payment_fee_rate: float = 0.00
    default_shipping_eur: float = 8.0
    default_packaging_eur: float = 2.0
    default_other_costs_eur: float = 3.0

    # Paper trading
    paper_trade_days: int = 14
    review_after_hours: int = 24
    stale_after_days: int = 21

CONFIG = StrategyConfig()
