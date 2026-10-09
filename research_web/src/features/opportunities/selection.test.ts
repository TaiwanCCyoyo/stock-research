import assert from "node:assert/strict";
import { test } from "node:test";
import {
    buildMarketView,
    validateBundle,
} from "../../domain/opportunities/model.ts";
import type { OpportunityBundle } from "../../domain/opportunities/types.ts";
import {
    opportunitySelection,
    resolveOpportunitySelection,
    selectedDisplayedSecurityId,
    timelineRow,
} from "./selection.ts";

const DAYS = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"];
function fixture(): OpportunityBundle {
    return validateBundle({
        schema: "opportunity-explorer.v1",
        id: "multiple-waves",
        label: "Multiple waves with a representative gap",
        kind: "synthetic",
        asOf: DAYS[3],
        dates: DAYS,
        priceBasis: "adjusted-close",
        catalogCoverage: "case-slice",
        ruleVersion: "rules.v1",
        selectionPolicy: "explicit.v1",
        classificationVersion: "unknown",
        sources: [{ id: "fixture", label: "Fixture" }],
        limitations: [],
        securities: [
            {
                id: "TW:A",
                code: "A",
                name: "Two-wave stock",
                market: "TW",
                currency: "TWD",
                industry: [],
                prices: [10, 20, 30, 25].map((close, i) => ({
                    date: DAYS[i],
                    close,
                    flags: [],
                })),
            },
        ],
        waves: [0, 1].map((i) => ({
            id: `wave-${i + 1}`,
            securityId: "TW:A",
            start: DAYS[i],
            launch: {
                date: DAYS[i],
                rangeFrom: DAYS[i],
                rangeUntil: DAYS[i],
                sourceId: "fixture",
            },
            launchMissingReason: null,
            peakDate: DAYS[i + 1],
            endConfirmedAt: i === 0 ? DAYS[1] : DAYS[3],
            observedThrough: i === 0 ? DAYS[1] : DAYS[3],
            leftCensored: false,
            rightCensored: false,
            scale: "large",
            parentId: null,
            sourceId: "fixture",
            phases: [],
        })),
        representatives: [
            {
                securityId: "TW:A",
                waveId: "wave-1",
                from: DAYS[0],
                untilExclusive: DAYS[1],
            },
            {
                securityId: "TW:A",
                waveId: "wave-2",
                from: DAYS[2],
                untilExclusive: DAYS[3],
            },
        ],
        portfolios: [],
    });
}

test("a directory selection keeps the second wave's evidence when no representative is defined", () => {
    const view = buildMarketView(fixture(), DAYS[1]);
    assert.equal(view.rows.length, 2);
    assert.equal(view.active.length, 0);
    const selected = opportunitySelection(view.rows[1]);
    assert.deepEqual(selected, { securityId: "TW:A", waveId: "wave-2" });
    const row = resolveOpportunitySelection(view.rows, selected);
    assert.equal(row, view.rows[1]);
    assert.deepEqual(
        [row?.wave.start, row?.wave.peakDate, row?.wave.endConfirmedAt],
        [DAYS[1], DAYS[2], DAYS[3]],
    );
    assert.equal(row?.peakGain, 50);
    assert.equal(
        resolveOpportunitySelection([...view.rows].reverse(), selected),
        row,
    );
    assert.equal(
        resolveOpportunitySelection(view.rows, {
            ...selected,
            securityId: "TW:other",
        }),
        null,
    );
});

test("timeline clicks resolve the representative at the target date in both directions", () => {
    const bundle = fixture();
    const oldView = buildMarketView(bundle, DAYS[0]);
    const clicked = timelineRow(bundle, oldView.rows[0].security.id, DAYS[2]);
    assert.equal(clicked?.wave.id, "wave-2");
    assert.equal(
        resolveOpportunitySelection(
            buildMarketView(bundle, DAYS[2]).rows,
            opportunitySelection(clicked!),
        )?.wave.id,
        "wave-2",
    );
    assert.equal(timelineRow(bundle, "TW:A", DAYS[0])?.wave.id, "wave-1");
    // A representative gap is not permission to select the first catalog wave.
    assert.equal(timelineRow(bundle, "TW:A", DAYS[1]), null);
    assert.equal(
        timelineRow(
            { ...bundle, waves: [...bundle.waves].reverse() },
            "TW:A",
            DAYS[1],
        ),
        null,
    );
    assert.equal(
        timelineRow({ ...bundle, representatives: [] }, "TW:A", DAYS[0]),
        null,
    );
    assert.equal(timelineRow(bundle, "missing", DAYS[2]), null);
    assert.equal(timelineRow(bundle, "TW:A", "2099-01-01"), null);
});

test("date changes never substitute another wave and returning to the date restores the selected row", () => {
    const bundle = fixture();
    const gap = buildMarketView(bundle, DAYS[1]);
    const selected = opportunitySelection(gap.rows[1]);
    const earlier = buildMarketView(bundle, DAYS[0]);
    assert.equal(earlier.rows[0].wave.id, "wave-1");
    assert.equal(resolveOpportunitySelection(earlier.rows, selected), null);
    assert.equal(selectedDisplayedSecurityId(earlier.active, selected), null);
    assert.equal(selectedDisplayedSecurityId(earlier.rows, selected), null);
    assert.equal(
        resolveOpportunitySelection(
            buildMarketView(bundle, DAYS[1]).rows,
            selected,
        )?.wave.id,
        "wave-2",
    );
});

test("map and timeline highlight only the exact wave they display", () => {
    const bundle = fixture();
    const gap = buildMarketView(bundle, DAYS[1]);
    const first = opportunitySelection(gap.rows[0]);
    const second = opportunitySelection(gap.rows[1]);
    // Timeline deduplicates stocks using the first catalog row.
    assert.equal(selectedDisplayedSecurityId(gap.rows, first), "TW:A");
    assert.equal(selectedDisplayedSecurityId(gap.rows, second), null);
    const mapView = buildMarketView(bundle, DAYS[2]);
    const clicked = opportunitySelection(mapView.active[0]);
    assert.deepEqual(clicked, second);
    assert.equal(
        resolveOpportunitySelection(mapView.rows, clicked),
        mapView.active[0],
    );
    assert.equal(selectedDisplayedSecurityId(mapView.active, first), null);
    assert.equal(selectedDisplayedSecurityId(mapView.active, second), "TW:A");
    assert.equal(selectedDisplayedSecurityId(mapView.active, null), null);
});
