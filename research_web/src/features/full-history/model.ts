import type {
    MapRow,
    MapView,
} from "../../visualizations/opportunity/mapTypes.ts";
import {
    HISTORY_SCHEMA,
    type HistoryFrame,
    type HistoryRow,
    type HistoryPhase,
    type HistoryDirectoryRow,
    type GrowthMetric,
} from "./types.ts";

export const phaseLabel = (phase: HistoryPhase | null) =>
    phase === null
        ? "階段待辨識"
        : {
              slow: "慢慢上漲",
              rising: "大漲中",
              resting: "漲多休息",
              retreat: "從高點拉回",
          }[phase];
export const percent = (value: number | null) =>
    value === null ? "未知" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
export type HistoryDisplayMode = "launched" | "catalog";
const GROWTH_THRESHOLD_TOLERANCE_PCT = 1e-9;

function eligibleGrowth(
    growth: GrowthMetric | null | undefined,
    thresholdPct: number,
): boolean {
    const value = growth?.sizingGainPct;
    return (
        (growth?.basis === "actual" || growth?.basis === "annualized") &&
        typeof value === "number" &&
        Number.isFinite(value) &&
        Number.isFinite(thresholdPct) &&
        value >= thresholdPct - GROWTH_THRESHOLD_TOLERANCE_PCT
    );
}

export function appears(
    row: HistoryRow,
    date: string,
    mode: HistoryDisplayMode,
    thresholdPct = 100,
): boolean {
    if (row.endConfirmedAt !== null && date >= row.endConfirmedAt) return false;
    if (!eligibleGrowth(row.growth, thresholdPct)) return false;
    return (
        mode === "catalog" ||
        (!!row.launchCandidate && row.launchCandidate.date <= date)
    );
}

/** Clamp calendar input, then snap to the preceding observed trading session. */
export function dateIndex(dates: readonly string[], requested: string): number {
    if (!dates.length) return -1;
    let low = 0,
        high = dates.length;
    while (low < high) {
        const mid = Math.floor((low + high) / 2);
        if (dates[mid] <= requested) low = mid + 1;
        else high = mid;
    }
    return Math.max(0, low - 1);
}

/** An explicit date keeps normal URL snapping; saved visits must match this catalog exactly. */
export function initialHistoryIndex(
    dates: readonly string[],
    catalogId: string,
    readSavedDate: (key: string) => string | null,
    requestedDate: string | null = null,
): number {
    if (!dates.length) return -1;
    if (requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate))
        return dateIndex(dates, requestedDate);
    try {
        const savedDate = readSavedDate(`history.date.${catalogId}`);
        const savedIndex = savedDate === null ? -1 : dates.indexOf(savedDate);
        if (savedIndex >= 0) return savedIndex;
    } catch {
        /* Storage getters and reads may both be blocked in private browsing. */
    }
    return dates.length - 1;
}

/** Position of a date boundary on equal-width observed trading-session slots. */
export function timelineDateBoundary(
    dates: readonly string[],
    requested: string,
): number {
    if (!dates.length) return 0;
    let low = 0;
    let high = dates.length;
    while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (dates[middle] < requested) low = middle + 1;
        else high = middle;
    }
    return (low / dates.length) * 100;
}

/** The end of an inclusive interval is the next observed session boundary. */
export function timelineInclusiveEndBoundary(
    dates: readonly string[],
    inclusiveEnd: string,
): number {
    if (!dates.length) return 0;
    let low = 0;
    let high = dates.length;
    while (low < high) {
        const middle = Math.floor((low + high) / 2);
        if (dates[middle] <= inclusiveEnd) low = middle + 1;
        else high = middle;
    }
    return (low / dates.length) * 100;
}

/** Map a closed trading-date interval onto session slots without dropping either end. */
export function timelineInclusiveRange(
    dates: readonly string[],
    from: string,
    until: string,
): { left: number; right: number } {
    return {
        left: timelineDateBoundary(dates, from),
        right: timelineInclusiveEndBoundary(dates, until),
    };
}

