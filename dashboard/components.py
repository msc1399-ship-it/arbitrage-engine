from dataclasses import asdict
from datetime import datetime

import pandas as pd
import streamlit as st

from dashboard.data_loader import CATALOG_PATH, PAPER_STATUSES, append_paper_trade, update_paper_trade
from opportunity_engine.scoring import evaluate
from opportunity_engine.max_buy_price import max_buy_price_for_target
from opportunity_engine.lot_analyzer import LotItem, analyze_lot
from services.system_status import connector_statuses
from services.market_refresh import MarketRefreshPipeline
from services.ebay_refresh import EbayRefreshPipeline
from services.market_store import MarketStore


def show_values(row, fields):
    st.dataframe(pd.DataFrame({"Campo": fields, "Valor": [
        "PENDING" if pd.isna(row.get(key)) else str(row[key]) for key in fields]}), hide_index=True)


def radar_view(radar, paper):
    counts = [("Sets", len(radar)), ("Con valoracion", radar.conservative_value.notna().sum()),
        ("Tradeables", radar.decision.eq("PAPER_BUY").sum()),
        ("Oportunidades", radar.decision.isin(["PAPER_BUY", "WATCH"]).sum()),
        ("PAPER_BUY activos", (paper.decision.eq("PAPER_BUY") & paper.status.eq("OPEN")).sum())]
    for col, (label, count) in zip(st.columns(5), counts):
        col.metric(label, int(count))
    filtered = radar.copy()
    with st.expander("Filtros"):
        cols = st.columns(3)
        for column, label, container in [("year", "Anos", cols[0]), ("theme_id", "Temas", cols[1]),
                                          ("decision", "Decision", cols[2]),
                                          ("market_status", "Estado de mercado", cols[0]),
                                          ("ebay_status", "EBAY DATA", cols[1])]:
            selected = container.multiselect(label, sorted(radar[column].dropna().unique().tolist()))
            if selected:
                filtered = filtered[filtered[column].isin(selected)]
        for i, (column, label, upper) in enumerate([
            ("num_parts", "Piezas minimas", False), ("num_parts", "Piezas maximas", True),
            ("max_buy_price", "MAX BUY PRICE hasta (EUR)", True), ("expected_roi", "ROI minimo (%)", False),
            ("monthly_sales", "Ventas/mes minimas", False), ("score", "Score minimo", False),
            ("confidence_score", "Confianza minima", False)]):
            limit = cols[i % 3].number_input(label, min_value=0.0, value=None, key=f"filter_{i}")
            if limit is not None:
                limit = limit / 100 if column == "expected_roi" else limit
                values = pd.to_numeric(filtered[column], errors="coerce")
                filtered = filtered[values.le(limit) if upper else values.ge(limit)]
    st.dataframe(filtered, hide_index=True)
    selected = st.selectbox("Set", filtered.set_num.tolist(), index=None)
    if selected is not None:
        st.session_state["selected_market_set"] = selected
        row = filtered[filtered.set_num.eq(selected)].iloc[0]
        st.subheader(f"{row.set_num} | {row['name']}")
        left, right = st.columns([1, 3])
        with left:
            url = row.get("set_img_url")
            if pd.notna(url) and str(url).startswith("https://"):
                st.image(url, width=240)
            show_values(row, ["year", "num_parts"])
        with right:
            st.write(row.decision)
            for title, fields in [
                ("MERCADO", ["market_value", "conservative_value", "sales_6m", "monthly_sales", "active_listings", "expected_days_to_sell"]),
                ("OPERACION", ["current_listing_price", "max_buy_price", "expected_profit", "expected_roi", "capital_efficiency", "profit_per_30_days"]),
                ("RIESGO", ["confidence", "liquidity_score", "rotation_label"])]:
                st.write(title)
                show_values(row, fields)
            st.write("CONFIDENCE ENGINE")
            show_values(row, ["confidence_score", "confidence_label", "market_status", "last_market_refresh"])
            st.write("EBAY ASKING PRICE — NO SOLD PRICE")
            show_values(row, [
                "ebay_status", "ebay_full_set_count", "ebay_asking_reference_new",
                "ebay_new_median", "ebay_asking_reference_used", "ebay_used_median",
                "ebay_retrieval_yield", "ebay_uncertain_rate",
                "ebay_price_stability", "ebay_last_refresh",
            ])
            factors = row.get("confidence_factors")
            if isinstance(factors, dict):
                st.dataframe(pd.DataFrame(factors.items(), columns=["Factor", "Score"]), hide_index=True)
            reasons = row.get("confidence_reasons")
            if isinstance(reasons, list):
                st.write("; ".join(reasons))


