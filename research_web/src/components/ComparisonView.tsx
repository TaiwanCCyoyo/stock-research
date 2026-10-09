import { useState } from "react";
import type { Summary, TaskBundle } from "../api/types";
import { fmtNum, fmtPct, fmtRatio, tdSignClass } from "../lib/format";
import { MODE_LABELS } from "../lib/capitalModes";
import { EquityChart } from "./EquityChart";

const METRIC_ROWS: {
    key: string;
    label: string;
    fmt: (v: number | null | undefined) => string;
    signed?: boolean;
}[] = [
    {
        key: "return_rate",
        label: "報酬率",
        fmt: (v) => fmtPct(v),
        signed: true,
    },
    {
        key: "max_drawdown_rate",
        label: "最大回撤",
        fmt: (v) => fmtPct(v),
        signed: true,
    },
    { key: "win_rate", label: "勝率", fmt: (v) => fmtPct(v) },
    { key: "payoff_ratio", label: "盈虧比", fmt: (v) => fmtRatio(v) },
    { key: "expectancy", label: "期望值", fmt: (v) => fmtNum(v), signed: true },
    {
        key: "cash_blocked_entry_count",
        label: "資金不足擋單數",
        fmt: (v) => fmtNum(v),
    },
];

interface ComparisonViewProps {
    bundle: TaskBundle;
}

function modeMetric(
    modes: Record<string, Record<string, number | null>>,
    modeSummaries: Record<string, Summary>,
    mode: string,
    key: string,
): number | null | undefined {
    const direct = modes[mode]?.[key];
    if (direct !== null && direct !== undefined) return direct;
    // Fall back to the per-mode summary (e.g. max_drawdown_rate is not in comparison.json).
    return modeSummaries[mode]?.metrics?.[key];
}

function PoolTab({ bundle, mode }: { bundle: TaskBundle; mode: string }) {
    const summary = bundle.mode_summaries[mode];
    if (!summary)
        return <div className="empty-state">缺少 summary_{mode}.json</div>;
    const metrics = summary.metrics ?? {};
    const verdict = bundle.judgments?.pools?.[mode];
    const curve = summary.portfolio?.equity_curve ?? [];
    const debugRows: [string, string][] = [
        ["資金不足擋單數", fmtNum(metrics.cash_blocked_entry_count)],
        ["買進次數", fmtNum(metrics.buy_count)],
        ["賣出次數", fmtNum(metrics.sell_count)],
        ["配息次數", fmtNum(metrics.dividend_count)],
        ["期末資產", fmtNum(metrics.final_value)],
        ["總損益", fmtNum(metrics.total_pnl)],
    ];
    return (
        <>
            {verdict && <div className="verdict-note">{verdict}</div>}
            <div
                className="metric-row"
                style={{ padding: 0, marginBottom: 14 }}
            >
                {METRIC_ROWS.map((row) => (
                    <div key={row.key} className="metric-chip">
                        <div className="label">{row.label}</div>
                        <div
                            className={`value ${row.signed ? (tdSignClass(metrics[row.key])?.replace("td-", "") ?? "") : ""}`}
                        >
                            {row.fmt(metrics[row.key])}
                        </div>
                    </div>
                ))}
            </div>
            {curve.length > 0 ? (
                <EquityChart curve={curve} />
            ) : (
                <div className="empty-state" style={{ minHeight: 80 }}>
                    無淨值曲線資料
                </div>
            )}
            <h3 className="panel-title" style={{ marginTop: 16 }}>
                除錯資訊
            </h3>
            <div className="health-grid">
                {debugRows.map(([label, value]) => (
                    <div key={label} className="health-cell">
                        <div className="label">{label}</div>
                        <div className="value num">{value}</div>
                    </div>
                ))}
            </div>
            {(summary.warnings ?? []).length > 0 && (
                <div className="error-banner" style={{ marginTop: 12 }}>
                    {(summary.warnings ?? []).map((warning, i) => (
                        <div key={i}>{warning}</div>
                    ))}
                </div>
            )}
        </>
    );
}

