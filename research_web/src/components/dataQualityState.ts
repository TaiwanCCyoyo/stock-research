import type { DataQualityResponse } from "../api/types";

export const DATA_QUALITY_STALE_AFTER_MS = 72 * 60 * 60 * 1000;

/** Keep a partial official share distinguishable from complete coverage. */
export function formatQualityShare(share: number | null | undefined): string {
    if (share == null || !Number.isFinite(share) || share < 0 || share > 1)
        return "未知";
    const percentage = (share * 100).toFixed(2);
    return share < 1 && percentage === "100.00"
        ? "接近 100%"
        : `${Number(percentage)}%`;
}

export type DataQualityState =
    | { status: "loading" }
    | { status: "failure"; message: string }
    | { status: "missing" }
    | { status: "fresh"; data: DataQualityResponse }
    | { status: "stale"; data: DataQualityResponse; ageHours: number };

/**
 * Producer freshness applies only to this explicitly UTC report timestamp.
 * The 72-hour window allows ordinary weekends without calling a frozen
 * research input stale based on the producer's separate generation dates.
 */
export function dataQualityState(
    input:
        | { status: "loading" }
        | { status: "failure"; message: string }
        | { status: "loaded"; data: DataQualityResponse },
    now: number = Date.now(),
): DataQualityState {
    if (input.status === "loading") return { status: "loading" };
    if (input.status === "failure")
        return { status: "failure", message: input.message };
    if (!input.data.available || !input.data.report)
        return { status: "missing" };

    const timestamp = input.data.report.generated_at;
    const generatedAt = Date.parse(timestamp);
    if (
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(
            timestamp,
        ) ||
        !Number.isFinite(generatedAt)
    )
        return {
            status: "failure",
            message: "報告時間格式無效，無法判斷檢查狀態。",
        };
    const age = now - generatedAt;
    if (age < 0) return { status: "fresh", data: input.data };
    if (age > DATA_QUALITY_STALE_AFTER_MS)
        return {
            status: "stale",
            data: input.data,
            ageHours: Math.floor(age / (60 * 60 * 1000)),
        };
    return { status: "fresh", data: input.data };
}
