import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { gzipSync, gunzipSync } from "node:zlib";
import {
    analyzeCase,
    analyzeComparisons,
} from "../../tasks/20261004-sector-wave-full-history-preview/method-snapshot/analysis.ts";
import {
    analyzeSeries,
    buildLabCase,
    codeIdentity,
    deriveSupportRecords,
    sourceRunIndices,
    SCALES,
    SOURCE_HASHES,
} from "../opportunity_history_methods.mjs";

const fixture = (values) => ({
    series: {
        schema: "opportunity-series.v1",
        security_id: "synthetic:A",
        code: "A",
        name: "Fixture",
        cohort: "synthetic",
        instrument_role: "stock",
        series_id: "series:A",
        calendar_id: "calendar:A",
        raw: [...values],
        adjusted: [...values],
        numeric_flags: {},
        coverage_caveats: ["retrospective"],
    },
    calendar: {
        calendar_id: "calendar:A",
        dates: values.map((_, index) => `D${String(index).padStart(4, "0")}`),
    },
});
const curve = Array.from(
    { length: 100 },
    (_, i) =>
        100 *
        Math.exp(
            i < 25
                ? -i * 0.004
                : i < 55
                  ? -0.1 + (i - 25) * 0.018
                  : i < 80
                    ? 0.44 + (i - 55) * 0.001
                    : 0.465 - (i - 80) * 0.01,
        ),
);

test("six exact native invocations stay unchanged; separate support equals legacy comparisons at all scales", () => {
    const { series, calendar } = fixture(curve);
    const input = buildLabCase(series, calendar);
    const before = structuredClone(series);
    const returned = [];
    const saved = [];
    const output = analyzeSeries(series, calendar, {
        analyze: (lab, method, scale) => {
            const result = analyzeCase(lab, method, scale);
            returned.push(result);
            saved.push(structuredClone(result));
            return result;
        },
    });
    assert.equal(returned.length, 6);
    assert.deepEqual(series, before);
    assert.deepEqual(returned, saved);
    assert.ok(output.native.every((record) => record.status === "ok"));
    assert.ok(output.support_records.length > 0);
    for (let i = 0; i < 6; i++)
        assert.strictEqual(output.native[i].result, returned[i]);
    for (const scale of SCALES) {
        const legacy = analyzeComparisons(input, scale);
        for (const result of legacy) {
            for (const launch of result.launches) {
                const support = output.support_records.find(
                    (record) =>
                        record.method === result.method &&
                        record.scale === scale &&
                        record.candidate_id === launch.id,
                );
                assert.deepEqual(
                    [support.support, support.rangeStart, support.rangeEnd],
                    [launch.support, launch.rangeStart, launch.rangeEnd],
                );
            }
        }
        const native = output.native.filter((record) => record.scale === scale);
        assert.deepEqual(native[0].result.waves, native[1].result.waves);
    }
});

test("nulls and point flags keep global indices; caveats do not block; large jump keeps both quotes", () => {
    const { series, calendar } = fixture([
        100,
        101,
        null,
        110,
        111,
        160,
        161,
        162,
    ]);
    series.numeric_flags = { 3: ["action barrier"] };
    const lab = buildLabCase(series, calendar);
    assert.equal(lab.points.length, 8);
    assert.equal(lab.points[2].adjusted, null);
    assert.deepEqual(lab.points[3].flags, ["action barrier"]);
    assert.deepEqual(lab.points[4].flags, []);
    assert.deepEqual(lab.source.limitations, ["retrospective"]);
    const output = analyzeSeries(series, calendar);
    assert.deepEqual(output.source_run_indices, [0, 0, null, null, 1, 2, 2, 2]);
    for (const { result } of output.native) {
        assert.equal(result.fit[2], null);
        assert.equal(result.fit[3], null);
        assert.ok(Number.isFinite(result.fit[4]));
        assert.ok(Number.isFinite(result.fit[5]));
        assert.ok(result.segments.some((segment) => segment.start === 5));
    }
    const singletons = fixture([100, null, 160]);
    const singletonOutput = analyzeSeries(
        singletons.series,
        singletons.calendar,
    );
    assert.deepEqual(
        singletonOutput.native[0].result.segments.map((segment) => [
            segment.start,
            segment.end,
        ]),
        [
            [0, 0],
            [2, 2],
        ],
    );
    assert.throws(
        () => buildLabCase(series, { ...calendar, calendar_id: "other" }),
        /identity mismatch/,
    );
    assert.throws(
        () => buildLabCase(series, { ...calendar, dates: [] }),
        /aligned/,
    );
});

test("source run indices use the pinned log-difference boundary, preserving null and flagged slots", () => {
    const { series, calendar } = fixture([4, 5.4, null, 6, 7, 8, 0, 9]);
    series.numeric_flags = { 4: ["barrier"] };
    const lab = buildLabCase(series, calendar);
    const before = structuredClone(lab);
    assert.equal(Math.log(5.4 / 4), Math.log(1.35));
    assert.ok(Math.log(5.4) - Math.log(4) > Math.log(1.35));
    assert.deepEqual(sourceRunIndices(lab), [0, 1, null, 2, null, 3, null, 4]);
    assert.deepEqual(lab, before);
    const output = analyzeSeries(series, calendar);
    assert.deepEqual(output.source_run_indices, [
        0,
        1,
        null,
        2,
        null,
        3,
        null,
        4,
    ]);
    assert.ok(
        output.native.every(
            ({ result }) =>
                Number.isFinite(result.fit[0]) &&
                Number.isFinite(result.fit[1]),
        ),
    );
});

