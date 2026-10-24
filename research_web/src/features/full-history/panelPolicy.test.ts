import assert from "node:assert/strict";
import test from "node:test";
import {
    PANEL_PLAYBACK_SWAP_MS,
    PANEL_SETTLE_MS,
    initialPanel,
    panelConcealed,
    panelCue,
    panelWake,
    stepPanel,
    type PanelInput,
    type PanelState,
} from "./panelPolicy.ts";

type Snap = { date: string; key: string; rows: string[] };
const snap = (date: string): Snap => ({
    date,
    key: date,
    rows: [`row-${date}`],
});
const input = (
    date: string | null,
    over: Partial<PanelInput<Snap>> = {},
): PanelInput<Snap> => ({
    live: date === null ? null : snap(date),
    playing: false,
    scrubbing: false,
    reduced: false,
    ...over,
});

/** Feed `inputs` at the given times; return every state seen. */
function drive(
    steps: { at: number; input: PanelInput<Snap> }[],
    from: PanelState<Snap> = initialPanel<Snap>(),
) {
    const seen: PanelState<Snap>[] = [];
    let state = from;
    for (const { at, input: next } of steps) {
        state = stepPanel(state, next, at);
        seen.push(state);
    }
    return seen;
}
/** Evaluate on a fine grid between `from` and `to` ms with a fixed input. */
function run(
    state: PanelState<Snap>,
    next: PanelInput<Snap>,
    from: number,
    to: number,
    every = 25,
) {
    const seen: { at: number; state: PanelState<Snap> }[] = [];
    for (let at = from; at <= to; at += every) {
        state = stepPanel(state, next, at);
        seen.push({ at, state });
    }
    return seen;
}
const shownAt = (date: string, at = 0) =>
    run(initialPanel<Snap>(), input(date), at, at + 1500).at(-1)!.state;

test("the first snapshot enters at once and then settles to shown", () => {
    const early = stepPanel(initialPanel<Snap>(), input("2020-01-02"), 0);
    assert.equal(early.phase, "entering");
    assert.equal(early.shown?.date, "2020-01-02");
    assert.equal(shownAt("2020-01-02").phase, "shown");
});

test("paused: a new date shows only after it has been stable for the settle delay", () => {
    const base = shownAt("2020-01-02");
    const t0 = 2000;
    // The date changes every 100 ms for a while (stepping by hand).
    let state = base;
    for (let i = 0; i < 6; i++) {
        state = stepPanel(state, input(`2020-02-0${i + 1}`), t0 + i * 100);
        assert.equal(state.shown?.date, "2020-01-02", "old set stays put");
        assert.equal(state.phase, "shown");
    }
    const last = t0 + 500;
    const before = stepPanel(
        state,
        input("2020-02-06"),
        last + PANEL_SETTLE_MS - 10,
    );
    assert.equal(before.phase, "shown");
    const after = stepPanel(state, input("2020-02-06"), last + PANEL_SETTLE_MS);
    assert.equal(after.phase, "leaving");
    // Leaving finishes, then the new set (the date as it is now) enters.
    const later = run(
        after,
        input("2020-02-06"),
        last + PANEL_SETTLE_MS,
        last + 3000,
    );
    const phases = [...new Set(later.map((entry) => entry.state.phase))];
    assert.deepEqual(phases, ["leaving", "entering", "shown"]);
    assert.equal(later.at(-1)!.state.shown?.date, "2020-02-06");
});

test("a date change while entering sends the set away; it never counts as shown", () => {
    const first = stepPanel(initialPanel<Snap>(), input("2020-01-02"), 0);
    assert.equal(first.phase, "entering");
    // 100 ms into entering the date moves on (paused).
    const moved = stepPanel(first, input("2020-01-03"), 100);
    assert.equal(moved.phase, "leaving");
    // Nothing is entered for 2020-01-03 until it has settled, and no stale
    // set is ever shown in between.
    const seen = run(moved, input("2020-01-03"), 100, 1500);
    for (const { at, state } of seen) {
        if (state.phase === "shown" || state.phase === "entering")
            assert.equal(state.shown?.date, "2020-01-03", `at ${at}`);
        if (state.phase === "shown") assert.ok(at >= 100 + PANEL_SETTLE_MS);
    }
    assert.equal(seen.at(-1)!.state.phase, "shown");
});

test("playback: rows and date change together, at the swap cadence only", () => {
    // Playback steps the live date every 500 ms from the start.
    let state = initialPanel<Snap>();
    const swaps: { at: number; date: string; rows: string[] }[] = [];
    let lastSwap = -Infinity;
    for (let at = 0; at <= 15000; at += 100) {
        const date = `2020-01-${String(1 + Math.floor(at / 500)).padStart(2, "0")}`;
        state = stepPanel(state, input(date, { playing: true }), at);
        if (state.shown && state.swappedAt !== lastSwap) {
            lastSwap = state.swappedAt;
            swaps.push({ at, ...state.shown });
        }
    }
    assert.ok(swaps.length >= 4, "it does swap");
    for (const swap of swaps)
        assert.deepEqual(
            swap.rows,
            [`row-${swap.date}`],
            "date and rows agree",
        );
    for (let i = 1; i < swaps.length; i++)
        assert.ok(
            swaps[i]!.at - swaps[i - 1]!.at >= PANEL_PLAYBACK_SWAP_MS,
            `swap ${i} came ${swaps[i]!.at - swaps[i - 1]!.at} ms after the last`,
        );
});

