import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
from dashboard.data_loader import apply_market_history, load_catalog, build_radar_frame, load_paper_trades
from dashboard.components import radar_view, analyzer_view, lots_view, paper_view, system_view

st.set_page_config(page_title="Arbitrage Engine LEGO V0.6", layout="wide")
st.title("ARBITRAGE ENGINE — LEGO V0.6")
st.caption("PAPER TRADING")
try:
    catalog = load_catalog()
    radar = apply_market_history(build_radar_frame(catalog))
    paper = load_paper_trades()
except (OSError, ValueError, pd.errors.ParserError) as exc:
    st.error(f"No se pudieron cargar los datos: {exc}")
    st.stop()

open_profit = pd.to_numeric(paper.loc[paper.status.eq("OPEN"), "expected_profit"], errors="coerce").sum(min_count=1)
metrics = [("Capital inicial", "1.000 EUR"), ("Capital disponible", "1.000 EUR"),
           ("Capital inmovilizado", "0 EUR"), ("Beneficio realizado", "0 EUR"),
           ("Beneficio esperado (paper)", "PENDING" if pd.isna(open_profit) else f"{open_profit:.2f} EUR")]
for col, (label, value) in zip(st.columns(5), metrics):
    col.metric(label, value)

tabs = st.tabs(["RADAR", "OPORTUNIDADES", "ANALIZADOR", "LOTES", "PAPER TRADES", "CARTERA", "SISTEMA"])
with tabs[0]:
    radar_view(radar, paper)
with tabs[1]:
    st.dataframe(radar[radar.decision.isin(["PAPER_BUY", "WATCH"])], hide_index=True)
with tabs[2]:
    analyzer_view()
with tabs[3]:
    lots_view()
with tabs[4]:
    paper_view(paper)
with tabs[5]:
    st.info("NO REAL TRADES — PAPER TRADING PHASE")
    for col, (label, value) in zip(st.columns(4), [("Capital disponible", "1.000 EUR"),
            ("Capital inmovilizado", "0 EUR"), ("Inventario", "0"), ("Beneficio realizado", "0 EUR")]):
        col.metric(label, value)
    st.dataframe(pd.DataFrame(columns=["set_num", "purchase_date", "purchase_price", "total_acquisition_cost",
        "expected_sale_price", "listed_price", "sale_price", "status", "days_held", "realized_profit", "realized_roi"]), hide_index=True)
with tabs[6]:
    system_view(catalog, radar)
