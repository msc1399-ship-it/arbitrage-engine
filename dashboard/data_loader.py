from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd

from opportunity_engine.max_buy_price import max_buy_price_for_target
from opportunity_engine.scoring import evaluate, rotation_label_for_monthly_sales
from services.market_store import MarketStore

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "lego_universe_v0.csv"
PAPER_TRADES_PATH = ROOT / "paper_trading" / "paper_trades.csv"

RADAR_COLUMNS = [
    "set_num",
    "name",
    "year",
    "num_parts",
    "theme_id",
    "market_value",
    "conservative_value",
    "max_buy_price",
    "current_listing_price",
    "expected_profit",
    "expected_roi",
    "sales_6m",
    "monthly_sales",
    "expected_days_to_sell",
    "active_listings",
    "liquidity_score",
    "confidence",
    "confidence_score",
    "confidence_label",
    "capital_efficiency",
    "profit_per_30_days",
    "rotation_label",
    "score",
    "decision",
    "market_status",
    "last_market_refresh",
]

MARKET_DETAIL_COLUMNS = ["confidence_reasons", "confidence_factors", "error_message"]

PAPER_TRADE_COLUMNS = [
    "id",
    "date",
    "set_num",
    "source_marketplace",
    "source_url",
    "asking_price",
    "expected_sale_price",
    "expected_profit",
    "expected_roi",
    "monthly_sales",
    "expected_days_to_sell",
    "score",
    "decision",
    "status",
    "final_observed_price",
    "outcome",
    "notes",
]


def load_catalog() -> pd.DataFrame:
    if not CATALOG_PATH.exists():
        return pd.DataFrame(columns=RADAR_COLUMNS + ["set_img_url", "set_url"])
    return pd.read_csv(CATALOG_PATH)


