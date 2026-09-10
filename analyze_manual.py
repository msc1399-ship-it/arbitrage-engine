import argparse
from opportunity_engine.scoring import evaluate
from opportunity_engine.max_buy_price import max_buy_price_for_target

def main():
    p = argparse.ArgumentParser()
    p.add_argument("purchase_price", type=float)
    p.add_argument("expected_sale_price", type=float)
    p.add_argument("--confidence", type=float, default=0.8)
    p.add_argument("--sales-6m", type=int, default=10)
    args = p.parse_args()

    opp = evaluate(
        purchase_price=args.purchase_price,
        expected_sale_price=args.expected_sale_price,
        confidence=args.confidence,
        sales_6m=args.sales_6m,
    )
    ceiling = max_buy_price_for_target(args.expected_sale_price)

    print("OPPORTUNITY")
    print(opp)
    print("\nMAX BUY PRICE")
    print(ceiling)

if __name__ == "__main__":
    main()
