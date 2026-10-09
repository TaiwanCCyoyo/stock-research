import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { gzipSync, gunzipSync } from "node:zlib";
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { analyzeCase } from "../tasks/20261004-sector-wave-full-history-preview/method-snapshot/analysis.ts";

export const METHODS = ["segments", "filter"];
export const SCALES = ["fine", "balanced", "coarse"];
const snapshotRoot = new URL(
    "../tasks/20261004-sector-wave-full-history-preview/method-snapshot/",
    import.meta.url,
);
export const SOURCE_HASHES = {
    analysis:
        "550c277df28c7ac0b2d4deb69b67eb137b500c0f8b2c80c78880fda79aef1a25",
    types: "9ee6c25365f2acbaf889151fa29727457e70319277aa60cca64bcadd38a675cb",
};
export const sha256 = (bytes) =>
    createHash("sha256").update(bytes).digest("hex");

export async function codeIdentity() {
    const [analysis, types, wrapper] = await Promise.all([
        readFile(new URL("analysis.ts", snapshotRoot)),
        readFile(new URL("types.ts", snapshotRoot)),
        readFile(fileURLToPath(import.meta.url)),
    ]);
    const actual = { analysis: sha256(analysis), types: sha256(types) };
    for (const key of Object.keys(SOURCE_HASHES)) {
        if (actual[key] !== SOURCE_HASHES[key])
            throw new Error(`Pinned ${key} source hash mismatch`);
    }
    return {
        source: actual,
        method: "wave-lab-exploratory.v1",
        wrapper: { sha256: sha256(wrapper) },
    };
}

export function buildLabCase(series, calendar) {
    if (
        series.schema !== "opportunity-series.v1" &&
        series.schema_version !== "opportunity-series.v1"
    ) {
        throw new Error("Expected opportunity-series.v1");
    }
    const dates = calendar.dates;
    if (
        !Array.isArray(dates) ||
        !Array.isArray(series.raw) ||
        !Array.isArray(series.adjusted) ||
        dates.length !== series.raw.length ||
        dates.length !== series.adjusted.length
    ) {
        throw new Error("Calendar, raw and adjusted arrays must be aligned");
    }
    if (calendar.calendar_id !== series.calendar_id)
        throw new Error("Calendar identity mismatch");
    for (const key of ["security_id", "series_id", "calendar_id"]) {
        if (typeof series[key] !== "string" || !series[key])
            throw new Error(`Missing ${key}`);
    }
    for (const [index, flags] of Object.entries(series.numeric_flags ?? {})) {
        if (
            !/^(0|[1-9]\d*)$/.test(index) ||
            Number(index) >= dates.length ||
            !Array.isArray(flags) ||
            flags.some((flag) => typeof flag !== "string")
        ) {
            throw new Error(`Invalid numeric_flags entry: ${index}`);
        }
    }
    for (const values of [series.raw, series.adjusted]) {
        if (values.some((value) => value !== null && typeof value !== "number"))
            throw new Error("Prices must be numbers or null");
    }
    return {
        id: series.series_id,
        name: series.name ?? series.code ?? series.security_id,
        code: series.code,
        kind: "historical",
        category: series.cohort ?? "",
        question: "",
        points: dates.map((date, index) => ({
            date,
            raw: series.raw[index],
            adjusted: series.adjusted[index],
            flags: [...(series.numeric_flags?.[index] ?? [])],
        })),
        source: {
            label: "Pinned opportunity-series.v1",
            from: dates[0] ?? "",
            to: dates.at(-1) ?? "",
            priceBasis:
                series.price_basis ??
                "permanent-reference-factor-close.preview.v1",
            limitations: [...(series.coverage_caveats ?? [])],
        },
    };
}

function assertFinite(value, path = "result") {
    if (typeof value === "number" && !Number.isFinite(value))
        throw new Error(`Nonfinite output at ${path}`);
    if (value && typeof value === "object") {
        for (const [key, child] of Object.entries(value))
            assertFinite(child, `${path}.${key}`);
    }
}

export function sourceRunIndices(input) {
    let previousLog = null;
    let run = -1;
    const logJump = Math.log(1.35);
    return input.points.map((point) => {
        const price = point.adjusted;
        if (
            price === null ||
            !Number.isFinite(price) ||
            price <= 0 ||
            point.flags.length !== 0
        ) {
            previousLog = null;
            return null;
        }
        const value = Math.log(price);
        if (previousLog === null || Math.abs(value - previousLog) > logJump)
            run++;
        previousLog = value;
        return run;
    });
}

