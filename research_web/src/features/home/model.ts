import { appears } from "../full-history/model.ts";
import type { HistoryFrame, HistoryRow } from "../full-history/types.ts";

/** The homepage and territory map share the exact eligibility function. */
export function latestMarketSummary(frame: HistoryFrame, threshold = 100) {
    const rows = frame.rows.filter((row) =>
        appears(row, frame.date, "launched", threshold),
    );
    const sorted = [...rows].sort(
        (a, b) =>
            (b.growth?.sizingGainPct ?? -Infinity) -
                (a.growth?.sizingGainPct ?? -Infinity) ||
            a.code.localeCompare(b.code),
    );
    const groups = new Map<
        string,
        { id: string; label: string; rows: HistoryRow[]; best: HistoryRow }
    >();
    for (const row of sorted) {
        const group = groups.get(row.industry.id);
        if (group) group.rows.push(row);
        else
            groups.set(row.industry.id, {
                id: row.industry.id,
                label: row.industry.label,
                rows: [row],
                best: row,
            });
    }
    return {
        count: rows.length,
        strongest: sorted.slice(0, 8),
        industries: [...groups.values()].sort(
            (a, b) => b.rows.length - a.rows.length || a.id.localeCompare(b.id),
        ),
    };
}
