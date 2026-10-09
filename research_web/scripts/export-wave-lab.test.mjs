import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { validateLabBundle } from "../src/features/wave-lab/bundle.ts";
import { exportCases } from "./export-wave-lab.mjs";

const codes = ["3017", "2330", "2609", "9919", "3481", "2002", "2498", "4743"];

function atlas() {
    const dates = [
        "2019-01-02",
        "2020-01-02",
        "2021-01-04",
        "2022-12-30",
        "2023-12-29",
        "2026-08-14",
    ];
    return {
        schema: "market-atlas.v1",
        catalogHash: "catalog-fixture",
        dates,
        stocks: codes.map((code, codeIndex) => ({
            code,
            name: `名稱 ${code}`,
            quality: ["source-check"],
            qualityFindings: [{ date: "2021-01-04", kind: "duplicate_date" }],
            raw: dates.map((_, index) => codeIndex + index + 10),
            adjusted: dates.map((_, index) => codeIndex + index + 20),
        })),
        provenance: {
            rawDefinition: "fixture raw",
            splitAdjustedDefinition: "fixture adjusted",
        },
        limitations: ["fixture limitation"],
    };
}

async function fixtureDir() {
    await mkdir(".tmp", { recursive: true });
    return mkdtemp(path.join(".tmp", "wave-lab-test-"));
}