export interface RequestIdentity {
    epoch: number;
    catalogId: string;
    date: string;
}
/** Shared success/failure guard; neither obsolete failures nor responses may commit. */
export function isCurrentRequest(
    request: RequestIdentity,
    current: RequestIdentity,
    response?: { schema: string; catalogId: string; date: string },
): boolean {
    return (
        request.epoch === current.epoch &&
        request.catalogId === current.catalogId &&
        request.date === current.date &&
        (!response ||
            (response.schema === HISTORY_SCHEMA &&
                response.catalogId === request.catalogId &&
                response.date === request.date))
    );
}
export function toMapRow(row: HistoryRow): MapRow {
    const industry = {
        id: row.industry.id,
        label: row.industry.label,
        basis: row.industry.basis,
        from: "",
        untilExclusive: null,
        sourceId: "history-classification-snapshot",
    };
    const growthKnown =
        (row.growth?.basis === "actual" ||
            row.growth?.basis === "annualized") &&
        typeof row.growth.sizingGainPct === "number" &&
        Number.isFinite(row.growth.sizingGainPct);
    const displayMetric = growthKnown
        ? {
              gain: row.growth!.sizingGainPct,
              basis: row.growth!.basis,
          }
        : { gain: null, basis: "unknown" as const };
    return {
        security: {
            id: row.securityId,
            code: row.code,
            name: row.name,
            industry: [],
            classificationSnapshot:
                row.industry.basis === "current-snapshot"
                    ? {
                          label: row.industry.label,
                          observedAt: row.industry.snapshotAt,
                          sourceId: industry.sourceId,
                      }
                    : undefined,
        },
        wave: {
            id: row.waveId,
            start: row.start,
            launch: row.launchCandidate
                ? { date: row.launchCandidate.date }
                : null,
            endConfirmedAt: row.endConfirmedAt,
            observedThrough: row.observedThrough,
            rightCensored: row.rightCensored,
        },
        industry,
        gain: row.gain,
        displayMetric,
        peakGain: row.peakGain,
        phase: row.phase,
        weight:
            displayMetric.gain === null
                ? 0
                : Math.max(displayMetric.gain, 0) ** 2 / 10000,
    };
}

function updateIndustryMetric(
    group: MapView["industries"][number],
    row: MapRow,
): void {
    const metric = row.displayMetric;
    if (!metric) return;
    if (metric.basis === "unknown" || metric.gain === null) return;
    if (
        group.displayMetric === undefined ||
        group.displayMetric.gain === null ||
        metric.gain > group.displayMetric.gain
    )
        group.displayMetric = {
            ...metric,
            leaderName: row.security.name,
            leaderCode: row.security.code,
        };
}

export function toMapView(
    frame: HistoryFrame,
    mode: HistoryDisplayMode = "launched",
    ended: MapRow[] = [],
    thresholdPct = 100,
): MapView {
    const rows = frame.rows.map(toMapRow);
    // Membership is saved by the producer; the explicit preview display is after
    // its saved candidate date. It never changes the underlying catalog.
    const active = frame.rows
        .filter((row) => appears(row, frame.date, mode, thresholdPct))
        .map(toMapRow);
    const industries = new Map<string, MapView["industries"][number]>();
    for (const row of active) {
        const group = industries.get(row.industry.id);
        if (group) {
            group.rows.push(row);
            if (row.gain !== null)
                group.maxGain =
                    group.maxGain === null
                        ? row.gain
                        : Math.max(group.maxGain, row.gain);
            updateIndustryMetric(group, row);
        } else
            industries.set(row.industry.id, {
                id: row.industry.id,
                label: row.industry.label,
                maxGain: row.gain,
                displayMetric: {
                    gain: null,
                    basis: "unknown",
                    leaderName: null,
                    leaderCode: null,
                },
                rows: [row],
            });
        updateIndustryMetric(industries.get(row.industry.id)!, row);
    }
    return {
        catalogId: frame.catalogId,
        date: frame.date,
        rows,
        active,
        ended,
        industries: [...industries.values()],
    };
}

