import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
    copyFile,
    mkdtemp,
    writeFile,
    readFile,
    rm,
    mkdir,
} from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { gzipSync, gunzipSync } from "node:zlib";
import { test } from "node:test";
import { applyClassificationEvidence } from "./apply-classification-evidence.mts";
import { buildMarketView } from "../src/domain/opportunities/model.ts";

const hash = (value) => createHash("sha256").update(value).digest("hex");
const identities = Object.fromEntries(
    ["classification", "sources", "receipt", "selections"].map((name, i) => [
        name,
        { path: `${name}.json`, sha256: String(i + 1).repeat(64) },
    ]),
);
function fixture() {
    const ids = ["TW:2609", "TW:2498", "TW:9919"];
    const dates = ["2020-07-23", "2021-07-23", "2022-07-23"];
    const bundle = {
        schema: "opportunity-explorer.v1",
        id: "test",
        label: "test",
        kind: "historical-preview",
        asOf: dates[2],
        dates,
        priceBasis: "close",
        catalogCoverage: "case-slice",
        ruleVersion: "v1",
        selectionPolicy: "explicit",
        classificationVersion: "v1",
        limitations: [],
        sources: [
            {
                id: "producer:catalog_hash",
                hash: "a".repeat(64),
                label: "catalog",
            },
        ],
        securities: ids.map((id) => ({
            id,
            code: id.slice(3),
            name: id,
            market: "TW",
            currency: "TWD",
            industry: [],
            prices: dates.map((date) => ({ date, close: 100, flags: [] })),
        })),
        waves: [],
        representatives: [],
        portfolios: [],
    };
    const reference = (id) => [{ source_id: id, locator: "page 1" }];
    const coverage = {
        from: "2021-01-01",
        until_exclusive: "2022-01-01",
        precision: "fiscal-year",
    };
    const claim = (id, label, source) => ({
        assertion_id: id,
        layer: "business_role",
        label,
        classification_id: id,
        basis: "primary-company-disclosure",
        document_covered_period: coverage,
        temporal_scope: "retrospective-period-summary",
        effective_interval: null,
        published_at: null,
        first_available_at: null,
        source_refs: reference(source),
    });
    const classification = {
        schema_version: "opportunity-classification-evidence.v1",
        catalog_identity: "sector-wave-catalog:sha256:" + "a".repeat(64),
        security_ids: ids,
        securities: ids.map((id, i) => ({
            security_id: id,
            official_industry_snapshot: {
                status: "known",
                label: i === 2 ? "其他業" : "航運業",
                metadata_fetched_at: null,
                effective_interval: null,
                source_refs: reference("catalog"),
            },
            official_value_chain_snapshot: {
                effective_interval: null,
                snapshot_recorded_at: null,
                memberships: [
                    {
                        node_id: "node",
                        label: "node",
                        source_fetched_at: null,
                        source_refs: reference("catalog"),
                    },
                ],
            },
            research_group_snapshot: {
                effective_interval: null,
                groups: [
                    {
                        group_id: "group",
                        label: "group",
                        source_refs: reference("catalog"),
                    },
                ],
            },
            company_business_assertions:
                i === 0
                    ? [claim("shipping", "貨櫃航運", "annual")]
                    : i === 1
                      ? [
                            claim("phone", "智慧手機", "phone"),
                            claim("vr", "虛擬實境", "vr"),
                        ]
                      : [
                            {
                                ...claim("hygiene", "衛生用品", "annual"),
                                document_covered_period: null,
                                temporal_scope: "undated-reference",
                            },
                        ],
        })),
    };
    const sources = {
        schema_version: "opportunity-classification-sources.v1",
        sources: ["catalog", "annual", "phone", "vr"].map((source_id) => ({
            source_id,
            title: source_id,
            url: "https://example.com/report",
            content_digest: {
                algorithm: "sha256",
                basis:
                    source_id === "catalog"
                        ? "raw-file-bytes"
                        : "canonical-retained-observation-json",
                value: "b".repeat(64),
            },
        })),
    };
    const selections = {
        schema: "opportunity-classification-selections.v1",
        selections: [
            {
                securityId: ids[0],
                groupId: "shipping",
                label: "航運／貨櫃航運",
                assertionIds: ["shipping"],
            },
            {
                securityId: ids[1],
                groupId: "devices",
                label: "智慧手機／虛擬實境",
                assertionIds: ["phone", "vr"],
            },
        ],
    };
    return { bundle, classification, sources, selections };
}
const apply = (f) =>
    applyClassificationEvidence(
        f.bundle,
        f.classification,
        f.sources,
        f.selections,
        identities,
    );
