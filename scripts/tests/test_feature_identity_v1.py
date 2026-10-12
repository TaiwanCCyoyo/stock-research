"""Invented metadata exercises exact identities and integer/set aggregation."""

from copy import deepcopy
from typing import Any

import pytest

from research_core.artifact_store import canonical, object_digest
from research_core.feature_identity_v1 import identity_digest, merge_count_batches, validate_identity


def identity() -> dict[str, Any]:
    return {
        "schema": "research-feature-block.v1",
        "feature_id": "invented-feature",
        "definition": {"id": "invented", "version": "v1", "metadata": {"notes": ["example"]}},
        "stock_code": "0050",
        "scope": "stock",
        "inputs": {"prices": "a" * 64},
        "implementation": {"research_core/example.py": "b" * 64},
        "calendar": {"sha256": "c" * 64, "rows": 2, "start": "2020-01-01", "end": "2020-01-02"},
        "semantics": {
            "price_basis": "invented-raw",
            "gap": "invented-reset",
            "warmup": "invented-full",
            "pivot_availability": "invented-confirmation",
            "calendar_policy": "invented-calendar",
            "quality_policy": "invented-quality",
        },
        "parameters": {"window": 3},
        "runtime": {"python": "invented-version"},
        "context": None,
    }


def test_identity_is_detached_exact_canonical_json() -> None:
    source = identity()
    result = validate_identity(source)
    assert result == source and result is not source
    assert result["stock_code"] == "0050"
    assert identity_digest(source) == object_digest(source)
    result["definition"]["metadata"]["notes"].append("changed")
    assert source["definition"]["metadata"]["notes"] == ["example"]
    source["parameters"]["window"] = 9
    assert result["parameters"]["window"] == 3


@pytest.mark.parametrize(
    "path,value",
    [
        (("implementation", "research_core/example.py"), "d" * 64),
        (("inputs", "prices"), "d" * 64),
        (("calendar", "sha256"), "d" * 64),
        (("calendar", "rows"), 3),
        (("calendar", "end"), "2020-01-03"),
        (("semantics", "price_basis"), "another-basis"),
        (("semantics", "gap"), "another-gap"),
        (("semantics", "pivot_availability"), "another-pivot"),
        (("runtime", "python"), "another-runtime"),
        (("definition", "version"), "old-v4"),
        (("stock_code",), "50"),
        (("context",), {"universe": ["0050", "0060"]}),
    ],
)
def test_any_dependency_or_policy_change_changes_identity(path: tuple[str, ...], value: Any) -> None:
    before = identity()
    after = deepcopy(before)
    target = after
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert identity_digest(before) != identity_digest(after)


def test_dictionary_order_does_not_change_digest() -> None:
    source = identity()
    assert identity_digest(source) == identity_digest(dict(reversed(list(source.items()))))


@pytest.mark.parametrize("field", list(identity()))
def test_missing_top_level_field_is_rejected(field: str) -> None:
    source = identity()
    del source[field]
    with pytest.raises(ValueError):
        validate_identity(source)


def test_unknown_field_is_rejected() -> None:
    source = identity()
    source["unknown"] = 1
    with pytest.raises(ValueError):
        validate_identity(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stock_code", 50),
        ("stock_code", ""),
        ("stock_code", "   "),
        ("schema", "other"),
        ("scope", "other"),
        ("feature_id", ""),
        ("definition", {}),
        ("definition", {"id": "x", "version": 1}),
        ("inputs", {}),
        ("inputs", {"prices": "A" * 64}),
        ("implementation", {"../example.py": "b" * 64}),
        ("implementation", {"D:/example.py": "b" * 64}),
        ("implementation", {"research_core\\example.py": "b" * 64}),
        ("runtime", {}),
        ("context", {}),
        ("context", []),
        ("parameters", []),
        ("parameters", {"bad": float("nan")}),
        ("parameters", {"bad": float("inf")}),
        ("parameters", {"bad": (1, 2)}),
        ("parameters", {1: "coerced"}),
    ],
)
def test_malformed_identity_is_rejected(field: str, value: Any) -> None:
    source = identity()
    source[field] = value
    with pytest.raises(ValueError):
        validate_identity(source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rows", True),
        ("rows", 2.0),
        ("rows", -1),
        ("sha256", "bad"),
        ("start", "20200101"),
        ("start", "2020-02-30"),
        ("end", ""),
    ],
)
def test_calendar_is_validated(field: str, value: Any) -> None:
    source = identity()
    source["calendar"][field] = value
    with pytest.raises(ValueError):
        validate_identity(source)