const launch = (id, index, outcome = "unresolved", kind = "breakout") => ({
    id,
    index,
    rangeStart: index,
    rangeEnd: index + 8,
    forwardEnd: index + 8,
    kind,
    outcome,
    support: 1,
});
test("support uses kind and nearest original order, across run/outcome, retaining failed and unlinked candidates", () => {
    const native = SCALES.map((scale, i) => ({
        method: "segments",
        scale,
        status: "ok",
        result: {
            launches:
                i === 0
                    ? [launch("target", 30, "failed")]
                    : i === 1
                      ? [
                            launch("first-tie", 25),
                            launch("second-tie", 35),
                            launch("wrong-kind", 30, "continued", "reversal"),
                        ]
                      : [launch("radius", 50), launch("outside", 90)],
        },
    }));
    const before = structuredClone(native);
    const records = deriveSupportRecords(native);
    const target = records.find((record) => record.candidate_id === "target");
    assert.deepEqual(
        target.matched_ids.map((match) => match.candidate_id),
        ["target", "first-tie", "radius"],
    );
    assert.deepEqual(
        [target.support, target.rangeStart, target.rangeEnd],
        [3, 25, 50],
    );
    assert.ok(
        records.some(
            (record) =>
                record.candidate_id === "outside" && record.support === 1,
        ),
    );
    assert.equal(records.length, 6);
    assert.deepEqual(native, before);
});

test("nonconvergence remains valid; per-method runtime and nonfinite errors are explicit; empty runs remain successful", () => {
    const { series, calendar } = fixture([100, 101]);
    let calls = 0;
    const output = analyzeSeries(series, calendar, {
        analyze: (input, method, scale) => {
            calls++;
            if (method === "segments" && scale === "fine")
                throw new Error("fixture runtime");
            const result = analyzeCase(input, method, scale);
            if (method === "segments" && scale === "balanced")
                result.fit[0] = Infinity;
            if (method === "filter") result.diagnostics.converged = false;
            return result;
        },
    });
    assert.equal(calls, 6);
    assert.deepEqual(
        output.native.map((record) => record.status),
        ["error", "error", "ok", "ok", "ok", "ok"],
    );
    assert.match(output.native[0].error.message, /fixture runtime/);
    assert.match(output.native[1].error.message, /Nonfinite/);
    assert.equal(output.native[0].result, null);
    assert.equal(output.native[3].result.diagnostics.converged, false);
    const empty = fixture([null, null]);
    const noRuns = analyzeSeries(empty.series, empty.calendar);
    assert.ok(
        noRuns.native.every(
            (record) =>
                record.status === "ok" && record.result.launches.length === 0,
        ),
    );
    assert.deepEqual(noRuns.support_records, []);
});

test("pinned identities and CLI handle paths with spaces, gzip header and overwrite refusal", async () => {
    const identity = await codeIdentity();
    assert.deepEqual(identity.source, SOURCE_HASHES);
    assert.match(identity.wrapper.sha256, /^[a-f0-9]{64}$/);
    const scratch = resolve(
        fileURLToPath(new URL("../../.tmp/", import.meta.url)),
    );
    await mkdir(scratch, { recursive: true });
    const dir = await mkdtemp(join(scratch, "methods test "));
    try {
        const { series, calendar } = fixture([100, 101, 102]);
        const seriesPath = join(dir, "input series.json.gz");
        const calendarPath = join(dir, "calendar file.json");
        const outputPath = join(dir, "native result.json.gz");
        await writeFile(
            seriesPath,
            gzipSync(JSON.stringify(series), { mtime: 0 }),
        );
        await writeFile(calendarPath, JSON.stringify(calendar));
        const command = [
            "--experimental-strip-types",
            fileURLToPath(
                new URL("../opportunity_history_methods.mjs", import.meta.url),
            ),
            "--series",
            seriesPath,
            "--calendar",
            calendarPath,
            "--output",
            outputPath,
        ];
        const first = spawnSync(process.execPath, command, {
            encoding: "utf8",
        });
        assert.equal(first.status, 0, first.stderr);
        assert.equal(JSON.parse(first.stdout).methods, 6);
        const bytes = await readFile(outputPath);
        assert.equal(bytes.readUInt32LE(4), 0);
        const output = JSON.parse(gunzipSync(bytes));
        assert.equal(output.schema, "opportunity-native-results.v1");
        assert.equal(output.native.length, 6);
        assert.ok(!("points" in output) && !("raw" in output));
        const second = spawnSync(process.execPath, command, {
            encoding: "utf8",
        });
        assert.equal(second.status, 1);
        assert.match(second.stderr, /EEXIST/);
        assert.deepEqual(await readFile(outputPath), bytes);
    } finally {
        await rm(dir, { recursive: true });
    }
});
