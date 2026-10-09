import { useMemo, useState } from "react";
import type { TaskBundle } from "../api/types";
import { fmtNum, fmtPct, stockLabel, tdSignClass } from "../lib/format";

interface RankingTableProps {
    bundle: TaskBundle;
}

const UNCLASSIFIED = "__unclassified__";

export function RankingTable({ bundle }: RankingTableProps) {
    const stocks = useMemo(() => bundle.rankings?.stocks ?? [], [bundle]);
    const [industryFilter, setIndustryFilter] = useState("");

    const industries = useMemo(
        () =>
            [
                ...new Set(
                    stocks
                        .map((row) => row.industry_category)
                        .filter((value): value is string => Boolean(value)),
                ),
            ].sort(),
        [stocks],
    );
    const hasUnclassified = useMemo(
        () => stocks.some((row) => !row.industry_category),
        [stocks],
    );

    const filtered = useMemo(() => {
        if (!industryFilter) return stocks;
        if (industryFilter === UNCLASSIFIED)
            return stocks.filter((row) => !row.industry_category);
        return stocks.filter((row) => row.industry_category === industryFilter);
    }, [stocks, industryFilter]);

    if (stocks.length === 0) {
        return <div className="empty-state">此任務沒有個股排名資料</div>;
    }

    return (
        <section className="panel">
            <div className="toolbar">
                <select
                    className="select"
                    value={industryFilter}
                    onChange={(e) => setIndustryFilter(e.target.value)}
                    aria-label="篩選產業別"
                >
                    <option value="">全部產業</option>
                    {industries.map((industry) => (
                        <option key={industry} value={industry}>
                            {industry}
                        </option>
                    ))}
                    {hasUnclassified && (
                        <option value={UNCLASSIFIED}>無分類資料</option>
                    )}
                </select>
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                    {filtered.length} / {stocks.length} 檔
                </span>
            </div>
            <div className="table-scroll">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>代號</th>
                            <th>產業別</th>
                            <th>損益</th>
                            <th>最大回撤</th>
                            <th>交易次數</th>
                            <th>勝率</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filtered.map((row) => (
                            <tr key={String(row.code)}>
                                <td>
                                    {stockLabel(row.code, bundle.stock_names)}
                                </td>
                                <td>{row.industry_category ?? "—"}</td>
                                <td className={tdSignClass(row.total_pnl)}>
                                    {fmtNum(row.total_pnl)}
                                </td>
                                <td>{fmtPct(row.max_drawdown_rate)}</td>
                                <td>{fmtNum(row.trade_count)}</td>
                                <td>{fmtPct(row.win_rate)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {filtered.length === 0 && (
                <div className="empty-state">沒有符合條件的股票</div>
            )}
        </section>
    );
}