@pytest.mark.parametrize("field", list(identity()["semantics"]))
def test_semantics_must_be_explicit_nonempty_strings(field: str) -> None:
    source = identity()
    del source["semantics"][field]
    with pytest.raises(ValueError):
        validate_identity(source)
    source["semantics"][field] = ""
    with pytest.raises(ValueError):
        validate_identity(source)


def test_cross_section_requires_context_and_preserves_metadata() -> None:
    source = identity()
    source["scope"] = "cross_section"
    with pytest.raises(ValueError, match="context"):
        validate_identity(source)
    source["context"] = {"universe": ["0050", "0060"], "dependency": {"vintage": "invented"}}
    assert validate_identity(source) == source


def batch(batch_id: str, counts: dict[str, Any], stocks: Any) -> dict[str, Any]:
    return {"batch_id": batch_id, "slice_id": "invented-slice", "counts": counts, "stocks": stocks}


def test_merge_has_integer_sum_and_stock_union_parity_independent_of_order() -> None:
    batches = [batch("one", {"trials": 3, "successes": 1}, ["0050", "50", "0050"]), batch("two", {"trials": 4, "successes": 2, "zero": 0}, ("0050", "0060"))]
    source = deepcopy(batches)
    expected = {"slice_id": "invented-slice", "counts": {"successes": 3, "trials": 7, "zero": 0}, "stocks": ["0050", "0060", "50"], "stock_n": 3, "batch_n": 2}
    assert merge_count_batches(batches) == expected
    assert canonical(merge_count_batches(reversed(batches))) == canonical(expected)
    assert batches == source


def test_empty_batches_and_empty_batch_contents() -> None:
    assert merge_count_batches([]) == {"slice_id": None, "counts": {}, "stocks": [], "stock_n": 0, "batch_n": 0}
    assert merge_count_batches([batch("one", {}, [])])["batch_n"] == 1


def test_duplicate_batch_and_mixed_slices_are_rejected() -> None:
    one = batch("one", {}, [])
    with pytest.raises(ValueError, match="duplicate"):
        merge_count_batches([one, one])
    two = batch("two", {}, [])
    two["slice_id"] = "other-slice"
    with pytest.raises(ValueError, match="mixed"):
        merge_count_batches([one, two])


@pytest.mark.parametrize("bad_count", [True, False, 1.0, 0.25, -1, "1", None])
def test_counts_reject_rates_floats_bools_and_negative_values(bad_count: Any) -> None:
    with pytest.raises(ValueError, match="integer"):
        merge_count_batches([batch("one", {"trials": bad_count}, [])])


@pytest.mark.parametrize("stocks", ["0050", [50], [""], {"0050"}, None])
def test_stocks_require_a_sequence_of_original_nonempty_strings(stocks: Any) -> None:
    with pytest.raises(ValueError):
        merge_count_batches([batch("one", {}, stocks)])


def test_batch_unknown_or_missing_fields_are_rejected() -> None:
    value = batch("one", {}, [])
    value["unknown"] = 1
    with pytest.raises(ValueError):
        merge_count_batches([value])
    del value["unknown"]
    del value["counts"]
    with pytest.raises(ValueError):
        merge_count_batches([value])
