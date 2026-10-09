"""Coordinate corrections preserve original evidence and all outcome fields."""

from __future__ import annotations

import pandas as pd
import pytest

from research_core.hhhl_v4_landmark_view import VIEW_VERSION, observed_landmark_coordinates


def test_censored_coordinate_view_preserves_original_and_scientific_fields() -> None:
    raw = pd.DataFrame({
        "landmark_date": ["2020-01-03", None, None],
        "landmark_index": [10, 170, 190],
        "status": ["active", "unknown", "early_hit"],
        "reason": [None, "window_end", None],
        "label_126": [1, None, None],
    })
    before = raw.copy(deep=True)
    view = observed_landmark_coordinates(raw)
    pd.testing.assert_frame_equal(raw, before)
    assert view["landmark_index"].tolist() == [10, pd.NA, pd.NA]
    pd.testing.assert_frame_equal(view.drop(columns="landmark_index"), raw.drop(columns="landmark_index"))
    assert view.attrs == {"coordinate_view_version": VIEW_VERSION, "censored_indices_nullified": 2}
    again = observed_landmark_coordinates(view)
    pd.testing.assert_frame_equal(again, view)
    assert again.attrs["censored_indices_nullified"] == 0


def test_coordinate_view_requires_explicit_saved_date_and_index() -> None:
    with pytest.raises(ValueError, match="requires date and index"):
        observed_landmark_coordinates(pd.DataFrame({"status": ["unknown"]}))
