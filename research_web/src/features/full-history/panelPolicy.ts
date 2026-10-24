/** When the side panel (stock list, holdings) changes. Its cards never move in
 *  place: the panel holds one snapshot (rows, date and holdings together) and
 *  changes only by a whole swap, the old set sliding out to the right and the
 *  new one entering from below.
 *
 *  - Paused or stepping by hand: the date must stay put for PANEL_SETTLE_MS
 *    before anything changes.
 *  - Playback: a swap every PANEL_PLAYBACK_SWAP_MS; between swaps nothing moves.
 *  - A fast scrub (the same signal as the map's pop, scrub.ts): the cards leave,
 *    the panel stays empty, and the new set enters once the date has settled.
 *  - Reduced motion: the same timing, but the swap is instant.
 *  Pure: time comes in as `now`, so the whole policy is testable. */

export type PanelPhase = "empty" | "entering" | "shown" | "leaving";
/** What the panel shows. `key` names the whole set (date, mode, threshold):
 *  a different key is a different set, swapped as a whole. */
export interface PanelSnap {
    date: string;
    key: string;
}

/** Paused: the date must be stable this long before the panel swaps. */
export const PANEL_SETTLE_MS = 300;
/** Playback: the panel swaps to the current frame this often. */
export const PANEL_PLAYBACK_SWAP_MS = 3000;
/** Only the first cards animate; the rest vanish or appear at once. */
export const PANEL_ANIMATED_CARDS = 10;
export const PANEL_LEAVE_MS = 200;
export const PANEL_LEAVE_STAGGER = 18;
export const PANEL_ENTER_MS = 240;
export const PANEL_ENTER_STAGGER = 28;
const LEAVE_TOTAL =
    PANEL_LEAVE_MS + (PANEL_ANIMATED_CARDS - 1) * PANEL_LEAVE_STAGGER + 20;
const ENTER_TOTAL =
    PANEL_ENTER_MS + (PANEL_ANIMATED_CARDS - 1) * PANEL_ENTER_STAGGER + 20;

export interface PanelState<T extends PanelSnap> {
    phase: PanelPhase;
    /** The snapshot on screen (or leaving it); null before the first one. */
    shown: T | null;
    phaseAt: number;
    /** When the current snapshot was adopted. */
    swappedAt: number;
    /** The live set last seen and when it last changed. */
    liveKey: string;
    liveChangedAt: number;
}
export interface PanelInput<T extends PanelSnap> {
    /** The newest data, or null while nothing is loaded. */
    live: T | null;
    playing: boolean;
    scrubbing: boolean;
    reduced: boolean;
}

export function initialPanel<T extends PanelSnap>(): PanelState<T> {
    return {
        phase: "empty",
        shown: null,
        phaseAt: 0,
        swappedAt: -Infinity,
        liveKey: "",
        liveChangedAt: 0,
    };
}

function sameState<T extends PanelSnap>(a: PanelState<T>, b: PanelState<T>) {
    return (
        a.phase === b.phase &&
        a.shown === b.shown &&
        a.phaseAt === b.phaseAt &&
        a.swappedAt === b.swappedAt &&
        a.liveKey === b.liveKey &&
        a.liveChangedAt === b.liveChangedAt
    );
}

export function stepPanel<T extends PanelSnap>(
    state: PanelState<T>,
    input: PanelInput<T>,
    now: number,
): PanelState<T> {
    const s = { ...state };
    const liveKey = input.live?.key ?? "";
    if (liveKey !== s.liveKey) {
        s.liveKey = liveKey;
        s.liveChangedAt = now;
    }
    const settled = now - s.liveChangedAt >= PANEL_SETTLE_MS;
    // May a snapshot of the live data be adopted right now? Never during a
    // scrub, and never for a date that is still moving.
    const canSwap =
        input.live !== null &&
        !input.scrubbing &&
        (s.shown === null ||
            (input.playing
                ? now - s.swappedAt >= PANEL_PLAYBACK_SWAP_MS
                : settled));
    const stale = s.shown?.key !== liveKey;
    // The same set with only its holdings updated (they load late): no
    // swap, nothing moves.
    if (!stale && input.live && s.shown !== input.live) s.shown = input.live;
    const adopt = (phase: PanelPhase) => {
        s.shown = input.live;
        s.swappedAt = now;
        s.phase = phase;
        s.phaseAt = now;
    };
    if (input.reduced) {
        // No slide, no fade: hold the old set until the date settles, then swap.
        s.phase = s.shown ? "shown" : "empty";
        if (canSwap && stale) adopt("shown");
        return sameState(state, s) ? state : s;
    }
    switch (s.phase) {
        case "empty":
            if (canSwap) adopt("entering");
            break;
        case "shown":
            if (input.scrubbing || (stale && canSwap)) {
                s.phase = "leaving";
                s.phaseAt = now;
            }
            break;
        case "leaving":
            if (now - s.phaseAt >= LEAVE_TOTAL) {
                if (canSwap) adopt("entering");
                else {
                    s.phase = "empty";
                    s.phaseAt = now;
                }
            }
            break;
        case "entering":
            // The date moved on before the set was fully in: send it away
            // again at once. It never counts as shown.
            if (input.scrubbing || (!input.playing && stale)) {
                s.phase = "leaving";
                s.phaseAt = now;
            } else if (now - s.phaseAt >= ENTER_TOTAL) {
                s.phase = "shown";
                s.phaseAt = now;
            }
            break;
    }
    return sameState(state, s) ? state : s;
}

/** Milliseconds until the policy next needs a look, or null when only an
 *  input change can move it. */
export function panelWake<T extends PanelSnap>(
    state: PanelState<T>,
    input: PanelInput<T>,
    now: number,
): number | null {
    const waits: number[] = [];
    if (!input.reduced) {
        if (state.phase === "leaving")
            waits.push(state.phaseAt + LEAVE_TOTAL - now);
        if (state.phase === "entering")
            waits.push(state.phaseAt + ENTER_TOTAL - now);
    }
    const stale = state.shown?.key !== (input.live?.key ?? "");
    if (input.live && !input.scrubbing && stale) {
        waits.push(
            input.playing
                ? state.swappedAt + PANEL_PLAYBACK_SWAP_MS - now
                : state.liveChangedAt + PANEL_SETTLE_MS - now,
        );
    }
    const next = waits.filter((wait) => wait > 0);
    return next.length ? Math.min(...next) : null;
}

export interface PanelCue {
    /** The cards belong to an earlier date than the map: fade them. */
    dimmed: boolean;
    /** Playback only: the ring that fills until the next swap. */
    ringVisible: boolean;
}

/** What the panel shows, without words, about how current its cards are. */
export function panelCue(
    snapshotDate: string | null,
    liveDate: string,
    playing: boolean,
): PanelCue {
    return {
        dimmed:
            snapshotDate !== null &&
            liveDate !== "" &&
            snapshotDate !== liveDate,
        ringVisible: playing,
    };
}
