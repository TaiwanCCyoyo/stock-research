import type { DataQualityCheckName, DataQualityResponse } from "../api/types";

interface DataQualityProps {
    data: DataQualityResponse | null;
}

const CHECK_LABELS: Record<DataQualityCheckName, string> = {
    price_gap_without_ca_event: "漲跌幅無法解釋的價格跳空",
    ca_event_without_price_gap: "公司行為未反映在價格",
    unexplained_fallback: "官方涵蓋範圍內卻由備援填補",
};

function formatShare(share: number | null | undefined): string {
    if (share === null || share === undefined) return "—";
    return `${Math.round(share * 100)}%`;
}

/** Global data-completeness panel fed by stock-data-downloader's health-check report.
 * Unlike StrategyHealth, this renders a neutral empty state rather than hiding —
 * "not yet checked" is itself useful signal, not a state to suppress. */
export function DataQuality({ data }: DataQualityProps) {
    if (!data || !data.available || !data.report) {
        return (
            <section className="panel">
                <h3 className="panel-title">資料完整性</h3>
                <div className="empty-state">
                    尚未檢查（於 stock-data-downloader 執行 run_daily.py
                    後即可產生報告）
                </div>
            </section>
        );
    }

    const { report } = data;
    const coverage = report.coverage ?? {};
    const checks = report.checks ?? {};
    // v3 lists only symbols with a finding, so the scanned total comes from
    // coverage rather than the size of the symbols map.
    const flaggedCount = Object.keys(report.symbols ?? {}).length;
    const scanned = coverage.symbol_count ?? 0;

    const warnings: string[] = [];
    for (const [name, label] of Object.entries(CHECK_LABELS) as [
        DataQualityCheckName,
        string,
    ][]) {
        const check = checks[name];
        if (check && check.symbol_count > 0) {
            warnings.push(
                `${label}：${check.symbol_count} 檔 / ${check.finding_count} 筆`,
            );
        }
    }
    // The newest bar is provisional while the official feed lags a trading day.
    const officialShare = coverage.latest_day_official_share;
    if (
        officialShare !== null &&
        officialShare !== undefined &&
        officialShare < 1
    ) {
        warnings.push(
            `最新一日 ${coverage.last_date ?? ""} 僅 ${formatShare(officialShare)} 來自官方，其餘為備援值，待回補後改寫`,
        );
    }

    return (
        <section className="panel">
            <h3 className="panel-title">
                資料完整性 · {report.subject ?? "price_daily.parquet"} · 產出於{" "}
                {report.generated_at}
            </h3>
            <div className="health-grid">
                <div className="health-cell">
                    <div className="label">涵蓋股票數</div>
                    <div className="value num">{scanned}</div>
                </div>
                <div className="health-cell">
                    <div className="label">交易日數</div>
                    <div className="value num">
                        {coverage.trading_day_count ?? 0}
                    </div>
                </div>
                <div className="health-cell">
                    <div className="label">被標記股票</div>
                    <div className="value num">{flaggedCount}</div>
                </div>
                <div className="health-cell">
                    <div className="label">官方來源占比</div>
                    <div className="value num">
                        {coverage.row_count
                            ? `${Math.round(((coverage.rows_by_source?.official ?? 0) / coverage.row_count) * 100)}%`
                            : "—"}
                    </div>
                </div>
            </div>
            {coverage.first_date && coverage.last_date && (
                <div className="empty-state" style={{ marginTop: 8 }}>
                    {coverage.first_date} ～ {coverage.last_date} ·{" "}
                    {coverage.row_count?.toLocaleString() ?? 0} 筆
                </div>
            )}
            {warnings.length > 0 && (
                <div className="error-banner" style={{ marginTop: 12 }}>
                    {warnings.map((warning) => (
                        <div key={warning}>{warning}</div>
                    ))}
                </div>
            )}
        </section>
    );
}
