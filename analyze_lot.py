import argparse
import csv
from opportunity_engine.lot_analyzer import LotItem, analyze_lot

def main():
    p = argparse.ArgumentParser()
    p.add_argument("asking_price", type=float)
    p.add_argument("csv_file")
    args = p.parse_args()

    items = []
    with open(args.csv_file, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            items.append(LotItem(
                item_no=row["item_no"],
                quantity=int(row["quantity"]),
                conservative_unit_value=float(row["conservative_unit_value"]),
                completeness_factor=float(row.get("completeness_factor") or 1.0),
            ))

    result = analyze_lot(args.asking_price, items)
    print(result)

if __name__ == "__main__":
    main()