def analyzer_view():
    with st.form("analyzer"):
        set_num = st.text_input("set_num")
        cols = st.columns(3)
        purchase = cols[0].number_input("Precio compra", min_value=0.01, value=None)
        sale = cols[1].number_input("Valor conservador", min_value=0.0, value=None)
        confidence = cols[2].number_input("Confianza", min_value=0.0, max_value=1.0, value=None)
        sales = cols[0].number_input("Ventas 6m", min_value=0, value=None)
        listings = cols[1].number_input("Listings activos", min_value=0, value=None)
        submitted = st.form_submit_button("Analizar")
    if submitted:
        st.session_state.pop("analysis", None)
        if any(v is None for v in [purchase, sale, confidence, sales]):
            st.info("PENDING MARKET DATA")
        else:
            try:
                opp = evaluate(purchase, sale, confidence, sales, listings)
                st.session_state.analysis = {"set_num": set_num, **asdict(opp), **max_buy_price_for_target(sale)}
            except ValueError as exc:
                st.error(str(exc))
    if "analysis" in st.session_state:
        row = st.session_state.analysis
        st.subheader(row["decision"])
        st.metric("MAX BUY PRICE", f"{row['max_buy_price']:.2f} EUR")
        show_values(row, ["set_num", "purchase_price", "expected_sale_price", "selling_fees", "shipping", "packaging",
            "other_costs", "expected_profit", "expected_roi", "monthly_sales", "expected_days_to_sell",
            "capital_efficiency", "profit_per_30_days", "rotation_label", "score"])
        if row["reasons"]:
            st.write(", ".join(row["reasons"]))


def lots_view():
    with st.form("lots"):
        price = st.number_input("Precio total lote", min_value=0.01, value=None)
        items = st.data_editor(pd.DataFrame({"set_num": pd.Series(dtype=str), "cantidad": pd.Series(dtype=int),
            "valor_conservador": pd.Series(dtype=float), "completeness_factor": pd.Series(dtype=float)}),
            num_rows="dynamic", hide_index=True, key="lot_rows")
        submitted = st.form_submit_button("Analizar lote")
    if submitted:
        try:
            if price is None or items.empty or items.isna().any().any():
                raise ValueError("Completa el precio y todas las filas del lote")
            result = analyze_lot(price, [LotItem(str(r.set_num), float(r.cantidad), float(r.valor_conservador),
                float(r.completeness_factor)) for r in items.itertuples()])
            st.subheader(result.decision)
            show_values(asdict(result), ["gross_value", "adjusted_value", "selling_fees", "estimated_costs", "expected_profit", "expected_roi"])
        except (ValueError, TypeError) as exc:
            st.error(str(exc))


def paper_view(paper):
    st.dataframe(paper, hide_index=True)
    analysis = st.session_state.get("analysis")
    if analysis and analysis.get("set_num"):
        with st.form("register_paper"):
            st.write(f"{analysis['set_num']} | {analysis['decision']}")
            marketplace = st.text_input("Marketplace")
            url = st.text_input("URL origen")
            notes = st.text_area("Notas")
            if st.form_submit_button("Registrar PAPER TRADE"):
                append_paper_trade({**analysis, "asking_price": analysis["purchase_price"],
                    "source_marketplace": marketplace, "source_url": url, "notes": notes})
                st.rerun()
    else:
        st.info("Sin oportunidad analizada con set_num")
    if not paper.empty:
        trade_id = st.selectbox("Operacion", paper.id.astype(str).tolist())
        row = paper[paper.id.astype(str).eq(trade_id)].iloc[0]
        with st.form(f"update_{trade_id}"):
            status = st.selectbox("Estado", PAPER_STATUSES, index=PAPER_STATUSES.index(row.status) if row.status in PAPER_STATUSES else 0)
            observed = st.number_input("Precio final observado", min_value=0.0,
                value=None if pd.isna(row.final_observed_price) else float(row.final_observed_price))
            outcome = st.text_input("Resultado", value="" if pd.isna(row.outcome) else str(row.outcome))
            notes = st.text_area("Notas de seguimiento", value="" if pd.isna(row.notes) else str(row.notes))
            if st.form_submit_button("Guardar seguimiento"):
                update_paper_trade(trade_id, status, observed, outcome, notes)
                st.rerun()