export function deriveSupportRecords(native) {
    const records = [];
    for (const target of native) {
        if (target.status !== "ok") continue;
        for (const launch of target.result.launches) {
            const matches = SCALES.flatMap((scale) => {
                const result = native.find(
                    (item) =>
                        item.method === target.method &&
                        item.scale === scale &&
                        item.status === "ok",
                );
                let nearest;
                for (const candidate of result?.result.launches ?? []) {
                    const distance = Math.abs(candidate.index - launch.index);
                    if (
                        candidate.kind === launch.kind &&
                        distance <= 20 &&
                        (!nearest ||
                            distance < Math.abs(nearest.index - launch.index))
                    )
                        nearest = candidate;
                }
                return nearest
                    ? [
                          {
                              method: target.method,
                              scale,
                              candidate_id: nearest.id,
                              index: nearest.index,
                          },
                      ]
                    : [];
            });
            records.push({
                method: target.method,
                scale: target.scale,
                candidate_id: launch.id,
                index: launch.index,
                kind: launch.kind,
                matched_ids: matches,
                support: matches.length,
                rangeStart: Math.min(...matches.map((match) => match.index)),
                rangeEnd: Math.max(...matches.map((match) => match.index)),
            });
        }
    }
    return records;
}

export function analyzeSeries(
    series,
    calendar,
    { analyze = analyzeCase, identity = null, inputIdentity = null } = {},
) {
    const input = buildLabCase(series, calendar);
    const started = performance.now();
    const timings = [];
    const native = METHODS.flatMap((method) =>
        SCALES.map((scale) => {
            const start = performance.now();
            let record;
            try {
                const result = analyze(input, method, scale);
                assertFinite(result);
                record = { method, scale, status: "ok", result, error: null };
            } catch (error) {
                record = {
                    method,
                    scale,
                    status: "error",
                    result: null,
                    error: {
                        name: error?.name ?? "Error",
                        message: String(error?.message ?? error),
                    },
                };
            }
            timings.push({
                method,
                scale,
                elapsed_ms: performance.now() - start,
            });
            return record;
        }),
    );
    return {
        schema: "opportunity-native-results.v1",
        security_id: series.security_id,
        series_id: series.series_id,
        calendar_id: series.calendar_id,
        input_identity: inputIdentity,
        code_identity: identity,
        coverage: {
            cohort: series.cohort,
            instrument_role: series.instrument_role,
            points: input.points.length,
            coverage_caveats: input.source.limitations,
        },
        source_run_indices: sourceRunIndices(input),
        native,
        support_records: deriveSupportRecords(native),
        timing: { elapsed_ms: performance.now() - started, methods: timings },
    };
}

export async function runFiles({ seriesPath, calendarPath, outputPath }) {
    const [seriesBytes, calendarBytes, identity] = await Promise.all([
        readFile(seriesPath),
        readFile(calendarPath),
        codeIdentity(),
    ]);
    const series = JSON.parse(gunzipSync(seriesBytes));
    const calendar = JSON.parse(calendarBytes);
    const output = analyzeSeries(series, calendar, {
        identity,
        inputIdentity: {
            series_sha256: sha256(seriesBytes),
            calendar_sha256: sha256(calendarBytes),
        },
    });
    await writeFile(
        outputPath,
        gzipSync(Buffer.from(JSON.stringify(output)), { mtime: 0 }),
        { flag: "wx" },
    );
    return output;
}

async function main(args) {
    const options = {};
    for (let i = 0; i < args.length; i += 2) {
        if (
            !["--series", "--calendar", "--output"].includes(args[i]) ||
            !args[i + 1] ||
            options[args[i]]
        ) {
            throw new Error(
                "Usage: --series <series.json.gz> --calendar <calendar.json> --output <new.json.gz>",
            );
        }
        options[args[i]] = args[i + 1];
    }
    if (Object.keys(options).length !== 3)
        throw new Error("Required: --series, --calendar, --output");
    const output = await runFiles({
        seriesPath: options["--series"],
        calendarPath: options["--calendar"],
        outputPath: options["--output"],
    });
    console.log(
        JSON.stringify({
            security_id: output.security_id,
            methods: output.native.length,
            errors: output.native.filter((record) => record.status === "error")
                .length,
            output: options["--output"],
        }),
    );
}

if (
    process.argv[1] &&
    pathToFileURL(resolve(process.argv[1])).href === import.meta.url
) {
    main(process.argv.slice(2)).catch((error) => {
        console.error(error.message);
        process.exitCode = 1;
    });
}
