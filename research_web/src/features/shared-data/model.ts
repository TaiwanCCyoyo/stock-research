export type Basis = "reference_factor_adjusted" | "raw" | "permanent_adjusted";
export const BASIS_LABELS: Record<Basis, string> = {
    reference_factor_adjusted: "參考因子還原",
    raw: "原始價格",
    permanent_adjusted: "永久還原",
};
export const BASIS_EXPLANATIONS: Record<Basis, string> = {
    reference_factor_adjusted:
        "依公司事件參考因子還原，包含現金股息；用於本頁技術指標比較，不代表股息再投入或帳戶含息報酬。",
    raw: "保留來源報價、不做還原；用來查看當時報價，公司事件可能造成價格不連續。",
    permanent_adjusted:
        "依分割、除權、減資等永久事件參考因子還原，不還原現金股息；用來比較排除這些事件影響後的價格。",
};
const QUALITY_LABELS: Record<string, string> = {
    missing_official_quote: "缺少官方報價",
    invalid_ohlc: "開高低收價格不合理或缺漏",
    duplicate_date: "同一日期有重複紀錄",
    unsupported_action: "公司事件類型尚未支援",
    ambiguous_same_day_actions: "同日公司事件的組合尚未釐清",
    ambiguous_or_missing_action_factor: "公司事件還原因子缺漏或不一致",
    invalid_adjusted_ohlc: "還原後價格無效",
    unexplained_raw_jump: "原始價格有無法解釋的大幅跳動",
    unexplained_adjusted_jump: "還原價格有無法解釋的大幅跳動",
};
export function qualityReasonLabel(reason: string | null | undefined): string {
    if (!reason || reason === "缺少有效 OHLC") return "缺少有效開高低收價格";
    return [
        ...new Set(
            reason
                .split("|")
                .map(
                    (code) =>
                        QUALITY_LABELS[code] ?? "其他資料品質問題（詳見來源）",
                ),
        ),
    ].join("；");
}
/** Shorten hash tokens only; the original identity remains the lookup value. */
export function compactVersionLabel(version: string): string {
    return version.replace(
        /(^|[^a-zA-Z0-9])([a-fA-F0-9]{32,})(?=$|[^a-zA-Z0-9])/g,
        (_match, separator: string, hash: string) =>
            `${separator}${hash.slice(0, 12)}…`,
    );
}

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
export interface SymbolsResponse {
    generation: string;
    status_sha256: string;
    namesAvailable: boolean;
    symbols: SharedSymbol[];
}
export function resolveSymbolInput(
    input: string,
    symbols: SharedSymbol[],
): string | null {
    const query = input.trim();
    const found = symbols.find(
        (item) => item.code === query.split(/\s+/)[0] || item.name === query,
    );
    const code = found?.code || query;
    return /^[A-Za-z0-9._-]+$/.test(code) ? code : null;
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
