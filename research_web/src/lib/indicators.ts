import type { PriceRow } from "../api/types";

export interface LinePoint {
    time: string;
    value: number;
}

/** Simple moving average over Close; emits points only once the window is full. */
export function movingAverage(rows: PriceRow[], window: number): LinePoint[] {
    const points: LinePoint[] = [];
    let sum = 0;
    for (let i = 0; i < rows.length; i++) {
        sum += rows[i].Close;
        if (i >= window) sum -= rows[i - window].Close;
        if (i >= window - 1) {
            points.push({
                time: rows[i].Date.slice(0, 10),
                value: sum / window,
            });
        }
    }
    return points;
}
