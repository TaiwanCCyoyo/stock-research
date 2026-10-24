import type { StudyCard } from "./model.ts";
import type { StudiesResponse } from "./v2.ts";

/** What the research list knows: the last good response, the latest error,
 *  and whether the shown cards are older than a failed refresh. */
export interface StudiesState {
    data: StudiesResponse | null;
    error: string;
    stale: boolean;
}

export function studiesLoaded(data: StudiesResponse): StudiesState {
    return { data, error: "", stale: false };
}

/** A failed refresh keeps the last good cards but marks them stale, so old
 *  progress is never presented as verified current state. */
export function studiesFailed(
    current: StudiesState,
    message: string,
): StudiesState {
    return current.data
        ? { data: current.data, error: message, stale: true }
        : { data: null, error: message, stale: false };
}

export const STALE_PROGRESS = "進度可能已過時";

/** Cards shown from a stale response warn wherever they show live progress. */
export function markStale(cards: readonly StudyCard[]): StudyCard[] {
    return cards.map((card) =>
        card.progress && !card.caveats.includes(STALE_PROGRESS)
            ? { ...card, caveats: [...card.caveats, STALE_PROGRESS] }
            : card,
    );
}
