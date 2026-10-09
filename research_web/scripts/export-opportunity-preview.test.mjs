import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { gzipSync } from "node:zlib";
import { test } from "node:test";
import {
    adaptPreview,
    exportOpportunityPreview,
} from "./export-opportunity-preview.mts";
import {
    buildMarketView,
    validateBundle,
} from "../src/domain/opportunities/model.ts";

const days = Array.from({ length: 8 }, (_, i) => `2020-01-0${i + 1}`);
const identity = {
    inputPath: "D:\\preview folder\\preview.json.gz",
    inputHash: "a".repeat(64),
    jsonHash: "b".repeat(64),
    selectionsPath: "D:\\preview folder\\selections.json",
    selectionsHash: "c".repeat(64),
};
const methodId = (caseId) => JSON.stringify([caseId, "segments", "balanced"]);
const waveId = (caseId) => `${methodId(caseId)}:wave:w`;
const launchId = (caseId) => `${methodId(caseId)}:launch:l`;
const selection = [
    { wave_id: waveId("case-A"), launch_id: launchId("case-A") },
];

function fixture() {
    const preview = {
        schema: "opportunity-catalog.preview.v1",
        mode: "retrospective_preview",
        identities: {
            code_commit: "a".repeat(9),
            code_hashes: { "analysis.ts": "d".repeat(64) },
            input_hash: "e".repeat(64),
            projection_hash: "f".repeat(64),
            catalog_hash: "1".repeat(64),
            input_sha256: "2".repeat(64),
            input_identity_basis: "file_bytes",
            scope: "Fixed case fixture",
            classification_sha256: "3".repeat(64),
            classification_source_ref: "Snapshot evidence",
        },
        limitations: ["Fixture is retrospective"],
        series: [],
        methods: [],
        waves: [],
        phases: [],
        launches: [],
        relations: [],
        quality_events: [],
        comparison_status: {
            holdings: "not_supplied",
            allocations: "not_supplied",
            metric_definitions: "not_supplied",
        },
    };
    for (const [caseId, security, kind, prices, withWave] of [
        [
            "case-A",
            "TW:1234",
            "historical",
            [100, 120, 160, 180, 140, 130],
            true,
        ],
        [
            "case-B",
            "TW:5678",
            "historical",
            [10, 10, 10, 10, 10, 10, 10, 10],
            false,
        ],
        [
            "synthetic-case",
            "SYNTHETIC:synthetic-case",
            "synthetic",
            [100, 120, 160, 180, 140, 130],
            true,
        ],
    ]) {
        const points = prices.map((price, i) => ({
            date: days[i],
            raw: price / 2,
            adjusted: price,
            flags: [],
        }));
        preview.series.push({
            case_id: caseId,
            security_id: security,
            name: caseId,
            kind,
            category: "inspection-only",
            start_date: days[0],
            observed_through: days[prices.length - 1],
            points,
            source: {
                label: "Recorded test source",
                priceBasis: "adjusted close, no reinvestment",
                from: days[0],
                to: days[prices.length - 1],
                limitations: ["Bounded fixture"],
                ...(kind === "historical"
                    ? {
                          hash: preview.identities.projection_hash,
                          catalogHash: preview.identities.catalog_hash,
                      }
                    : {}),
            },
            historical_industry: null,
            historical_unknown_reason: "historical_effective_period_unverified",
            snapshot_industry: {
                code: "test",
                label: "Snapshot industry",
                source_ref: "snapshot-file",
            },
            snapshot_industry_status: "snapshot_only",
        });
        if (!withWave) continue;
        const method = methodId(caseId);
        preview.methods.push({
            method_id: method,
            case_id: caseId,
            source_method: "segments",
            scale: "balanced",
            rule_version: "exploratory.v1",
            diagnostics: {
                converged: true,
                iterations: 0,
                noise: 0.1,
                penalty: 0.2,
            },
            warnings: [],
            fit: [...prices],
            numerically_valid: true,
            acceptance: "exploratory",
        });
        preview.waves.push({
            wave_id: waveId(caseId),
            case_id: caseId,
            security_id: security,
            method_id: method,
            source_id: "w",
            start_date: days[0],
            peak_date: days[3],
            end_confirmed_at: days[4],
            end_unknown_reason: null,
            observed_through: days[4],
            scale: "large",
            left_censored: true,
            right_censored: false,
            parent_wave_id: null,
            peak_gain_percent: 80,
            max_drawdown_percent: -22.2,
            left_boundary_reason: "source_boundary_reason_unexported",
            quality_run_id: null,
            quality_run_unknown_reason:
                "source_quality_run_boundaries_unexported",
        });
        preview.phases.push({
            phase_id: `${method}:phase:0`,
            case_id: caseId,
            method_id: method,
            start_date: days[0],
            end_date: days[3],
            log_slope_per_quote_interval: -0.1,
            source_label: "falling",
        });
        preview.phases.push({
            phase_id: `${method}:phase:1`,
            case_id: caseId,
            method_id: method,
            start_date: days[3],
            end_date: days[5],
            log_slope_per_quote_interval: 0,
            source_label: "flat",
        });
        preview.launches.push({
            launch_id: launchId(caseId),
            source_id: "l",
            method_id: method,
            case_id: caseId,
            security_id: security,
            candidate_date: days[1],
            range_first_date: days[1],
            range_last_date: days[2],
            ensuing_end_date: days[3],
            source_kind: "breakout",
            outcome: "continued",
            pre_slope: 0.01,
            post_slope: 0.1,
            support: 1,
            sustain_sessions: 2,
            relative_strength: 0.3,
            gain_percent: 50,
            drawdown_percent: -5,
        });
        preview.relations.push({
            kind: "candidate_in_wave",
            wave_id: waveId(caseId),
            launch_id: launchId(caseId),
            provisional: false,
        });
    }
    return preview;
}

