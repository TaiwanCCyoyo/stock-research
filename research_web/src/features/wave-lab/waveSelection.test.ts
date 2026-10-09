import assert from "node:assert/strict";
import { test } from "node:test";
import {
    buildMarketView,
    validateBundle,
} from "../../domain/opportunities/model.ts";
import { toLabCase } from "../opportunities/labCase.ts";
import { analyzeComparisons } from "./analysis.ts";
import type { LabCase } from "./types.ts";
import type { OpportunityBundle } from "../../domain/opportunities/types.ts";
import {
    observationGain,
    resolveLabLaunch,
    resolveLabWave,
    waveBoundary,
} from "./waveSelection.ts";

// Two rises separated by a deep decline create a later completed large wave.
// Both methods must reconstruct the saved dates from independently analyzed prices.
const anchors = [100, 300, 60, 500, 70, 120];
const values = anchors
    .slice(1)
    .flatMap((value, index) =>
        Array.from(
            { length: 100 },
            (_, day) => anchors[index] + ((value - anchors[index]) * day) / 99,
        ),
    );
const dates = values.map((_, index) =>
    new Date(Date.UTC(2020, 0, 1 + index)).toISOString().slice(0, 10),
);
const cases = ["SYNTH-A", "SYNTH-B"].map((code) => {
    const control: LabCase = {
        id: code,
        name: code,
        code,
        kind: "synthetic",
        category: "Fictional controls",
        question:
            "Resolve the later wave without falling back to the first wave.",
        points: values.map((price, index) => ({
            date: dates[index],
            raw: price,
            adjusted: price,
            flags: [],
        })),
        source: {
            label: "Deterministic fictional piecewise prices",
            from: dates[0],
            to: dates.at(-1)!,
            priceBasis: "synthetic adjusted-close",
            limitations: [],
        },
    };
    const analysis = analyzeComparisons(control, "balanced");
    const later = analysis[0].waves.filter((wave) => wave.scale === "large")[1];
    assert.ok(later?.end);
    assert.equal(later.start, 199);
    assert.equal(later.peak, 299);
    assert.equal(later.end, 347);
    const launch = analysis[0].launches.find(
        (candidate) =>
            candidate.index >= later.start && candidate.index <= later.peak,
    )!;
    assert.ok(launch);
    const boundary = waveBoundary(control, later)!;
    const expected = {
        code,
        start: dates[199],
        peak: dates[299],
        end: dates[347],
    };
    const bundle = validateBundle({
        schema: "opportunity-explorer.v1",
        id: code,
        label: "Synthetic saved map",
        kind: "synthetic",
        asOf: dates.at(-1)!,
        dates,
        priceBasis: "adjusted-close",
        catalogCoverage: "case-slice",
        ruleVersion: "synthetic-v1",
        selectionPolicy: "explicit",
        classificationVersion: "synthetic-v1",
        limitations: [],
        sources: [
            { id: "fictional", label: "Deterministic synthetic test source" },
        ],
        securities: [
            {
                id: code,
                code,
                name: code,
                market: "SYNTHETIC",
                currency: "TWD",
                industry: [],
                prices: control.points.map((point) => ({
                    date: point.date,
                    close: point.adjusted,
                    raw: point.raw,
                    flags: [],
                })),
            },
        ],
        waves: [
            {
                id: "saved-later-wave",
                securityId: code,
                start: boundary.start,
                peakDate: boundary.peakDate,
                endConfirmedAt: boundary.endConfirmedAt,
                observedThrough: boundary.observedThrough,
                scale: boundary.scale,
                leftCensored: boundary.leftCensored,
                rightCensored: boundary.rightCensored,
                sourceId: "fictional",
                parentId: null,
                phases: [],
                launchMissingReason: null,
                launch: {
                    date: dates[launch.index],
                    rangeFrom: dates[launch.rangeStart],
                    rangeUntil: dates[launch.rangeEnd],
                    sourceId: "fictional",
                },
            },
        ],
        representatives: [
            {
                securityId: code,
                waveId: "saved-later-wave",
                from: dates[199],
                untilExclusive: dates[348],
            },
        ],
        portfolios: [],
    } satisfies OpportunityBundle);
    const view = buildMarketView(bundle, dates[220]);
    const row = view.active.find(
        (candidate) => candidate.security.code === expected.code,
    );
    assert.ok(
        row,
        `Synthetic bundle must retain ${expected.code} on ${view.date}`,
    );
    const sample = toLabCase(row, bundle);
    assert.ok(sample?.selectedOpportunity);
    return {
        expected,
        row,
        sample,
        view,
        results: analyzeComparisons(sample, "balanced"),
    };
});

test("synthetic saved map selections open the matching later wave, never the first large wave", () => {
    for (const { expected, row, sample, results, view } of cases) {
        assert.equal(sample.selectedOpportunity!.waveId, row.wave.id);
        assert.deepEqual(sample.selectedOpportunity!.launch, row.wave.launch);
        for (const result of results) {
            const selected = resolveLabWave(
                sample,
                result.waves,
                sample.selectedOpportunity!,
            );
            assert.ok(
                selected,
                `${expected.code}/${result.method} must match its saved boundaries`,
            );
            assert.notEqual(
                selected,
                result.waves.find((wave) => wave.scale === "large"),
            );
            assert.equal(sample.points[selected.start].date, expected.start);
            assert.equal(sample.points[selected.peak].date, expected.peak);
            assert.equal(sample.points[selected.end!].date, expected.end);
            assert.equal(
                sample.points[selected.observedThrough].date,
                row.wave.observedThrough,
            );
            // The initialDate prop remains the exact map observation, not a wave boundary.
            assert.ok(sample.points.some((point) => point.date === view.date));
        }
    }
});

