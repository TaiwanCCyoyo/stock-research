import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { validateBundle } from "../src/domain/opportunities/model.ts";
import type {
    OpportunityBundle,
    OpportunitySecurity,
    OpportunityWave,
    SourceRef,
} from "../src/domain/opportunities/types.ts";

export const ADAPTER_VERSION = "opportunity-preview-adapter.v1";
type RecordValue = Record<string, unknown>;
export interface PreviewFileIdentity {
    inputPath: string;
    inputHash: string;
    jsonHash: string;
    selectionsPath: string;
    selectionsHash: string;
}
interface Point {
    date: string;
    raw: number | null;
    adjusted: number | null;
    flags: string[];
}
interface Series {
    case_id: string;
    security_id: string;
    name: string;
    kind: "historical" | "synthetic";
    start_date: string;
    observed_through: string;
    points: Point[];
    source: RecordValue;
    snapshotIndustry: {
        label: string;
        observedAt: string | null;
        sourceRef: string;
    } | null;
}
interface Method {
    method_id: string;
    case_id: string;
    source_method: string;
    scale: string;
    rule_version: string;
    numerically_valid: boolean;
}
interface Wave {
    wave_id: string;
    case_id: string;
    security_id: string;
    method_id: string;
    start_date: string;
    peak_date: string;
    observed_through: string;
    end_confirmed_at: string | null;
    parent_wave_id: string | null;
    scale: string;
    left_censored: boolean;
    right_censored: boolean;
}
interface Launch {
    launch_id: string;
    case_id: string;
    security_id: string;
    method_id: string;
    candidate_date: string;
    range_first_date: string;
    range_last_date: string;
}
interface Selection {
    wave_id: string;
    launch_id: string | null;
}

function fail(message: string): never {
    throw new Error(`Invalid opportunity preview: ${message}`);
}
function object(value: unknown, label: string): RecordValue {
    if (!value || typeof value !== "object" || Array.isArray(value))
        fail(`${label} must be an object`);
    return value as RecordValue;
}
function list(value: unknown, label: string): unknown[] {
    if (!Array.isArray(value)) fail(`${label} must be an array`);
    return value;
}
function text(value: unknown, label: string): string {
    if (typeof value !== "string" || !value.trim())
        fail(`${label} must be a nonempty string`);
    return value;
}
function strings(value: unknown, label: string): string[] {
    return list(value, label).map((entry) => text(entry, label));
}
function number(value: unknown, label: string): number {
    if (typeof value !== "number" || !Number.isFinite(value))
        fail(`${label} must be finite`);
    return value;
}
function bool(value: unknown, label: string): boolean {
    if (typeof value !== "boolean") fail(`${label} must be boolean`);
    return value;
}
function date(value: unknown, label: string): string {
    const result = text(value, label);
    if (
        !/^\d{4}-\d{2}-\d{2}$/.test(result) ||
        !Number.isFinite(Date.parse(`${result}T00:00:00Z`)) ||
        new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result
    )
        fail(`${label} must be a valid YYYY-MM-DD date`);
    return result;
}
function hash(value: unknown, label: string): string {
    const result = text(value, label);
    if (!/^[a-f\d]{64}$/i.test(result)) fail(`${label} must be a SHA-256 hash`);
    return result;
}
function enumValue<T extends string>(
    value: unknown,
    choices: readonly T[],
    label: string,
): T {
    if (typeof value !== "string" || !choices.includes(value as T))
        fail(`unsupported ${label}`);
    return value as T;
}
function table(
    value: unknown,
    key: string,
    label: string,
): Map<string, RecordValue> {
    const result = new Map<string, RecordValue>();
    for (const entry of list(value, label)) {
        const row = object(entry, label);
        const id = text(row[key], `${label}.${key}`);
        if (result.has(id)) fail(`duplicate ${label} identity: ${id}`);
        result.set(id, row);
    }
    return result;
}
function nextDay(value: string): string {
    return new Date(Date.parse(`${value}T00:00:00Z`) + 86_400_000)
        .toISOString()
        .slice(0, 10);
}
function sha256(bytes: string | Buffer): string {
    return createHash("sha256").update(bytes).digest("hex");
}

