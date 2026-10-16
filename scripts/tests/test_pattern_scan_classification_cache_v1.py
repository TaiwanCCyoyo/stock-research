"""Exact oracle parity and isolation for caller-only classification memoization."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

import research_core.pattern_scan_classification_cache_v1 as cache_module
from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_conditions_v1 import FEATURES, classify_column


def _sources(values: list[Any], *, index: pd.Index | None = None) -> tuple[pd.Series, pd.Series, pd.Series]:
    series = pd.Series(values, index=index, dtype=object, name="caller-values")
    allowed = pd.Series(True, index=series.index, dtype=bool, name="caller-applicability")
    reasons = pd.Series(None, index=series.index, dtype=object, name="caller-reasons")
    return series, allowed, reasons


def _assert_oracle(cache: ConditionClassificationCache, feature: str, values: pd.Series, allowed: pd.Series, reasons: pd.Series) -> pd.DataFrame:
    originals = [source.copy(deep=True) for source in (values, allowed, reasons)]
    expected = classify_column(feature, values, applicable=allowed, unknown_reason=reasons)
    result = cache.classify(feature, values, applicable=allowed, unknown_reason=reasons)
    pd.testing.assert_frame_equal(result, expected)
    for source, original in zip((values, allowed, reasons), originals):
        pd.testing.assert_series_equal(source, original)
    return result


@pytest.mark.parametrize("feature", tuple(FEATURES))
def test_every_feature_boundaries_categories_missing_reasons_and_applicability(feature: str) -> None:
    definition = FEATURES[feature]
    samples: list[Any] = [None, np.nan, pd.NA, *[value for _, value in definition.categories]]
    if definition.numeric_bins:
        samples.extend([0, 1, 1000, np.int64(1), np.float32(1.0), np.float64(1.0), np.inf, -np.inf])
        for interval in definition.numeric_bins:
            for bound in (interval.lower, interval.upper):
                if bound is not None:
                    if definition.discrete_count:
                        samples.extend([max(0, int(bound) - 1), int(bound), int(bound) + 1])
                    else:
                        samples.extend([np.nextafter(float(bound), -np.inf), float(bound), np.nextafter(float(bound), np.inf)])
    if feature == "MKT":
        samples.append("unknown")
    values, allowed, reasons = _sources(samples * 2)
    cache = ConditionClassificationCache()
    _assert_oracle(cache, feature, values, allowed, reasons)
    _assert_oracle(cache, feature, values, allowed, reasons)
    reasons[:] = "missing_source_column"
    _assert_oracle(cache, feature, values, allowed, reasons)
    allowed.iloc[::2] = False
    _assert_oracle(cache, feature, values, allowed, reasons)


def test_only_first_use_keys_batched_and_exact_scalar_types_remain_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[Any]] = []
    original = cache_module.classify_column

    def record(feature: str, values: pd.Series, **kwargs: Any) -> pd.DataFrame:
        calls.append(values.tolist())
        return original(feature, values, **kwargs)

    monkeypatch.setattr(cache_module, "classify_column", record)
    cache = ConditionClassificationCache()
    values, allowed, reasons = _sources([1, np.int64(1), 1.0, np.float32(1), np.float64(1), True, np.bool_(True), "1", -0.0, 0.0, None, np.nan, pd.NA] * 2)
    allowed[:] = False  # All types are legal inputs outside the applicable cohort.
    _assert_oracle(cache, "MA_a", values, allowed, reasons)
    assert len(calls) == 1 and len(calls[0]) == 11
    _assert_oracle(cache, "MA_a", values, allowed, reasons)
    assert len(calls) == 1
    changed = values.copy(deep=True)
    changed.iloc[-1] = 0.5
    _assert_oracle(cache, "MA_a", changed, allowed, reasons)
    assert len(calls) == 2 and calls[-1] == [0.5]


@pytest.mark.parametrize("dtype", ("float32", "Float32", "float64", "Float64"))
def test_native_numeric_dtype_comparisons_keep_original_classifier_semantics(dtype: str) -> None:
    cache = ConditionClassificationCache()
    for feature, definition in FEATURES.items():
        if not definition.numeric_bins:
            continue
        bounds = [value for interval in definition.numeric_bins for value in (interval.lower, interval.upper) if value is not None]
        samples = [0.0, 1.0, np.nan, *bounds]
        values, allowed, reasons = _sources(samples)
        _assert_oracle(cache, feature, values.astype(dtype), allowed, reasons)
    assert cache._entries == {}


def test_repeat_dates_different_indices_nullable_bool_and_fresh_outputs() -> None:
    cache = ConditionClassificationCache()
    index = pd.DatetimeIndex(["2020-01-02", "2020-01-02", "2020-01-03", "2020-01-01"], name="calendar")
    values, allowed, reasons = _sources([0.0, 0.05, None, -0.1], index=index)
    allowed = allowed.astype("boolean")
    first = _assert_oracle(cache, "MA_a", values, allowed, reasons)
    first.iloc[:, :] = "modified result"
    first.index.name = "modified index"
    assert values.index.name == "calendar"
    _assert_oracle(cache, "MA_a", values, allowed, reasons)
    new_index = pd.Index(["c", "b", "a", "a"], name="other-calendar")
    others = [source.set_axis(new_index) for source in (values, allowed, reasons)]
    _assert_oracle(cache, "MA_a", *others)


@pytest.mark.parametrize("feature,invalid", (("MA_a", True), ("MACD", 1), ("PAT_other_B1", -1), ("MKT", "invalid"), ("BB_b", "1"), ("E", -1)))
def test_invalid_batch_preserves_full_error_text_and_never_partially_populates(feature: str, invalid: Any) -> None:
    values, allowed, reasons = _sources([invalid] * 4)
    cache = ConditionClassificationCache()
    with pytest.raises(Exception) as oracle:
        classify_column(feature, values, applicable=allowed, unknown_reason=reasons)
    with pytest.raises(type(oracle.value)) as actual:
        cache.classify(feature, values, applicable=allowed, unknown_reason=reasons)
    assert str(actual.value) == str(oracle.value)
    assert cache._entries == {}


@pytest.mark.parametrize("invalid", ("reason_number", "reason_blank", "applicable_number", "applicable_missing", "alignment", "custom", "unknown_feature"))
def test_invalid_metadata_and_custom_values_fallback_exactly(invalid: str) -> None:
    values, allowed, reasons = _sources([0.0, 0.05, None])
    feature = "MA_a"
    if invalid == "reason_number":
        reasons.iloc[1] = 3
    elif invalid == "reason_blank":
        reasons.iloc[1] = " "
    elif invalid == "applicable_number":
        allowed = allowed.astype(int)
    elif invalid == "applicable_missing":
        allowed = allowed.astype("boolean")
        allowed.iloc[1] = pd.NA
    elif invalid == "alignment":
        reasons.index += 1
    elif invalid == "custom":
        values.iloc[1] = object()
    else:
        feature = "not-a-feature"
    cache = ConditionClassificationCache()
    with pytest.raises(Exception) as oracle:
        classify_column(feature, values, applicable=allowed, unknown_reason=reasons)
    with pytest.raises(type(oracle.value)) as actual:
        cache.classify(feature, values, applicable=allowed, unknown_reason=reasons)
    assert str(actual.value) == str(oracle.value)
    assert cache._entries == {}


def test_unused_calendar_invalid_values_are_never_scanned() -> None:
    full, allowed, reasons = _sources([0.0, 0.05, True, "bad", object()])
    cache = ConditionClassificationCache()
    _assert_oracle(cache, "MA_a", full.iloc[:2], allowed.iloc[:2], reasons.iloc[:2])
    assert len(cache._entries) == 2


def test_invalid_new_keys_do_not_pollute_previous_successful_entries() -> None:
    cache = ConditionClassificationCache()
    values, allowed, reasons = _sources([0.0])
    _assert_oracle(cache, "MA_a", values, allowed, reasons)
    before = dict(cache._entries)
    invalid_values, invalid_allowed, invalid_reasons = _sources([0.0, 0.05, True, True, True, True])
    with pytest.raises(ValueError) as oracle:
        classify_column("MA_a", invalid_values, applicable=invalid_allowed, unknown_reason=invalid_reasons)
    with pytest.raises(ValueError) as actual:
        cache.classify("MA_a", invalid_values, applicable=invalid_allowed, unknown_reason=invalid_reasons)
    assert str(actual.value) == str(oracle.value)
    assert cache._entries == before
    values.iloc[0] = 0.05
    _assert_oracle(cache, "MA_a", values, allowed, reasons)
    assert len(cache._entries) == 2


def test_empty_input_retains_exact_public_schema() -> None:
    _assert_oracle(ConditionClassificationCache(), "MA_a", *_sources([]))
