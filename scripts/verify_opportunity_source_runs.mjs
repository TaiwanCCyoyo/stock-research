import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { gunzipSync } from "node:zlib";
import { isDeepStrictEqual } from "node:util";
import {
    buildLabCase,
    sourceRunIndices,
    codeIdentity,
    sha256,
} from "./opportunity_history_methods.mjs";

async function checkedJson(root, reference) {
    const path = resolve(root, reference.path);
    const bytes = await readFile(path);
    if (
        typeof reference.sha256 !== "string" ||
        !/^[0-9a-fA-F]{64}$/.test(reference.sha256) ||
        sha256(bytes) !== reference.sha256.toLowerCase()
    )
        throw new Error(`Source run input hash mismatch: ${path}`);
    return JSON.parse(
        path.endsWith(".gz")
            ? gunzipSync(bytes).toString("utf8")
            : bytes.toString("utf8"),
    );
}

async function main(args) {
    if (args.length < 2 || args[0] !== "--manifest" || args.length % 2 !== 0)
        throw new Error(
            "Usage: --manifest <catalog manifest.json> [--code <code>]...",
        );
    const selectedCodes = [];
    for (let index = 2; index < args.length; index += 2) {
        if (args[index] !== "--code" || !args[index + 1])
            throw new Error(
                "Usage: --manifest <catalog manifest.json> [--code <code>]...",
            );
        selectedCodes.push(args[index + 1]);
    }
    const manifestPath = resolve(args[1]);
    const root = dirname(manifestPath);
    const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
    if (!isDeepStrictEqual(await codeIdentity(), manifest.code_identity))
        throw new Error("Source run code identity mismatch");
    const calendar = await checkedJson(root, manifest.calendar);
    if (
        calendar.calendar_id !== manifest.calendar_id ||
        (manifest.calendar.count !== undefined &&
            calendar.dates.length !== manifest.calendar.count)
    )
        throw new Error("Source run calendar identity/count mismatch");
    const results = Object.create(null);
    const codes = selectedCodes.length
        ? [...new Set(selectedCodes)].sort()
        : Object.keys(manifest.native).sort();
    for (const code of codes) {
        if (!Object.hasOwn(manifest.native, code))
            throw new Error(`Missing selected native code: ${code}`);
        const reference = manifest.series[code];
        if (!reference)
            throw new Error(`Missing source run series reference: ${code}`);
        const series = await checkedJson(root, reference);
        if (
            series.code !== code ||
            series.security_id !== reference.security_id ||
            series.series_id !== reference.series_id ||
            series.instrument_role !== "stock" ||
            !["metadata_stock", "innovation_board"].includes(series.cohort)
        )
            throw new Error(
                `Source run series identity/cohort mismatch: ${code}`,
            );
        // Only deterministic run indices are recomputed; saved analysis is never invoked or read.
        results[code] = sourceRunIndices(buildLabCase(series, calendar));
    }
    process.stdout.write(
        JSON.stringify({
            schema: "opportunity-expected-source-runs.v1",
            calendar_count: calendar.dates.length,
            results,
        }) + "\n",
        "utf8",
    );
}

main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(String(error.message) + "\n", "utf8");
    process.exitCode = 1;
});
