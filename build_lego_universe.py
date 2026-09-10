import argparse
import os
import time
import pandas as pd
from collectors.rebrickable import RebrickableClient

OUTPUT_COLUMNS = ["set_num", "name", "year", "theme_id", "num_parts", "set_img_url", "set_url"]

def normalize_sets_dataframe(df, min_year, max_year, min_parts):
    df = df.rename(columns={"img_url": "set_img_url"})
    required = ["set_num", "name", "year", "theme_id", "num_parts"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"El CSV no contiene columnas necesarias: {missing}")

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["num_parts"] = pd.to_numeric(df["num_parts"], errors="coerce")
    df = df[
        (df["year"] >= min_year) &
        (df["year"] <= max_year) &
        (df["num_parts"] >= min_parts)
    ].copy()

    for c in ["set_img_url", "set_url"]:
        if c not in df.columns:
            df[c] = ""

    return df[OUTPUT_COLUMNS].sort_values(["year", "num_parts"], ascending=[False, False])

def build_from_csv(csv_path, out, min_year, max_year, min_parts):
    df = pd.read_csv(csv_path)
    filtered = normalize_sets_dataframe(df, min_year, max_year, min_parts)
    filtered.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Saved {len(filtered)} sets to {out}")

def build_from_api(out, min_year, max_year, min_parts, delay, checkpoint):
    client = RebrickableClient()
    rows = []
    page = 1

    if os.path.exists(checkpoint):
        cp = pd.read_csv(checkpoint)
        if not cp.empty and "_page" in cp.columns:
            page = int(cp["_page"].max()) + 1
            rows = cp.drop(columns=["_page"]).to_dict("records")
            print(f"Reanudando desde página {page}")

    while True:
        payload = client.list_sets(
            page=page, page_size=100,
            min_year=min_year, max_year=max_year,
            ordering="-year",
        )

        batch = payload.get("results", [])
        for s in batch:
            num_parts = int(s.get("num_parts") or 0)
            if num_parts >= min_parts:
                rows.append({
                    "set_num": s.get("set_num"),
                    "name": s.get("name"),
                    "year": s.get("year"),
                    "theme_id": s.get("theme_id"),
                    "num_parts": num_parts,
                    "set_img_url": s.get("set_img_url"),
                    "set_url": s.get("set_url"),
                })

        checkpoint_rows = [dict(r, _page=page) for r in rows]
        pd.DataFrame(checkpoint_rows).drop_duplicates(subset=["set_num"]).to_csv(
            checkpoint, index=False, encoding="utf-8-sig"
        )
        print(f"Página {page}: {len(rows)} sets filtrados acumulados")

        if not payload.get("next"):
            break

        page += 1
        time.sleep(delay)

    df = pd.DataFrame(rows).drop_duplicates(subset=["set_num"])
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} sets to {out}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", help="Ruta al sets.csv oficial descargado desde Rebrickable")
    p.add_argument("--min-year", type=int, default=2010)
    p.add_argument("--max-year", type=int, default=2025)
    p.add_argument("--min-parts", type=int, default=300)
    p.add_argument("--out", default="lego_universe_v0.csv")
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--checkpoint", default="lego_universe_checkpoint.csv")
    args = p.parse_args()

    if args.csv:
        build_from_csv(args.csv, args.out, args.min_year, args.max_year, args.min_parts)
    else:
        print("AVISO: para catálogo masivo, Rebrickable recomienda usar su CSV de Downloads.")
        print("Usando API como fallback con pausas, reintentos y checkpoint.")
        build_from_api(args.out, args.min_year, args.max_year, args.min_parts, args.delay, args.checkpoint)

if __name__ == "__main__":
    main()
