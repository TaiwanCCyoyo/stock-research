import type { Summary } from "../api/types";
import { fmtNum, fmtPct, fmtRatio, signClass } from "../lib/format";

interface MetricChipsProps {
    summary: Summary;
}

interface ChipSpec {
    label: string;
    value: string;
    cls?: string;
}

export function MetricChips({ summary }: MetricChipsProps) {
    const metrics = summary.metrics ?? {};
    const chips: ChipSpec[] = [
        {
            label: "報酬率",
            value: fmtPct(metrics.return_rate),
            cls: signClass(metrics.return_rate),
        },
        {
            label: "買進持有",
            value: fmtPct(metrics.buy_and_hold_return_rate),
            cls: signClass(metrics.buy_and_hold_return_rate),
        },
        {
            label: "最大回撤",
            value: fmtPct(metrics.max_drawdown_rate),
            cls: signClass(metrics.max_drawdown_rate),
        },
        { label: "勝率", value: fmtPct(metrics.win_rate) },
        { label: "盈虧比", value: fmtRatio(metrics.payoff_ratio) },
        {
            label: "期望值",
            value: fmtNum(metrics.expectancy),
            cls: signClass(metrics.expectancy),
        },
        { label: "交易數", value: fmtNum(metrics.trade_count) },
    ];
    return (
        <div className="metric-row">
            {chips.map((chip) => (
                <div key={chip.label} className="metric-chip">
                    <div className="label">{chip.label}</div>
                    <div className={`value ${chip.cls ?? ""}`}>
                        {chip.value}
                    </div>
                </div>
            ))}
        </div>
    );
}
