export type Basis = "reference_factor_adjusted" | "raw" | "permanent_adjusted";
export interface SharedSeries {
    code: string;
    basis: Basis;
    generation: string;
    status_sha256: string;
    asof: string;
    dates: string[];
    open: (number | null)[];
    high: (number | null)[];
    low: (number | null)[];
    close: (number | null)[];
    volume: (number | null)[];
    quality: boolean[];
    quality_reason: string[];
    tech: Record<string, (number | boolean | null)[]>;
    pivots: {
        k: number;
        kind: "high" | "low";
        extreme_date: string;
        confirmed_at: string;
        price: number;
    }[];
}
export interface SharedSymbol {
    code: string;
    name: string;
    market: string;
    first: string;
    last: string;
}
export interface Family {
    display_title?: string | null;
    purpose?: string | null;
    family: string;
    generation: string;
    asof: string;
    status_sha256: string;
    codes: number;
    calendar: { first: string; last: string; sessions: number };
    definition: unknown;
    bases: unknown;
    technical: unknown;
}
export interface CatalogEntry {
    display_title?: string | null;
    purpose?: string | null;
    data_id: string;
    version_id: string;
    kind: string;
    status: string;
    definition_version?: string;
    coverage?: {
        scope?: string;
        raw_input_period?: { start?: string; end?: string; reason?: string };
    };
    limitations?: unknown;
    manifest?: { scope: string; path: string; sha256: string };
    recommended?: boolean;
    superseded_by?: string;
    viewer_metadata?: {
        schema: string | null;
        columns: string[] | null;
        security_count: number | null;
        analyzed_security_count: number | null;
        manifest_member_count: number | null;
    };
    metadata_error?: string | null;
}
export interface Families {
    families: Family[];
    catalog: {
        version_id: string;
        entries: CatalogEntry[];
        retired: unknown[];
    } | null;
    catalogError: string | null;
}
export const MA_PERIODS = [5, 10, 20, 60, 120, 240];
export const numeric = (v: unknown): v is number =>
    typeof v === "number" && Number.isFinite(v);
export function validPrice(s: SharedSeries, i: number) {
    return (
        s.quality[i] === true &&
        [s.open[i], s.high[i], s.low[i], s.close[i]].every(numeric)
    );
}
/** Preserve invalid sessions as whitespace; never interpolate or calculate features. */
export function candleRows(s: SharedSeries) {
    return s.dates.map((time, i) =>
        validPrice(s, i)
            ? {
                  time,
                  open: s.open[i]!,
                  high: s.high[i]!,
                  low: s.low[i]!,
                  close: s.close[i]!,
              }
            : { time },
    );
}
export function featureRows(s: SharedSeries, key: string) {
    return s.dates.map((time, i) => {
        const value = s.tech[key]?.[i];
        return s.quality[i] === true && numeric(value)
            ? { time, value }
            : { time };
    });
}
export function qualityCounts(s: SharedSeries) {
    const reasons = new Map<string, number>();
    s.dates.forEach((_, i) => {
        if (!validPrice(s, i)) {
            const reason = s.quality_reason[i] || "缺少有效 OHLC";
            reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
        }
    });
    return [...reasons.entries()];
}
export function versionLabel(entry: CatalogEntry) {
    if (entry.superseded_by) return `後續版本：${entry.superseded_by}`;
    return entry.recommended === true ? "目錄推薦版本" : "未標示現行版";
}
export function metadataText(value: unknown): string {
    return value == null
        ? "未提供"
        : typeof value === "string"
          ? value
          : JSON.stringify(value);
}

export function groupCatalog(entries: CatalogEntry[]) {
    const groups = new Map<string, CatalogEntry[]>();
    entries.forEach((entry) => {
        const versions = groups.get(entry.data_id) ?? [];
        versions.push(entry);
        groups.set(entry.data_id, versions);
    });
    return [...groups.entries()];
}
export function selectedCatalogVersion(
    entries: CatalogEntry[],
    version?: string,
) {
    return (
        entries.find((entry) => entry.version_id === version) ??
        entries.find((entry) => entry.recommended === true) ??
        entries[0]
    );
}
export const featureLabels: Record<string, string> = {
    BB20_Upper: "布林上軌",
    BB20_Middle: "布林中軌",
    BB20_Lower: "布林下軌",
    RSI14: "相對強弱 RSI14",
    MACDHist: "MACD 柱狀值",
    ADX14: "趨勢強度 ADX14",
    atr14_pct: "平均真實波幅 ATR14",
    none: "隱藏",
};
export function formatNumber(value: unknown, digits = 2): string {
    if (!numeric(value)) return "—";
    const rounded = Number(value.toFixed(digits));
    return (Object.is(rounded, -0) ? 0 : rounded).toLocaleString("zh-TW", {
        maximumFractionDigits: digits,
    });
}
export function formatFeature(key: string, value: unknown): string {
    return key === "atr14_pct"
        ? numeric(value)
            ? `${formatNumber(value * 100)}%`
            : "—"
        : formatNumber(value);
}
export function priceChange(series: SharedSeries, day: number) {
    if (day < 0 || !validPrice(series, day))
        return { amount: null, percent: null, direction: "flat" };
    for (let i = day - 1; i >= 0; i--) {
        if (!validPrice(series, i)) continue;
        const previous = series.close[i]!;
        const amount = series.close[day]! - previous;
        // Non-positive denominators cannot express a meaningful stock return.
        return {
            amount,
            percent: previous > 0 ? (amount / previous) * 100 : null,
            direction: amount > 0 ? "gain" : amount < 0 ? "loss" : "flat",
        };
    }
    return { amount: null, percent: null, direction: "flat" };
}
export function formatSigned(value: number | null): string {
    return value === null
        ? "—"
        : `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}