test("snapshot and multiple references remain independent; document grouping only covers 2021", () => {
    const f = fixture(),
        before = structuredClone(f),
        result = apply(f);
    assert.deepEqual(f, before);
    for (let i = 0; i < 3; i++)
        assert.deepEqual(
            result.securities[i].prices,
            f.bundle.securities[i].prices,
        );
    for (const key of ["waves", "representatives", "portfolios"])
        assert.deepEqual(result[key], f.bundle[key]);
    assert.equal(result.securities[2].classificationSnapshot.label, "其他業");
    assert.equal(result.securities[2].classificationSnapshot.observedAt, null);
    assert.equal(result.securities[2].industry.length, 0);
    assert.equal(
        result.securities[1].classificationReferences.filter(
            (x) => x.layer === "business-role",
        ).length,
        2,
    );
    const selectedSource = result.sources.find(
        (x) => x.id === result.securities[1].industry[0].sourceId,
    );
    assert.match(selectedSource.label, /phone, vr/);
    assert.match(selectedSource.label, /智慧手機／虛擬實境/);
    assert.match(selectedSource.label, /page 1/);
    assert.equal(selectedSource.url, "https://example.com/report");
    assert.ok(
        result.sources.some((x) =>
            x.label.includes("canonical-retained-observation-json"),
        ),
    );
    // Calendar-independent membership is deliberately bounded by the document year.
    const member = result.securities[0].industry[0];
    for (const [date, expected] of [
        ["2020-07-23", false],
        ["2021-07-23", true],
        ["2022-07-23", false],
    ])
        assert.equal(
            member.from <= date && date < member.untilExclusive,
            expected,
        );
    assert.equal(buildMarketView(result, "2021-07-23").date, "2021-07-23");
    f.sources.sources.find((x) => x.source_id === "vr").url =
        "https://example.com/vr-report";
    const multipleUrls = apply(f);
    assert.equal(
        multipleUrls.sources.find(
            (x) => x.id === multipleUrls.securities[1].industry[0].sourceId,
        ).url,
        undefined,
    );
    assert.equal(
        multipleUrls.securities[1].classificationReferences
            .filter((x) => x.layer === "business-role")
            .flatMap((x) => x.sourceIds).length,
        2,
    );
});
test("overlapping group IDs reject conflicting labels across selected stocks", () => {
    for (const reverse of [false, true]) {
        const f = fixture();
        f.selections.selections[1].groupId = f.selections.selections[0].groupId;
        if (reverse) f.selections.selections.reverse();
        const before = structuredClone(f);
        assert.throws(() => apply(f), /overlapping group label conflict/);
        assert.deepEqual(f, before);
    }
});
test("overlapping group IDs accept matching labels across selections and existing memberships", () => {
    const f = fixture();
    const selection = f.selections.selections[0];
    f.selections.selections[1].groupId = selection.groupId;
    f.selections.selections[1].label = selection.label;
    f.bundle.securities[2].industry.push({
        id: selection.groupId,
        label: selection.label,
        from: "2020-01-01",
        untilExclusive: null,
        basis: "historical",
        sourceId: f.bundle.sources[0].id,
    });
    const result = apply(f);
    for (const security of result.securities) {
        assert.equal(security.industry[0].id, selection.groupId);
        assert.equal(security.industry[0].label, selection.label);
    }
});
test("overlapping group IDs reject conflicting existing membership labels on any stock", () => {
    for (const stockIndex of [0, 2]) {
        const f = fixture();
        f.bundle.securities[stockIndex].industry.push({
            id: f.selections.selections[0].groupId,
            label: "Conflicting existing label",
            from: "2020-01-01",
            untilExclusive: null,
            basis: "historical",
            sourceId: f.bundle.sources[0].id,
        });
        const before = structuredClone(f);
        assert.throws(() => apply(f), /overlapping group label conflict/);
        assert.deepEqual(f, before);
    }
});
test("overlapping group IDs reject conflicting labels already present in the input", () => {
    const f = fixture();
    for (const [index, label] of [
        "First existing label",
        "Second existing label",
    ].entries())
        f.bundle.securities[index].industry.push({
            id: "existing-group",
            label,
            from: "2020-01-01",
            untilExclusive: null,
            basis: "historical",
            sourceId: f.bundle.sources[0].id,
        });
    assert.throws(() => apply(f), /overlapping group label conflict/);
});
test("different group IDs retain identical labels", () => {
    const f = fixture();
    f.selections.selections[1].label = f.selections.selections[0].label;
    const result = apply(f);
    assert.notEqual(
        result.securities[0].industry[0].id,
        result.securities[1].industry[0].id,
    );
    assert.equal(
        result.securities[0].industry[0].label,
        result.securities[1].industry[0].label,
    );
});
test("nonoverlapping group periods allow label changes at exclusive boundaries", () => {
    for (const interval of [
        { from: "2020-01-01", untilExclusive: "2021-01-01" },
        { from: "2022-01-01", untilExclusive: null },
    ]) {
        const f = fixture();
        f.bundle.securities[2].industry.push({
            id: f.selections.selections[0].groupId,
            label: "Other period label",
            ...interval,
            basis: "historical",
            sourceId: f.bundle.sources[0].id,
        });
        const result = apply(f);
        assert.equal(
            result.securities[2].industry[0].label,
            "Other period label",
        );
        assert.equal(
            result.securities[0].industry[0].label,
            f.selections.selections[0].label,
        );
    }
});
test("fail closed for catalog, sources, claims, dates, event evidence, and conflicts", () => {
    const mutations = [
        (f) => (f.classification.catalog_identity = "other"),
        (f) => (f.bundle.sources[0].hash = "c".repeat(64)),
        (f) =>
            (f.classification.catalog_identity =
                "unrecognized:sha256:" + "a".repeat(64)),
        (f) => f.sources.sources.push(f.sources.sources[0]),
        (f) => f.classification.securities.push(f.classification.securities[0]),
        (f) =>
            (f.classification.securities[0].company_business_assertions[0].source_refs[0].source_id =
                "missing"),
        (f) =>
            (f.classification.securities[0].company_business_assertions[0].document_covered_period.from =
                "2021-02-30"),
        (f) =>
            (f.classification.securities[0].company_business_assertions[0].document_covered_period =
                null),
        (f) =>
            delete f.classification.securities[0].company_business_assertions[0]
                .document_covered_period,
        (f) =>
            (f.classification.securities[0].company_business_assertions[0].temporal_scope =
                "retrospective-event-context"),
        (f) =>
            (f.classification.securities[0].company_business_assertions[0].document_covered_period.precision =
                "event-year"),
        (f) => (f.selections.selections[0].assertionIds = ["phone"]),
        (f) => (f.sources.sources[0].content_digest.value = "not-hash"),
        (f) => (f.sources.sources[0].url = "javascript:alert(1)"),
        (f) =>
            f.bundle.securities[0].industry.push({
                id: "existing",
                label: "existing",
                from: "2021-01-01",
                untilExclusive: "2022-01-01",
                basis: "document-period",
                sourceId: f.bundle.sources[0].id,
            }),
    ];
    for (const mutation of mutations) {
        const f = fixture();
        mutation(f);
        assert.throws(() => apply(f));
    }
    const f = fixture();
    f.bundle = apply(f);
    assert.throws(() => apply(f), /collision/);
});
test("preview-export snapshots retain provenance when equal and reject conflicting reconstruction", () => {
    const f = fixture();
    const snapshot = {
        label: "航運業",
        observedAt: null,
        sourceId: f.bundle.sources[0].id,
    };
    f.bundle.securities[0].classificationSnapshot = snapshot;
    f.bundle.securities[0].classificationReferences = [];
    const result = apply(f);
    assert.deepEqual(result.securities[0].classificationSnapshot, snapshot);
    assert.ok(
        result.sources.some(
            (x) => x.hash === "b".repeat(64) && x.label.includes("page 1"),
        ),
    );
    f.bundle.securities[0].classificationSnapshot.label = "other";
    assert.throws(() => apply(f), /existing snapshot conflict/);
    f.bundle.securities[0].classificationSnapshot.label = "航運業";
    f.bundle.securities[0].classificationSnapshot.observedAt =
        "2026-10-04T00:00:00Z";
    assert.throws(() => apply(f), /existing snapshot conflict/);
    const changedSources = structuredClone(identities);
    changedSources.sources.sha256 = "f".repeat(64);
    const base = fixture(),
        other = applyClassificationEvidence(
            base.bundle,
            base.classification,
            base.sources,
            base.selections,
            changedSources,
        );
    assert.notEqual(other.id, apply(base).id);
    assert.notEqual(
        other.classificationVersion,
        apply(base).classificationVersion,
    );
});
test("library identity paths require portable repository-relative locators", () => {
    for (const path of [
        "C:/evidence.json",
        "C:evidence.json",
        "/evidence.json",
        "../evidence.json",
        "folder/../evidence.json",
        "folder\\evidence.json",
        "./evidence.json",
        "folder//evidence.json",
    ]) {
        const f = fixture();
        const bad = structuredClone(identities);
        bad.classification.path = path;
        assert.throws(
            () =>
                applyClassificationEvidence(
                    f.bundle,
                    f.classification,
                    f.sources,
                    f.selections,
                    bad,
                ),
            /repository-relative forward-slash locator/,
        );
    }
    for (const kind of Object.keys(identities)) {
        const f = fixture();
        const bad = structuredClone(identities);
        bad[kind].path = "../escape.json";
        assert.throws(
            () =>
                applyClassificationEvidence(
                    f.bundle,
                    f.classification,
                    f.sources,
                    f.selections,
                    bad,
                ),
            /repository-relative forward-slash locator/,
        );
    }
});
test("CLI output is byte-identical across physical checkouts, cwd, and absolute or relative arguments", async () => {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const dir = await mkdtemp(join(scratch, "classification portable roots "));
    try {
        const f = fixture();
        const classification = JSON.stringify(f.classification);
        const sources = JSON.stringify(f.sources);
        const receipt = {
            schema_version: "opportunity-classification-verification.v1",
            checks: JSON.parse(
                await readFile(
                    "fixtures/classification-v1/verification-receipt.json",
                    "utf8",
                ),
            ).checks,
            files: {
                "classification-v1.json": { raw_sha256: hash(classification) },
                "sources-v1.json": { raw_sha256: hash(sources) },
            },
        };
        const packets = {
            input: JSON.stringify(f.bundle),
            classification,
            sources,
            selections: JSON.stringify(f.selections),
            receipt: JSON.stringify(receipt),
        };
        const outputs = [];
        for (const checkoutName of ["checkout A", "checkout B"]) {
            const root = join(dir, checkoutName);
            const script = join(
                root,
                "research_web/scripts/apply-classification-evidence.mts",
            );
            for (const path of [
                "scripts/apply-classification-evidence.mts",
                "src/domain/opportunities/model.ts",
                "src/domain/opportunities/types.ts",
            ]) {
                const target = join(root, "research_web", path);
                await mkdir(dirname(target), { recursive: true });
                await copyFile(resolve(path), target);
            }
            const evidence = join(root, "evidence snapshots");
            const cwd = join(root, "unrelated cwd");
            await mkdir(evidence);
            await mkdir(cwd);
            const paths = Object.fromEntries(
                Object.keys(packets).map((name) => [
                    name,
                    join(evidence, `${name}.json`),
                ]),
            );
            for (const [name, value] of Object.entries(packets))
                await writeFile(paths[name], value);
            for (const relativeArgs of [false, true]) {
                const output = join(root, `output-${relativeArgs}.json`);
                const args = Object.fromEntries(
                    Object.entries(paths).map(([name, path]) => [
                        name,
                        relativeArgs ? relative(cwd, path) : path,
                    ]),
                );
                args.output = output;
                const run = spawnSync(
                    process.execPath,
                    [
                        "--experimental-strip-types",
                        script,
                        ...Object.entries(args).flatMap(([key, value]) => [
                            `--${key}`,
                            value,
                        ]),
                    ],
                    { cwd, encoding: "utf8" },
                );
                assert.equal(run.status, 0, run.stderr);
                outputs.push(await readFile(output));
            }
            const external = join(dir, "outside evidence.json");
            await writeFile(external, classification);
            const output = join(root, "rejected-output.json");
            const before = await readFile(paths.input);
            const run = spawnSync(
                process.execPath,
                [
                    "--experimental-strip-types",
                    script,
                    ...Object.entries({
                        ...paths,
                        classification: external,
                        output,
                    }).flatMap(([key, value]) => [`--${key}`, value]),
                ],
                { cwd, encoding: "utf8" },
            );
            assert.notEqual(run.status, 0);
            assert.match(run.stderr, /explicit snapshot inside the repository/);
            await assert.rejects(readFile(output), { code: "ENOENT" });
            assert.deepEqual(await readFile(paths.input), before);
            assert.equal(await readFile(external, "utf8"), classification);
        }
        for (const output of outputs) assert.deepEqual(output, outputs[0]);
        const result = JSON.parse(outputs[0]);
        for (const source of result.sources.filter((item) => item.path)) {
            assert.doesNotMatch(source.path, /\\|^(?:\/|[a-z]:)/i);
            assert.ok(!source.path.split("/").includes(".."));
        }
        assert.deepEqual(
            result.sources
                .filter((item) => item.id.includes(":file:"))
                .map((item) => item.path)
                .sort(),
            ["classification", "receipt", "selections", "sources"].map(
                (name) => `evidence snapshots/${name}.json`,
            ),
        );
    } finally {
        await rm(dir, { recursive: true, force: true });
    }
});
test("CLI checks raw receipt bytes, gzip input, space paths, and exclusive output", async () => {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const dir = await mkdtemp(join(scratch, "classification cli "));
    try {
        const f = fixture(),
            c = JSON.stringify(f.classification),
            s = JSON.stringify(f.sources);
        const receipt = {
            schema_version: "opportunity-classification-verification.v1",
            checks: JSON.parse(
                await readFile(
                    "fixtures/classification-v1/verification-receipt.json",
                    "utf8",
                ),
            ).checks,
            files: {
                "classification-v1.json": { raw_sha256: hash(c) },
                "sources-v1.json": { raw_sha256: hash(s) },
            },
        };
        const paths = Object.fromEntries(
            [
                "input",
                "classification",
                "sources",
                "receipt",
                "selections",
                "output",
            ].map((name) => [
                name,
                join(
                    dir,
                    `${name} file${name === "input" ? ".JSON.GZ" : ".json"}`,
                ),
            ]),
        );
        for (const [name, value] of Object.entries({
            input: gzipSync("\uFEFF" + JSON.stringify(f.bundle)),
            classification: c,
            sources: s,
            receipt: JSON.stringify(receipt),
            selections: JSON.stringify(f.selections),
        }))
            await writeFile(paths[name], value);
        const run = () =>
            spawnSync(
                process.execPath,
                [
                    "--experimental-strip-types",
                    resolve("scripts/apply-classification-evidence.mts"),
                    ...Object.entries(paths).flatMap(([key, path]) => [
                        `--${key}`,
                        path,
                    ]),
                ],
                { encoding: "utf8" },
            );
        const success = run();
        assert.equal(success.status, 0, success.stderr);
        const output = await readFile(paths.output);
        assert.equal(
            JSON.parse(output).securities[0].industry[0].basis,
            "document-period",
        );
        const exists = run();
        assert.notEqual(exists.status, 0);
        assert.match(exists.stderr, /EEXIST/);
        assert.deepEqual(await readFile(paths.output), output);
        await rm(paths.output);
        await writeFile(paths.classification, `${c}\n`);
        const mismatch = run();
        assert.notEqual(mismatch.status, 0);
        assert.match(mismatch.stderr, /receipt hash mismatch/);
    } finally {
        await rm(dir, { recursive: true, force: true });
    }
});
async function syntheticPacket(directory) {
    const f = fixture();
    f.bundle.id = "synthetic-classification-integration";
    f.bundle.label = "Fictional classification integration fixture";
    // Invented values exercise preservation independently of market fixtures.
    for (const [index, security] of f.bundle.securities.entries())
        security.prices = f.bundle.dates.map((date, day) => ({
            date,
            close: 100 + index * 10 + [0, 40, 20][day],
            flags: [],
        }));
    const classification = JSON.stringify(f.classification);
    const sources = JSON.stringify(f.sources);
    const receipt = {
        schema_version: "opportunity-classification-verification.v1",
        checks: JSON.parse(
            await readFile(
                "fixtures/classification-v1/verification-receipt.json",
                "utf8",
            ),
        ).checks,
        checks_scope:
            "Synthetic integrity fixture; no issuer or market evidence.",
        files: {
            "classification-v1.json": { raw_sha256: hash(classification) },
            "sources-v1.json": { raw_sha256: hash(sources) },
        },
    };
    const args = {
        input: join(directory, "synthetic input.json.gz"),
        classification: join(directory, "classification-v1.json"),
        sources: join(directory, "sources-v1.json"),
        receipt: join(directory, "verification-receipt.json"),
        selections: join(directory, "selections.json"),
        output: join(directory, "integrated bundle.json"),
    };
    const bytes = {
        input: gzipSync(JSON.stringify(f.bundle)),
        classification,
        sources,
        receipt: JSON.stringify(receipt),
        selections: JSON.stringify(f.selections),
    };
    for (const [name, value] of Object.entries(bytes))
        await writeFile(args[name], value);
    return { args, receipt, fixture: f, bytes };
}

