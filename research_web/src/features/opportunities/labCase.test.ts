import assert from "node:assert/strict";
import { test } from "node:test";
import {
    buildMarketView,
    validateBundle,
} from "../../domain/opportunities/model.ts";
import type { OpportunityBundle } from "../../domain/opportunities/types.ts";
import { analyzeComparisons } from "../wave-lab/analysis.ts";
import { createFeedbackIdentity } from "../wave-lab/feedbackIdentity.ts";
import { toLabCase } from "./labCase.ts";

const CASE_HASH = "a".repeat(64);
const CATALOG_HASH = "b".repeat(64);
const OTHER_CASE_HASH = "c".repeat(64);
function fixture(): OpportunityBundle {
    return {
        schema: "opportunity-explorer.v1",
        id: "fixture",
        label: "Recorded bundle",
        kind: "historical-preview",
        asOf: "2020-01-03",
        dates: ["2020-01-02", "2020-01-03"],
        priceBasis: "adjusted close",
        catalogCoverage: "case-slice",
        ruleVersion: "rules.v1",
        selectionPolicy: "explicit.v1",
        classificationVersion: "unverified",
        sources: [
            {
                id: "case:other-case",
                label: "Another case",
                hash: OTHER_CASE_HASH,
            },
            {
                id: "preview-file",
                label: "Whole preview file",
                hash: "d".repeat(64),
            },
            {
                id: "producer:catalog_hash",
                label: "Original producer catalog",
                hash: CATALOG_HASH,
            },
            {
                id: "case:shared-detail-id",
                label: "This case's price source",
                hash: CASE_HASH,
            },
        ],
        limitations: ["Historical industry is not verified"],
        securities: [
            {
                id: "TW:1234",
                code: "1234",
                name: "Recorded stock",
                market: "TW",
                currency: "TWD",
                detailCaseId: "shared-detail-id",
                industry: [],
                prices: [
                    { date: "2020-01-02", close: 20, raw: 10, flags: [] },
                    { date: "2020-01-03", close: 22, raw: 11, flags: [] },
                ],
            },
        ],
        waves: [
            {
                id: "wave",
                securityId: "TW:1234",
                start: "2020-01-02",
                launch: {
                    date: "2020-01-02",
                    rangeFrom: "2020-01-02",
                    rangeUntil: "2020-01-02",
                    sourceId: "preview-file",
                },
                launchMissingReason: null,
                peakDate: "2020-01-03",
                endConfirmedAt: null,
                observedThrough: "2020-01-03",
                leftCensored: false,
                rightCensored: true,
                scale: "large",
                parentId: null,
                sourceId: "preview-file",
                phases: [],
            },
        ],
        representatives: [
            {
                securityId: "TW:1234",
                waveId: "wave",
                from: "2020-01-02",
                untilExclusive: "2020-01-04",
            },
        ],
        portfolios: [],
    };
}
function convert(bundle: OpportunityBundle) {
    const sample = toLabCase(
        buildMarketView(bundle, "2020-01-03").rows[0],
        bundle,
    );
    assert.ok(sample);
    return sample;
}

test("validated empty-price securities remain in the catalog without a detail case", () => {
    const input = fixture();
    input.securities[0].prices = [];
    const before = structuredClone(input);
    const bundle = validateBundle(input);
    const view = buildMarketView(bundle, "2020-01-03");
    assert.equal(view.rows.length, 1);
    assert.equal(view.rows[0].security.id, "TW:1234");
    assert.equal(view.rows[0].state, "unknown");
    assert.equal(toLabCase(view.rows[0], bundle), null);
    assert.deepEqual(input, before);
});

test("a single recorded price keeps its detail case and uses existing short-series analysis guards", () => {
    const input = fixture();
    input.securities[0].prices = [input.securities[0].prices[0]];
    const sample = convert(validateBundle(input));
    assert.equal(sample.points.length, 1);
    assert.equal(sample.source.from, "2020-01-02");
    assert.equal(sample.source.to, "2020-01-02");
    for (const scale of ["fine", "balanced", "coarse"] as const) {
        const results = analyzeComparisons(sample, scale);
        assert.equal(results.length, 2);
        for (const result of results) {
            assert.equal(result.fit.length, 1);
            assert.ok(Math.abs(result.fit[0]! - 20) < 1e-10);
            assert.equal(result.diagnostics.converged, true);
            assert.deepEqual(result.launches, []);
            assert.deepEqual(result.waves, []);
        }
    }
});