/** All paths in source metadata remain inert evidence strings; only CLI inputs are read. */
export function adaptPreview(
    value: unknown,
    selectionValue: unknown,
    identity: PreviewFileIdentity,
    exportKind: "historical" | "synthetic" = "historical",
): OpportunityBundle {
    enumValue(exportKind, ["historical", "synthetic"], "export kind");
    const preview = object(value, "preview");
    if (
        preview.schema !== "opportunity-catalog.preview.v1" ||
        preview.mode !== "retrospective_preview"
    )
        fail("unsupported schema or mode");
    const identities = object(preview.identities, "identities");
    text(identities.code_commit, "identities.code_commit");
    text(identities.scope, "identities.scope");
    enumValue(
        identities.input_identity_basis,
        ["file_bytes", "canonical_json"],
        "input identity basis",
    );
    for (const key of [
        "input_sha256",
        "input_hash",
        "projection_hash",
        "catalog_hash",
    ])
        hash(identities[key], `identities.${key}`);
    const codeHashes = object(identities.code_hashes, "code_hashes");
    if (Object.keys(codeHashes).length === 0)
        fail("code_hashes must not be empty");
    for (const codeHash of Object.values(codeHashes))
        hash(codeHash, "code hash");
    if (identities.classification_sha256 !== undefined) {
        hash(identities.classification_sha256, "classification_sha256");
        text(identities.classification_source_ref, "classification_source_ref");
    }
    for (const key of ["inputHash", "jsonHash", "selectionsHash"] as const)
        hash(identity[key], key);
    text(identity.inputPath, "inputPath");
    text(identity.selectionsPath, "selectionsPath");
    const status = object(preview.comparison_status, "comparison_status");
    for (const key of ["holdings", "allocations", "metric_definitions"])
        if (status[key] !== "not_supplied")
            fail(`unsupported comparison_status.${key}`);
    const limitations = [
        ...strings(preview.limitations, "limitations"),
        "這是既有案例的回溯預覽；明示代表波段與發車選擇不代表已核准自動選股規則。",
        "來源 falling/flat/rising/fast 為擬合觀察，未轉譯成生命週期階段；原觀察保留於具雜湊的來源 JSON。",
        "沒有歷史有效期間分類；快照產業未當作歷史分類。未提供持股及資金權重，不補零或等權。",
        "宣告的外部雜湊只保留来源身分，不表示已驗證外部檔案真實性。",
    ];
    const seriesRows = table(preview.series, "case_id", "series");
    if (seriesRows.size === 0) fail("series must not be empty");
    const series = new Map<string, Series>();
    const securityIds = new Set<string>();
    for (const [caseId, row] of seriesRows) {
        const securityId = text(row.security_id, "series.security_id");
        if (securityIds.has(securityId))
            fail(
                `multiple cases for security ${securityId} require an explicit case adapter`,
            );
        securityIds.add(securityId);
        const kind = enumValue(
            row.kind,
            ["historical", "synthetic"],
            "series kind",
        );
        if (
            kind === "historical"
                ? !/^TW:[\dA-Za-z]+$/.test(securityId)
                : securityId !== `SYNTHETIC:${caseId}`
        )
            fail("series security identity mismatch");
        const points: Point[] = list(row.points, "points").map((entry) => {
            const point = object(entry, "point");
            return {
                date: date(point.date, "point.date"),
                raw: point.raw === null ? null : number(point.raw, "point.raw"),
                adjusted:
                    point.adjusted === null
                        ? null
                        : number(point.adjusted, "point.adjusted"),
                flags: strings(point.flags, "point.flags"),
            };
        });
        if (
            !points.length ||
            points.some((point, i) => i > 0 && points[i - 1].date >= point.date)
        )
            fail("quote dates must be unique and increasing");
        const source = object(row.source, "series.source");
        text(source.label, "source.label");
        text(source.priceBasis, "source.priceBasis");
        strings(source.limitations, "source.limitations");
        if (
            row.start_date !== points[0].date ||
            row.observed_through !== points.at(-1)!.date ||
            source.from !== row.start_date ||
            source.to !== row.observed_through
        )
            fail("series/source cutoff mismatch");
        if (kind === "historical") {
            if (
                source.hash !== identities.projection_hash ||
                source.catalogHash !== identities.catalog_hash
            )
                fail("historical source identity mismatch");
        }
        for (const key of ["hash", "catalogHash"])
            if (source[key] !== undefined) hash(source[key], `source.${key}`);
        if (
            row.historical_industry !== null ||
            row.historical_unknown_reason !==
                "historical_effective_period_unverified"
        )
            fail("unverified historical industry claim");
        if (!("snapshot_industry" in row))
            fail("missing snapshot industry observation");
        let snapshotIndustry: Series["snapshotIndustry"] = null;
        if (row.snapshot_industry !== null) {
            if (
                row.snapshot_industry_status !== "snapshot_only" ||
                identities.classification_sha256 === undefined
            )
                fail("unbound snapshot industry");
            const snapshot = object(row.snapshot_industry, "snapshot industry");
            snapshotIndustry = {
                label: text(snapshot.label, "snapshot label"),
                observedAt:
                    snapshot.metadata_fetched_at == null
                        ? null
                        : text(
                              snapshot.metadata_fetched_at,
                              "snapshot metadata_fetched_at",
                          ),
                sourceRef: text(snapshot.source_ref, "snapshot source_ref"),
            };
            if (
                Object.keys(snapshot).some((key) =>
                    /historical|effective/i.test(key),
                )
            )
                fail(
                    "snapshot industry cannot assert historical effective periods",
                );
        }
        series.set(caseId, {
            case_id: caseId,
            security_id: securityId,
            name: text(row.name, "series.name"),
            kind,
            start_date: points[0].date,
            observed_through: points.at(-1)!.date,
            points,
            source,
            snapshotIndustry,
        });
    }
    const methods = new Map<string, Method>();
    for (const [id, row] of table(preview.methods, "method_id", "methods")) {
        const caseId = text(row.case_id, "method.case_id");
        const sample = series.get(caseId);
        if (!sample) fail("unknown method case");
        const method = enumValue(
            row.source_method,
            ["segments", "filter"],
            "source method",
        );
        const scale = enumValue(
            row.scale,
            ["fine", "balanced", "coarse"],
            "method scale",
        );
        if (id !== JSON.stringify([caseId, method, scale]))
            fail("method identity mismatch");
        const diagnostics = object(row.diagnostics, "method.diagnostics");
        const valid = bool(row.numerically_valid, "method.numerically_valid");
        if (
            valid !== bool(diagnostics.converged, "diagnostics.converged") ||
            row.acceptance !== "exploratory"
        )
            fail("method validity/acceptance mismatch");
        for (const key of ["iterations", "noise", "penalty"])
            number(diagnostics[key], `diagnostics.${key}`);
        const fit = list(row.fit, "method.fit");
        if (fit.length !== sample.points.length)
            fail("method fit length mismatch");
        fit.forEach((entry) => {
            if (entry !== null) number(entry, "method.fit point");
        });
        strings(row.warnings, "method.warnings");
        methods.set(id, {
            method_id: id,
            case_id: caseId,
            source_method: method,
            scale,
            rule_version: text(row.rule_version, "method.rule_version"),
            numerically_valid: valid,
        });
    }
    function context(row: RecordValue, keys: string[], security = true) {
        const method = methods.get(text(row.method_id, "method reference"));
        const sample = series.get(text(row.case_id, "case reference"));
        if (
            !method ||
            !sample ||
            method.case_id !== sample.case_id ||
            (security && row.security_id !== sample.security_id)
        )
            fail("cross-case/method/security reference");
        const dates = new Set(sample.points.map((point) => point.date));
        for (const key of keys)
            if (!dates.has(date(row[key], key)))
                fail(`${key} is not an observed quote date`);
        return { method, sample };
    }
    const waves = new Map<string, Wave>();
    const waveRows = table(preview.waves, "wave_id", "waves");
    for (const [id, row] of waveRows) {
        const { method, sample } = context(row, [
            "start_date",
            "peak_date",
            "observed_through",
        ]);
        if (
            id !==
            `${method.method_id}:wave:${text(row.source_id, "wave.source_id")}`
        )
            fail("wave identity mismatch");
        const start = date(row.start_date, "wave.start");
        const peak = date(row.peak_date, "wave.peak");
        const observed = date(row.observed_through, "wave.observed_through");
        const end =
            row.end_confirmed_at === null
                ? null
                : date(row.end_confirmed_at, "wave.end_confirmed_at");
        if (
            start > peak ||
            peak > observed ||
            observed > sample.observed_through ||
            (end !== null && (end !== observed || end < peak))
        )
            fail("invalid wave date ordering/cutoff");
        if (
            row.end_unknown_reason !==
            (end === null ? "not_confirmed_within_observation" : null)
        )
            fail("missing-end reason mismatch");
        const startPrice = sample.points.find(
            (point) => point.date === start,
        )!.adjusted;
        const peakPrice = sample.points.find(
            (point) => point.date === peak,
        )!.adjusted;
        if (
            startPrice === null ||
            peakPrice === null ||
            startPrice <= 0 ||
            peakPrice <= 0 ||
            Math.abs(
                (peakPrice / startPrice - 1) * 100 -
                    number(row.peak_gain_percent, "peak_gain_percent"),
            ) > 1e-6
        )
            fail("wave peak gain mismatch");
        number(row.max_drawdown_percent, "max_drawdown_percent");
        waves.set(id, {
            wave_id: id,
            method_id: method.method_id,
            case_id: sample.case_id,
            security_id: sample.security_id,
            start_date: start,
            peak_date: peak,
            observed_through: observed,
            end_confirmed_at: end,
            parent_wave_id:
                row.parent_wave_id === null
                    ? null
                    : text(row.parent_wave_id, "parent_wave_id"),
            scale: enumValue(row.scale, ["small", "large"], "wave scale"),
            left_censored: bool(row.left_censored, "left_censored"),
            right_censored: bool(row.right_censored, "right_censored"),
        });
    }
    for (const wave of waves.values())
        if (wave.parent_wave_id !== null) {
            const parent = waves.get(wave.parent_wave_id);
            if (
                !parent ||
                parent.method_id !== wave.method_id ||
                parent.start_date > wave.start_date ||
                parent.observed_through < wave.observed_through
            )
                fail("invalid wave parent containment");
        }
    const launches = new Map<string, Launch>();
    for (const [id, row] of table(preview.launches, "launch_id", "launches")) {
        const { method, sample } = context(row, [
            "candidate_date",
            "range_first_date",
            "range_last_date",
            "ensuing_end_date",
        ]);
        if (
            id !==
            `${method.method_id}:launch:${text(row.source_id, "launch.source_id")}`
        )
            fail("launch identity mismatch");
        const candidate = date(row.candidate_date, "candidate_date");
        const first = date(row.range_first_date, "range_first_date");
        const last = date(row.range_last_date, "range_last_date");
        if (
            first > candidate ||
            candidate > last ||
            candidate > String(row.ensuing_end_date)
        )
            fail("invalid launch dates");
        enumValue(
            row.outcome,
            ["continued", "failed", "unresolved"],
            "launch outcome",
        );
        enumValue(
            row.source_kind,
            ["reversal", "breakout", "acceleration"],
            "launch source kind",
        );
        for (const key of [
            "pre_slope",
            "post_slope",
            "support",
            "sustain_sessions",
            "relative_strength",
            "gain_percent",
            "drawdown_percent",
        ]) {
            if (!(key in row)) fail(`missing launch ${key}`);
            if (
                row[key] !== null ||
                ![
                    "relative_strength",
                    "gain_percent",
                    "drawdown_percent",
                ].includes(key)
            )
                number(row[key], `launch.${key}`);
        }
        launches.set(id, {
            launch_id: id,
            method_id: method.method_id,
            case_id: sample.case_id,
            security_id: sample.security_id,
            candidate_date: candidate,
            range_first_date: first,
            range_last_date: last,
        });
    }
    for (const row of table(preview.phases, "phase_id", "phases").values()) {
        context(row, ["start_date", "end_date"], false);
        if (String(row.start_date) > String(row.end_date))
            fail("invalid source phase interval");
        enumValue(
            row.source_label,
            ["falling", "flat", "rising", "fast"],
            "source phase label",
        );
        number(row.log_slope_per_quote_interval, "phase slope");
    }
    const quality = new Map<string, Set<string>>();
    for (const entry of list(preview.quality_events, "quality_events")) {
        const row = object(entry, "quality event");
        const sample = series.get(text(row.case_id, "quality case"));
        if (
            !sample ||
            row.security_id !== sample.security_id ||
            !sample.points.some(
                (point) => point.date === date(row.date, "quality date"),
            )
        )
            fail("unknown quality event case/security/date");
        const key = JSON.stringify([sample.case_id, row.date]);
        const flags = quality.get(key) ?? new Set<string>();
        strings(row.flags, "quality flags").forEach((flag) => flags.add(flag));
        quality.set(key, flags);
    }
    for (const wave of waves.values()) {
        const sample = series.get(wave.case_id)!;
        let maximum = 0;
        for (const point of sample.points) {
            if (
                point.date < wave.start_date ||
                point.date > wave.observed_through
            )
                continue;
            if (
                point.adjusted === null ||
                point.adjusted <= 0 ||
                point.flags.length > 0 ||
                (quality.get(JSON.stringify([wave.case_id, point.date]))
                    ?.size ?? 0) > 0
            )
                fail("wave peak requires a clean adjusted-price interval");
            maximum = Math.max(maximum, point.adjusted);
        }
        const peakPrice = sample.points.find(
            (point) => point.date === wave.peak_date,
        )!.adjusted;
        // Any observed day tied at the maximum is valid; never select a new date.
        if (peakPrice !== maximum) fail("wave peak is not an interval maximum");
    }
    const sourceCandidatePairs = new Set<string>();
    for (const entry of list(preview.relations, "relations")) {
        const relation = object(entry, "relation");
        const wave = waves.get(text(relation.wave_id, "relation wave"));
        if (!wave) fail("unknown relation wave");
        bool(relation.provisional, "relation provisional");
        if (relation.kind === "candidate_in_wave") {
            const launch = launches.get(
                text(relation.launch_id, "relation launch"),
            );
            if (
                !launch ||
                launch.method_id !== wave.method_id ||
                launch.candidate_date < wave.start_date ||
                launch.candidate_date > wave.observed_through
            )
                fail("invalid candidate relation");
            if (relation.provisional === false)
                sourceCandidatePairs.add(
                    JSON.stringify([wave.wave_id, launch.launch_id]),
                );
        } else {
            enumValue(relation.kind, ["parent", "overlap"], "relation kind");
            const other = waves.get(
                text(relation.other_wave_id, "relation other wave"),
            );
            if (
                !other ||
                other.wave_id === wave.wave_id ||
                other.method_id !== wave.method_id
            )
                fail("invalid wave relation");
            if (
                relation.kind === "parent" &&
                wave.parent_wave_id !== other.wave_id
            )
                fail("inconsistent parent relation");
        }
    }
    const selections = new Map<string, Selection>();
    for (const entry of list(selectionValue, "selections")) {
        const row = object(entry, "selection");
        const wave = waves.get(text(row.wave_id, "selection.wave_id"));
        if (!wave || !("launch_id" in row))
            fail("explicit known wave_id and launch_id are required");
        if (series.get(wave.case_id)!.kind !== exportKind)
            fail("selection belongs to an excluded case kind");
        if (selections.has(wave.security_id))
            fail(`duplicate selected security: ${wave.security_id}`);
        const launchId =
            row.launch_id === null
                ? null
                : text(row.launch_id, "selection.launch_id");
        if (launchId !== null) {
            const launch = launches.get(launchId);
            if (
                !launch ||
                launch.method_id !== wave.method_id ||
                launch.case_id !== wave.case_id ||
                launch.security_id !== wave.security_id
            )
                fail("unknown or cross-case/method selected launch");
            if (
                launch.candidate_date < wave.start_date ||
                launch.candidate_date > wave.observed_through
            )
                fail("selected launch is outside wave lifecycle");
            if (
                wave.end_confirmed_at !== null &&
                launch.candidate_date >= wave.end_confirmed_at
            )
                fail(
                    "selected launch has no active interval before confirmed end",
                );
            if (
                !sourceCandidatePairs.has(
                    JSON.stringify([wave.wave_id, launchId]),
                )
            )
                fail(
                    "selected launch requires a non-provisional source wave relation",
                );
        }
        selections.set(wave.security_id, {
            wave_id: wave.wave_id,
            launch_id: launchId,
        });
    }
    const exportedSeries = [...series.values()].filter(
        (sample) => sample.kind === exportKind,
    );
    if (exportedSeries.length === 0) fail(`no ${exportKind} cases to export`);
    const exportedCaseIds = new Set(
        exportedSeries.map((sample) => sample.case_id),
    );
    const exportedMethods = [...methods.values()].filter((method) =>
        exportedCaseIds.has(method.case_id),
    );
    const exportedWaves = [...waves.values()].filter((wave) =>
        exportedCaseIds.has(wave.case_id),
    );
    limitations.push(
        `輸出種類篩選：${exportKind}；保留 ${exportedSeries.length} 個案例，原始來源其他 ${series.size - exportedSeries.length} 個案例未混入此 bundle。`,
    );
    limitations.push(
        "展示政策 v1：固定代表選擇覆蓋此 bundle 全日期；已確認結束事件在案例截止後仍保留 ended，與研究 project_day 的案例截止後 unknown 不同；未結束波段仍在 observedThrough 後 unknown。",
    );
    const dates = [
        ...new Set(
            exportedSeries.flatMap((row) =>
                row.points.map((point) => point.date),
            ),
        ),
    ].sort();
    const sources: SourceRef[] = [
        {
            id: "preview-file",
            label: "Original preview stored bytes",
            path: identity.inputPath,
            hash: identity.inputHash,
        },
        {
            id: "preview-json",
            label: "Original preview uncompressed JSON bytes; includes all source phase observations",
            path: identity.inputPath,
            hash: identity.jsonHash,
        },
        {
            id: "presentation-selections",
            label: "Explicit presentation selections; fixed across dates",
            path: identity.selectionsPath,
            hash: identity.selectionsHash,
        },
        {
            id: "producer-code-commit",
            label: `Producer code commit: ${identities.code_commit}`,
        },
        ...Object.entries(codeHashes).map(([path, value]) => ({
            id: `producer-code:${path}`,
            label: `Producer source code: ${path}`,
            path,
            hash: String(value),
        })),
        ...[
            "input_sha256",
            "input_hash",
            "projection_hash",
            "catalog_hash",
        ].map((key) => ({
            id: `producer:${key}`,
            label: `Producer ${key}${key === "input_sha256" ? ` (${identities.input_identity_basis})` : ""}`,
            hash: String(identities[key]),
        })),
    ];
    if (identities.classification_sha256 !== undefined)
        sources.push({
            id: "snapshot-classification",
            label: `Snapshot-only classification: ${identities.classification_source_ref}`,
            hash: String(identities.classification_sha256),
        });
    for (const method of exportedMethods)
        sources.push({
            id: `method:${method.method_id}`,
            label: `${method.source_method}/${method.scale}; rule=${method.rule_version}; numerically_valid=${method.numerically_valid}; exploratory`,
            path: identity.inputPath,
            hash: identity.jsonHash,
        });
    const securities: OpportunitySecurity[] = exportedSeries.map((sample) => {
        const sourceId = `case:${sample.case_id}`;
        const snapshotSourceId = `snapshot-classification:${sample.case_id}`;
        if (sample.snapshotIndustry)
            sources.push({
                id: snapshotSourceId,
                label: `Snapshot-only classification: ${sample.snapshotIndustry.label}`,
                path: sample.snapshotIndustry.sourceRef,
                hash: String(identities.classification_sha256),
            });
        sources.push({
            id: sourceId,
            label: `${sample.source.label}; ${sample.start_date}..${sample.observed_through}; ${sample.source.priceBasis}`,
            path: identity.inputPath,
            hash:
                sample.source.hash === undefined
                    ? identity.jsonHash
                    : String(sample.source.hash),
        });
        const selection = selections.get(sample.security_id);
        const method = selection
            ? methods.get(waves.get(selection.wave_id)!.method_id)
            : undefined;
        if (!selection)
            limitations.push(
                `${sample.security_id}: ${[...waves.values()].some((wave) => wave.security_id === sample.security_id) ? "未指定代表波段；不自動選擇" : "來源未記錄符合波段；保留股票與價格，未製造波段"}。`,
            );
        if (method && !method.numerically_valid)
            limitations.push(
                `${sample.security_id}: 所選方法未收斂，衍生 method-not-converged 標記使版圖保持未知；來源價格未變更。`,
            );
        limitations.push(
            ...(sample.source.limitations as string[]).map(
                (limitation) => `${sample.security_id}: ${limitation}`,
            ),
        );
        return {
            id: sample.security_id,
            code: sample.security_id.replace(/^[^:]+:/, ""),
            name: sample.name,
            market: sample.kind === "historical" ? "TW" : "SYNTHETIC",
            currency: sample.kind === "historical" ? "TWD" : "SYNTHETIC",
            detailCaseId: sample.case_id,
            ...(sample.snapshotIndustry
                ? {
                      classificationSnapshot: {
                          label: sample.snapshotIndustry.label,
                          observedAt: sample.snapshotIndustry.observedAt,
                          sourceId: snapshotSourceId,
                      },
                  }
                : {}),
            industry: [
                {
                    id: "unknown",
                    label: "產業資料未知",
                    from: sample.start_date,
                    untilExclusive: nextDay(sample.observed_through),
                    basis: "unknown",
                    sourceId,
                },
            ],
            prices: sample.points.map((point) => {
                const flags = new Set([
                    ...point.flags,
                    ...(quality.get(
                        JSON.stringify([sample.case_id, point.date]),
                    ) ?? []),
                ]);
                if (point.adjusted === null || point.adjusted <= 0)
                    flags.add("missing_or_invalid_adjusted_quote");
                if (method && !method.numerically_valid)
                    flags.add(`method-not-converged:${method.method_id}`);
                return {
                    date: point.date,
                    close:
                        point.adjusted !== null && point.adjusted > 0
                            ? point.adjusted
                            : null,
                    raw: point.raw !== null && point.raw > 0 ? point.raw : null,
                    flags: [...flags],
                };
            }),
        };
    });
    const bundleWaves: OpportunityWave[] = exportedWaves.map((wave) => {
        const selection = selections.get(wave.security_id);
        const selected = selection?.wave_id === wave.wave_id;
        const launch =
            selected && selection.launch_id !== null
                ? launches.get(selection.launch_id)
                : undefined;
        return {
            id: wave.wave_id,
            securityId: wave.security_id,
            start: wave.start_date,
            launch: launch
                ? {
                      date: launch.candidate_date,
                      rangeFrom: launch.range_first_date,
                      rangeUntil: launch.range_last_date,
                      sourceId: `method:${wave.method_id}`,
                  }
                : null,
            launchMissingReason: launch
                ? null
                : selected
                  ? "explicit-no-launch-selection"
                  : "no-presentation-launch-selected-for-wave",
            peakDate: wave.peak_date,
            endConfirmedAt: wave.end_confirmed_at,
            observedThrough: wave.observed_through,
            leftCensored: wave.left_censored,
            rightCensored: wave.right_censored,
            scale: wave.scale,
            parentId: wave.parent_wave_id,
            sourceId: `method:${wave.method_id}`,
            phases: [],
        };
    });
    return validateBundle({
        schema: "opportunity-explorer.v1",
        id: `preview-${identity.jsonHash.slice(0, 12)}-${identity.selectionsHash.slice(0, 12)}`,
        label:
            exportKind === "historical"
                ? "歷史案例機會預覽（只含歷史；明示代表選擇）"
                : "合成案例機會預覽（只含合成；明示代表選擇）",
        kind: exportKind === "historical" ? "historical-preview" : "synthetic",
        asOf: dates.at(-1)!,
        dates,
        priceBasis: [
            ...new Set(
                exportedSeries.map((sample) =>
                    String(sample.source.priceBasis),
                ),
            ),
        ].join("; "),
        catalogCoverage: "case-slice",
        ruleVersion:
            [
                ...new Set(
                    exportedMethods.map((method) => method.rule_version),
                ),
            ].join("; ") || "no-source-method",
        selectionPolicy: `${ADAPTER_VERSION}; explicit-fixed-wave-and-launch; selection-sha256=${identity.selectionsHash}`,
        classificationVersion: "historical_effective_period_unverified",
        sources,
        limitations,
        securities,
        waves: bundleWaves,
        representatives: [...selections.values()].map((selection) => {
            const wave = waves.get(selection.wave_id)!;
            return {
                securityId: wave.security_id,
                waveId: wave.wave_id,
                from: dates[0],
                untilExclusive: nextDay(dates.at(-1)!),
            };
        }),
        portfolios: [],
    });
}

