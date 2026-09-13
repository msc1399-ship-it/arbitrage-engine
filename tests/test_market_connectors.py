import requests
import pytest

from collectors import ebay
from collectors.bricklink import BrickLinkClient
from models.market_data import MarketData
from services.http import ConnectorAuthenticationError
from services.market_aggregator import PENDING, aggregate_market_data
from tests.fixtures.market_samples import (
    GOOD_MARGIN_BAD_ROTATION, GOOD_ROTATION_AND_MARGIN, NO_ACTIVE_LISTINGS,
    NO_SALES_HISTORY, bricklink_sales, ebay_listings,
)


class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_ebay_normalization_keeps_active_and_sold_separate():
    items = [
        {"itemId": "1", "condition": "Used", "price": {"value": "50", "currency": "EUR"}},
        {"itemId": "2", "condition": "Used", "price": {"value": "100", "currency": "EUR"}},
        {"itemId": "3", "condition": "Used", "price": {"value": "150", "currency": "EUR"}},
    ]
    result = ebay.EbayClient.normalize_listings(set_num="TEST-1", items=items)
    assert result.active_listing_count == 3
    assert result.asking_price_min == 50
    assert result.asking_price_median == 100
    assert result.asking_price_p25 == 75
    assert result.sales_6m is None
    assert result.sold_price_median is None
    assert result.confidence is None


def test_bricklink_sold_normalization():
    payload = {
        "item": {"no": "TEST-1", "type": "SET"}, "new_or_used": "U",
        "currency_code": "EUR", "min_price": "80", "qty_avg_price": "120",
        "unit_quantity": 60,
        "price_detail": [{"unit_price": "80"}, {"unit_price": "100"}, {"unit_price": "160"}],
    }
    result = BrickLinkClient.normalize_price_guide(payload, guide_type="sold")
    assert result.sales_6m == 60
    assert result.monthly_sales == 10
    assert result.sold_price_min == 80
    assert result.sold_price_median == 100
    assert result.sold_price_p25 == 90
    assert result.sold_price_weighted_avg == 120
    assert result.active_listing_count is None
    assert result.confidence is None


def test_combination_preserves_sources_and_identity():
    bricklink, listings = GOOD_ROTATION_AND_MARGIN
    result = aggregate_market_data(
        set_num="TEST-1", identity_data={"name": "Fixture"},
        bricklink_data=bricklink, ebay_data=listings,
    )
    metrics = result.derived_metrics
    assert result.identity_data == {"name": "Fixture"}
    assert metrics.sources["sales_6m"] == "BRICKLINK"
    assert metrics.sources["asking_price"] == "EBAY"
    assert metrics.sources["conservative_value"] == "BRICKLINK"
    assert metrics.demand_supply_ratio == 2


def test_none_is_not_zero_and_missing_listings_stay_unknown():
    bricklink, listings = NO_ACTIVE_LISTINGS
    result = aggregate_market_data(set_num="TEST-1", bricklink_data=bricklink, ebay_data=listings)
    assert listings.active_listing_count is None
    assert result.derived_metrics.demand_supply_ratio is None
    assert result.derived_metrics.expected_profit is None
    assert result.derived_metrics.decision == PENDING


def test_sales_only_come_from_a_source_that_provides_them():
    bricklink = bricklink_sales(sales_6m=24)
    listings = ebay_listings()
    result = aggregate_market_data(set_num="TEST-1", bricklink_data=bricklink, ebay_data=listings)
    assert listings.sales_6m is None
    assert result.derived_metrics.monthly_sales == 4
    assert result.derived_metrics.sources["sales_6m"] == "BRICKLINK"


def test_high_roi_with_low_rotation_is_rejected():
    bricklink, listings = GOOD_MARGIN_BAD_ROTATION
    result = aggregate_market_data(set_num="TEST-1", bricklink_data=bricklink, ebay_data=listings)
    assert result.derived_metrics.expected_roi > .2
    assert result.derived_metrics.decision == "REJECT"


def test_good_roi_and_rotation_is_paper_buy():
    bricklink, listings = GOOD_ROTATION_AND_MARGIN
    result = aggregate_market_data(set_num="TEST-1", bricklink_data=bricklink, ebay_data=listings)
    assert result.derived_metrics.expected_roi > .2
    assert result.derived_metrics.decision == "PAPER_BUY"


def test_missing_sales_history_is_pending():
    bricklink, listings = NO_SALES_HISTORY
    result = aggregate_market_data(set_num="TEST-1", bricklink_data=bricklink, ebay_data=listings)
    assert result.derived_metrics.monthly_sales is None
    assert result.derived_metrics.decision == PENDING


def test_ebay_retries_rate_limit_and_paginates_without_sold_data():
    session = FakeSession([
        FakeResponse(200, {"access_token": "test-token", "expires_in": 7200}),
        FakeResponse(429, headers={"Retry-After": "0"}),
        FakeResponse(200, {"itemSummaries": [{"itemId": "1", "price": {"value": "90", "currency": "EUR"}}],
                           "next": "https://api.sandbox.ebay.com/next"}),
        FakeResponse(200, {"itemSummaries": [{"itemId": "2", "price": {"value": "110", "currency": "EUR"}}]}),
    ])
    client = ebay.EbayClient("id", "secret", "sandbox", session=session, sleep=lambda _: None)
    result = client.search_set("TEST-1")
    assert result.active_listing_count == 2
    assert result.sales_6m is None
    assert len(session.calls) == 4
    assert client.rate_limit_retries == 1
    assert session.calls[2][2]["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_ES"


def test_authentication_errors_are_clean(monkeypatch):
    monkeypatch.setattr(ebay, "load_dotenv", lambda: None)
    for name in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConnectorAuthenticationError, match="eBay requires"):
        ebay.EbayClient()

    session = FakeSession([FakeResponse(401)])
    client = ebay.EbayClient("id", "secret", "production", session=session, sleep=lambda _: None)
    with pytest.raises(ConnectorAuthenticationError, match="authentication failed"):
        client.get_application_token()


def test_bricklink_missing_credentials_are_clean(monkeypatch):
    for name in ("BRICKLINK_CONSUMER_KEY", "BRICKLINK_CONSUMER_SECRET", "BRICKLINK_TOKEN", "BRICKLINK_TOKEN_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConnectorAuthenticationError, match="Missing BrickLink credentials"):
        BrickLinkClient()
