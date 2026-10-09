import type {
    OpportunityRow,
    OpportunitySecurity,
    OpportunityWave,
} from "../../domain/opportunities/types.ts";
import type { PackedNode, PreviousPackingPosition } from "./packing.ts";

export interface DisplayMetric {
    gain: number | null;
    basis: "actual" | "annualized" | "unknown";
}

export interface IndustryDisplayMetric extends DisplayMetric {
    leaderName: string | null;
    leaderCode: string | null;
}

export function metricLabel(metric: DisplayMetric): string {
    if (metric.basis === "unknown" || metric.gain === null) return "尺度未知";
    const basis = metric.basis === "annualized" ? "年化" : "實際";
    const value = `${metric.gain >= 0 ? "+" : ""}${metric.gain.toFixed(0)}%`;
    return `${basis} ${value}`;
}

/** Short label drawn on top of an industry's territory: name, size, best stock. */
export function territoryLabelText(
    industry: Pick<
        MapView["industries"][number],
        "label" | "maxGain" | "displayMetric"
    >,
    count: number,
): string {
    // Keep the leader's basis: one industry can mix actual and annualized values.
    const best =
        industry.displayMetric !== undefined
            ? metricLabel(industry.displayMetric)
            : industry.maxGain === null
              ? "不知道"
              : `${industry.maxGain >= 0 ? "+" : ""}${industry.maxGain.toFixed(0)}%`;
    return `${industry.label} ${count} 檔 · 最高 ${best}`;
}

/** Raw peak gain cannot define an equivalent radius for duration-normalized cells. */
export function showPeakAreaReference(
    row: Pick<MapRow, "displayMetric">,
): boolean {
    return row.displayMetric === undefined;
}

/** Zero-area nodes have no visible location to preserve in the next packing. */
export function visiblePackingPositions(
    nodes: readonly Pick<PackedNode, "id" | "x" | "y" | "r">[],
): PreviousPackingPosition[] {
    return nodes
        .filter((node) => node.r > 0)
        .map(({ id, x, y, r }) => ({ id, x, y, r }));
}

/** Display-only inputs: the map never needs price history or full wave phases. */
export type MapRow = Pick<
    OpportunityRow,
    "industry" | "gain" | "peakGain" | "phase" | "weight"
> & {
    /** Omitted only by legacy previews; unknown never falls back to raw gain. */
    displayMetric?: DisplayMetric;
    security: Pick<
        OpportunitySecurity,
        "id" | "code" | "name" | "industry" | "classificationSnapshot"
    >;
    wave: Pick<
        OpportunityWave,
        "id" | "start" | "endConfirmedAt" | "observedThrough" | "rightCensored"
    > & { launch: { date: string } | null };
};
export interface MapView {
    catalogId?: string;
    date: string;
    rows: MapRow[];
    active: MapRow[];
    ended: MapRow[];
    industries: {
        id: string;
        label: string;
        maxGain: number | null;
        displayMetric?: IndustryDisplayMetric;
        rows: MapRow[];
    }[];
}
export type GroupingMode = "historical" | "snapshot";
export type ColorBasis = "phase" | "gain";

/** Recorded gain controls display color only; it does not infer a wave phase. */
export function gainColorBand(
    gain: number | null,
): "strong" | "medium" | "light" | "unknown" {
    if (gain === null || !Number.isFinite(gain) || gain < 0) return "unknown";
    return gain >= 100 ? "strong" : gain >= 60 ? "medium" : "light";
}

/** API catalog identity survives new JSON objects; preview retains object identity. */
export function sameSource(a: MapView | undefined, b: MapView): boolean {
    if (!a) return false;
    if (a.catalogId !== undefined || b.catalogId !== undefined)
        return !!a.catalogId && a.catalogId === b.catalogId;
    if (a === b) return true;
    const other = new Map(b.rows.map((row) => [row.security.id, row.security]));
    const shared = a.rows.filter((row) => other.has(row.security.id));
    return (
        shared.length > 0 &&
        shared.every((row) => other.get(row.security.id) === row.security)
    );
}

export function hasMapIndustry(row: MapRow, mode: GroupingMode): boolean {
    return mode === "snapshot"
        ? row.industry.basis === "current-snapshot"
        : row.industry.basis === "historical" ||
              row.industry.basis === "document-period";
}

export function mapGroupId(
    row: MapRow,
    mode: GroupingMode,
    knownGroups: ReadonlySet<string>,
): string {
    if (hasMapIndustry(row, mode)) return row.industry.id;
    let id = JSON.stringify(["unclassified-stock", row.security.id]);
    while (knownGroups.has(id)) id = `_${id}`;
    return id;
}

export function mapIndustries(
    view: MapView,
    mode: GroupingMode,
): MapView["industries"] {
    if (mode === "historical") return view.industries;
    const groups = new Map<string, MapView["industries"][number]>();
    const updateDisplayMetric = (
        group: MapView["industries"][number],
        row: MapRow,
    ) => {
        if (row.displayMetric === undefined) return;
        if (group.displayMetric === undefined)
            group.displayMetric = {
                gain: null,
                basis: "unknown",
                leaderName: null,
                leaderCode: null,
            };
        const metric = row.displayMetric;
        if (
            metric.basis === "unknown" ||
            metric.gain === null ||
            !Number.isFinite(metric.gain)
        )
            return;
        if (
            group.displayMetric.gain === null ||
            metric.gain > group.displayMetric.gain
        )
            group.displayMetric = {
                ...metric,
                leaderName: row.security.name,
                leaderCode: row.security.code,
            };
    };
    for (const row of view.active) {
        if (!hasMapIndustry(row, mode)) continue;
        const group = groups.get(row.industry.id);
        if (group) {
            group.rows.push(row);
            if (row.gain !== null)
                group.maxGain =
                    group.maxGain === null
                        ? row.gain
                        : Math.max(group.maxGain, row.gain);
            updateDisplayMetric(group, row);
        } else
            groups.set(row.industry.id, {
                id: row.industry.id,
                label: row.industry.label,
                maxGain: row.gain,
                ...(row.displayMetric === undefined
                    ? {}
                    : {
                          displayMetric: {
                              gain: null,
                              basis: "unknown" as const,
                              leaderName: null,
                              leaderCode: null,
                          },
                      }),
                rows: [row],
            });
        updateDisplayMetric(groups.get(row.industry.id)!, row);
    }
    return [...groups.values()];
}

/** Only a vanished stock with a confirmed end bursts, never a representative switch. */
export function endedBurst(
    previous: MapView,
    next: MapView,
    row: MapRow,
): boolean {
    if (!sameSource(previous, next) || next.date <= previous.date) return false;
    if (previous.catalogId) {
        const end = row.wave.endConfirmedAt;
        return !!end && previous.date < end && end <= next.date;
    }
    const ended = next.ended.find(
        (item) =>
            item.security.id === row.security.id &&
            item.wave.id === row.wave.id,
    );
    return !!(
        ended &&
        ended.security === row.security &&
        ended.wave === row.wave &&
        ended.wave.endConfirmedAt &&
        ended.wave.endConfirmedAt <= next.date
    );
}
