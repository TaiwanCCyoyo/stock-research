import type { ReactNode } from "react";
import { CompareBars } from "../../components/ui/primitives";
import { percentage } from "../strategies/format";
import { marketCaptureLink } from "../full-history/navigation.ts";
import type { latestMarketSummary } from "./model";

type Summary = ReturnType<typeof latestMarketSummary>;

/** Market block of the home page: counts, industries and the strongest names. */
export function MarketOverview({
    summary,
    date,
}: {
    summary: Summary;
    date: string;
}) {
    const gain = (pct: number | null | undefined) =>
        percentage((pct ?? 0) / 100, 0);
    if (!summary.count) {
        return (
            <div className="u-card hm-state" role="status">
                <p>這個日期沒有符合首頁門檻的股票。</p>
                <a className="u-btn" href={marketCaptureLink(date)}>
                    到地圖選其他日期或調整門檻
                </a>
            </div>
        );
    }
    return (
        <div className="hm-grid">
            <div className="u-stack">
                <div className="u-grid-2 hm-kpis">
                    <Kpi
                        value={summary.count}
                        unit="檔"
                        label="符合波段門檻"
                        feature
                    />
                    <Kpi
                        value={summary.industries.length}
                        unit="個"
                        label="涵蓋產業"
                    />
                </div>
                <div className="u-card">
                    <h2 className="hm-card-title">哪些產業最多</h2>
                    <CompareBars
                        rows={summary.industries.slice(0, 6).map((group) => ({
                            label: group.label,
                            value: group.rows.length,
                            display: `${group.rows.length}`,
                        }))}
                    />
                    <div className="u-actions hm-more">
                        <a
                            className="u-btn u-btn-primary"
                            href={marketCaptureLink(date)}
                        >
                            打開飆股地圖
                        </a>
                    </div>
                </div>
            </div>
            <div className="u-card">
                <h2 className="hm-card-title">波段漲幅指標較高的股票</h2>
                <ul className="u-list">
                    {summary.strongest.slice(0, 7).map((row) => (
                        <li key={row.securityId}>
                            <a href={marketCaptureLink(date, row.code)}>
                                <span className="u-code">{row.code}</span>
                                {row.name}
                            </a>
                            <span>
                                <span className="u-gain u-num">
                                    {gain(row.growth?.sizingGainPct)}
                                </span>
                                <small className="u-muted hm-basis">
                                    {row.growth?.basis === "annualized"
                                        ? "年化"
                                        : "實際"}
                                </small>
                            </span>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    );
}

function Kpi({
    value,
    unit,
    label,
    feature = false,
}: {
    value: number;
    unit: string;
    label: ReactNode;
    feature?: boolean;
}) {
    return (
        <div className={`u-card${feature ? " u-feature" : ""}`}>
            <div className="u-big">
                {value}
                <small>{unit}</small>
            </div>
            <p className="u-muted">{label}</p>
        </div>
    );
}