export function ComparisonView({ bundle }: ComparisonViewProps) {
    const [subTab, setSubTab] = useState("overview");
    const comparison = bundle.comparison;
    if (
        !comparison ||
        typeof comparison !== "object" ||
        !("modes" in comparison)
    ) {
        return (
            <div className="empty-state">
                此任務沒有資金池比較資料（需以 --capital-mode all 重跑）
            </div>
        );
    }
    const modes = (comparison.modes ?? {}) as Record<
        string,
        Record<string, number | null>
    >;
    const symbols = ((comparison as Record<string, unknown>).symbols ??
        {}) as Record<
        string,
        {
            shared_total_pnl?: number;
            per_stock_total_pnl?: number;
            contention_affected?: boolean;
        }
    >;
    const modeKeys = Object.keys(modes);
    const symbolKeys = Object.keys(symbols).sort();
    const affectedCount = symbolKeys.filter(
        (code) => symbols[code].contention_affected,
    ).length;
    const subTabs = [
        { key: "overview", label: "比較總覽" },
        ...modeKeys.map((mode) => ({
            key: mode,
            label: MODE_LABELS[mode] ?? mode,
        })),
    ];

    return (
        <>
            <div
                className="tab-strip"
                style={{ padding: "0 0 0 4px", marginBottom: 16 }}
            >
                {subTabs.map((item) => (
                    <button
                        key={item.key}
                        type="button"
                        className={`tab${subTab === item.key ? " active" : ""}`}
                        onClick={() => setSubTab(item.key)}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            {subTab === "overview" && (
                <>
                    {bundle.judgments?.comparative && (
                        <div className="verdict-note">
                            {bundle.judgments.comparative}
                        </div>
                    )}
                    <section className="panel">
                        <h3 className="panel-title">三種資金模式總覽</h3>
                        <div className="table-scroll">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>指標</th>
                                        {modeKeys.map((mode) => (
                                            <th key={mode}>
                                                {MODE_LABELS[mode] ?? mode}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {METRIC_ROWS.map((row) => (
                                        <tr key={row.key}>
                                            <td
                                                style={{
                                                    color: "var(--text-secondary)",
                                                    fontWeight: 550,
                                                }}
                                            >
                                                {row.label}
                                            </td>
                                            {modeKeys.map((mode) => {
                                                const value = modeMetric(
                                                    modes,
                                                    bundle.mode_summaries,
                                                    mode,
                                                    row.key,
                                                );
                                                return (
                                                    <td
                                                        key={mode}
                                                        className={
                                                            row.signed
                                                                ? tdSignClass(
                                                                      value,
                                                                  )
                                                                : ""
                                                        }
                                                    >
                                                        {row.fmt(value)}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </section>

                    <section className="panel">
                        <h3 className="panel-title">
                            個股損益對照（共用 vs 各股獨立）· 受資金競爭影響{" "}
                            {affectedCount}/{symbolKeys.length} 檔
                        </h3>
                        <div className="table-scroll">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>代號</th>
                                        <th>共用資金池損益</th>
                                        <th>各股獨立損益</th>
                                        <th>差異</th>
                                        <th>資金競爭</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {symbolKeys.map((code) => {
                                        const row = symbols[code];
                                        const shared =
                                            row.shared_total_pnl ?? null;
                                        const perStock =
                                            row.per_stock_total_pnl ?? null;
                                        const delta =
                                            shared !== null && perStock !== null
                                                ? shared - perStock
                                                : null;
                                        return (
                                            <tr key={code}>
                                                <td style={{ fontWeight: 550 }}>
                                                    {code}
                                                </td>
                                                <td
                                                    className={tdSignClass(
                                                        shared,
                                                    )}
                                                >
                                                    {fmtNum(shared)}
                                                </td>
                                                <td
                                                    className={tdSignClass(
                                                        perStock,
                                                    )}
                                                >
                                                    {fmtNum(perStock)}
                                                </td>
                                                <td
                                                    className={tdSignClass(
                                                        delta,
                                                    )}
                                                >
                                                    {fmtNum(delta)}
                                                </td>
                                                <td>
                                                    {row.contention_affected ? (
                                                        <span className="badge sell">
                                                            受影響
                                                        </span>
                                                    ) : (
                                                        <span
                                                            style={{
                                                                color: "var(--text-muted)",
                                                            }}
                                                        >
                                                            —
                                                        </span>
                                                    )}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </section>
                </>
            )}

            {subTab !== "overview" && (
                <section className="panel">
                    <PoolTab bundle={bundle} mode={subTab} />
                </section>
            )}
        </>
    );
}