test("historical filter preserves all cases, including no-wave security, identities, adjusted prices and unknown industry", () => {
    const input = fixture();
    const original = structuredClone(input);
    const bundle = validateBundle(adaptPreview(input, selection, identity));
    assert.deepEqual(input, original);
    assert.equal(bundle.kind, "historical-preview");
    assert.deepEqual(
        bundle.securities.map((security) => security.id),
        ["TW:1234", "TW:5678"],
    );
    assert.equal(bundle.waves.length, 1);
    assert.equal(bundle.representatives.length, 1);
    assert.deepEqual(bundle.portfolios, []);
    assert.deepEqual(bundle.dates, days);
    assert.equal(bundle.securities[0].prices[2].close, 160);
    assert.equal(bundle.securities[0].prices[2].raw, 80);
    assert.equal(bundle.securities[0].industry[0].basis, "unknown");
    assert.equal(
        buildMarketView(bundle, days[2]).active[0].industry.id,
        "unknown",
    );
    assert.equal(buildMarketView(bundle, days[2]).active[0].phase, null);
    assert.deepEqual(bundle.waves[0].phases, []);
    assert.ok(
        bundle.limitations.some(
            (value) =>
                value.includes("TW:5678") && value.includes("未製造波段"),
        ),
    );
    assert.ok(
        bundle.limitations.some(
            (value) =>
                value.includes("historical") && value.includes("其他 1 個"),
        ),
    );
    assert.equal(
        bundle.sources.find((source) => source.id === "preview-file").hash,
        identity.inputHash,
    );
    assert.equal(
        bundle.sources.find((source) => source.id === "preview-json").hash,
        identity.jsonHash,
    );
    assert.equal(
        bundle.sources.find((source) => source.id === "presentation-selections")
            .hash,
        identity.selectionsHash,
    );
    assert.equal(
        bundle.sources.find(
            (source) => source.id === "producer:projection_hash",
        ).hash,
        input.identities.projection_hash,
    );
    assert.equal(bundle.ruleVersion, "exploratory.v1");
    assert.match(bundle.selectionPolicy, new RegExp(identity.selectionsHash));
});

test("selected launches require their exact non-provisional source wave relation", () => {
    for (const provisional of [null, true]) {
        const input = fixture();
        const relation = input.relations.find(
            (entry) => entry.wave_id === waveId("case-A"),
        );
        if (provisional === null)
            input.relations = input.relations.filter(
                (entry) => entry !== relation,
            );
        else relation.provisional = provisional;
        const original = structuredClone(input);
        assert.throws(
            () => adaptPreview(input, selection, identity),
            /selected launch requires a non-provisional source wave relation/,
        );
        assert.deepEqual(input, original);
        assert.doesNotThrow(() =>
            adaptPreview(
                input,
                [{ wave_id: waveId("case-A"), launch_id: null }],
                identity,
            ),
        );
    }
});