test("synthetic producer and classification packets integrate through the real CLI", async () => {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const dir = await mkdtemp(join(scratch, "classification integration "));
    try {
        const { args, receipt, fixture: f, bytes } = await syntheticPacket(dir);
        const inputBytes = await readFile(args.input);
        const run = spawnSync(
            process.execPath,
            [
                "--experimental-strip-types",
                resolve("scripts/apply-classification-evidence.mts"),
                ...Object.entries(args).flatMap(([key, value]) => [
                    `--${key}`,
                    value,
                ]),
            ],
            { encoding: "utf8" },
        );
        assert.equal(run.status, 0, run.stderr);
        const before = JSON.parse(gunzipSync(inputBytes).toString("utf8"));
        const after = JSON.parse(await readFile(args.output, "utf8"));
        assert.deepEqual(await readFile(args.input), inputBytes);
        for (const key of ["waves", "representatives", "portfolios"])
            assert.deepEqual(after[key], before[key]);
        for (const security of before.securities)
            assert.deepEqual(
                after.securities.find((x) => x.id === security.id).prices,
                security.prices,
            );
        for (const name of ["classification", "sources"])
            assert.equal(
                hash(await readFile(args[name])),
                receipt.files[`${name}-v1.json`].raw_sha256,
            );
        for (const name of [
            "classification",
            "sources",
            "receipt",
            "selections",
        ])
            assert.ok(
                after.sources.some(
                    (source) => source.hash === hash(bytes[name]),
                ),
            );
        const first = after.securities[0];
        const membership = first.industry.find(
            (x) => x.basis === "document-period",
        );
        assert.equal(membership.from, "2021-01-01");
        assert.equal(membership.untilExclusive, "2022-01-01");
        const evidence = after.sources.find(
            (x) => x.id === membership.sourceId,
        );
        assert.match(evidence.label, /annual/);
        assert.match(evidence.label, /page 1/);
        assert.match(evidence.label, /canonical-retained-observation-json/);
        assert.equal(evidence.url, "https://example.com/report");
        const second = after.securities[1];
        const multiEvidence = after.sources.find(
            (x) => x.id === second.industry[0].sourceId,
        );
        assert.match(multiEvidence.label, /phone, vr/);
        assert.equal(
            second.classificationReferences.filter(
                (x) => x.layer === "business-role",
            ).length,
            2,
        );
        assert.equal(
            after.securities[2].classificationSnapshot.label,
            f.classification.securities[2].official_industry_snapshot.label,
        );
    } finally {
        await rm(dir, { recursive: true, force: true });
    }
});
test("synthetic receipt requires every unique producer check to pass before CLI output", async () => {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const dir = await mkdtemp(join(scratch, "classification receipt checks "));
    try {
        const {
            args,
            receipt: original,
            fixture: f,
        } = await syntheticPacket(dir);
        const run = () =>
            spawnSync(
                process.execPath,
                [
                    "--experimental-strip-types",
                    resolve("scripts/apply-classification-evidence.mts"),
                    ...Object.entries(args).flatMap(([key, value]) => [
                        `--${key}`,
                        value,
                    ]),
                ],
                { encoding: "utf8" },
            );
        // Mutate each required check in turn, keeping all packet hashes truthful.
        for (let index = 0; index < original.checks.length; index++) {
            for (const kind of ["failed", "missing", "duplicate"]) {
                const receipt = structuredClone(original);
                if (kind === "failed") receipt.checks[index].status = "failed";
                if (kind === "missing") receipt.checks.splice(index, 1);
                if (kind === "duplicate")
                    receipt.checks.push(structuredClone(receipt.checks[index]));
                await writeFile(args.receipt, JSON.stringify(receipt));
                const rejected = run();
                assert.notEqual(
                    rejected.status,
                    0,
                    `${kind} ${original.checks[index].check}`,
                );
                assert.match(rejected.stderr, /receipt check/);
                await assert.rejects(readFile(args.output), { code: "ENOENT" });
            }
        }
        const extra = structuredClone(original);
        extra.checks.push({
            check: "additional-producer-check",
            status: "failed",
        });
        await writeFile(args.receipt, JSON.stringify(extra));
        const rejected = run();
        assert.notEqual(rejected.status, 0);
        assert.match(rejected.stderr, /additional-producer-check/);
        await assert.rejects(readFile(args.output), { code: "ENOENT" });
        await writeFile(args.receipt, JSON.stringify(original));
        const accepted = run();
        assert.equal(accepted.status, 0, accepted.stderr);
        assert.equal(
            JSON.parse(await readFile(args.output, "utf8")).securities.length,
            f.bundle.securities.length,
        );
    } finally {
        await rm(dir, { recursive: true, force: true });
    }
});