test("playback: the set on screen is never cancelled by the date moving on", () => {
    let state = stepPanel(
        initialPanel<Snap>(),
        input("2020-01-01", { playing: true }),
        0,
    );
    for (let at = 100; at <= 500; at += 100)
        state = stepPanel(
            state,
            input(`2020-01-0${1 + at / 100}`, { playing: true }),
            at,
        );
    assert.equal(state.shown?.date, "2020-01-01");
    assert.notEqual(state.phase, "leaving");
});

test("pausing playback swaps to the paused date after the settle delay", () => {
    let state = shownAt("2020-01-01", 1500);
    state = stepPanel(state, input("2020-01-09", { playing: true }), 3500);
    assert.equal(state.shown?.date, "2020-01-01");
    // Paused at 2020-01-09 (date unchanged since 3500 ms).
    const paused = stepPanel(state, input("2020-01-09"), 3600);
    assert.equal(paused.phase, "shown");
    assert.equal(paused.shown?.date, "2020-01-01");
    const settled = stepPanel(
        paused,
        input("2020-01-09"),
        3500 + PANEL_SETTLE_MS,
    );
    assert.equal(settled.phase, "leaving");
});

test("a fast scrub: cards leave, the panel stays empty, the set enters after it settles", () => {
    const base = shownAt("2020-01-02");
    const scrub = input("2020-03-01", { scrubbing: true });
    let state = stepPanel(base, scrub, 2000);
    assert.equal(state.phase, "leaving");
    const seen = run(state, scrub, 2000, 6000);
    assert.equal(seen.at(-1)!.state.phase, "empty");
    assert.equal(seen.at(-1)!.state.shown?.date, "2020-01-02", "old set held");
    // The scrub ends: the date has been still for a while, so it enters at once.
    const end = stepPanel(seen.at(-1)!.state, input("2020-03-01"), 6100);
    assert.equal(end.phase, "entering");
    assert.equal(end.shown?.date, "2020-03-01");
});

test("reduced motion: no animation phases, same snapshot timing, instant swap", () => {
    const reduced = (date: string, over: Partial<PanelInput<Snap>> = {}) =>
        input(date, { reduced: true, ...over });
    const first = stepPanel(initialPanel<Snap>(), reduced("2020-01-02"), 0);
    assert.equal(first.phase, "shown");
    const seen: PanelState<Snap>[] = drive(
        [
            { at: 1000, input: reduced("2020-01-05") },
            { at: 1100, input: reduced("2020-01-06") },
            { at: 1100 + PANEL_SETTLE_MS - 1, input: reduced("2020-01-06") },
            { at: 1100 + PANEL_SETTLE_MS, input: reduced("2020-01-06") },
        ],
        first,
    );
    assert.deepEqual(
        seen.map((s) => s.shown?.date),
        ["2020-01-02", "2020-01-02", "2020-01-02", "2020-01-06"],
    );
    for (const state of seen)
        assert.ok(state.phase === "shown", "no leaving or entering");
    // A scrub holds the old set until it settles.
    const held = stepPanel(
        seen.at(-1)!,
        reduced("2020-02-01", { scrubbing: true }),
        3000,
    );
    assert.equal(held.shown?.date, "2020-01-06");
    assert.equal(held.phase, "shown");
});

test("the policy asks to be woken only when something is due", () => {
    const shown = shownAt("2020-01-02");
    assert.equal(panelWake(shown, input("2020-01-02"), 1500), null);
    const moved = stepPanel(shown, input("2020-01-09"), 2000);
    const wake = panelWake(moved, input("2020-01-09"), 2000)!;
    assert.ok(wake > 0 && wake <= PANEL_SETTLE_MS);
    const playing = panelWake(
        shown,
        input("2020-01-09", { playing: true }),
        2000,
    );
    assert.ok(playing === null || playing <= PANEL_PLAYBACK_SWAP_MS);
});

test("the cue: dim when the cards lag the map, ring only while playing", () => {
    assert.deepEqual(panelCue("2020-01-02", "2020-01-02", false), {
        dimmed: false,
        ringVisible: false,
    });
    assert.deepEqual(panelCue("2020-01-02", "2020-01-09", false), {
        dimmed: true,
        ringVisible: false,
    });
    assert.deepEqual(panelCue("2020-01-02", "2020-01-09", true), {
        dimmed: true,
        ringVisible: true,
    });
    assert.deepEqual(panelCue("2020-01-09", "2020-01-09", true), {
        dimmed: false,
        ringVisible: true,
    });
    assert.equal(panelCue(null, "2020-01-09", false).dimmed, false);
});

test("holdings that load late update the shown set without a swap", () => {
    const shown = shownAt("2020-01-02");
    const refreshed: Snap = { ...snap("2020-01-02"), rows: ["with-holdings"] };
    const next = stepPanel(
        shown,
        { ...input("2020-01-02"), live: refreshed },
        2000,
    );
    assert.equal(next.phase, "shown");
    assert.equal(next.shown, refreshed);
    assert.equal(next.swappedAt, shown.swappedAt);
});

test("a different set for the same date (threshold, mode) swaps as a whole", () => {
    const shown = shownAt("2020-01-02");
    const other: Snap = { date: "2020-01-02", key: "2020-01-02|200", rows: [] };
    const live = { ...input("2020-01-02"), live: other };
    const waiting = stepPanel(shown, live, 2000);
    assert.equal(waiting.phase, "shown");
    assert.equal(
        stepPanel(waiting, live, 2000 + PANEL_SETTLE_MS).phase,
        "leaving",
    );
});

test("leaving and gone cards are concealed from keyboard and screen readers", () => {
    assert.equal(panelConcealed("leaving"), true);
    assert.equal(panelConcealed("empty"), true);
    assert.equal(panelConcealed("entering"), false);
    assert.equal(panelConcealed("shown"), false);
});