test("snapshot labels and observation times retain per-case source bindings without historical membership", () => {
    const input = fixture();
    const snapshot = input.series[0].snapshot_industry;
    snapshot.label = "Shipping snapshot";
    snapshot.metadata_fetched_at = "2026-07-13T17:54:57+00:00";
    snapshot.source_ref = "catalog:sha256:fixture#securities/TW:1234";
    input.series[1].snapshot_industry.source_ref =
        "catalog:sha256:fixture#securities/TW:5678";
    const before = structuredClone(input);
    const bundle = validateBundle(adaptPreview(input, selection, identity));
    assert.deepEqual(input, before);
    assert.deepEqual(bundle.securities[0].classificationSnapshot, {
        label: snapshot.label,
        observedAt: snapshot.metadata_fetched_at,
        sourceId: "snapshot-classification:case-A",
    });
    assert.equal(bundle.securities[1].classificationSnapshot.observedAt, null);
    for (const [index, security] of bundle.securities.entries()) {
        const source = bundle.sources.find(
            (entry) => entry.id === security.classificationSnapshot.sourceId,
        );
        assert.equal(
            source.path,
            input.series[index].snapshot_industry.source_ref,
        );
        assert.equal(source.hash, input.identities.classification_sha256);
        assert.equal(security.industry[0].basis, "unknown");
    }
    assert.equal(buildMarketView(bundle, days[2]).industries[0].id, "unknown");
    input.series[1].snapshot_industry = null;
    const absent = adaptPreview(input, selection, identity);
    assert.equal(absent.securities[1].classificationSnapshot, undefined);
    assert.ok(
        !absent.sources.some(
            (source) => source.id === "snapshot-classification:case-B",
        ),
    );
    input.series[0].snapshot_industry.metadata_fetched_at = 2026;
    assert.throws(
        () => adaptPreview(input, selection, identity),
        /metadata_fetched_at/,
    );
});

test("fixed representative interval retains confirmed end after case cutoff; unfinished cutoff remains unknown", () => {
    const input = fixture();
    let bundle = adaptPreview(input, selection, identity);
    assert.deepEqual(bundle.representatives[0], {
        securityId: "TW:1234",
        waveId: waveId("case-A"),
        from: days[0],
        untilExclusive: "2020-01-09",
    });
    let row = buildMarketView(bundle, days[7]).ended[0];
    assert.equal(row.gain, null);
    assert.ok(Math.abs(row.endGain - 40) < 1e-10);
    assert.ok(
        bundle.limitations.some((value) => value.includes("project_day")),
    );
    input.waves[0].end_confirmed_at = null;
    input.waves[0].end_unknown_reason = "not_confirmed_within_observation";
    input.waves[0].right_censored = true;
    input.waves[0].observed_through = days[3];
    bundle = adaptPreview(input, selection, identity);
    assert.equal(buildMarketView(bundle, days[3]).active.length, 1);
    row = buildMarketView(bundle, days[4]).unknown[0];
    assert.equal(row.reason, "after-observed-through");
    assert.equal(
        buildMarketView(bundle, days[7]).unknown[0].reason,
        "after-observed-through",
    );
});

test("explicit null launch stays unlaunched and no selection never silently chooses a wave", () => {
    const noLaunch = adaptPreview(
        fixture(),
        [{ wave_id: waveId("case-A"), launch_id: null }],
        identity,
    );
    assert.equal(buildMarketView(noLaunch, days[2]).unlaunched.length, 1);
    const unselected = adaptPreview(fixture(), [], identity);
    assert.equal(unselected.representatives.length, 0);
    assert.equal(buildMarketView(unselected, days[2]).active.length, 0);
    assert.equal(
        buildMarketView(unselected, days[2]).unknown[0].reason,
        "missing-representative-interval",
    );
    assert.ok(
        unselected.limitations.some((value) =>
            value.includes("未指定代表波段"),
        ),
    );
});

test("synthetic preview preserves the recorded peak and rejects a consistent but false start-day peak", () => {
    const input = fixture();
    const selections = structuredClone(selection);
    const selected = selections[0];
    const wave = input.waves.find((wave) => wave.wave_id === selected.wave_id);
    assert.equal(wave.start_date, days[0]);
    assert.equal(wave.peak_date, days[3]);
    const before = structuredClone(input);
    const bundle = adaptPreview(input, selections, identity);
    assert.equal(
        bundle.waves.find((row) => row.id === wave.wave_id).peakDate,
        wave.peak_date,
    );
    assert.deepEqual(input, before);
    wave.peak_date = wave.start_date;
    wave.peak_gain_percent = 0;
    assert.throws(
        () => adaptPreview(input, selections, identity),
        /wave peak is not an interval maximum/,
    );
});

