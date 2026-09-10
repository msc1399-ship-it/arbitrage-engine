from opportunity_engine.scoring import evaluate
from opportunity_engine.max_buy_price import max_buy_price_for_target
from opportunity_engine.lot_analyzer import LotItem, analyze_lot

def test_good_trade():
    x = evaluate(100, 200, 0.9, 20)
    assert x.expected_profit > 50
    assert x.expected_roi > 0.20
    assert x.decision == "PAPER_BUY"

def test_bad_trade_profit():
    x = evaluate(100, 140, 0.9, 20)
    assert x.decision == "REJECT"

def test_max_buy_price_positive():
    x = max_buy_price_for_target(200)
    assert x["max_buy_price"] > 0

def test_lot():
    items = [
        LotItem("A", 1, 150, 1.0),
        LotItem("B", 1, 120, 0.9),
        LotItem("C", 1, 100, 1.0),
    ]
    x = analyze_lot(180, items)
    assert x.expected_profit > 0
