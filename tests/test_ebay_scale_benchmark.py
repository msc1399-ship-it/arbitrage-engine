import csv

from services.ebay_scale_benchmark import (
    benchmark_status,
    price_stability,
    sample_quality,
    select_benchmark_sets,
)


def test_scale_selection_is_reproducible_and_has_no_duplicates(tmp_path):
    universe = tmp_path / "universe.csv"
    with universe.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output, fieldnames=("set_num", "name", "year", "theme_id", "num_parts")
        )
        writer.writeheader()
        for index in range(60):
            writer.writerow({
                "set_num": f"{10000 + index}-1",
                "name": f"City Space Castle {index}",
                "year": 2010 + index % 16,
                "theme_id": 100 + index % 4,
                "num_parts": 300 + index * 50,
            })

    first = select_benchmark_sets(universe, count=20, seed=42)
    second = select_benchmark_sets(universe, count=20, seed=42)

    assert [row["set_num"] for row in first] == [row["set_num"] for row in second]
    assert len({row["set_num"] for row in first}) == 20
    assert {int(row["year"]) <= 2015 for row in first} == {True, False}


def test_sample_quality_boundaries():
    assert sample_quality(40) == "HIGH"
    assert sample_quality(15) == "MEDIUM"
    assert sample_quality(5) == "LOW"
    assert sample_quality(4) == "INSUFFICIENT"


def test_price_stability_uses_worst_available_condition():
    first = {
        "NEW": {"median": 100.0},
        "USED": {"median": 80.0},
    }
    ensemble = {
        "NEW": {"median": 108.0},
        "USED": {"median": 100.0},
    }

    assert price_stability(first, ensemble) == "UNSTABLE"


def test_price_stability_does_not_treat_missing_data_as_zero():
    missing = {"NEW": {"median": None}, "USED": {"median": None}}
    assert price_stability(missing, missing) == "PENDING"


def test_benchmark_status_rules():
    assert benchmark_status(30, 0.05, "STABLE") == "GOOD_EBAY_DATA"
    assert benchmark_status(14, 0.05, "STABLE") == "PARTIAL_EBAY_DATA"
    assert benchmark_status(4, 0.05, "STABLE") == "INSUFFICIENT_EBAY_DATA"
    assert benchmark_status(30, 0.11, "STABLE") == "REVIEW_REQUIRED"
    assert benchmark_status(30, 0.05, "UNSTABLE") == "REVIEW_REQUIRED"