test("detail conversion preserves the selected wave's identity, boundaries and launch evidence without shared mutable state", () => {
    const bundle = fixture();
    const before = structuredClone(bundle);
    const sample = convert(bundle);
    const wave = bundle.waves[0];
    assert.deepEqual(sample.selectedOpportunity, {
        securityId: "TW:1234",
        waveId: wave.id,
        sourceId: wave.sourceId,
        start: wave.start,
        peakDate: wave.peakDate,
        endConfirmedAt: wave.endConfirmedAt,
        observedThrough: wave.observedThrough,
        scale: wave.scale,
        leftCensored: wave.leftCensored,
        rightCensored: wave.rightCensored,
        launch: wave.launch,
    });
    sample.selectedOpportunity!.launch!.rangeFrom = "2020-01-01";
    sample.selectedOpportunity!.start = "2020-01-01";
    assert.deepEqual(bundle, before);
});

test("case and catalog hashes use their exact source ids regardless of source order", () => {
    const bundle = fixture();
    const sample = convert(bundle);
    assert.equal(sample.id, "shared-detail-id");
    assert.equal(sample.source.hash, CASE_HASH);
    assert.equal(sample.source.catalogHash, CATALOG_HASH);
    assert.equal(sample.source.label, "This case's price source");
    assert.notEqual(sample.source.hash, OTHER_CASE_HASH);
    assert.notEqual(sample.source.hash, sample.source.catalogHash);
    bundle.sources.reverse();
    assert.deepEqual(convert(bundle), sample);
    assert.equal(sample.category, "分類待補");
    assert.equal(sample.source.priceBasis, "adjusted close");
});

test("same detailCaseId in a different custom bundle retains its own source and content identity", async () => {
    const first = fixture();
    const next = fixture();
    next.sources.find((source) => source.id === "case:shared-detail-id")!.hash =
        "e".repeat(64);
    next.sources.find((source) => source.id === "producer:catalog_hash")!.hash =
        "f".repeat(64);
    next.securities[0].prices[1].close = 24;
    const firstSample = convert(first);
    const nextSample = convert(next);
    assert.equal(firstSample.id, nextSample.id);
    assert.equal(nextSample.source.hash, "e".repeat(64));
    assert.equal(nextSample.source.catalogHash, "f".repeat(64));
    assert.notEqual(
        await createFeedbackIdentity(firstSample, "rules.v1"),
        await createFeedbackIdentity(nextSample, "rules.v1"),
    );
    assert.equal(convert(first).source.hash, CASE_HASH);
});

test("missing exact case binding never borrows another case, preview or catalog hash", () => {
    const bundle = fixture();
    bundle.sources = bundle.sources.filter(
        (source) => source.id !== "case:shared-detail-id",
    );
    let sample = convert(bundle);
    assert.equal(sample.source.hash, undefined);
    assert.equal(sample.source.catalogHash, CATALOG_HASH);
    assert.match(sample.source.label, /未綁定/);
    assert.ok(
        sample.source.limitations.some((reason) =>
            reason.includes("來源身分未知"),
        ),
    );
    bundle.securities[0].detailCaseId = undefined;
    bundle.sources.push({
        id: "case:TW:1234",
        label: "Unbound name coincidence",
        hash: OTHER_CASE_HASH,
    });
    sample = convert(bundle);
    assert.equal(sample.id, "TW:1234");
    assert.equal(sample.source.hash, undefined);
});

test("missing catalog provenance stays unknown even when the case hash is present", () => {
    const bundle = fixture();
    bundle.sources = bundle.sources.filter(
        (source) => source.id !== "producer:catalog_hash",
    );
    const sample = convert(bundle);
    assert.equal(sample.source.hash, CASE_HASH);
    assert.equal(sample.source.catalogHash, undefined);
    assert.ok(
        sample.source.limitations.some((reason) =>
            reason.includes("目錄身分未知"),
        ),
    );
});

test("source-free custom and synthetic cases preserve prices without invented hashes or input mutation", () => {
    for (const kind of ["historical-preview", "synthetic"] as const) {
        const bundle = fixture();
        bundle.kind = kind;
        bundle.sources = [];
        bundle.securities[0].prices[1].flags = ["source-quality-observation"];
        const before = structuredClone(bundle);
        const sample = convert(bundle);
        assert.equal(
            sample.kind,
            kind === "synthetic" ? "synthetic" : "historical",
        );
        assert.equal(sample.source.hash, undefined);
        assert.equal(sample.source.catalogHash, undefined);
        assert.deepEqual(sample.points[1], {
            date: "2020-01-03",
            raw: 11,
            adjusted: 22,
            flags: ["source-quality-observation"],
        });
        assert.ok(
            sample.source.limitations.some((reason) =>
                reason.includes("來源身分未知"),
            ),
        );
        assert.ok(
            sample.source.limitations.some((reason) =>
                reason.includes("目錄身分未知"),
            ),
        );
        sample.points[1].flags.push("local-only");
        sample.source.limitations.push("local-only");
        assert.deepEqual(bundle, before);
    }
});
