# ruff: noqa: E501
import math
from pathlib import Path
from typing import Any, cast

import pytest
from pytest import MonkeyPatch

from research_lab import dashboard_core, display
from research_lab.dashboard_core import (
    artifact_link_targets,
    build_help_view,
    build_task_view,
    capital_mode_comparative_verdict,
    capital_mode_comparison_panel,
    capital_mode_comparison_rows,
    capital_mode_pool_verdict,
    capital_mode_tabs_panel,
    comparison_table_html,
    fmt_ratio,
    format_corporate_action_warning,
    ranking_display_frame,
    strategy_diagnosis_panel,
    strategy_health_panel,
    strategy_health_rows,
    strategy_health_verdict,
    strategy_rule_rows,
    trade_price_section_title,
    trade_verification_mode,
    trades_display_frame,
)
from research_lab.display import corporate_action_labels, signal_price_policy_label, signal_reason_label


@pytest.fixture(autouse=True)
def synthetic_stock_names(monkeypatch: MonkeyPatch) -> None:
    """Presentation checks must not depend on a private data-submodule checkout."""
    names = {"2330": "台積電", "3037": "欣興"}
    monkeypatch.setattr(display, "stock_names", lambda: names)
    monkeypatch.setattr(dashboard_core, "stock_names", lambda: names)


def test_simple_buy_hold_uses_strategy_specific_rules():
    summary = {
        "strategy": {"name": "TaskSimpleBuyHold", "params": {}},
        "run": {"initial_cash": 1_000_000},
    }

    rows = strategy_rule_rows(summary)

    # Verify 4 rule categories are returned for SimpleBuyHold
    assert len(rows) == 4
    assert all("2B" not in row["\u898f\u5247"] for row in rows)
    assert all("n/a" not in row["\u53c3\u6578"] for row in rows)


def test_ranking_table_uses_index_instead_of_duplicate_rank_column():
    rankings = {
        "stocks": [
            {
                "code": "2330",
                "total_pnl": 22966.0,
                "max_drawdown_rate": -7.81759,
                "trade_count": 12,
                "win_rate": math.nan,
                "final_qty": 1000,
            }
        ]
    }

    frame = ranking_display_frame(rankings)

    assert list(frame.columns) == ["\u80a1\u7968", "\u640d\u76ca", "\u6700\u5927\u56de\u64a4", "\u4ea4\u6613\u6b21\u6578", "\u52dd\u7387"]
    assert list(frame.index) == [1]
    assert frame.iloc[0]["\u640d\u76ca"] == "22,966"
    assert frame.iloc[0]["\u6700\u5927\u56de\u64a4"] == "-7.82%"
    assert frame.iloc[0]["\u52dd\u7387"] == "n/a"


def test_key_trades_are_localized_and_dates_do_not_include_time():
    summary = {
        "trades": [
            {
                "date": "2024-01-02T00:00:00",
                "code": "2330",
                "action": "BUY",
                "price": 593.0,
                "qty": 1000,
                "total": -593845.0,
            }
        ]
    }

    frame = trades_display_frame(summary)

    assert list(frame.columns) == [
        "\u4ea4\u6613 ID",
        "\u65e5\u671f",
        "\u80a1\u7968",
        "\u52d5\u4f5c",
        "\u6210\u4ea4\u50f9",
        "\u80a1\u6578",
        "\u4ea4\u6613\u7e3d\u984d",
    ]
    assert frame.iloc[0].to_dict() == {
        "\u4ea4\u6613 ID": "T001",
        "\u65e5\u671f": "2024-01-02",
        "\u80a1\u7968": "2330 \u53f0\u7a4d\u96fb",
        "\u52d5\u4f5c": "\u8cb7\u9032",
        "\u6210\u4ea4\u50f9": "593.00",
        "\u80a1\u6578": "1,000",
        "\u4ea4\u6613\u7e3d\u984d": "-593,845",
    }


