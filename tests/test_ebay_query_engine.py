from models.market_data import MarketData
from models.product_aliases import get_product_aliases
from services.ebay_listing_classifier import classify_ebay_listing
from services.ebay_query_engine import (
    PENDING_HUMAN_REVIEW,
    EbayQueryEngine,
    score_query,
)
from services.ebay_query_planner import normalize_product_name, plan_ebay_queries


def listing(item_id, title, price="100.00", condition="Nuevo", condition_id="1000"):
    return {
        "itemId": item_id,
        "title": title,
        "price": {"value": price, "currency": "EUR"},
        "condition": condition,
        "conditionId": condition_id,
    }


class FakeEbayClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def search_keywords(self, query, **kwargs):
        self.calls.append((query, kwargs))
        items = self.responses.get(query, [])
        return MarketData(raw_data={"pages": [{"itemSummaries": items}]})


def test_name_normalization_keeps_useful_product_identity():
    porsche = normalize_product_name("Porsche 911 Turbo & 911 Targa")
    lamborghini = normalize_product_name("Lamborghini Sián FKP 37")

    assert porsche.full_name == "Porsche 911 Turbo & 911 Targa"
    assert porsche.short_name == "Porsche 911"
    assert "Porsche" in porsche.important_tokens
    assert lamborghini.short_name == "Lamborghini Sian"
    assert "Sian" in lamborghini.important_tokens


def test_query_generation_is_ordered_short_and_bounded():
    plan = plan_ebay_queries(
        "10300-1", "Back to the Future Time Machine", max_queries=5
    )

    assert plan.queries == (
        "LEGO 10300",
        "LEGO 10300 Back to the Future",
        "LEGO 10300 Time Machine",
        "LEGO 10300 DeLorean",
        "LEGO 10300 Regreso al Futuro",
    )
    assert all(len(query.split()) <= 7 for query in plan.queries)


def test_configured_and_extra_aliases_are_merged_without_duplicates():
    aliases = get_product_aliases(
        "21318-1", "Tree House", ("Casa del Árbol", "Tree House")
    )

    assert aliases.canonical_name == "Tree House"
    assert "Baumhaus" in aliases.aliases
    assert "Casa del Árbol" not in aliases.aliases
    assert aliases.aliases.count("Casa del Arbol") == 1


def test_ensemble_deduplicates_and_records_all_matched_queries():
    first = "LEGO 10300"
    second = "LEGO 10300 Back to the Future"
    shared = listing("same", "LEGO 10300 Back to the Future DeLorean nuevo")
    client = FakeEbayClient({
        first: [shared, listing("one", "LEGO 10300 Time Machine nuevo")],
        second: [shared, listing("two", "LEGO 10300 DeLorean sellado")],
    })

    result = EbayQueryEngine(client).search_product(
        "10300-1", "Back to the Future Time Machine",
        max_queries=2, target_full_sets=99, min_queries=2,
    )

    assert result.unique_results == 3
    assert result.full_set_unique == 3
    assert result.duplicates_removed == 1
    assert result.classifier_precision_sample == PENDING_HUMAN_REVIEW
    matched = next(item for item in result.listings if item["itemId"] == "same")
    assert matched["matched_queries"] == [first, second]
    assert len({item["itemId"] for item in result.listings}) == 3


def test_stop_early_after_target_is_reached():
    plan = plan_ebay_queries("75308-1", "R2-D2", max_queries=3)
    enough = [listing(str(index), f"LEGO 75308 R2-D2 nuevo {index}") for index in range(3)]
    client = FakeEbayClient({query: enough for query in plan.queries})

    result = EbayQueryEngine(client).search_product(
        "75308-1", "R2-D2", max_queries=3,
        target_full_sets=3, min_queries=1,
    )

    assert result.api_calls == 1
    assert result.queries_used == ("LEGO 75308",)


def test_stop_early_when_additional_query_has_low_marginal_value():
    plan = plan_ebay_queries("21318-1", "Tree House", max_queries=4)
    first_items = [listing(str(index), f"LEGO 21318 Tree House nuevo {index}") for index in range(4)]
    client = FakeEbayClient({
        plan.queries[0]: first_items,
        plan.queries[1]: first_items,
        plan.queries[2]: [listing("new", "LEGO 21318 Baumhaus nuevo")],
    })

    result = EbayQueryEngine(client).search_product(
        "21318-1", "Tree House", max_queries=4, target_full_sets=99,
        min_queries=2, min_marginal_full_sets=2,
    )

    assert result.api_calls == 2
    assert result.query_quality[1].unique_full_sets_added == 0


def test_query_score_rewards_new_full_sets_not_raw_volume():
    noisy = score_query(results_returned=100, unique_full_sets_added=2, uncertain_count=0)
    useful = score_query(results_returned=50, unique_full_sets_added=35, uncertain_count=0)

    assert noisy < useful


def test_exact_set_number_does_not_match_a_longer_number():
    result = classify_ebay_listing(
        {"title": "LEGO 110300 Back to the Future nuevo"},
        set_num="10300-1",
        expected_terms=("Back to the Future",),
    )
    assert result.category == "OTHER"


def test_alias_is_positive_identity_signal_for_translated_title():
    plan = plan_ebay_queries("21318-1", "Tree House")
    result = classify_ebay_listing(
        {"title": "LEGO Ideas 21318 Baumhaus neu"},
        set_num="21318-1",
        expected_terms=plan.identity_terms,
    )
    assert result.category == "FULL_SET"


def test_negative_compatible_signal_wins_over_alias_identity():
    plan = plan_ebay_queries("10300-1", "Back to the Future Time Machine")
    result = classify_ebay_listing(
        {"title": "MOC DeLorean compatible with LEGO 10300"},
        set_num="10300-1",
        expected_terms=plan.identity_terms,
    )
    assert result.category == "COMPATIBLE_PRODUCT"
