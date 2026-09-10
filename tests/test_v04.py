import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dashboard import data_loader as data
from opportunity_engine.scoring import evaluate, rotation_label_for_monthly_sales
from opportunity_engine.max_buy_price import max_buy_price_for_target
from opportunity_engine.lot_analyzer import LotItem, analyze_lot
from services import system_status


def test_high_roi_cannot_override_rotation():
    result = evaluate(50, 200, .9, 6)
    assert result.expected_roi > 1
    assert result.decision == "REJECT"
    assert "rotation_below_2_sales_month" in result.reasons


def test_long_sale_time_rejected():
    result = evaluate(50, 200, .9, 6, active_listings=100)
    assert result.expected_days_to_sell > 45
    assert result.decision == "REJECT"
    assert "expected_days_to_sell_above_45" in result.reasons


@pytest.mark.parametrize("sale", [100, 200, 350.01, 390.77, 600])
def test_ceiling_respects_all_constraints(sale):
    price = max_buy_price_for_target(sale)["max_buy_price"]
    result = evaluate(price, sale, .9, 30)
    assert result.expected_profit >= 50
    assert result.expected_roi >= .2
    assert price <= 300


def test_profit_per_30_days():
    result = evaluate(100, 200, .9, 18)
    assert result.profit_per_30_days == pytest.approx(result.expected_profit * 3)
    assert result.capital_efficiency == pytest.approx(result.expected_profit / 100 * 3 * 100)


@pytest.mark.parametrize("monthly,label", [(0,"MUY BAJA"),(1,"BAJA"),(2,"ACEPTABLE"),(5,"ALTA"),(10,"ALTA"),(11,"MUY ALTA")])
def test_rotation_boundaries(monthly, label):
    assert rotation_label_for_monthly_sales(monthly) == label


def test_watch_only_near_both_thresholds():
    assert evaluate(250, 344, .9, 30).decision == "WATCH"
    assert evaluate(100, 140, .9, 30).decision == "REJECT"
    assert evaluate(250, 344, .9, 6).decision == "REJECT"


def test_lot_thresholds_and_completeness():
    items = [LotItem("TEST", 2, 150, .8)]
    good = analyze_lot(100, items)
    assert good.gross_value == 300
    assert good.adjusted_value == 240
    assert good.expected_profit == 78
    assert good.decision == "PAPER_BUY"
    assert analyze_lot(120, items).decision == "REJECT"
    with pytest.raises(ValueError):
        analyze_lot(100, [LotItem("TEST", 1, 100, 1.1)])


def test_missing_market_does_not_reuse_stale_decision():
    frame = data.build_radar_frame(pd.DataFrame([{"set_num": "TEST", "score": 99, "decision": "PAPER_BUY"}]))
    assert frame.iloc[0].decision == "PENDING MARKET DATA"
    assert pd.isna(frame.iloc[0].score)
    assert pd.isna(frame.iloc[0].confidence)


def test_market_feed_and_invalid_data():
    frame = data.build_radar_frame(pd.DataFrame([
        {"set_num": "TEST", "conservative_value": 200, "current_listing_price": 100, "sales_6m": 30, "confidence": .9},
        {"set_num": "INVALID", "conservative_value": 200, "current_listing_price": 0, "sales_6m": 30, "confidence": .9}]))
    assert frame.iloc[0].decision == "PAPER_BUY"
    assert frame.iloc[1].decision == "PENDING MARKET DATA"


def test_paper_persistence_preserves_history(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "PAPER_TRADES_PATH", tmp_path / "paper.csv")
    assert data.load_paper_trades().empty
    data.append_paper_trade({"set_num": "TEST-A", "decision": "WATCH"})
    data.append_paper_trade({"set_num": "TEST-B", "decision": "PAPER_BUY"})
    before = data.load_paper_trades()
    data.update_paper_trade(before.iloc[0].id, "EXPIRED", None, "Expired", "Reviewed")
    after = data.load_paper_trades()
    assert len(after) == 2
    assert after.iloc[0].status == "EXPIRED"
    assert after.iloc[1].id == before.iloc[1].id


def test_connectors_without_credentials(monkeypatch):
    monkeypatch.setattr(system_status, "load_dotenv", lambda: None)
    for key in ["REBRICKABLE_API_KEY", "BRICKLINK_CONSUMER_KEY", "BRICKLINK_CONSUMER_SECRET", "BRICKLINK_TOKEN", "BRICKLINK_TOKEN_SECRET",
                "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"]:
        monkeypatch.delenv(key, raising=False)
    assert set(system_status.connector_statuses().values()) == {"PENDING"}
    monkeypatch.setenv("REBRICKABLE_API_KEY", "test-only")
    assert system_status.connector_statuses()["Rebrickable"] == "ACTIVE"


def test_dashboard_catalog_and_manual_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "PAPER_TRADES_PATH", tmp_path / "paper.csv")
    catalog = data.load_catalog()
    assert len(catalog) > 0
    assert "set_num" in catalog.columns
    app = AppTest.from_file(str(data.ROOT / "dashboard" / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["RADAR", "OPORTUNIDADES", "ANALIZADOR", "LOTES", "PAPER TRADES", "CARTERA", "SISTEMA"]
    market_button = next(b for b in app.button if b.label == "Actualizar datos de mercado")
    assert market_button.disabled
    app.selectbox[0].select(catalog.iloc[0].set_num).run()
    assert not app.exception
    for field in app.text_input:
        if field.label == "set_num":
            field.set_value("TEST")
    values = {"Precio compra": 100., "Valor conservador": 200., "Confianza": .9, "Ventas 6m": 30}
    for field in app.number_input:
        if field.label in values:
            field.set_value(values[field.label])
    next(b for b in app.button if b.label == "Analizar").click().run()
    assert not app.exception
    assert app.session_state["analysis"]["decision"] == "PAPER_BUY"
    next(b for b in app.button if b.label == "Registrar PAPER TRADE").click().run()
    assert not app.exception
    assert len(data.load_paper_trades()) == 1
    next(s for s in app.selectbox if s.label == "Estado").select("EXPIRED")
    next(b for b in app.button if b.label == "Guardar seguimiento").click().run()
    assert not app.exception
    assert data.load_paper_trades().iloc[0].status == "EXPIRED"
    next(n for n in app.number_input if n.label == "ROI minimo (%)").set_value(20.).run()
    assert not app.exception
    assert app.selectbox[0].options == []
