import type { HealthRows } from "../api/types";

interface StrategyHealthProps {
    health: HealthRows;
}

/** Active-trading health panel; hidden when there are no closed trades (spec). */
export function StrategyHealth({ health }: StrategyHealthProps) {
    if (!health || health.closed_trade_count === 0) return null;
    const rows: [string, string][] = [
        ["盈虧比", health.payoff_ratio_fmt],
        ["期望值", health.expectancy_fmt],
        ["獲利因子", health.profit_factor_fmt],
        ["Calmar", health.calmar_fmt],
        ["平均獲利", health.avg_win_fmt],
        ["平均虧損", health.avg_loss_fmt],
        ["最大單筆獲利", health.largest_win_fmt],
        ["最大單筆虧損", health.largest_loss_fmt],
        ["已結束交易", String(health.closed_trade_count)],
    ];
    return (
        <section className="panel">
            <h3 className="panel-title">策略健康檢查 — {health.verdict}</h3>
            <div className="health-grid">
                {rows.map(([label, value]) => (
                    <div key={label} className="health-cell">
                        <div className="label">{label}</div>
                        <div className="value num">{value}</div>
                    </div>
                ))}
            </div>
        </section>
    );
}
