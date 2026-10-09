export interface AtlasStock {
    code: string;
    name: string;
    groupIds: string[];
    quality: string[];
    qualityFindings?: { date: string; kind: string }[];
    raw: (number | null)[];
    adjusted: (number | null)[];
    marketCap?: (number | null)[];
}
export interface AtlasData {
    schema: "market-atlas.v1";
    catalogHash: string;
    classificationAsOf: string;
    dates: string[];
    groups: { id: string; label: string }[];
    stocks: AtlasStock[];
    provenance: Record<string, unknown>;
    limitations: string[];
}
export type Encoding = "return" | "weighted";
export type Measure = "endpoint" | "peak";
export interface Observation {
    stock: AtlasStock;
    gain: number | null;
    weight: number;
    reason: string | null;
    cap: number | null;
    observedEnd: number | null;
}
export const CAP_EXPONENT = Math.log(1.25) / Math.log(100);
export function observationBounds(
    dateCount: number,
    windowSize: number,
    customStart: number,
): { min: number; max: number; available: boolean } {
    const max = Math.max(0, dateCount - 1);
    const required = windowSize > 0 ? windowSize : Math.max(0, customStart) + 1;
    return {
        min: Math.min(required, max),
        max,
        available: dateCount > 0 && required <= max,
    };
}
export function areaWeight(
    gain: number,
    cap: number | null,
    encoding: Encoding,
): number {
    if (!Number.isFinite(gain) || gain <= 0) return 0;
    if (
        encoding === "weighted" &&
        (cap === null || !Number.isFinite(cap) || cap <= 0)
    )
        return 0;
    return (
        (gain / 50) ** 2 *
        (encoding === "weighted" ? (cap! / 50) ** CAP_EXPONENT : 1)
    );
}
export function observe(
    data: AtlasData,
    start: number,
    end: number,
    encoding: Encoding,
    measure: Measure = "endpoint",
): Observation[] {
    return data.stocks.map((stock) => {
        let candidateEnd = end;
        let incompletePeak = false;
        if (measure === "peak" && start >= 0) {
            candidateEnd = start;
            for (let i = start; i <= end; i++) {
                if (stock.adjusted[i] == null) incompletePeak = true;
                if (
                    stock.adjusted[i] !== null &&
                    (stock.adjusted[i] ?? 0) >
                        (stock.adjusted[candidateEnd] ?? 0)
                )
                    candidateEnd = i;
            }
        }
        const from = stock.adjusted[start],
            to = stock.adjusted[candidateEnd];
        const datedFinding = stock.qualityFindings?.some(
            (f) => f.date >= data.dates[start] && f.date <= data.dates[end],
        );
        const reason =
            start < 0
                ? "共同起點超出資料範圍"
                : stock.quality.length || datedFinding
                  ? "區間來源品質待核對"
                  : incompletePeak
                    ? "區間缺報價，期間最高未知"
                    : from == null || to == null
                      ? "起點或觀察日缺報價"
                      : from <= 0 || to <= 0
                        ? "價格無效"
                        : null;
        const gain = reason ? null : (to! / from! - 1) * 100;
        const observedEnd =
            measure === "peak" && reason !== null ? null : candidateEnd;
        const cap =
            observedEnd === null
                ? null
                : (stock.marketCap?.[observedEnd] ?? null);
        return {
            stock,
            gain,
            cap,
            observedEnd,
            reason:
                reason ??
                (encoding === "weighted" && cap === null ? "缺歷史市值" : null),
            weight: gain === null ? 0 : areaWeight(gain, cap, encoding),
        };
    });
}
export function exportObservation(data: AtlasData, observation: Observation) {
    return {
        code: observation.stock.code,
        name: observation.stock.name,
        groupIds: observation.stock.groupIds,
        gainPercent: observation.gain,
        gainObservedAt:
            observation.observedEnd === null
                ? null
                : data.dates[observation.observedEnd],
        marketCapYi: observation.cap,
        areaWeight: observation.weight,
        missingReason: observation.reason,
    };
}
export function nearestDate(dates: string[], value: string): number {
    let lo = 0,
        hi = dates.length - 1;
    while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        if (dates[mid] <= value) lo = mid;
        else hi = mid - 1;
    }
    return lo;
}
export const percent = (value: number | null) =>
    value === null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
function isNonemptyString(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0;
}
function isCalendarDate(value: unknown): value is string {
    return (
        typeof value === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(value) &&
        Number.isFinite(Date.parse(`${value}T00:00:00Z`)) &&
        new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
    );
}
function isStringArray(value: unknown): value is string[] {
    return (
        Array.isArray(value) &&
        Array.from(value).every((entry) => typeof entry === "string")
    );
}
function isQualityFinding(value: unknown): boolean {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return false;
    const finding = value as { date?: unknown; kind?: unknown };
    return isCalendarDate(finding.date) && isNonemptyString(finding.kind);
}
function isPriceSeries(value: unknown, dateCount: number): boolean {
    if (!Array.isArray(value) || value.length !== dateCount) return false;
    for (const entry of value)
        if (
            entry !== null &&
            (typeof entry !== "number" || !Number.isFinite(entry) || entry <= 0)
        )
            return false;
    return true;
}
export function isAtlasData(value: unknown): value is AtlasData {
    if (!value || typeof value !== "object" || Array.isArray(value))
        return false;
    const d = value as AtlasData;
    return (
        d.schema === "market-atlas.v1" &&
        isNonemptyString(d.catalogHash) &&
        isCalendarDate(d.classificationAsOf) &&
        d.provenance !== null &&
        typeof d.provenance === "object" &&
        !Array.isArray(d.provenance) &&
        isStringArray(d.limitations) &&
        Array.isArray(d.dates) &&
        d.dates.length > 0 &&
        Array.from(d.dates).every(
            (date, index) =>
                isCalendarDate(date) &&
                (index === 0 || date > d.dates[index - 1]),
        ) &&
        Array.isArray(d.groups) &&
        Array.from(d.groups).every(
            (group) =>
                group !== null &&
                typeof group === "object" &&
                !Array.isArray(group) &&
                isNonemptyString(group.id) &&
                isNonemptyString(group.label),
        ) &&
        new Set(d.groups.map((group) => group.id)).size === d.groups.length &&
        Array.isArray(d.stocks) &&
        Array.from(d.stocks).every(
            (s) =>
                s !== null &&
                typeof s === "object" &&
                !Array.isArray(s) &&
                isNonemptyString(s.code) &&
                isNonemptyString(s.name) &&
                isPriceSeries(s.adjusted, d.dates.length) &&
                isPriceSeries(s.raw, d.dates.length) &&
                (s.marketCap === undefined ||
                    isPriceSeries(s.marketCap, d.dates.length)) &&
                isStringArray(s.groupIds) &&
                isStringArray(s.quality) &&
                (s.qualityFindings === undefined ||
                    (Array.isArray(s.qualityFindings) &&
                        Array.from(s.qualityFindings).every(isQualityFinding))),
        ) &&
        new Set(d.stocks.map((stock) => stock.code)).size === d.stocks.length
    );
}
