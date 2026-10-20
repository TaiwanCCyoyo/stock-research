import type { DataQualityCheckName, DataQualityResponse } from "../api/types";
import type { ReactNode } from "react";
import type { DataQualityState } from "./dataQualityState";
import { formatQualityShare as formatShare } from "./dataQualityState";

interface DataQualityProps {
    state: DataQualityState;
    onRetry: () => void;
}

const CHECK_LABELS: Record<DataQualityCheckName, string> = {
    price_gap_without_ca_event: "價格缺口未對應公司行動",
    ca_event_without_price_gap: "公司行動未反映於價格缺口",
    unexplained_fallback: "備援資料未能說明",
};

function ReadStatus({
    children,
    onRetry,
}: {
    children: ReactNode;
    onRetry: () => void;
}) {
    return (
        <div className="empty-state">
            <div>{children}</div>
            <button type="button" onClick={onRetry} style={{ marginTop: 8 }}>
                重新讀取
            </button>
        </div>
    );
}

/** Global data-completeness panel for the local price archive report. */
export function DataQuality({ state, onRetry }: DataQualityProps) {
    if (state.status === "loading")
        return (
            <section className="panel">
                <h3 className="panel-title">資料品質</h3>
                <ReadStatus onRetry={onRetry}>正在讀取資料品質報告…</ReadStatus>
            </section>
        );
    if (state.status === "failure")
        return (
            <section className="panel">
                <h3 className="panel-title">資料品質讀取失敗</h3>
                <ReadStatus onRetry={onRetry}>
                    讀取資料品質報告失敗：{state.message}
                </ReadStatus>
            </section>
        );
    if (state.status === "missing")
        return (
            <section className="panel">
                <h3 className="panel-title">資料品質</h3>
                <ReadStatus onRetry={onRetry}>
                    目前沒有可用的資料品質報告。
                </ReadStatus>
            </section>
        );

    const data: DataQualityResponse = state.data;
    const report = data.report;
    if (!report) return null;
    const coverage = report.coverage ?? {};
    const checks = report.checks ?? {};
    const flaggedCount = report.symbols
        ? Object.keys(report.symbols).length
        : null;
    const warnings: string[] = [];
    for (const [name, label] of Object.entries(CHECK_LABELS) as [
        DataQualityCheckName,
        string,
    ][]) {
        const check = checks[name];
        if (check && check.symbol_count > 0)
            warnings.push(
                `${label}：${check.symbol_count} 個代號 / ${check.finding_count} 項`,
            );
    }
    const officialShare = coverage.latest_day_official_share;
    if (
        officialShare !== null &&
        officialShare !== undefined &&
        officialShare < 1
    )
        warnings.push(
            `最新交易日 ${coverage.last_date ?? "未知"} 有 ${formatShare(officialShare)} 來自官方來源，其餘資料暫為備援，待回補更新`,
        );

    return (
        <section className="panel">
            <h3 className="panel-title">
                資料品質 · {report.subject ?? "price_daily.parquet"} ·
                報告產生於 {report.generated_at}
                {state.status === "stale" &&
                    ` · 舊報告（約 ${state.ageHours} 小時）`}
            </h3>
            {state.status === "stale" && (
                <div className="empty-state">
                    此報告超過 72 小時，僅供參考；可以重新讀取最新報告。
                </div>
            )}
            <div className="health-grid">
                <div className="health-cell">
                    <div className="label">掃描代號</div>
                    <div className="value num">
                        {coverage.symbol_count ?? "未知"}
                    </div>
                </div>
                <div className="health-cell">
                    <div className="label">交易日</div>
                    <div className="value num">
                        {coverage.trading_day_count ?? "未知"}
                    </div>
                </div>
                <div className="health-cell">
                    <div className="label">有標記代號</div>
                    <div className="value num">{flaggedCount ?? "未知"}</div>
                </div>
                <div className="health-cell">
                    <div className="label">官方來源列占比</div>
                    <div className="value num">
                        {coverage.row_count &&
                        coverage.rows_by_source?.official !== undefined
                            ? formatShare(
                                  coverage.rows_by_source.official /
                                      coverage.row_count,
                              )
                            : "未知"}
                    </div>
                </div>
            </div>
            {coverage.first_date && coverage.last_date && (
                <div className="empty-state" style={{ marginTop: 8 }}>
                    報告涵蓋 {coverage.first_date} 至 {coverage.last_date} ·{" "}
                    {coverage.row_count?.toLocaleString() ?? "未知"} 列
                </div>
            )}
            {warnings.length > 0 && (
                <div className="error-banner" style={{ marginTop: 12 }}>
                    {warnings.map((warning) => (
                        <div key={warning}>{warning}</div>
                    ))}
                </div>
            )}
            <button type="button" onClick={onRetry} style={{ marginTop: 8 }}>
                重新讀取報告
            </button>
        </section>
    );
}