def test_signal_codes_are_translated_for_user_facing_tables():
    assert signal_reason_label("ma_convergence_price_strength") == "\u5747\u7dda\u6536\u6582\u5f8c\u50f9\u683c\u8f49\u5f37"
    assert signal_reason_label("ma_convergence,top_2b") == "\u5747\u7dda\u6536\u6582 + \u9802\u90e8 2B \u53cd\u8f49"
    assert signal_price_policy_label("split_adjusted") == "\u5206\u5272\u8abf\u6574\u50f9"


def test_artifact_links_use_different_targets_for_static_and_server_views(monkeypatch: MonkeyPatch, tmp_path: Path):
    """`artifact_link_targets` only emits a link for a file that exists on disk.

    The fixture is built here rather than read from `tasks/sample/`: that task's
    `summary.json` is a run output and stays out of git, so reading it made this test
    pass only on a machine that had already run the sample backtest, and fail in any
    fresh clone or worktree. Both module roots are redirected together because the two
    modes derive their paths from different globals -- `server` from `TASKS_ROOT`,
    `static` via `site_relative` from `REPO_ROOT` -- and patching only one produces a
    `relative_to` error rather than a wrong link.
    """
    tasks_root = tmp_path / "tasks"
    (tasks_root / "sample").mkdir(parents=True)
    (tasks_root / "sample" / "summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dashboard_core, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tasks_root)

    server_targets = artifact_link_targets("sample", mode="server")
    static_targets = artifact_link_targets("sample", mode="static")

    assert server_targets["summary.json"] == "/artifacts/sample/summary.json"
    assert static_targets["summary.json"] == "../../tasks/sample/summary.json"


def test_artifact_links_omit_files_that_do_not_exist(monkeypatch: MonkeyPatch, tmp_path: Path):
    """A missing artifact is skipped, not linked to a 404."""
    tasks_root = tmp_path / "tasks"
    (tasks_root / "sample").mkdir(parents=True)
    (tasks_root / "sample" / "summary.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dashboard_core, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(dashboard_core, "TASKS_ROOT", tasks_root)

    targets = artifact_link_targets("sample", mode="server")

    assert "summary.json" in targets
    assert "stock_rankings.json" not in targets
    assert "signal_events.json" not in targets


def test_capital_mode_comparison_rows_formats_required_metrics():
    comparison = {
        "modes": {
            "shared": {
                "return_rate": -1.234,
                "max_drawdown_rate": -7.891,
                "win_rate": 25.0,
                "payoff_ratio": 0.8,
                "expectancy": -100.0,
                "cash_blocked_entry_count": 2,
            },
            "per_stock": {
                "return_rate": 5.0,
                "max_drawdown_rate": -4.0,
                "win_rate": 50.0,
                "payoff_ratio": 2.0,
                "expectancy": 100.0,
                "cash_blocked_entry_count": 0,
            },
            "unconstrained": {
                "return_rate": None,
                "max_drawdown_rate": None,
                "win_rate": 75.0,
                "payoff_ratio": 3.0,
                "expectancy": 200.0,
                "cash_blocked_entry_count": 0,
            },
        },
        "symbols": {"2330": {"contention_affected": True}},
    }

    rows = capital_mode_comparison_rows(comparison)

    assert rows[0]["\u6a21\u5f0f"] == "shared"
    assert rows[0]["\u5831\u916c\u7387"] == "-1.23%"
    assert rows[0]["\u6700\u5927\u56de\u64a4"] == "-7.89%"
    assert rows[2]["\u6700\u5927\u56de\u64a4"] == "n/a"
    assert rows[2]["\u5831\u916c\u7387"] == "n/a"
    assert rows[0]["\u73fe\u91d1\u963b\u64cb"] == 2
    assert rows[0]["\u8cc7\u91d1\u6392\u64e0\u80a1\u7968"] == "2330"


def test_comparison_table_html_renders_headers_and_rows():
    rows = [
        {"模式": "shared", "報酬率": "-1.23%"},
        {"模式": "per_stock", "報酬率": "5.00%"},
    ]

    html = comparison_table_html(rows)

    assert '<table class="capital-table">' in html
    assert "<th>模式</th>" in html
    assert "<th>報酬率</th>" in html
    assert html.count("<tr>") == 3  # header row + 2 data rows
    assert "<td>shared</td>" in html
    assert "<td>5.00%</td>" in html


def test_comparison_table_html_escapes_values():
    rows = [{"col": "<b>2330 & 2454</b>"}]

    html = comparison_table_html(rows)

    assert "<b>" not in html.replace("<table", "").replace("<tbody", "")
    assert "&lt;b&gt;2330 &amp; 2454&lt;/b&gt;" in html


def test_comparison_table_html_empty_rows_yield_empty_string():
    assert comparison_table_html([]) == ""


def test_capital_mode_comparison_panel_contract():
    import panel as pn

    assert capital_mode_comparison_panel(None) is None
    assert capital_mode_comparison_panel({}) is None

    panel = capital_mode_comparison_panel({
        "modes": {"shared": {"return_rate": 1.0}},
        "symbols": {},
    })

    assert isinstance(panel, pn.Column)


def test_capital_mode_comparative_verdict_flags_capital_bottleneck():
    comparison = {
        "modes": {
            "shared": {"return_rate": -5.0, "cash_blocked_entry_count": 3},
            "per_stock": {"return_rate": 8.0, "cash_blocked_entry_count": 0},
            "unconstrained": {"expectancy": 5000.0, "payoff_ratio": 2.4},
        },
        "symbols": {"2330": {"contention_affected": True}},
    }

    verdict = capital_mode_comparative_verdict(comparison)

    assert "\u8cc7\u91d1\u5206\u914d" in verdict
    assert "\u8f2a\u52d5" in verdict


def test_capital_mode_comparative_verdict_flags_signal_quality_when_per_stock_weak():
    comparison = {
        "modes": {
            "shared": {"return_rate": -8.0, "cash_blocked_entry_count": 0},
            "per_stock": {"return_rate": -7.0, "cash_blocked_entry_count": 0},
            "unconstrained": {"expectancy": -2000.0, "payoff_ratio": 0.8},
        },
        "symbols": {},
    }

    verdict = capital_mode_comparative_verdict(comparison)

    assert "\u4fe1\u865f\u54c1\u8cea" in verdict


def test_capital_mode_comparative_verdict_flags_similar_pools():
    comparison = {
        "modes": {
            "shared": {"return_rate": 3.0, "cash_blocked_entry_count": 0},
            "per_stock": {"return_rate": 3.4, "cash_blocked_entry_count": 0},
            "unconstrained": {"expectancy": 1000.0, "payoff_ratio": 1.5},
        },
        "symbols": {},
    }

    verdict = capital_mode_comparative_verdict(comparison)

    assert "\u63a5\u8fd1" in verdict


def test_capital_mode_pool_verdict_marks_unconstrained_as_signal_quality_only():
    summary = {
        "metrics": {
            "return_rate": None,
            "max_drawdown_rate": None,
            "expectancy": 2500.0,
            "payoff_ratio": 2.2,
            "closed_trade_count": 3,
        }
    }

    verdict = capital_mode_pool_verdict("unconstrained", summary)

    assert "\u4fe1\u865f\u54c1\u8cea" in verdict
    assert "\u771f\u5be6\u5831\u916c" in verdict


def test_capital_mode_tabs_panel_contract():
    import panel as pn

    assert capital_mode_tabs_panel({"comparison": None, "mode_summaries": {}}) is None

    panel = capital_mode_tabs_panel({
        "comparison": {
            "modes": {
                "shared": {"return_rate": 1.0, "win_rate": 50.0},
                "per_stock": {"return_rate": 2.0, "win_rate": 60.0},
                "unconstrained": {"return_rate": None, "win_rate": 70.0},
            },
            "symbols": {},
        },
        "mode_summaries": {
            mode: {
                "metrics": {
                    "return_rate": None if mode == "unconstrained" else 1.0,
                    "max_drawdown_rate": None if mode == "unconstrained" else -5.0,
                    "cash_blocked_entry_count": 0,
                    "closed_trade_count": 0,
                    "trade_count": 0,
                },
                "equity_curve": [],
                "drawdown_curve": [],
                "run": {"capital_mode": mode, "initial_cash": 1000000},
                "strategy": {"name": "TwoBMovingAverageConvergence"},
            }
            for mode in ["shared", "per_stock", "unconstrained"]
        },
    })

    assert isinstance(panel, pn.Tabs)
    assert len(panel) == 4


def test_build_help_view_documents_commands_and_locations():
    view = build_help_view()
    text = "\n".join(str(item.object) for item in cast(list[Any], view.objects) if hasattr(item, "object"))

    assert "run_task_backtest" in text
    assert "--capital-mode all" in text
    assert "tasks/" in text
    assert "scripts.build_research_dashboard" in text
    assert ".\\scripts\\research\\open_research_dashboard.cmd" in text
    assert "panel serve" not in text
    assert "dashboard_app.py" not in text


def test_task_view_can_render_without_exposing_dataframe_index_controls():
    view = build_task_view("sample")

    assert view is not None


def test_corporate_action_warning_is_user_facing():
    warning = "Unsupported corporate action for 3037 on 2025-11-14: EX_RIGHT"

    result = format_corporate_action_warning(warning)

    assert "3037 \u6b23\u8208" in result
    assert "2025-11-14" in result
    assert "\u9664\u6b0a" in result
    assert "\u5c1a\u672a\u81ea\u52d5\u8abf\u6574\u80a1\u6578" in result
    assert "Unsupported" not in result


def test_simple_buy_hold_uses_buy_hold_trade_verification():
    report = {"strategy": {"name": "TaskSimpleBuyHold", "params": {}}}

    assert trade_verification_mode(report) == "buy_hold"


def test_two_b_uses_signal_trade_verification():
    report = {
        "strategy": {
            "name": "TwoBMovingAverageConvergence",
            "params": {"windows": [5, 10, 20]},
        }
    }

    assert trade_verification_mode(report) == "two_b"


def test_buy_hold_price_section_does_not_claim_to_show_moving_averages():
    report = {"strategy": {"name": "TaskSimpleBuyHold"}}

    assert trade_price_section_title(report) == "\u7576\u65e5\u50f9\u683c\u8cc7\u6599"


# ── B1: fmt_pct_value NaN guard ──────────────────────────────────────────────


def test_fmt_pct_value_returns_na_for_nan_input():
    """fmt_pct_value in dashboard_core must handle NaN without showing 'nan'."""
    from research_lab.dashboard_core import fmt_pct_value  # noqa: PLC0415

    assert fmt_pct_value(math.nan) == "n/a"


def test_fmt_pct_value_formats_number_with_three_decimal_places():
    """fmt_pct_value formats a valid float as a 3-decimal-place percentage."""
    from research_lab.dashboard_core import fmt_pct_value  # noqa: PLC0415

    assert fmt_pct_value(2.0) == "2.000%"


# ── B3: corporate_action_labels comma splitting ───────────────────────────────


def test_corporate_action_labels_translates_comma_separated_string():
    """Comma-joined string from price_context should be split and each token translated."""
    assert corporate_action_labels("EX_RIGHT,CASH_DIVIDEND") == "\u9664\u6b0a\u3001\u73fe\u91d1\u80a1\u5229"


def test_corporate_action_labels_single_string_works_after_fix():
    """Single-value string still translates correctly after the comma-split change."""
    assert corporate_action_labels("EX_RIGHT") == "\u9664\u6b0a"


def test_corporate_action_labels_list_input_unaffected():
    """List input behaviour is unchanged by the comma-split fix."""
    assert corporate_action_labels(["EX_RIGHT", "CASH_DIVIDEND"]) == "\u9664\u6b0a\u3001\u73fe\u91d1\u80a1\u5229"


# ── B4: _ma_rows_for_windows uses strategy windows ───────────────────────────


def test_two_b_ma_rows_uses_given_windows():
    """_ma_rows_for_windows must produce rows keyed to the given windows, not hardcoded 5/10/20."""
    from research_lab.dashboard_core import _ma_rows_for_windows  # noqa: PLC0415

    price_context = {
        "moving_averages": {"ma8": 150.5, "ma21": 145.2},
        "ma_max": 150.5,
        "ma_min": 145.2,
    }
    rows = _ma_rows_for_windows(price_context, [8, 21])
    assert [r["\u6b04\u4f4d"] for r in rows] == ["MA8", "MA21", "\u5747\u7dda\u6700\u9ad8\u503c", "\u5747\u7dda\u6700\u4f4e\u503c"]
    assert rows[0]["\u6578\u503c"] == "150.50"


def test_two_b_ma_rows_missing_value_shows_na():
    """A window with no data in moving_averages should show n/a, not raise KeyError."""
    from research_lab.dashboard_core import _ma_rows_for_windows  # noqa: PLC0415

    price_context = {
        "moving_averages": {"ma5": 100.0},
        "ma_max": 100.0,
        "ma_min": 100.0,
    }
    rows = _ma_rows_for_windows(price_context, [5, 10, 20])
    assert rows[1]["\u6578\u503c"] == "n/a"  # ma10 is missing


# ── U1: _win_rate_display shows '\u4e0d\u9069\u7528' for buy-hold ─────────────────────────


def test_buy_hold_win_rate_shows_not_applicable():
    """SimpleBuyHold never closes trades, so win rate must display '\u4e0d\u9069\u7528', not 'n/a'."""
    from research_lab.dashboard_core import _win_rate_display  # noqa: PLC0415

    summary = {
        "strategy": {"name": "TaskSimpleBuyHold", "params": {}},
        "metrics": {"win_rate": None},
    }
    assert _win_rate_display(summary) == "\u4e0d\u9069\u7528"


def test_non_buy_hold_win_rate_shows_formatted_percentage():
    """Non-buy-hold strategy with a numeric win rate should show a formatted percentage."""
    from research_lab.dashboard_core import _win_rate_display  # noqa: PLC0415

    summary = {
        "strategy": {"name": "TwoBMovingAverageConvergence", "params": {}},
        "metrics": {"win_rate": 45.5},
    }
    assert _win_rate_display(summary) == "45.50%"


def test_non_buy_hold_win_rate_shows_na_when_none():
    """Non-buy-hold strategy with None win rate falls back to 'n/a'."""
    from research_lab.dashboard_core import _win_rate_display  # noqa: PLC0415

    summary = {
        "strategy": {"name": "TwoBMovingAverageConvergence", "params": {}},
        "metrics": {"win_rate": None},
    }
    assert _win_rate_display(summary) == "n/a"


# ── U2: _strategy_verdict uses '\u500b\u767e\u5206\u9ede' wording ────────────────────────────


def test_strategy_verdict_for_underperformance_uses_percentage_points():
    """Underperformance verdict must say '\u843d\u5f8c X \u500b\u767e\u5206\u9ede', not '\u8dd1\u8f38', to avoid misreading gap as benchmark value."""
    from research_lab.dashboard_core import _strategy_verdict  # noqa: PLC0415

    summary = {
        "strategy": {"name": "TwoBMovingAverageConvergence", "params": {}},
        "metrics": {"return_rate": -5.34, "excess_return_rate": -193.45},
        "benchmark": {"benchmark_code": "0050"},
        "run": {"initial_cash": 1_000_000},
    }
    verdict = _strategy_verdict(summary)
    assert "\u500b\u767e\u5206\u9ede" in verdict
    assert "\u843d\u5f8c" in verdict
    assert "\u8dd1\u8f38" not in verdict


# \u2500\u2500 Part B: strategy health check \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


def test_fmt_ratio_formats_with_two_decimal_places():
    """fmt_ratio must format a float as 'Nx.xxxx' with two decimals and 'x' suffix."""
    assert fmt_ratio(2.5) == "2.50x"
    assert fmt_ratio(None) == "n/a"


def test_strategy_health_verdict_compliant():
    """payoff_ratio >= 2 and expectancy > 0 should report compliance."""
    result = strategy_health_verdict(2.5, 10000)
    assert "\u7b26\u5408\u5927\u8cfa\u5c0f\u8ce0" in result


def test_strategy_health_verdict_wrong_direction():
    """payoff_ratio < 1 and expectancy <= 0 should flag wrong direction."""
    result = strategy_health_verdict(0.8, -5000)
    assert "\u5c0f\u8cfa\u5927\u8ce0" in result


def test_strategy_health_verdict_no_closed_trades():
    """Both None should return the 'not applicable' string."""
    assert strategy_health_verdict(None, None) == "\u4e0d\u9069\u7528\uff08\u7121\u5df2\u7d50\u675f\u4ea4\u6613\uff09"


def test_strategy_health_rows_full_data():
    """Full metrics dict should produce formatted values and a passing verdict."""
    summary = {
        "strategy": {"name": "TwoBMovingAverageConvergence"},
        "metrics": {
            "expectancy": 12345.0,
            "payoff_ratio": 2.5,
            "profit_factor": 3.1,
            "calmar_ratio": 1.8,
            "avg_win": 25000.0,
            "avg_loss": -10000.0,
            "largest_win": 80000.0,
            "largest_loss": -30000.0,
            "closed_trade_count": 42,
        },
    }
    rows = strategy_health_rows(summary)
    assert rows["payoff_ratio_fmt"].endswith("x")
    assert rows["expectancy_fmt"] != "n/a"
    assert "\u7b26\u5408\u5927\u8cfa\u5c0f\u8ce0" in rows["verdict"]


def test_strategy_health_rows_calmar_fallback():
    """When calmar_ratio is absent, compute it from return_rate / abs(max_drawdown_rate)."""
    summary = {
        "metrics": {
            "return_rate": 20.0,
            "max_drawdown_rate": -10.0,
            "closed_trade_count": 5,
        }
    }
    rows = strategy_health_rows(summary)
    assert rows["calmar_fmt"] == "2.00x"


def test_strategy_health_rows_old_summary_graceful_degradation():
    """A summary missing all health-check keys should degrade gracefully."""
    summary = {
        "metrics": {
            "return_rate": 15.0,
            "max_drawdown_rate": -5.0,
            "trade_count": 10,
        }
    }
    rows = strategy_health_rows(summary)
    assert rows["payoff_ratio_fmt"] == "n/a"
    assert rows["expectancy_fmt"] == "n/a"
    assert rows["profit_factor_fmt"] == "n/a"
    assert rows["verdict"] == "\u4e0d\u9069\u7528\uff08\u7121\u5df2\u7d50\u675f\u4ea4\u6613\uff09"


def test_strategy_health_panel_returns_none_for_simple_buy_hold():
    """SimpleBuyHold strategy should always return None from strategy_health_panel."""
    summary = {
        "strategy": {"name": "TaskSimpleBuyHold"},
        "metrics": {"closed_trade_count": 10},
    }
    assert strategy_health_panel(summary) is None


def test_strategy_health_panel_returns_none_when_no_closed_trades():
    """Zero closed trades should return None from strategy_health_panel."""
    summary = {
        "strategy": {"name": "TwoBMovingAverageConvergence"},
        "metrics": {"closed_trade_count": 0},
    }
    assert strategy_health_panel(summary) is None


def test_strategy_health_verdict_positive_expectancy_no_payoff() -> None:
    result = strategy_health_verdict(None, 5000)
    assert "\u671f\u671b\u503c\u6b63" in result
    assert "\u76c8\u8667\u6bd4" in result


def test_fmt_ratio_handles_nan() -> None:
    assert fmt_ratio(float("nan")) == "n/a"


# ── Part D: strategy_diagnosis_panel ────────────────────────────────────────────


def test_strategy_diagnosis_panel_returns_none_for_empty_string() -> None:
    assert strategy_diagnosis_panel("") is None


def test_strategy_diagnosis_panel_returns_none_for_whitespace() -> None:
    assert strategy_diagnosis_panel("   \n  ") is None


def test_strategy_diagnosis_panel_returns_panel_for_content() -> None:
    import panel as pn

    result = strategy_diagnosis_panel("# \u7b56\u7565\u9ad4\u6aa2\u5831\u544a\n\nsome content")
    assert result is not None
    assert isinstance(result, pn.Column)


# \u2500\u2500 Part E: marks_for_trade \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


from research_lab.dashboard_core import marks_for_trade  # noqa: E402


def _mk_trade(trade_id: str, action: str, qty: int, date: str = "2022-01-01", price: float = 100.0) -> dict:
    return {"trade_id": trade_id, "action": action, "qty": qty, "date": date, "price": price}


def test_marks_for_trade_empty_trades_returns_empty():
    assert marks_for_trade([], "T001") == []


def test_marks_for_trade_show_all_returns_all():
    trades = [_mk_trade("T001", "BUY", 1000), _mk_trade("T002", "SELL", 1000)]
    assert len(marks_for_trade(trades, "T001", show_all=True)) == 2


def test_marks_for_trade_buy_sell_same_episode():
    """Selecting the buy or the sell should return both trades."""
    trades = [_mk_trade("T001", "BUY", 1000), _mk_trade("T002", "SELL", 1000)]
    assert len(marks_for_trade(trades, "T001")) == 2
    assert len(marks_for_trade(trades, "T002")) == 2


def test_marks_for_trade_with_add_on_all_in_episode():
    """BUY + add-on BUY + two SELLs form a single episode."""
    trades = [
        _mk_trade("T001", "BUY", 1000),
        _mk_trade("T002", "BUY", 1000),
        _mk_trade("T003", "SELL", 1000),
        _mk_trade("T004", "SELL", 1000),
    ]
    result = marks_for_trade(trades, "T001")
    assert len(result) == 4


def test_marks_for_trade_two_episodes_are_isolated():
    """Point in episode 1 must not return episode 2 trades and vice-versa."""
    trades = [
        _mk_trade("T001", "BUY", 1000, date="2022-01-01"),
        _mk_trade("T002", "SELL", 1000, date="2022-02-01"),
        _mk_trade("T003", "BUY", 1000, date="2022-03-01"),
        _mk_trade("T004", "SELL", 1000, date="2022-04-01"),
    ]
    ep1 = marks_for_trade(trades, "T001")
    ep2 = marks_for_trade(trades, "T003")
    assert [t["trade_id"] for t in ep1] == ["T001", "T002"]
    assert [t["trade_id"] for t in ep2] == ["T003", "T004"]


def test_marks_for_trade_open_episode_at_end():
    """An unclosed position episode (no final sell) is still returned."""
    trades = [_mk_trade("T001", "BUY", 1000), _mk_trade("T002", "BUY", 1000)]
    result = marks_for_trade(trades, "T002")
    assert len(result) == 2


def test_marks_for_trade_fallback_for_unknown_id():
    """A trade_id that does not exist in any episode returns an empty list."""
    trades = [_mk_trade("T001", "BUY", 1000)]
    assert marks_for_trade(trades, "T999") == []


def test_marks_for_trade_dividend_does_not_close_episode():
    """DIVIDEND inside a position must not split the episode."""
    trades = [
        _mk_trade("T001", "BUY", 1000),
        _mk_trade("T002", "DIVIDEND", 0),
        _mk_trade("T003", "SELL", 1000),
    ]
    result = marks_for_trade(trades, "T001")
    assert len(result) == 3
    assert result[1]["trade_id"] == "T002"


def test_marks_for_trade_partial_sell_keeps_episode_open():
    """Partial sell that leaves remaining shares does not close the episode."""
    trades = [
        _mk_trade("T001", "BUY", 2000),
        _mk_trade("T002", "SELL", 1000),  # partial; 1000 shares remain
        _mk_trade("T003", "SELL", 1000),  # final exit
    ]
    result = marks_for_trade(trades, "T002")  # select the partial sell
    assert len(result) == 3  # all three belong to the same episode
