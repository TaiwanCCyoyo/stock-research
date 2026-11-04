import assert from "node:assert/strict";
import { test } from "node:test";
import {
    matchWaveDetail,
    matchWaveFrame,
    readWaveContext,
    readWaveDetail,
    waveContext,
    waveHref,
    type WaveContext,
} from "./stockJourney.ts";
import {
    HISTORY_SCHEMA,
    type HistoryDetail,
    type HistoryFrame,
    type HistoryMetadata,
    type HistoryRow,
} from "./types.ts";

const metadata: HistoryMetadata = {
    schema: HISTORY_SCHEMA,
    catalogId: "catalog-abc",
    dates: ["2020-01-02", "2020-01-03", "2020-01-06"],
    coverage: { stocks: 1, excluded: 0, from: "2020-01-02", to: "2020-01-06" },
    limitations: [],
    basisLabel: "adjusted-v1",
    ruleLabel: "saved",
};
const row: HistoryRow = {
    securityKey: "s_a%/?:#漢字",
    securityId: "sec-internal",
    code: "SYNTH",
    name: "Synthetic",
    seriesId: "series-1",
    waveId: "wave-1",
    start: "2020-01-02",
    peakDate: "2020-01-03",
    endConfirmedAt: null,
    observedThrough: "2020-01-06",
    leftCensored: false,
    rightCensored: true,
    scale: "large",
    gain: 12,
    peakGain: 20,
    raw: 10,
    adjusted: 10,
    reason: null,
    industry: {
        id: "unknown",
        label: "Unknown",
        basis: "unknown",
        snapshotAt: null,
    },
    earliestCandidateId: null,
    phase: null,
};
const frame: HistoryFrame = {
    schema: HISTORY_SCHEMA,
    catalogId: metadata.catalogId,
    date: "2020-01-03",
    rows: [row],
};
const sample = {
    source: {
        catalogHash: metadata.catalogId,
        priceBasis: "adjusted-v1",
        hash: "synthetic-hash",
    },
    points: ["2020-01-02", "2020-01-03", "2020-01-06"].map((date, i) => ({
        date,
        adjusted: 10 + i,
    })),
};
const detail: HistoryDetail = {
    schema: HISTORY_SCHEMA,
    catalogId: metadata.catalogId,
    date: frame.date,
    row,
    sample: sample as HistoryDetail["sample"],
    results: [],
    evidence: {},
};
const ctx: WaveContext = waveContext(metadata, frame, row, "catalog", 100);

test("opaque producer key with special characters round trips stock and market links", () => {
    for (const target of ["stock", "market"] as const) {
        const hash = waveHref(ctx, target);
        assert.deepEqual(readWaveContext(hash), ctx);
        const refreshed = waveHref(readWaveContext(hash)!, target);
        assert.deepEqual(readWaveContext(refreshed), ctx);
    }
    assert.equal(readWaveContext("#market"), null);
});

test("rejects duplicate/unknown query params, malformed context and invalid dates", () => {
    const hash = waveHref(ctx, "market");
    assert.throws(() => readWaveContext(`${hash}&other=1`));
    assert.throws(() =>
        readWaveContext(
            `${hash}&wave=${encodeURIComponent(JSON.stringify(ctx))}`,
        ),
    );
    assert.throws(() =>
        readWaveContext(
            `#market?wave=${encodeURIComponent(JSON.stringify({ ...ctx, date: "2020-02-30" }))}`,
        ),
    );
    assert.throws(() =>
        readWaveContext(
            `#market?wave=${encodeURIComponent(JSON.stringify({ ...ctx, threshold: 90 }))}`,
        ),
    );
    assert.throws(() =>
        readWaveContext(
            `#stock/securityId?wave=${encodeURIComponent(JSON.stringify(ctx))}`,
        ),
    );
});

test("missing producer key prevents creating a wave context", () => {
    const { securityKey: _ignored, ...withoutKey } = row;
    assert.throws(() =>
        waveContext(metadata, frame, withoutKey, "catalog", 100),
    );
});

test("frame verification rejects catalog/date/member/series/wave/basis mismatches and duplicate rows", () => {
    const variants: Array<[HistoryMetadata, HistoryFrame, WaveContext]> = [
        [metadata, { ...frame, catalogId: "other" }, ctx],
        [metadata, { ...frame, date: "2020-01-02" }, ctx],
        [metadata, { ...frame, rows: [{ ...row, securityKey: "other" }] }, ctx],
        [metadata, { ...frame, rows: [{ ...row, seriesId: "other" }] }, ctx],
        [metadata, { ...frame, rows: [{ ...row, waveId: "other" }] }, ctx],
        [{ ...metadata, basisLabel: "raw" }, frame, ctx],
        [metadata, { ...frame, rows: [row, row] }, ctx],
    ];
    for (const [m, f, c] of variants)
        assert.throws(() => matchWaveFrame(c, m, f));
});

test("detail verification rejects identity, provenance, and missing price points", () => {
    for (const d of [
        { ...detail, catalogId: "other" },
        { ...detail, row: { ...row, securityId: "other" } },
        { ...detail, row: { ...row, waveId: "other" } },
        {
            ...detail,
            sample: {
                ...sample,
                source: { ...sample.source, priceBasis: "raw" },
            },
        },
        {
            ...detail,
            sample: {
                ...sample,
                points: [{ date: "2020-01-02", adjusted: null }],
            },
        },
    ])
        assert.throws(() => matchWaveDetail(ctx, d as HistoryDetail));
});

test("reader uses only verified frame code and stops before prices on version mismatch", async () => {
    const calls: string[] = [];
    const reader = async <T>(path: string) => {
        calls.push(path);
        if (path === "/metadata") return metadata as T;
        if (path.startsWith("/frame")) return frame as T;
        return detail as T;
    };
    await readWaveDetail(ctx, new AbortController().signal, reader);
    assert.equal(calls[2], "/security/SYNTH?date=2020-01-03");
    calls.length = 0;
    await assert.rejects(
        readWaveDetail(
            { ...ctx, catalogId: "stale" },
            new AbortController().signal,
            reader,
        ),
    );
    assert.deepEqual(calls, ["/metadata"]);
});

test("aborted stale read stops before the next request", async () => {
    const controller = new AbortController();
    const reader = async <T>(path: string) => {
        if (path === "/metadata") controller.abort();
        return metadata as T;
    };
    await assert.rejects(readWaveDetail(ctx, controller.signal, reader));
});
