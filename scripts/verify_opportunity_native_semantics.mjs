/** Verify saved native source semantics using the immutable original pure TS functions. */
import { readFile } from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { isDeepStrictEqual } from "node:util";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import {
    buildLabCase,
    codeIdentity,
    sha256,
    sourceRunIndices,
} from "./opportunity_history_methods.mjs";

export async function deriveNativeSourceExpectations({
    series,
    calendar,
    native,
    segments = [],
    exact_runs,
    launch_noise,
}) {
    const identity = await codeIdentity();
    if (native && !isDeepStrictEqual(native.code_identity, identity)) {
        throw new Error("Pinned native source code identity mismatch");
    }
    const bytes = await readFile(
        new URL(
            "../tasks/20261004-sector-wave-full-history-preview/method-snapshot/analysis.ts",
            import.meta.url,
        ),
    );
    if (sha256(bytes) !== identity.source.analysis)
        throw new Error("Pinned native analysis hash mismatch");
    // The preserved file stays untouched. Expose only existing pure source functions in memory.
    const sourceText = stripTypeScriptTypes(
        bytes.toString("utf8") +
            "\nexport { runs, waves, launches, estimateNoise, phase };\n",
        { mode: "strip" },
    );
    const source = await import(
        "data:text/javascript;base64," +
            Buffer.from(sourceText).toString("base64")
    );
    if (!Array.isArray(series.adjusted))
        throw new Error("Expected adjusted price array");
    if (
        calendar &&
        (!Array.isArray(calendar.dates) ||
            calendar.dates.length !== series.adjusted.length)
    ) {
        throw new Error("Source semantic calendar/price length mismatch");
    }
    const pureInput = {
        points: series.adjusted.map((adjusted, index) => {
            const flags = series.numeric_flags?.[String(index)] ?? [];
            if (
                (adjusted !== null &&
                    (typeof adjusted !== "number" ||
                        !Number.isFinite(adjusted))) ||
                !Array.isArray(flags) ||
                flags.some((flag) => typeof flag !== "string")
            ) {
                throw new Error("Invalid pure source price or flags");
            }
            return { adjusted, flags };
        }),
    };
    const input = native ? buildLabCase(series, calendar) : pureInput;
    const actualRuns = sourceRunIndices(input);
    if (exact_runs && !isDeepStrictEqual(exact_runs, actualRuns))
        throw new Error("Exact source run array mismatch");
    const allRuns = source.runs(input);
    const noise = source.estimateNoise(allRuns);
    const baselines = Object.fromEntries(
        ["fine", "balanced", "coarse"].map((scale) => [
            scale,
            source.waves(allRuns, scale),
        ]),
    );
    return {
        noise,
        baselines,
        phases: segments.map((segment) => ({
            ...segment,
            phase: source.phase(segment.slope),
        })),
        launches: source.launches(segments, input, launch_noise ?? noise),
        source_run_indices: actualRuns,
        records: (native?.native ?? [])
            .filter((record) => record.status === "ok")
            .map((record) => ({
                method: record.method,
                scale: record.scale,
                waves: baselines[record.scale],
                phases: record.result.segments.map((segment) => ({
                    ...segment,
                    phase: source.phase(segment.slope),
                })),
                launches: source.launches(record.result.segments, input, noise),
            })),
    };
}

export async function validateNativeSourceSemantics(payload) {
    const records = payload.native?.native;
    if (!Array.isArray(records) || records.length !== 6)
        throw new Error(
            "Native requires six unique known method/scale records",
        );
    const scopes = new Set();
    for (const record of records) {
        if (
            !record ||
            !["segments", "filter"].includes(record.method) ||
            !["fine", "balanced", "coarse"].includes(record.scale)
        )
            throw new Error(
                "Native requires six unique known method/scale records",
            );
        const scope = `${record.method}/${record.scale}`;
        if (scopes.has(scope))
            throw new Error(
                "Native requires six unique known method/scale records",
            );
        scopes.add(scope);
        if (!["ok", "error"].includes(record.status))
            throw new Error("Invalid native method status");
    }
    const failedScopes = records
        .filter((record) => record.status === "error")
        .map((record) => ({ method: record.method, scale: record.scale }));
    const expected = await deriveNativeSourceExpectations(payload);
    if (
        !isDeepStrictEqual(
            payload.native.source_run_indices,
            expected.source_run_indices,
        )
    )
        throw new Error("Exact source run array mismatch");
    let waves = 0,
        launches = 0;
    for (const sourceRecord of expected.records) {
        const record = payload.native.native.find(
            (item) =>
                item.method === sourceRecord.method &&
                item.scale === sourceRecord.scale,
        );
        const scope = `${sourceRecord.method}/${sourceRecord.scale}`;
        if (!isDeepStrictEqual(record.result.waves, sourceRecord.waves))
            throw new Error(`Original source wave mismatch: ${scope}`);
        if (record.result.diagnostics.noise !== expected.noise)
            throw new Error(`Original source noise mismatch: ${scope}`);
        if (!isDeepStrictEqual(record.result.segments, sourceRecord.phases))
            throw new Error(`Original source phase mismatch: ${scope}`);
        if (!isDeepStrictEqual(record.result.launches, sourceRecord.launches))
            throw new Error(`Original source launch mismatch: ${scope}`);
        waves += sourceRecord.waves.length;
        launches += sourceRecord.launches.length;
    }
    return {
        schema: "opportunity-native-source-semantics.v1",
        status: failedScopes.length ? "partial" : "verified",
        failed_method_count: failedScopes.length,
        failed_scopes: failedScopes,
        method_count: expected.records.length,
        wave_count: waves,
        launch_count: launches,
    };
}

if (
    process.argv[1] &&
    import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
    try {
        process.stdin.setEncoding("utf8");
        let text = "";
        for await (const chunk of process.stdin) text += chunk;
        const mode = process.argv[2] ?? "--verify";
        if (!["--verify", "--derive"].includes(mode) || process.argv.length > 3)
            throw new Error("Usage: --verify or --derive with JSON stdin");
        const payload = JSON.parse(text);
        const output =
            mode === "--derive"
                ? {
                      schema: "opportunity-native-source-expectations.v1",
                      ...(await deriveNativeSourceExpectations(payload)),
                  }
                : await validateNativeSourceSemantics(payload);
        // Mirrors the wrapper's finite-output requirement, including source null coercion edge cases.
        const finite = (value) => {
            if (typeof value === "number" && !Number.isFinite(value))
                throw new Error("Nonfinite original source output");
            if (value && typeof value === "object")
                for (const child of Object.values(value)) finite(child);
        };
        finite(output);
        process.stdout.write(JSON.stringify(output) + "\n");
    } catch (error) {
        process.stderr.write(String(error?.message ?? error) + "\n");
        process.exitCode = 1;
    }
}
