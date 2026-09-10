from dataclasses import dataclass
from math import isfinite

@dataclass
class LotItem:
    item_no: str
    quantity: int
    conservative_unit_value: float
    completeness_factor: float = 1.0

@dataclass
class LotResult:
    asking_price: float
    gross_value: float
    adjusted_value: float
    selling_fees: float
    estimated_costs: float
    expected_profit: float
    expected_roi: float
    decision: str

def analyze_lot(
    asking_price: float,
    items: list[LotItem],
    selling_fee_rate: float = 0.10,
    shipping_total: float = 20.0,
    packaging_total: float = 8.0,
    other_costs: float = 10.0,
    min_profit: float = 75.0,
    min_roi: float = 0.25,
) -> LotResult:
    values = [asking_price, selling_fee_rate, shipping_total, packaging_total, other_costs, min_profit, min_roi]
    if not items or any(not isfinite(v) or v < 0 for v in values) or asking_price <= 0 or selling_fee_rate >= 1:
        raise ValueError("Lote y precio positivo requeridos; costes no negativos")
    for item in items:
        if (not str(item.item_no).strip() or not isfinite(item.quantity) or item.quantity <= 0
                or item.quantity != int(item.quantity) or not isfinite(item.conservative_unit_value)
                or item.conservative_unit_value < 0 or not isfinite(item.completeness_factor)
                or not 0 <= item.completeness_factor <= 1):
            raise ValueError("Fila de lote no valida")
    gross = sum(i.quantity * i.conservative_unit_value for i in items)
    adjusted = sum(
        i.quantity * i.conservative_unit_value * i.completeness_factor
        for i in items
    )
    fees = adjusted * selling_fee_rate
    costs = fees + shipping_total + packaging_total + other_costs
    profit = adjusted - asking_price - costs
    roi = profit / asking_price if asking_price > 0 else -1

    decision = "PAPER_BUY" if (profit >= min_profit and roi >= min_roi) else "REJECT"

    return LotResult(
        asking_price=round(asking_price, 2),
        gross_value=round(gross, 2),
        adjusted_value=round(adjusted, 2),
        selling_fees=round(fees, 2),
        estimated_costs=round(costs, 2),
        expected_profit=round(profit, 2),
        expected_roi=round(roi, 4),
        decision=decision,
    )
