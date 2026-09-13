from __future__ import annotations

import os
import re
import statistics
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from models.market_data import MarketData
from services.http import ConnectorAuthenticationError, ConnectorError, request_with_backoff

MARKETPLACE_ES = "EBAY_ES"
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class EbayClient:
    def __init__(self, client_id=None, client_secret=None, environment=None, *,
                 session=None, sleep=time.sleep, max_retries=4):
        load_dotenv()
        self.client_id = client_id or os.getenv("EBAY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("EBAY_CLIENT_SECRET")
        self.environment = (environment or os.getenv("EBAY_ENVIRONMENT") or "").lower()
        if not self.client_id or not self.client_secret or self.environment not in {"sandbox", "production"}:
            raise ConnectorAuthenticationError(
                "eBay requires EBAY_CLIENT_ID, EBAY_CLIENT_SECRET and EBAY_ENVIRONMENT=sandbox|production"
            )
        host = "api.sandbox.ebay.com" if self.environment == "sandbox" else "api.ebay.com"
        self.token_url = f"https://{host}/identity/v1/oauth2/token"
        self.browse_url = f"https://{host}/buy/browse/v1/item_summary/search"
        self.session = session or requests.Session()
        self.sleep = sleep
        self.max_retries = max_retries
        self._token = None
        self._token_expires_at = 0.0
        self.rate_limit_retries = 0

    def _on_rate_limit(self, **_):
        self.rate_limit_retries += 1

    @property
    def configured(self):
        return True

    def get_application_token(self):
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        response = request_with_backoff(
            "POST", self.token_url, session=self.session,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
            auth=(self.client_id, self.client_secret), max_retries=self.max_retries,
            sleep=self.sleep, on_rate_limit=self._on_rate_limit,
        )
        try:
            payload = response.json()
        except (ValueError, AttributeError) as error:
            raise ConnectorAuthenticationError(
                "eBay token response was not valid JSON",
                status_code=response.status_code,
            ) from error
        token = payload.get("access_token")
        if not token:
            raise ConnectorAuthenticationError(
                "eBay token response did not contain an access token",
                status_code=response.status_code,
            )
        self._token = token
        self._token_expires_at = time.monotonic() + max(int(payload.get("expires_in", 7200)) - 60, 0)
        return token

    def search_set(self, set_num, **kwargs):
        return self.search_keywords(f"LEGO {set_num}", set_num=set_num, **kwargs)

    def search_keywords(self, keywords, *, set_num=None, marketplace=MARKETPLACE_ES,
                        limit=200, max_pages=None):
        token = self.get_application_token()
        headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": marketplace}
        url = self.browse_url
        params = {"q": keywords, "limit": min(max(int(limit), 1), 200), "offset": 0}
        items = []
        pages = []
        page_count = 0
        while url and (max_pages is None or page_count < max_pages):
            response = request_with_backoff(
                "GET", url, session=self.session, headers=headers, params=params,
                max_retries=self.max_retries, sleep=self.sleep,
                on_rate_limit=self._on_rate_limit,
            )
            payload = response.json()
            pages.append(payload)
            items.extend(payload.get("itemSummaries") or [])
            url = payload.get("next")
            params = None
            page_count += 1
        exact_matches = None
        if set_num is not None and items:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(set_num)}(?![A-Za-z0-9])", re.IGNORECASE)
            exact_matches = sum(bool(pattern.search(str(item.get("title", "")))) for item in items) / len(items)
        return self.normalize_listings(
            set_num=set_num, items=items,
            raw_data={"pages": pages, "identification": {
                "query": keywords, "exact_query": set_num is not None,
                "exact_match_ratio": exact_matches,
            }},
        )

    def get_market_data(self, set_num, **kwargs):
        return self.search_set(set_num, **kwargs)

    @staticmethod
    def normalize_listings(*, set_num, items, raw_data=None, observed_at=None):
        unique = {}
        for item in items or []:
            unique[item.get("itemId") or f"row-{len(unique)}"] = item
        listings = list(unique.values())
        prices = []
        currencies = set()
        conditions = set()
        for item in listings:
            price = item.get("price") or {}
            try:
                prices.append(float(price["value"]))
            except (KeyError, TypeError, ValueError):
                pass
            if price.get("currency"):
                currencies.add(price["currency"])
            if item.get("condition"):
                conditions.add(item["condition"])
        return MarketData(
            set_num=set_num, marketplace="EBAY", condition=next(iter(conditions)) if len(conditions) == 1 else None,
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            observed_at=observed_at or datetime.now(timezone.utc), active_listing_count=len(listings),
            asking_price_min=min(prices) if prices else None,
            asking_price_median=statistics.median(prices) if prices else None,
            asking_price_p25=_percentile(prices, .25),
            sales_6m=None, monthly_sales=None, sold_price_min=None, sold_price_median=None,
            sold_price_p25=None, sold_price_weighted_avg=None, expected_days_to_sell=None,
            confidence=None, raw_data=raw_data if raw_data is not None else {"items": listings},
        )