def build_radar_frame(catalog: pd.DataFrame) -> pd.DataFrame:
    df = catalog.copy()
    for col in RADAR_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    for col in ["year", "num_parts", "theme_id"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    market_cols = [
        "market_value",
        "conservative_value",
        "current_listing_price",
        "sales_6m",
        "monthly_sales",
        "expected_days_to_sell",
        "active_listings",
        "confidence",
    ]
    for col in market_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    derived = ["max_buy_price", "expected_profit", "expected_roi", "monthly_sales", "expected_days_to_sell",
               "liquidity_score", "capital_efficiency", "profit_per_30_days", "rotation_label", "score"]
    for col in derived:
        df[col] = pd.Series(pd.NA, index=df.index, dtype="object")
    df["decision"] = "PENDING MARKET DATA"
    df["market_status"] = "PENDING"
    df["last_market_refresh"] = pd.NA
    df["confidence_score"] = pd.NA
    df["confidence_label"] = pd.NA
    for col in MARKET_DETAIL_COLUMNS:
        df[col] = pd.NA

    for idx, row in df.iterrows():
        conservative = row.get("conservative_value")
        listing = row.get("current_listing_price")
        sales_6m = row.get("sales_6m")
        confidence = row.get("confidence")

        if pd.notna(conservative) and 0 <= conservative < float("inf"):
            ceiling = max_buy_price_for_target(float(conservative))
            df.at[idx, "max_buy_price"] = ceiling["max_buy_price"]

        if pd.notna(sales_6m) and 0 <= sales_6m < float("inf") and sales_6m == int(sales_6m):
            monthly_sales = float(sales_6m) / 6.0
            df.at[idx, "monthly_sales"] = round(monthly_sales, 2)
            df.at[idx, "rotation_label"] = rotation_label_for_monthly_sales(monthly_sales)

        if pd.notna(conservative) and pd.notna(listing) and pd.notna(sales_6m) and pd.notna(confidence):
            if (not 0 < listing < float("inf") or not 0 <= conservative < float("inf")
                    or not 0 <= confidence <= 1 or not 0 <= sales_6m < float("inf")
                    or sales_6m != int(sales_6m)
                    or (pd.notna(row.get("active_listings")) and not 0 <= row["active_listings"] < float("inf"))):
                continue
            opp = evaluate(
                purchase_price=float(listing),
                expected_sale_price=float(conservative),
                confidence=float(confidence),
                sales_6m=int(sales_6m),
                active_listings=None if pd.isna(row.get("active_listings")) else float(row.get("active_listings")),
            )
            df.at[idx, "expected_profit"] = opp.expected_profit
            df.at[idx, "expected_roi"] = opp.expected_roi
            df.at[idx, "monthly_sales"] = opp.monthly_sales
            df.at[idx, "expected_days_to_sell"] = opp.expected_days_to_sell
            df.at[idx, "liquidity_score"] = opp.liquidity_score
            df.at[idx, "capital_efficiency"] = opp.capital_efficiency
            df.at[idx, "profit_per_30_days"] = opp.profit_per_30_days
            df.at[idx, "rotation_label"] = opp.rotation_label
            df.at[idx, "score"] = opp.score
            df.at[idx, "decision"] = opp.decision

    return df[RADAR_COLUMNS + MARKET_DETAIL_COLUMNS + [c for c in ["set_img_url", "set_url"] if c in df.columns]].sort_values(
        by="score", ascending=False, na_position="last"
    )


def apply_market_history(radar, store=None):
    rows = (store or MarketStore()).latest_radar_rows()
    if not rows:
        return radar
    output = radar.copy()
    by_set = {str(row["set_num"]): row for row in rows}
    for idx, set_num in output["set_num"].astype(str).items():
        saved = by_set.get(set_num)
        if saved is None:
            continue
        for column, value in saved.items():
            if column != "set_num" and column in output.columns:
                output.at[idx, column] = value
        monthly = saved.get("monthly_sales")
        if monthly is not None:
            output.at[idx, "rotation_label"] = rotation_label_for_monthly_sales(monthly)
    return output.sort_values(by="score", ascending=False, na_position="last")


def ensure_paper_trades_file() -> None:
    PAPER_TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PAPER_TRADES_PATH.exists():
        pd.DataFrame(columns=PAPER_TRADE_COLUMNS).to_csv(PAPER_TRADES_PATH, index=False)


def load_paper_trades() -> pd.DataFrame:
    ensure_paper_trades_file()
    df = pd.read_csv(PAPER_TRADES_PATH)
    for col in PAPER_TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def append_paper_trade(record: dict) -> None:
    ensure_paper_trades_file()
    df = load_paper_trades()
    row = {col: record.get(col, pd.NA) for col in PAPER_TRADE_COLUMNS}
    row["id"] = row["id"] if pd.notna(row["id"]) else uuid4().hex[:12]
    row["date"] = row["date"] if pd.notna(row["date"]) else date.today().isoformat()
    row["status"] = row["status"] if pd.notna(row["status"]) else "OPEN"
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _save_paper_trades(df)


PAPER_STATUSES = ["OPEN", "WON", "LOST", "EXPIRED", "FALSE_POSITIVE"]


def _save_paper_trades(df):
    temporary = PAPER_TRADES_PATH.with_suffix(".tmp")
    df.to_csv(temporary, index=False)
    temporary.replace(PAPER_TRADES_PATH)


def update_paper_trade(trade_id, status, final_observed_price, outcome, notes):
    if status not in PAPER_STATUSES:
        raise ValueError("Estado no valido")
    df = load_paper_trades()
    mask = df["id"].astype(str) == str(trade_id)
    if mask.sum() != 1:
        raise ValueError("Operacion no encontrada o ID duplicado")
    for key, value in dict(status=status, final_observed_price=final_observed_price, outcome=outcome, notes=notes).items():
        df[key] = df[key].astype(object)
        df.loc[mask, key] = value
    _save_paper_trades(df)
