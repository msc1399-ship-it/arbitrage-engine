import argparse
from collectors.bricklink import BrickLinkClient
from valuation.bricklink_valuation import build_valuation
from opportunity_engine.scoring import evaluate

def main():
    p = argparse.ArgumentParser()
    p.add_argument("set_no", help="BrickLink set number, e.g. 10295-1")
    p.add_argument("purchase_price", type=float)
    p.add_argument("--condition", choices=["N", "U"], default="U")
    args = p.parse_args()

    client = BrickLinkClient()
    item = client.get_item(args.set_no)
    guide = client.get_price_guide(args.set_no, condition=args.condition)
    val = build_valuation(args.set_no, args.condition, guide)
    opp = evaluate(
        purchase_price=args.purchase_price,
        expected_sale_price=val.conservative_value,
        confidence=val.confidence,
        sales_6m=val.sales_count,
    )

    print("\nITEM")
    print(item)
    print("\nVALUATION")
    print(val)
    print("\nOPPORTUNITY")
    print(opp)

if __name__ == "__main__":
    main()
