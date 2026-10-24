export type CoverageMark =
    "present" | "partial" | "missing" | "not_applicable" | "unknown";
export interface CoverageCell {
    dataset: string;
    mark: CoverageMark;
    existence: string;
    completeness: string;
    read_status: string;
    freshness: string;
    rows: number | null;
    period: { from: string | null; to: string | null };
    checked_at: string | null;
    reasons: string[];
}
export interface CoveredSecurity {
    key: string;
    market: string;
    code: string;
    name: string | null;
    kind: string;
    identity_status: string;
    listing_status: string;
    activity: string;
    listed_date: string | null;
    observed_at: string | null;
    segment: { from: string | null; to: string | null };
    period: { from: string | null; to: string | null };
    reasons: string[];
    can_view_prices: boolean;
    coverage: CoverageCell[];
}
export interface CoverageList {
    schema: "security-coverage.v1";
    status: "ok" | "partial" | "unavailable";
    synthetic?: boolean;
    generation: string | null;
    built_at: string | null;
    datasets: { id: string; name: string; frequency: string }[];
    rows: CoveredSecurity[];
    total: number;
    page: number;
    size: number;
    unknown: number;
    confirmed_missing: number;
    hidden: { delisted: number; unresolved: number; listing_unknown: number };
}
export const MARKS: Record<CoverageMark, { icon: string; label: string }> = {
    present: { icon: "●", label: "有資料" },
    partial: { icon: "◐", label: "部分或已知缺口" },
    missing: { icon: "○", label: "應有但缺" },
    not_applicable: { icon: "－", label: "不適用" },
    unknown: { icon: "？", label: "未確認" },
};
const REASONS: Record<string, string> = {
    historical_completeness_unverified: "有紀錄，歷史完整性尚未確認。",
    stored_history_before_2019_missing:
        "這個市場的已存法人歷史缺少 2019 年前資料。",
    listing_period_unverified: "上市有效期間尚未確認。",
    no_observations: "成功檢查後沒有發現紀錄，是否應有資料仍待確認。",
    source_unavailable: "來源暫時無法讀取或摘要尚未建立。",
    event_absence_does_not_prove_missing: "沒有事件紀錄不等於漏下載。",
    current_revision_not_point_in_time:
        "目前修訂值，不能作為當時已知資料的證明。",
    price_basis_and_warmup_apply: "價格基礎與指標暖身規則仍適用。",
    identity_unresolved: "歷史證券身分待確認，不能直接串接。",
    identity_segment_summary_required:
        "需要確認這段歷史的身分與涵蓋，暫不套用其他時段紀錄。",
    bounded_identity_segment: "這個身分只適用於所標示的時段。",
};
export function reasonText(code: string): string {
    return REASONS[code] ?? "需要進一步確認資料限制。";
}
export function stockHref(
    key: string,
    dataset = "",
    back = "#overview/stocks",
): string {
    const query = new URLSearchParams({ back });
    if (dataset) query.set("dataset", dataset);
    return `#stock/${encodeURIComponent(key)}?${query}`;
}
export function safeBack(value: string | null): string {
    return value && /^#overview\/stocks(?:\?|$)/.test(value)
        ? value
        : "#overview/stocks";
}
export function legacyTarget(
    status: string,
    candidates: CoveredSecurity[],
): string | null {
    return status !== "unavailable" && candidates.length === 1
        ? candidates[0].key
        : null;
}
export function legacyHasNoMatch(
    status: string,
    candidates: CoveredSecurity[],
): boolean {
    return status !== "unavailable" && candidates.length === 0;
}
export function canUseCodeSeries(identityStatus: string): boolean {
    return identityStatus !== "unresolved";
}
export function listQuery(raw: string): URLSearchParams {
    const query = new URLSearchParams(raw);
    if (!query.has("kind")) query.set("kind", "stock");
    if (!query.has("status")) query.set("status", "recent");
    query.set("size", "50");
    return query;
}
