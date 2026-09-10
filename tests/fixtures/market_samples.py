from datetime import datetime, timezone

from models.market_data import MarketData

OBSERVED_AT = datetime.now(timezone.utc)


def bricklink_sales(set_num="TEST-1", *, sales_6m=60, p25=200, confidence=.9):
    return MarketData(
        set_num=set_num, marketplace="BRICKLINK", condition="U", currency="EUR",
        observed_at=OBSERVED_AT, sales_6m=sales_6m,
        monthly_sales=None if sales_6m is None else sales_6m / 6,
        sold_price_min=None if p25 is None else p25 - 20,
        sold_price_median=None if p25 is None else p25 + 20,
        sold_price_p25=p25, sold_price_weighted_avg=p25,
        confidence=confidence, raw_data={"fixture": True},
    )


def ebay_listings(set_num="TEST-1", *, count=5, asking_min=100, confidence=None):
    return MarketData(
        set_num=set_num, marketplace="EBAY", condition="Used", currency="EUR",
        observed_at=OBSERVED_AT, active_listing_count=count,
        asking_price_min=asking_min, asking_price_median=asking_min,
        asking_price_p25=asking_min, confidence=confidence,
        raw_data={"fixture": True},
    )


LIQUID_PRODUCT = (bricklink_sales(), ebay_listings())
ILLIQUID_PRODUCT = (bricklink_sales(sales_6m=5), ebay_listings())
GOOD_MARGIN_BAD_ROTATION = (bricklink_sales(sales_6m=5, p25=300), ebay_listings(asking_min=50))
GOOD_ROTATION_AND_MARGIN = (bricklink_sales(sales_6m=60, p25=200), ebay_listings(asking_min=100))
NO_SALES_HISTORY = (bricklink_sales(sales_6m=None, p25=None, confidence=None), ebay_listings())
NO_ACTIVE_LISTINGS = (bricklink_sales(), ebay_listings(count=None, asking_min=None))