export async function exportOpportunityPreview(
    inputPath: string,
    selectionsPath: string,
    outputPath: string,
    kind: "historical" | "synthetic" = "historical",
): Promise<OpportunityBundle> {
    const input = resolve(inputPath);
    const selections = resolve(selectionsPath);
    const output = resolve(outputPath);
    const stored = await readFile(input);
    const json = input.toLowerCase().endsWith(".gz")
        ? gunzipSync(stored, { maxOutputLength: 64 * 1024 * 1024 })
        : stored;
    const selectionBytes = await readFile(selections);
    const bundle = adaptPreview(
        JSON.parse(json.toString("utf8").replace(/^\uFEFF/, "")),
        JSON.parse(selectionBytes.toString("utf8").replace(/^\uFEFF/, "")),
        {
            inputPath: input,
            inputHash: sha256(stored),
            jsonHash: sha256(json),
            selectionsPath: selections,
            selectionsHash: sha256(selectionBytes),
        },
        kind,
    );
    await writeFile(output, `${JSON.stringify(bundle, null, 2)}\n`, {
        encoding: "utf8",
        flag: "wx",
    });
    return bundle;
}

async function main() {
    const options = new Map<string, string>();
    const args = process.argv.slice(2);
    for (let i = 0; i < args.length; i += 2) {
        const key = args[i];
        const value = args[i + 1];
        if (
            !["--input", "--selections", "--output", "--kind"].includes(key) ||
            !value ||
            value.startsWith("--") ||
            options.has(key)
        )
            throw new Error(`Invalid argument: ${key}`);
        options.set(key, value);
    }
    if (
        !["--input", "--selections", "--output"].every((key) =>
            options.has(key),
        )
    )
        throw new Error(
            "Usage: node --experimental-strip-types scripts/export-opportunity-preview.mts --input preview.json[.gz] --selections selections.json --output new-bundle.json [--kind historical|synthetic]",
        );
    const kind = enumValue(
        options.get("--kind") ?? "historical",
        ["historical", "synthetic"],
        "export kind",
    );
    const bundle = await exportOpportunityPreview(
        options.get("--input")!,
        options.get("--selections")!,
        options.get("--output")!,
        kind,
    );
    process.stdout.write(
        `${JSON.stringify({ schema: bundle.schema, id: bundle.id, securities: bundle.securities.length, waves: bundle.waves.length, selected: bundle.representatives.length, output: resolve(options.get("--output")!) })}\n`,
    );
}

if (
    process.argv[1] &&
    resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    main().catch((error: unknown) => {
        process.stderr.write(
            `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 1;
    });
}
