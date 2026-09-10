import os
import statistics
from datetime import datetime, timezone

import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv

from models.market_data import MarketData
from services.http import ConnectorAuthenticationError, ConnectorError, request_with_backoff

load_dotenv()

BASE_URL = "https://api.bricklink.com/api/store/v1"

def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class BrickLinkClient:
    def __init__(self, consumer_key=None, consumer_secret=None, token=None,
                 token_secret=None, *, session=None, sleep=None, max_retries=4):
        required = {
            "BRICKLINK_CONSUMER_KEY": consumer_key or os.getenv("BRICKLINK_CONSUMER_KEY"),
            "BRICKLINK_CONSUMER_SECRET": consumer_secret or os.getenv("BRICKLINK_CONSUMER_SECRET"),
            "BRICKLINK_TOKEN": token or os.getenv("BRICKLINK_TOKEN"),
            "BRICKLINK_TOKEN_SECRET": token_secret or os.getenv("BRICKLINK_TOKEN_SECRET"),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ConnectorAuthenticationError(f"Missing BrickLink credentials: {', '.join(missing)}")

        self.auth = OAuth1(
            required["BRICKLINK_CONSUMER_KEY"],
            client_secret=required["BRICKLINK_CONSUMER_SECRET"],
            resource_owner_key=required["BRICKLINK_TOKEN"],
            resource_owner_secret=required["BRICKLINK_TOKEN_SECRET"],
            signature_method="HMAC-SHA1",
        )
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_retries = max_retries

    @property
    def configured(self):
        return True

    def _get(self, path: str, params=None):
        kwargs = {}
        if self.sleep is not None:
            kwargs["sleep"] = self.sleep
        r = request_with_backoff(
            "GET", f"{BASE_URL}{path}", session=self.session, params=params or {},
            auth=self.auth, timeout=30, max_retries=self.max_retries, **kwargs,
        )
        payload = r.json()
        if "data" not in payload:
            meta = payload.get("meta") or {}
            raise ConnectorError(f"BrickLink response error {meta.get('code', 'unknown')}: {meta.get('message', 'no data')}")
        return payload["data"]

    def get_item(self, item_no: str, item_type: str = "SET"):
        return self._get(f"/items/{item_type}/{item_no}")

    def get_price_guide(
        self,
        item_no: str,
        condition: str = "U",
        guide_type: str = "sold",
        currency_code: str = "EUR",
        country_code: str | None = None,
        item_type: str = "SET",
    ):
        if condition not in {"N", "U"}:
            raise ValueError("condition must be N or U")
        if guide_type not in {"sold", "stock"}:
            raise ValueError("guide_type must be sold or stock")
        params = {
            "guide_type": guide_type,
            "new_or_used": condition,
            "currency_code": currency_code,
        }
        if country_code:
            params["country_code"] = country_code

        return self._get(
            f"/items/{item_type}/{item_no}/price",
            params=params,
        )

    def get_market_data(self, set_num, *, condition="U", guide_type="sold",
                        currency_code="EUR", country_code=None):
        payload = self.get_price_guide(
            set_num, condition=condition, guide_type=guide_type,
            currency_code=currency_code, country_code=country_code,
        )
        return self.normalize_price_guide(payload, set_num=set_num, guide_type=guide_type)

    @staticmethod
    def normalize_price_guide(payload, *, set_num=None, guide_type="sold", observed_at=None):
        if guide_type not in {"sold", "stock"}:
            raise ValueError("guide_type must be sold or stock")
        details = payload.get("price_detail") or []
        prices = [value for value in (_number(row.get("unit_price")) for row in details) if value is not None]
        item = payload.get("item") or {}
        unit_quantity = payload.get("unit_quantity")
        try:
            count = int(unit_quantity) if unit_quantity is not None else None
        except (TypeError, ValueError):
            count = None
        common = dict(
            set_num=set_num or item.get("no"), marketplace="BRICKLINK",
            condition=payload.get("new_or_used"), currency=payload.get("currency_code"),
            observed_at=observed_at or datetime.now(timezone.utc), confidence=None,
            raw_data=payload,
        )
        if guide_type == "sold":
            return MarketData(
                **common, sales_6m=count,
                monthly_sales=round(count / 6, 4) if count is not None else None,
                sold_price_min=_number(payload.get("min_price")),
                sold_price_median=statistics.median(prices) if prices else None,
                sold_price_p25=_percentile(prices, .25),
                sold_price_weighted_avg=_number(payload.get("qty_avg_price")),
            )
        return MarketData(
            **common, active_listing_count=count,
            asking_price_min=_number(payload.get("min_price")),
            asking_price_median=statistics.median(prices) if prices else None,
            asking_price_p25=_percentile(prices, .25),
        )
