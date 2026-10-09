import type {
    OpportunityBundle,
    OpportunityRow,
} from "../../domain/opportunities/types.ts";
import { buildMarketView } from "../../domain/opportunities/model.ts";

/** Resolve against the clicked date, never the pre-click rendered rows. */
export function timelineRow(
    bundle: OpportunityBundle,
    securityId: string,
    date: string,
): OpportunityRow | null {
    if (!bundle.dates.includes(date)) return null;
    const representatives = bundle.representatives.filter(
        (entry) =>
            entry.securityId === securityId &&
            entry.from <= date &&
            (entry.untilExclusive === null || date < entry.untilExclusive),
    );
    if (representatives.length !== 1) return null;
    return (
        buildMarketView(bundle, date).rows.find(
            (row) =>
                row.security.id === securityId &&
                row.wave.id === representatives[0].waveId,
        ) ?? null
    );
}

export interface OpportunitySelection {
    securityId: string;
    waveId: string;
}

export function opportunitySelection(
    row: OpportunityRow,
): OpportunitySelection {
    return { securityId: row.security.id, waveId: row.wave.id };
}

/** A missing selected wave must not resolve to another wave of the same stock. */
export function resolveOpportunitySelection(
    rows: readonly OpportunityRow[],
    selection: OpportunitySelection | null,
): OpportunityRow | null {
    if (!selection) return null;
    return (
        rows.find(
            (row) =>
                row.security.id === selection.securityId &&
                row.wave.id === selection.waveId,
        ) ?? null
    );
}

/** Map rows are unique; the timeline displays the first row for each stock. */
export function selectedDisplayedSecurityId(
    rows: readonly OpportunityRow[],
    selection: OpportunitySelection | null,
): string | null {
    if (!selection) return null;
    const displayed = rows.find(
        (row) => row.security.id === selection.securityId,
    );
    return displayed?.wave.id === selection.waveId
        ? selection.securityId
        : null;
}
