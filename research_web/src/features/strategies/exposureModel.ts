import type { StudioExposure } from "../../domain/strategies/types.ts";

export const EXPOSURE_KEYS = [
    "runawayWeight",
    "otherStockWeight",
    "unknownStockWeight",
    "otherAssetsWeight",
    "cashWeight",
] as const;
export type ExposureWeightKey = (typeof EXPOSURE_KEYS)[number];
type ExposureRow = StudioExposure["rows"][number];
type KnownExposureRow = ExposureRow & Record<ExposureWeightKey, number>;
export interface ExposurePoint {
    index: number;
    date: string;
    layers: { key: ExposureWeightKey; start: number; end: number }[];
}
export interface ExposureSegment {
    fromIndex: number;
    untilIndexExclusive: number;
    points: ExposurePoint[];
}
export interface ExposureUnknownRange {
    fromIndex: number;
    untilIndexExclusive: number;
}

export function isCompleteExposure(row: ExposureRow): row is KnownExposureRow {
    return (
        row.known &&
        EXPOSURE_KEYS.every(
            (key) => typeof row[key] === "number" && Number.isFinite(row[key]),
        )
    );
}

/** Unknown dates occupy their original slots and never join neighboring known areas. */
export function projectExposure(rows: readonly ExposureRow[]) {
    const segments: ExposureSegment[] = [];
    const unknownRanges: ExposureUnknownRange[] = [];
    const runawayValues: (number | null)[] = [];
    let segment: ExposureSegment | null = null;
    let unknownRange: ExposureUnknownRange | null = null;
    for (const [index, row] of rows.entries()) {
        if (!isCompleteExposure(row)) {
            segment = null;
            if (!unknownRange) {
                unknownRange = {
                    fromIndex: index,
                    untilIndexExclusive: index + 1,
                };
                unknownRanges.push(unknownRange);
            } else unknownRange.untilIndexExclusive = index + 1;
            runawayValues.push(null);
            continue;
        }
        unknownRange = null;
        let sum = 0;
        const layers = EXPOSURE_KEYS.map((key) => {
            const start = sum;
            sum += row[key];
            return { key, start, end: sum };
        });
        const point = { index, date: row.date, layers };
        if (!segment) {
            segment = {
                fromIndex: index,
                untilIndexExclusive: index + 1,
                points: [point],
            };
            segments.push(segment);
        } else {
            segment.untilIndexExclusive = index + 1;
            segment.points.push(point);
        }
        runawayValues.push(row.runawayWeight);
    }
    const unknownDays = unknownRanges.reduce(
        (total, range) => total + range.untilIndexExclusive - range.fromIndex,
        0,
    );
    return { segments, unknownRanges, runawayValues, unknownDays };
}
