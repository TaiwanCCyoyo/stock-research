from __future__ import annotations

import numpy as np
import pandas as pd

from research_core.industry_breadth_v1 import industry_daily, prior_turnover


def test_breadth_excludes_subject_and_marks_fewer_than_five_known_peers_unknown() -> None:
    dates = pd.date_range("2024-01-02", periods=2)
    codes = ["A", "B", "C", "D", "E", "F", "G"]
    eligible = pd.DataFrame(True, index=dates, columns=pd.Index(codes))
    eligible.loc[dates[1], "F"] = False
    a4 = pd.DataFrame([[1, 1, 0, 0, 0, 0, -1]] * 2, index=dates, columns=pd.Index(codes))
    turnover = pd.DataFrame(100.0, index=dates, columns=pd.Index(codes))
    result = industry_daily(eligible, a4, turnover, dict.fromkeys(codes, "industry"))

    # A's own A4=1 must not enter its numerator; its five known peers contain one high.
    assert result.known_peer_n.at[dates[0], "A"] == 5
    assert result.breadth.at[dates[0], "A"] == 1 / 5
    # F's later exit leaves only four known peers for A on the second session.
    assert result.known_peer_n.at[dates[1], "A"] == 4
    assert np.isnan(result.breadth.at[dates[1], "A"])
    assert result.hot.at[dates[1], "A"] == -1


def test_small_uses_average_percentile_for_ties_and_missing_turnover_stays_unknown() -> None:
    dates = pd.date_range("2024-01-02", periods=1)
    codes = ["A", "B", "C", "D"]
    eligible = pd.DataFrame(True, index=dates, columns=pd.Index(codes))
    a4 = pd.DataFrame(0, index=dates, columns=pd.Index(codes))
    turnover = pd.DataFrame([[10.0, 10.0, 20.0, np.nan]], index=dates, columns=pd.Index(codes))
    result = industry_daily(eligible, a4, turnover, dict.fromkeys(codes, "industry"))

    assert result.size_percentile.at[dates[0], "A"] == 50.0
    assert result.size_percentile.at[dates[0], "B"] == 50.0
    assert result.small.at[dates[0], "A"] == 0
    assert result.size_percentile.at[dates[0], "D"] != result.size_percentile.at[dates[0], "D"]
    assert result.small.at[dates[0], "D"] == -1


def test_new_listing_changes_daily_peer_set_without_backfilling_eligibility() -> None:
    dates = pd.date_range("2024-01-02", periods=3)
    codes = list("ABCDEF")
    eligible = pd.DataFrame(True, index=dates, columns=pd.Index(codes))
    eligible.loc[dates[0], "F"] = False
    eligible.loc[dates[2], "F"] = False  # an eligible peer exits; it must leave that day's denominator
    a4 = pd.DataFrame(0, index=dates, columns=pd.Index(codes))
    a4.loc[dates[1], "F"] = 1
    turnover = pd.DataFrame(100.0, index=dates, columns=pd.Index(codes))
    result = industry_daily(eligible, a4, turnover, dict.fromkeys(codes, "industry"))

    assert result.known_peer_n.at[dates[0], "A"] == 4
    assert np.isnan(result.breadth.at[dates[0], "A"])
    assert result.known_peer_n.at[dates[1], "A"] == 5
    assert result.breadth.at[dates[1], "A"] == 1 / 5
    assert np.isnan(result.size_percentile.at[dates[0], "F"])
    assert result.known_peer_n.at[dates[2], "A"] == 4
    assert np.isnan(result.breadth.at[dates[2], "A"])


def test_prior_turnover_is_previous_twenty_session_mean() -> None:
    raw_amount = pd.Series([100.0] * 20 + [100_000.0], index=pd.date_range("2024-01-02", periods=21))
    result = prior_turnover(raw_amount)

    assert result.iloc[:20].isna().all()
    # The current spike belongs to tomorrow; this series is producer amount in TWD.
    assert result.iloc[20] == 100.0