def system_view(catalog, radar):
    statuses = connector_statuses()
    st.dataframe(pd.DataFrame(statuses.items(), columns=["Conector", "Estado"]), hide_index=True)
    store = MarketStore()
    summary = store.status_summary()
    columns = st.columns(4)
    columns[0].metric("Ultimo refresh", summary["last_refresh"] or "PENDING")
    columns[1].metric("Sets actualizados", summary["updated"])
    columns[2].metric("Sets pendientes", max(len(catalog) - summary["updated"] - summary["errors"], 0))
    columns[3].metric("Sets con error", summary["errors"])
    ebay_summary = store.ebay_status_summary()
    ebay_columns = st.columns(5)
    ebay_columns[0].metric("Ultimo refresh eBay", ebay_summary["last_refresh"] or "PENDING")
    ebay_columns[1].metric("eBay GOOD", ebay_summary["good"])
    ebay_columns[2].metric("eBay PARTIAL", ebay_summary["partial"])
    ebay_columns[3].metric("eBay REVIEW", ebay_summary["review"])
    ebay_columns[4].metric("eBay INSUFFICIENT", ebay_summary["insufficient"])
    market_ready = statuses["BrickLink"] == "ACTIVE"
    scope = st.selectbox("Alcance", ["Set seleccionado", "Top N", "Todos"], key="refresh_scope")
    top_n = st.number_input("N", min_value=1, max_value=max(len(radar), 1), value=min(10, max(len(radar), 1)),
                            disabled=scope != "Top N")
    selected = st.session_state.get("selected_market_set")
    disabled = not market_ready or (scope == "Set seleccionado" and not selected)
    if st.button("Actualizar datos de mercado", disabled=disabled):
        if scope == "Set seleccionado":
            set_nums = [selected]
        elif scope == "Top N":
            set_nums = radar.head(int(top_n)).set_num.astype(str).tolist()
        else:
            set_nums = radar.set_num.astype(str).tolist()
        with st.spinner("Actualizando datos de mercado..."):
            batch = MarketRefreshPipeline.from_environment(store=store).refresh_sets(set_nums)
        errors = sum(item.market_status == "ERROR" for item in batch.results)
        st.success(f"Refresh terminado: {len(batch.results)} sets, {errors} errores")
        st.rerun()
    st.write("ACTUALIZAR EBAY")
    ebay_scope = st.selectbox(
        "Alcance eBay", ["Set seleccionado", "Top N", "Batch personalizado"],
        key="ebay_refresh_scope",
    )
    ebay_top_n = st.number_input(
        "N eBay", min_value=1, max_value=max(len(radar), 1),
        value=min(10, max(len(radar), 1)), disabled=ebay_scope != "Top N",
    )
    custom_sets = st.text_area(
        "Sets eBay", disabled=ebay_scope != "Batch personalizado",
        placeholder="10295-1, 75308-1",
    )
    custom_values = [
        value.strip() for value in custom_sets.replace("\n", ",").split(",")
        if value.strip()
    ]
    ebay_ready = statuses["eBay"] == "ACTIVE"
    ebay_disabled = (
        not ebay_ready
        or (ebay_scope == "Set seleccionado" and not selected)
        or (ebay_scope == "Batch personalizado" and not custom_values)
    )
    if st.button("Actualizar eBay", disabled=ebay_disabled):
        if ebay_scope == "Set seleccionado":
            set_nums = [selected]
        elif ebay_scope == "Top N":
            set_nums = radar.head(int(ebay_top_n)).set_num.astype(str).tolist()
        else:
            set_nums = custom_values
        with st.spinner("Actualizando oferta activa eBay..."):
            batch = EbayRefreshPipeline.from_environment(store=store).refresh_sets(set_nums)
        errors = sum(item.error is not None for item in batch.results)
        st.success(f"eBay terminado: {len(batch.results)} sets, {errors} errores")
        st.rerun()
    st.metric("Sets cargados", len(catalog))
    st.write("Ultima actualizacion catalogo:", datetime.fromtimestamp(CATALOG_PATH.stat().st_mtime).isoformat(timespec="seconds") if CATALOG_PATH.exists() else "PENDING")
    st.write("Version motor: V0.7")
    st.write("Fase: PAPER TRADING")