test("same analysis ID with different boundaries never matches, while a renamed exact wave can match", () => {
    const { sample, results } = cases[0];
    const preferred = sample.selectedOpportunity!;
    const selected = resolveLabWave(sample, results[0].waves, preferred)!;
    for (const patch of [
        { start: selected.start + 1 },
        { peak: selected.peak - 1 },
        { end: null },
        { observedThrough: selected.observedThrough - 1 },
        { scale: "small" as const },
        { leftCensored: !selected.leftCensored },
        { rightCensored: !selected.rightCensored },
    ]) {
        assert.equal(
            resolveLabWave(sample, [{ ...selected, ...patch }], preferred),
            undefined,
        );
    }
    const renamed = { ...selected, id: "another-method-local-id" };
    assert.equal(resolveLabWave(sample, [renamed], preferred), renamed);
    assert.equal(
        resolveLabWave(sample, [selected, renamed], preferred),
        undefined,
    );
    assert.equal(
        resolveLabWave(
            sample,
            results[0].waves.filter((wave) => wave !== selected),
            preferred,
        ),
        undefined,
    );
});

test("manual comparison uses boundaries and standalone cases retain the existing default", () => {
    const { sample, results } = cases[0];
    const first = results[0].waves.find((wave) => wave.scale === "large")!;
    assert.equal(resolveLabWave(sample, results[0].waves, null), first);
    const manual = waveBoundary(sample, first)!;
    assert.equal(resolveLabWave(sample, results[0].waves, manual), first);
    assert.equal(
        resolveLabWave(sample, [{ ...first, peak: first.peak + 1 }], manual),
        undefined,
    );
    assert.equal(
        waveBoundary(sample, { ...first, end: sample.points.length }),
        null,
    );
});

test("saved launch matching requires its date and full range, with no first-candidate fallback", () => {
    const { sample, results } = cases[0];
    const candidate = results[0].launches[0];
    assert.ok(candidate);
    const preferred = {
        date: sample.points[candidate.index].date,
        rangeFrom: sample.points[candidate.rangeStart].date,
        rangeUntil: sample.points[candidate.rangeEnd].date,
        sourceId: "saved-method",
    };
    assert.equal(
        resolveLabLaunch(sample, results[0].launches, preferred),
        candidate,
    );
    assert.equal(
        resolveLabLaunch(
            sample,
            [{ ...candidate, rangeEnd: candidate.rangeEnd + 1 }],
            preferred,
        ),
        undefined,
    );
    assert.equal(
        resolveLabLaunch(
            sample,
            [{ ...candidate, index: candidate.index + 1 }],
            preferred,
        ),
        undefined,
    );
    assert.equal(
        resolveLabLaunch(
            sample,
            [candidate, { ...candidate, id: "other-method-id" }],
            preferred,
        ),
        undefined,
    );
    assert.equal(
        resolveLabLaunch(sample, results[0].launches, null),
        undefined,
    );
});

test("synthetic selected waves bound both start and launch gains before and after their observed interval", () => {
    for (const { sample, results } of cases) {
        const wave = resolveLabWave(
            sample,
            results[0].waves,
            sample.selectedOpportunity!,
        )!;
        const launch = resolveLabLaunch(
            sample,
            results[0].launches,
            sample.selectedOpportunity!.launch,
        )!;
        assert.ok(wave?.end && launch);
        const expected =
            (sample.points[wave.end].adjusted! /
                sample.points[launch.index].adjusted! -
                1) *
            100;
        assert.equal(
            observationGain(sample, launch.index, wave.end, wave),
            expected,
        );
        assert.equal(
            observationGain(sample, launch.index, wave.end + 1, wave),
            null,
        );
        assert.equal(
            observationGain(sample, wave.start, wave.end + 1, wave),
            null,
        );
        assert.equal(
            observationGain(sample, launch.index, launch.index - 1, wave),
            null,
        );
        assert.equal(
            observationGain(sample, wave.start - 1, wave.peak, wave),
            null,
        );
        assert.equal(
            observationGain(sample, launch.index, wave.start - 1, wave),
            null,
        );
    }
});

test("unfinished and shorter observations retain cutoffs, gaps stay unknown, and standalone launch views remain independent", () => {
    const { sample, results } = cases[0];
    const wave = resolveLabWave(
        sample,
        results[0].waves,
        sample.selectedOpportunity!,
    )!;
    const launch = resolveLabLaunch(
        sample,
        results[0].launches,
        sample.selectedOpportunity!.launch,
    )!;
    const unfinished = { ...wave, end: null, observedThrough: wave.peak };
    assert.equal(
        observationGain(sample, launch.index, wave.peak + 1, unfinished),
        null,
    );
    assert.equal(
        observationGain(sample, launch.index, wave.peak + 1, {
            ...wave,
            observedThrough: wave.peak,
        }),
        null,
    );
    assert.equal(
        observationGain(sample, launch.index, wave.end! + 1),
        (sample.points[wave.end! + 1].adjusted! /
            sample.points[launch.index].adjusted! -
            1) *
            100,
    );
    const gap = structuredClone(sample);
    gap.points[wave.peak].flags = ["missing-action-factor"];
    assert.equal(observationGain(gap, launch.index, wave.end!, wave), null);
});
