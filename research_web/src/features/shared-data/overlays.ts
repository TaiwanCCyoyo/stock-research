import { apiUrl } from "../../api/base.ts";

/** GET /data-series/v1/{dataset}/{code} (research-data-series.v1). Stored rows
 *  only: shares stay shares, revenue stays thousands of TWD, nulls stay unknown. */
export interface SeriesResponse<Row> {
    schema: "research-data-series.v1";
    dataset: "institutional" | "monthly-revenue";
    code: string;
    status: "ok" | "missing" | "updating";
    rows: Row[];
    warnings: string[];
    synthetic?: boolean;
}

export interface InstitutionalRow {
    date: string;
    foreign_total_net: number | null;
    trust_net: number | null;
    dealer_total_net: number | null;
    three_institutions_net: number | null;
}

export interface RevenueRow {
    revenue_month: string;
    current_revenue_k_twd: number | null;
    yoy_pct: number | null;
    mom_pct: number | null;
}

export type InstitutionalField =
    | "three_institutions_net"
    | "foreign_total_net"
    | "trust_net"
    | "dealer_total_net";

export const INSTITUTIONAL_FIELDS: { id: InstitutionalField; label: string }[] =
    [
        { id: "three_institutions_net", label: "三大法人" },
        { id: "foreign_total_net", label: "外資" },
        { id: "trust_net", label: "投信" },
        { id: "dealer_total_net", label: "自營商" },
    ];

export async function readSeries<Row>(
    dataset: SeriesResponse<Row>["dataset"],
    code: string,
    from: string | null,
    signal: AbortSignal,
    fetcher: typeof fetch = fetch,
): Promise<SeriesResponse<Row>> {
    const query = from ? `?from=${encodeURIComponent(from)}` : "";
    const response = await fetcher(
        apiUrl(
            `/data-series/v1/${dataset}/${encodeURIComponent(code)}${query}`,
        ),
        { signal },
    );
    if (!response.ok)
        throw new Error(`資料暫時讀不到（HTTP ${response.status}）。`);
    const value = (await response.json()) as SeriesResponse<Row>;
    if (
        value?.schema !== "research-data-series.v1" ||
        !Array.isArray(value.rows)
    )
        throw new Error("資料格式不符，無法讀取。");
    return value;
}

/** Daily net shares aligned to the chart's own dates; other dates are dropped
 *  and a null stays a gap rather than becoming zero. */
export function institutionalPoints(
    rows: readonly InstitutionalRow[],
    field: InstitutionalField,
    dates: ReadonlySet<string>,
): { date: string; value: number | null }[] {
    return rows
        .filter((row) => dates.has(row.date))
        .map((row) => ({ date: row.date, value: row[field] ?? null }));
}

/** Monthly bars in month order; a month with no stored revenue is left out. */
export function revenueBars(rows: readonly RevenueRow[]) {
    return [...rows]
        .filter((row) => row.current_revenue_k_twd !== null)
        .sort((a, b) => a.revenue_month.localeCompare(b.revenue_month))
        .map((row) => ({
            month: row.revenue_month,
            revenueK: row.current_revenue_k_twd!,
            yoy: row.yoy_pct,
        }));
}

/** Share counts for people: 1.2 萬股, 3.4 億股. */
export function sharesLabel(value: number | null): string {
    if (value === null || !Number.isFinite(value)) return "未知";
    const sign = value < 0 ? "−" : value > 0 ? "+" : "";
    const abs = Math.abs(value);
    if (abs >= 100_000_000)
        return `${sign}${(abs / 100_000_000).toFixed(2)} 億股`;
    if (abs >= 10_000) return `${sign}${(abs / 10_000).toFixed(1)} 萬股`;
    return `${sign}${abs.toLocaleString("zh-TW")} 股`;
}

/** Revenue stored in thousands of TWD, shown as 億元 or 萬元. */
export function revenueLabel(thousands: number | null): string {
    if (thousands === null || !Number.isFinite(thousands)) return "未知";
    const twd = thousands * 1000;
    if (Math.abs(twd) >= 100_000_000)
        return `${(twd / 100_000_000).toFixed(2)} 億元`;
    return `${Math.round(twd / 10_000).toLocaleString("zh-TW")} 萬元`;
}

export function percentLabel(points: number | null): string {
    if (points === null || !Number.isFinite(points)) return "未知";
    return `${points > 0 ? "+" : ""}${points.toFixed(1)}%`;
}