/** Stable wave identity prevents an ended smaller wave duplicating an active stock. */
export function recentEnded(
    directory: readonly HistoryDirectoryRow[],
    frame: HistoryFrame,
    thresholdPct = 100,
): MapRow[] {
    const activeIds = new Set(frame.rows.map((row) => row.securityId));
    const cutoff = new Date(`${frame.date}T00:00:00Z`);
    cutoff.setUTCDate(cutoff.getUTCDate() - 30);
    const from = cutoff.toISOString().slice(0, 10);
    const selected = new Map<string, HistoryDirectoryRow>();
    for (const row of directory) {
        if (
            !row.endConfirmedAt ||
            row.endConfirmedAt > frame.date ||
            row.endConfirmedAt < from ||
            activeIds.has(row.securityId) ||
            !row.launchCandidate ||
            !eligibleGrowth(row.growthAtEnd, thresholdPct)
        )
            continue;
        const previous = selected.get(row.securityId);
        if (!previous || previous.endConfirmedAt! < row.endConfirmedAt)
            selected.set(row.securityId, row);
    }
    return [...selected.values()].map((row) =>
        toMapRow({
            ...row,
            seriesId: "saved-directory",
            gain: row.gainAtEnd,
            growth: row.growthAtEnd,
            raw: null,
            adjusted: null,
            reason: null,
            earliestCandidateId: null,
            phase: "retreat",
        }),
    );
}

/** Rank once per stock, then retain inactive history for the searchable time bands. */
export function timelineRows(
    directory: readonly HistoryDirectoryRow[],
    frame: HistoryFrame | null,
    query: string,
    thresholdPct = 100,
): HistoryDirectoryRow[] {
    const byStock = new Map<string, HistoryDirectoryRow>();
    const current = new Map(
        frame?.rows.map((row) => [row.securityId, row.waveId]) ?? [],
    );
    for (const row of directory) {
        if (
            !`${row.code} ${row.name} ${row.industry.label}`.includes(
                query.trim(),
            )
        )
            continue;
        const previous = byStock.get(row.securityId);
        const relevant = current.get(row.securityId) === row.waveId;
        const oldRelevant =
            previous && current.get(row.securityId) === previous.waveId;
        if (
            !previous ||
            relevant ||
            (!oldRelevant &&
                row.start <= (frame?.date ?? "9999") &&
                row.start > previous.start)
        )
            byStock.set(row.securityId, row);
    }
    const metricByWave = new Map<string, number>();
    const sums = new Map<string, number>();
    for (const row of frame?.rows ?? []) {
        if (!appears(row, frame!.date, "launched", thresholdPct)) continue;
        const metric = row.growth?.sizingGainPct;
        if (typeof metric !== "number" || !Number.isFinite(metric)) continue;
        metricByWave.set(`${row.securityId}\u0000${row.waveId}`, metric);
        sums.set(row.industry.id, (sums.get(row.industry.id) ?? 0) + metric);
    }
    const rankedMetric = (row: HistoryDirectoryRow): number => {
        const currentMetric = metricByWave.get(
            `${row.securityId}\u0000${row.waveId}`,
        );
        if (currentMetric !== undefined) return currentMetric;
        if (
            !frame ||
            !row.endConfirmedAt ||
            row.endConfirmedAt > frame.date ||
            !eligibleGrowth(row.growthAtEnd, thresholdPct)
        )
            return -Infinity;
        return row.growthAtEnd!.sizingGainPct!;
    };
    return [...byStock.values()].sort(
        (a, b) =>
            (sums.get(b.industry.id) ?? -Infinity) -
                (sums.get(a.industry.id) ?? -Infinity) ||
            rankedMetric(b) - rankedMetric(a) ||
            b.start.localeCompare(a.start) ||
            a.code.localeCompare(b.code),
    );
}