test("each observed maximum date is valid and prices beyond the wave cutoff cannot replace it", () => {
    const input = fixture();
    input.series[0].points[2].adjusted = 180;
    input.series[0].points[2].raw = 90;
    input.series[0].points[5].adjusted = 1000;
    for (const peak of [days[2], days[3]]) {
        input.waves[0].peak_date = peak;
        const bundle = adaptPreview(input, selection, identity);
        assert.equal(bundle.waves[0].peakDate, peak);
    }
});

test("wave peaks cannot rely on missing, flagged or dated-quality prices anywhere in their interval", () => {
    for (const index of [0, 1, 3, 4]) {
        for (const problem of ["missing", "point-flag", "quality-event"]) {
            const input = fixture();
            if (problem === "missing")
                input.series[0].points[index].adjusted = null;
            if (problem === "point-flag")
                input.series[0].points[index].flags = ["untrusted"];
            if (problem === "quality-event")
                input.quality_events.push({
                    case_id: "case-A",
                    security_id: "TW:1234",
                    date: days[index],
                    flags: ["untrusted"],
                });
            assert.throws(
                () => adaptPreview(input, selection, identity),
                /Invalid opportunity preview/,
            );
        }
    }
});

test("quality outside waves is retained and method nonconvergence still preserves unknown", () => {
    const input = fixture();
    input.series[0].points[5].flags = ["original-flag"];
    input.quality_events.push({
        case_id: "case-A",
        security_id: "TW:1234",
        date: days[5],
        flags: ["dated-quality"],
    });
    let bundle = adaptPreview(input, selection, identity);
    assert.deepEqual(bundle.securities[0].prices[5].flags, [
        "original-flag",
        "dated-quality",
    ]);
    input.series[1].points[1].adjusted = 0;
    bundle = adaptPreview(input, selection, identity);
    assert.equal(bundle.securities[1].prices[1].close, null);
    assert.ok(
        bundle.securities[1].prices[1].flags.includes(
            "missing_or_invalid_adjusted_quote",
        ),
    );
    const nonconverged = fixture();
    nonconverged.methods[0].numerically_valid = false;
    nonconverged.methods[0].diagnostics.converged = false;
    bundle = adaptPreview(nonconverged, selection, identity);
    assert.equal(buildMarketView(bundle, days[2]).unknown.length, 1);
    assert.ok(
        bundle.securities[0].prices.every((point) =>
            point.flags.some((flag) =>
                flag.startsWith("method-not-converged:"),
            ),
        ),
    );
});

test("synthetic export is explicitly selected and excluded-kind choices are rejected", () => {
    const syntheticSelection = [
        {
            wave_id: waveId("synthetic-case"),
            launch_id: launchId("synthetic-case"),
        },
    ];
    const bundle = adaptPreview(
        fixture(),
        syntheticSelection,
        identity,
        "synthetic",
    );
    assert.equal(bundle.kind, "synthetic");
    assert.equal(bundle.securities.length, 1);
    assert.equal(bundle.securities[0].id, "SYNTHETIC:synthetic-case");
    assert.throws(
        () => adaptPreview(fixture(), syntheticSelection, identity),
        /excluded case kind/,
    );
    assert.throws(
        () => adaptPreview(fixture(), selection, identity, "synthetic"),
        /excluded case kind/,
    );
});

