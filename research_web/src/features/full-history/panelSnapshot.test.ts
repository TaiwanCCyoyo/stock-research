import assert from "node:assert/strict";
import test from "node:test";
import { PANEL_REFRESH, nextPanelSnapshot } from "./panelSnapshot.ts";

const live = (date: string) => ({
    frame: { date },
    comparisons: [{ date, held: date }],
});

test("paused panels always show the live frame and holdings", () => {
    const first = nextPanelSnapshot(null, live("2020-06-01"), false, 0);
    const next = nextPanelSnapshot(first, live("2020-06-08"), false, 100);
    assert.equal(next.frame.date, "2020-06-08");
    assert.equal(next.comparisons[0]!.date, "2020-06-08");
});

test("during playback frame and holdings refresh together, never apart", () => {
    let snap = nextPanelSnapshot(null, live("2020-06-01"), true, 0);
    // Holdings arrive for later dates between refreshes: still the old pair.
    for (const [date, at] of [
        ["2020-06-08", 500],
        ["2020-06-15", 1000],
        ["2020-06-22", 1500],
    ] as const) {
        snap = nextPanelSnapshot(snap, live(date), true, at);
        assert.equal(snap.frame.date, snap.comparisons[0]!.date);
        assert.equal(snap.frame.date, "2020-06-01");
    }
    snap = nextPanelSnapshot(snap, live("2020-06-29"), true, PANEL_REFRESH);
    assert.equal(snap.frame.date, "2020-06-29");
    assert.equal(snap.comparisons[0]!.date, "2020-06-29");
});