test("rejects malformed or missing limitations before creating output", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        for (const limitations of [
            undefined,
            null,
            "warning",
            {},
            42,
            ["retained warning", {}],
            ["retained warning", 42],
            [null],
        ]) {
            const invalid = atlas();
            invalid.limitations = limitations;
            await writeFile(input, JSON.stringify(invalid));
            await assert.rejects(
                exportCases(input, output),
                /limitations must be a string array/,
            );
            await assert.rejects(readFile(output), { code: "ENOENT" });
        }
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("preserves every source limitation in order, including empty arrays and untrimmed strings", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json");
        let standardLimitations;
        for (const [index, limitations] of [
            [],
            ["first warning", " second warning ", "", "first warning"],
        ].entries()) {
            const source = atlas();
            source.limitations = limitations;
            const output = path.join(root, `wave-lab-cases-${index}.json`);
            await writeFile(input, JSON.stringify(source));
            const bundle = await exportCases(input, output);
            if (index === 0)
                standardLimitations = bundle.cases[0].source.limitations;
            for (const item of bundle.cases)
                assert.deepEqual(item.source.limitations, [
                    ...standardLimitations,
                    ...limitations,
                ]);
            const saved = JSON.parse(await readFile(output, "utf8"));
            assert.deepEqual(saved, bundle);
            assert.strictEqual(validateLabBundle(saved), saved);
        }
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("exports preselected cases with hashes and preserved quality flags", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        await writeFile(input, JSON.stringify(atlas()));
        const bundle = await exportCases(input, output);
        assert.equal(bundle.cases.length, 8);
        assert.match(bundle.projectionHash, /^[a-f0-9]{64}$/);
        const row = bundle.cases.find((item) => item.code === "2498").points[0];
        assert.equal(
            bundle.cases.find((item) => item.code === "2498").name,
            "名稱 2498",
        );
        assert.ok(row.flags.includes("stock-quality:source-check"));
        assert.ok(row.flags.includes("dated-quality:duplicate_date"));
        assert.deepEqual(JSON.parse(await readFile(output, "utf8")), bundle);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("rejects impossible Gregorian dates before creating output", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        for (const date of [
            "2020-02-30",
            "2021-02-29",
            "2020-04-31",
            "2020-13-01",
            "2020-01-00",
        ]) {
            const invalid = atlas();
            invalid.dates[1] = date;
            await writeFile(input, JSON.stringify(invalid));
            await assert.rejects(
                exportCases(input, output),
                /date 1 is invalid/,
            );
            await assert.rejects(readFile(output), { code: "ENOENT" });
        }
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("preserves a valid leap day and aligned prices in a reader-valid bundle", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        const source = atlas();
        source.dates[1] = "2020-02-29";
        await writeFile(input, JSON.stringify(source));
        const bundle = await exportCases(input, output);
        for (const item of bundle.cases) {
            const stock = source.stocks.find(
                (entry) => entry.code === item.code,
            );
            const indices = source.dates.flatMap((date, index) =>
                date >= item.source.from && date <= item.source.to
                    ? [index]
                    : [],
            );
            assert.deepEqual(
                item.points.map(({ date, raw, adjusted }) => ({
                    date,
                    raw,
                    adjusted,
                })),
                indices.map((index) => ({
                    date: source.dates[index],
                    raw: stock.raw[index],
                    adjusted: stock.adjusted[index],
                })),
            );
        }
        assert.ok(
            bundle.cases[0].points.some(({ date }) => date === "2020-02-29"),
        );
        const saved = JSON.parse(await readFile(output, "utf8"));
        assert.deepEqual(saved, bundle);
        assert.strictEqual(validateLabBundle(saved), saved);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("rejects malformed quality findings before creating output", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        for (const finding of [
            { date: "2020-02-30", kind: "duplicate_date" },
            { date: "2021-02-29", kind: "duplicate_date" },
            { date: "2020-1-02", kind: "duplicate_date" },
            { date: "not-a-date", kind: "duplicate_date" },
            { date: "2021-01-04", kind: "" },
            { date: "2021-01-04", kind: " \t " },
        ]) {
            const invalid = atlas();
            invalid.stocks[0].qualityFindings = [finding];
            await writeFile(input, JSON.stringify(invalid));
            await assert.rejects(
                exportCases(input, output),
                /3017.qualityFindings is invalid/,
            );
            await assert.rejects(readFile(output), { code: "ENOENT" });
        }
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("allows real quality-event dates outside the projection calendar without inventing points", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        const source = atlas();
        source.stocks[0].qualityFindings.push({
            date: "2020-02-29",
            kind: "outside-projection",
        });
        await writeFile(input, JSON.stringify(source));
        const bundle = await exportCases(input, output);
        assert.deepEqual(
            bundle.cases[0].points.map(({ date }) => date),
            source.dates,
        );
        assert.ok(
            bundle.cases[0].points.every(
                ({ flags }) =>
                    !flags.includes("dated-quality:outside-projection"),
            ),
        );
        assert.strictEqual(validateLabBundle(bundle), bundle);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("uses code fallback for blank names while preserving nonblank names", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        const source = atlas();
        source.stocks[0].name = "";
        source.stocks[1].name = " \t ";
        source.stocks[2].name = " 原有名稱 ";
        source.catalogHash = " catalog-fixture ";
        await writeFile(input, JSON.stringify(source));
        const bundle = await exportCases(input, output);
        assert.equal(bundle.cases[0].name, "代碼 3017");
        assert.equal(bundle.cases[1].name, "代碼 2330");
        assert.equal(bundle.cases[2].name, " 原有名稱 ");
        assert.equal(bundle.catalogHash, source.catalogHash);
        assert.ok(
            bundle.cases.every(
                (item) => item.source.catalogHash === source.catalogHash,
            ),
        );
        const saved = JSON.parse(await readFile(output, "utf8"));
        assert.deepEqual(saved, bundle);
        assert.strictEqual(validateLabBundle(saved), saved);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("rejects blank catalog hashes before creating output", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        for (const catalogHash of ["", " \t "]) {
            const invalid = atlas();
            invalid.catalogHash = catalogHash;
            await writeFile(input, JSON.stringify(invalid));
            await assert.rejects(
                exportCases(input, output),
                /catalogHash is required/,
            );
            await assert.rejects(readFile(output), { code: "ENOENT" });
        }
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("refuses malformed, duplicate-date, and existing-output inputs", async () => {
    const root = await fixtureDir();
    try {
        const input = path.join(root, "market-atlas.json"),
            output = path.join(root, "wave-lab-cases.json");
        const invalid = atlas();
        invalid.stocks = invalid.stocks.slice(1);
        await writeFile(input, JSON.stringify(invalid));
        await assert.rejects(
            exportCases(input, output),
            /required case code 3017 is missing/,
        );
        const duplicate = atlas();
        duplicate.dates[2] = duplicate.dates[1];
        await writeFile(input, JSON.stringify(duplicate));
        await assert.rejects(
            exportCases(input, output),
            /dates must be unique and increasing/,
        );
        await writeFile(input, JSON.stringify(atlas()));
        await writeFile(output, "already exists");
        await assert.rejects(exportCases(input, output), /EEXIST/);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});