test("malformed dates, identity mismatches, cross-scope selections and unreliable historical claims fail", () => {
    const mutations = [
        (input) => {
            input.series[0].points[1].date = "2020-02-30";
        },
        (input) => {
            input.series[0].points[1].date = days[0];
        },
        (input) => {
            input.series[0].source.to = days[7];
        },
        (input) => {
            input.series[0].source.hash = "0".repeat(64);
        },
        (input) => {
            input.identities.code_hashes["analysis.ts"] = "not-a-hash";
        },
        (input) => {
            input.waves[0].peak_gain_percent = 0.8;
        },
        (input) => {
            input.waves[0].observed_through = days[7];
        },
        (input) => {
            input.launches[0].method_id = methodId("synthetic-case");
        },
        (input) => {
            input.series[0].historical_industry = {
                label: "fabricated historical",
            };
        },
        (input) => {
            input.series[0].snapshot_industry.effective_from = days[0];
        },
        (input) => {
            input.methods[0].diagnostics.converged = false;
        },
        (input) => {
            input.series[0].points[2].adjusted = Infinity;
        },
        (input) => {
            input.series.push(structuredClone(input.series[0]));
        },
        (input) => {
            input.quality_events.push({
                case_id: "case-A",
                security_id: "TW:1234",
                date: days[7],
                flags: ["flag"],
            });
        },
    ];
    for (const mutate of mutations) {
        const input = fixture();
        mutate(input);
        assert.throws(
            () => adaptPreview(input, selection, identity),
            /Invalid opportunity preview/,
        );
    }
    for (const choices of [
        [...selection, ...selection],
        [{ wave_id: waveId("case-A") }],
        [{ wave_id: "absent", launch_id: null }],
        [{ wave_id: waveId("case-A"), launch_id: launchId("synthetic-case") }],
    ])
        assert.throws(
            () => adaptPreview(fixture(), choices, identity),
            /Invalid opportunity preview/,
        );
});

test("CLI reads gzip and Windows path spaces, binds exact bytes, requires selection file, and refuses overwrites", async () => {
    const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
    const scratch = join(root, ".tmp");
    await mkdir(scratch, { recursive: true });
    const directory = await mkdtemp(join(scratch, "preview adapter "));
    const input = join(directory, "source preview.json.gz");
    const selections = join(directory, "explicit selections.json");
    const output = join(directory, "adapted bundle.json");
    const script = fileURLToPath(
        new URL("./export-opportunity-preview.mts", import.meta.url),
    );
    const source = fixture();
    source.series[0].source.reportPath =
        "never-read-or-execute-this $(throw 'not executable')";
    const json = Buffer.from(JSON.stringify(source));
    const bytes = gzipSync(json);
    const choices = Buffer.from(`\uFEFF${JSON.stringify(selection)}`);
    try {
        await writeFile(input, bytes);
        await writeFile(selections, choices);
        const result = spawnSync(
            process.execPath,
            [
                "--experimental-strip-types",
                script,
                "--input",
                input,
                "--selections",
                selections,
                "--output",
                output,
                "--kind",
                "historical",
            ],
            { encoding: "utf8" },
        );
        assert.equal(result.status, 0, result.stderr);
        const bundle = validateBundle(
            JSON.parse(await readFile(output, "utf8")),
        );
        assert.equal(
            bundle.sources.find((entry) => entry.id === "preview-file").hash,
            createHash("sha256").update(bytes).digest("hex"),
        );
        assert.equal(
            bundle.sources.find((entry) => entry.id === "preview-json").hash,
            createHash("sha256").update(json).digest("hex"),
        );
        assert.equal(
            bundle.sources.find(
                (entry) => entry.id === "presentation-selections",
            ).hash,
            createHash("sha256").update(choices).digest("hex"),
        );
        assert.equal(JSON.parse(result.stdout).securities, 2);
        const before = await readFile(output);
        await assert.rejects(
            exportOpportunityPreview(input, selections, output),
            /EEXIST|already exists/,
        );
        assert.deepEqual(await readFile(output), before);
        await assert.rejects(
            exportOpportunityPreview(input, selections, input),
            /EEXIST|already exists/,
        );
        assert.deepEqual(await readFile(input), bytes);
        await assert.rejects(
            exportOpportunityPreview(input, selections, selections),
            /EEXIST|already exists/,
        );
        assert.deepEqual(await readFile(selections), choices);
        const missingSelections = spawnSync(
            process.execPath,
            [
                "--experimental-strip-types",
                script,
                "--input",
                input,
                "--output",
                join(directory, "missing.json"),
            ],
            { encoding: "utf8" },
        );
        assert.notEqual(missingSelections.status, 0);
        assert.match(missingSelections.stderr, /Usage/);
        const plain = join(directory, "plain preview.json");
        await writeFile(plain, json);
        const plainBundle = await exportOpportunityPreview(
            plain,
            selections,
            join(directory, "plain output.json"),
        );
        assert.deepEqual(plainBundle.securities, bundle.securities);
    } finally {
        await rm(directory, { recursive: true, force: true });
    }
});
