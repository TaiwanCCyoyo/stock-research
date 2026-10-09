import type {
    OpportunityRow,
    OpportunitySecurity,
    OpportunityWave,
} from "../../domain/opportunities/types.ts";
import type { PackedNode, PreviousPackingPosition } from "./packing.ts";
import type { Camera } from "./camera.ts";

export interface OverviewIndustryLabel {
    id: string;
    label: string;
    maxGain: number | null;
    displayMetric?: IndustryDisplayMetric;
    x: number;
    y: number;
    width: number;
    height: number;
    anchorX: number;
    anchorY: number;
    side: "left" | "right";
}

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

export function industryMetricLabel(
    industry: Pick<
        MapView["industries"][number],
        "label" | "maxGain" | "displayMetric"
    >,
): string {
    if (industry.displayMetric !== undefined) {
        const { displayMetric } = industry;
        const leader = displayMetric.leaderName
            ? ` · ${displayMetric.leaderName}`
            : "";
        return `${industry.label}　最高：${metricLabel(displayMetric)}${leader}`;
    }
    const value =
        industry.maxGain === null
            ? "不知道"
            : `${industry.maxGain >= 0 ? "+" : ""}${industry.maxGain.toFixed(0)}%`;
    return `${industry.label}　漲 ${value}`;
}

/** Raw peak gain cannot define an equivalent radius for duration-normalized cells. */
export function showPeakAreaReference(
    row: Pick<MapRow, "displayMetric">,
): boolean {
    return row.displayMetric === undefined;
}

/** The ten largest visible territories keep readable labels outside the world geometry. */
export function overviewIndustryLabels(
    groups: readonly { id: string; x: number; y: number; weight: number }[],
    industries: ReadonlyMap<
        string,
        {
            label: string;
            maxGain: number | null;
            displayMetric?: IndustryDisplayMetric;
        }
    >,
    camera: Camera,
    fontSize: number,
): OverviewIndustryLabel[] {
    const ranked = groups
        .filter((group) => group.weight > 0 && industries.has(group.id))
        .slice()
        .sort((a, b) => b.weight - a.weight || a.id.localeCompare(b.id))
        .slice(0, 10)
        .sort((a, b) => a.x - b.x || a.id.localeCompare(b.id));
    const screenFont = fontSize * camera.zoom;
    const longestLabel = Math.max(
        0,
        ...ranked.map((group) => {
            const label = industryMetricLabel(industries.get(group.id)!);
            return [...label].reduce(
                (sum, letter) => sum + (letter.charCodeAt(0) <= 255 ? 0.6 : 1),
                0,
            );
        }),
    );
    const width = Math.min(340, Math.max(180, (longestLabel + 4) * screenFont));
    const height = screenFont * 2.5;
    const gap = screenFont * 0.5;
    const middle = Math.ceil(ranked.length / 2);
    return [ranked.slice(0, middle), ranked.slice(middle)].flatMap(
        (column, index) => {
            const side = index === 0 ? "left" : "right";
            const ordered = column
                .slice()
                .sort((a, b) => a.y - b.y || a.id.localeCompare(b.id));
            const available = 620 - 54 - 18 - height;
            const step =
                ordered.length > 1 ? available / (ordered.length - 1) : 0;
            return ordered.map((group, position) => ({
                id: group.id,
                ...industries.get(group.id)!,
                x: side === "left" ? 14 : 1000 - 14 - width,
                y:
                    ordered.length === 1
                        ? Math.max(
                              54,
                              Math.min(
                                  620 - 18 - height,
                                  310 +
                                      (group.y - camera.y) * camera.zoom -
                                      height / 2,
                              ),
                          )
                        : 54 + position * Math.max(height + gap, step),
                width,
                height,
                anchorX: 500 + (group.x - camera.x) * camera.zoom,
                anchorY: 310 + (group.y - camera.y) * camera.zoom,
                side: side as "left" | "right",
            }));
        },
    );
}

/** Zero-area nodes have no visible location to preserve in the next packing. */
export function visiblePackingPositions(
    nodes: readonly Pick<PackedNode, "id" | "x" | "y" | "r">[],
): PreviousPackingPosition[] {
    return nodes
        .filter((node) => node.r > 0)
        .map(({ id, x, y }) => ({ id, x, y }));
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

/** Font and radius use world units, so zoom-dependent screen size stays comparable. */
export function groupLabelFits(
    label: string,
    radius: number,
    fontSize: number,
    lines = 1,
): boolean {
    const width =
        [...label].reduce(
            (sum, letter) => sum + (letter.charCodeAt(0) <= 255 ? 0.6 : 1),
            0,
        ) * fontSize;
    return (
        Number.isFinite(radius) &&
        radius > 0 &&
        radius * 2 >= width * 1.1 &&
        radius >= fontSize * lines
    );
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
