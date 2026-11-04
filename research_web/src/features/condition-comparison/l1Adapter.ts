import type {
    ComparisonView,
    Counts,
    Horizon,
    Summary,
    WindowView,
    TraceReference,
} from "./model.ts";

const HORIZONS = [126, 252] as const;
const VOLS = ["vol_le_0_7", "vol_gt_0_7"] as const;
const GS = ["g_ge_1_5", "g_lt_1_5"] as const;
const STATUSES = ["known", "feature_unknown", "not_applicable"] as const;
const UNAVAILABLE_PAIRS = [
    "known|feature_unknown",
    "known|not_applicable",
    "feature_unknown|known",
    "feature_unknown|feature_unknown",
    "feature_unknown|not_applicable",
    "not_applicable|known",
    "not_applicable|feature_unknown",
    "not_applicable|not_applicable",
] as const;
const COUNT_KEYS = [
    "event_n",
    "distinct_stock_n",
    "per_stock_event_count_median",
    "per_stock_event_count_max",
    "known_n",
    "unknown_n",
    "censored_n",
    "excluded_known_n",
    "hit_n",
    "loss_n",
    "flat_win_n",
    "hit_rate",
    "loss_rate",
    "observed_hit_n",
    "full_calendar_n",
    "full_calendar_unknown_n",
    "full_calendar_observed_hit_n",
    "censored_unknown_n",
    "censored_observed_hit_n",
    "full_main_potential_n",
    "full_eligibility_excluded_n",
    "censored_eligibility_excluded_n",
    "censored_potential_n",
    "censored_hit_lower_bound",
    "censored_hit_upper_bound",
    "full_calendar_hit_lower_bound",
    "full_calendar_hit_upper_bound",
] as const;
const RATE_KEYS = new Set([
    "hit_rate",
    "loss_rate",
    "censored_hit_lower_bound",
    "censored_hit_upper_bound",
    "full_calendar_hit_lower_bound",
    "full_calendar_hit_upper_bound",
]);
const DENOMINATORS: Record<string, string> = {
    hit_rate: "known_n",
    loss_rate: "known_n",
    censored_hit_lower_bound: "censored_potential_n",
    censored_hit_upper_bound: "censored_potential_n",
    full_calendar_hit_lower_bound: "full_main_potential_n",
    full_calendar_hit_upper_bound: "full_main_potential_n",
};
const SEMANTICS = {
    outcome_source: "research_core.pattern_scan_projection_v1.project_outcomes",
    summary_source: "research_core.pattern_scan_rates_v1.summarize_events",
    classification_source:
        "saved common_values via pattern_scan_conditions_v1.classify_column",
    partition:
        "Fix L1 union event IDs before conditions; same classification at both horizons.",
    boundaries: "VOL_a <= 0.7 / > 0.7; G >= 1.5 / < 1.5.",
    count_overlap:
        "unknown_n and censored_n overlap; eligibility exclusions can overlap both. None is loss.",
    stock_counts:
        "distinct_stock_n counts event-bearing stocks within this summary; do not add across cells or years.",
    zero_denominator:
        "Rates and bounds are null when their denominator is zero.",
    rate_denominators: DENOMINATORS,
    references:
        "At most three deterministic input event references per cell; not a representative sample or a file/URL locator.",
    provenance:
        "Caller assertions only. input_structure_verified means in-memory contract checks, not authentic-market-input certification.",
    research_scope:
        "Synthetic and pilot cells are not evaluated research conclusions; historical exposure never becomes unseen validation.",
};
const refKeys = ["event_id", "security_id", "t0", "horizon"];
interface ValidSummary extends Record<string, number | null> {
    event_n: number;
    distinct_stock_n: number;
    per_stock_event_count_median: number | null;
    per_stock_event_count_max: number;
    known_n: number;
    unknown_n: number;
    censored_n: number;
    excluded_known_n: number;
    hit_n: number;
    loss_n: number;
    flat_win_n: number;
    hit_rate: number | null;
    loss_rate: number | null;
    observed_hit_n: number;
    full_calendar_n: number;
    full_calendar_unknown_n: number;
    full_calendar_observed_hit_n: number;
    censored_unknown_n: number;
    censored_observed_hit_n: number;
    full_main_potential_n: number;
    full_eligibility_excluded_n: number;
    censored_eligibility_excluded_n: number;
    censored_potential_n: number;
    censored_hit_lower_bound: number | null;
    censored_hit_upper_bound: number | null;
    full_calendar_hit_lower_bound: number | null;
    full_calendar_hit_upper_bound: number | null;
}
function fail(message: string): never {
    throw new Error(`Invalid L1 comparison: ${message}`);
}
function obj(v: unknown, name: string): Record<string, any> {
    if (!v || typeof v !== "object" || Array.isArray(v))
        fail(`${name} must be an object`);
    return v as Record<string, any>;
}
function exact(v: Record<string, any>, keys: readonly string[], name: string) {
    if (Object.keys(v).length !== keys.length || keys.some((k) => !(k in v)))
        fail(`${name} fields mismatch`);
}
function text(v: unknown, name: string): asserts v is string {
    if (typeof v !== "string" || !v.trim()) fail(`${name} must be nonblank`);
}
function isoDate(v: unknown): v is string {
    return (
        typeof v === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(v) &&
        Number.isFinite(Date.parse(v)) &&
        new Date(v).toISOString().slice(0, 10) === v
    );
}
function same(a: unknown, b: unknown): boolean {
    if (a === b) return true;
    if (Array.isArray(a) || Array.isArray(b))
        return (
            Array.isArray(a) &&
            Array.isArray(b) &&
            a.length === b.length &&
            a.every((v, i) => same(v, b[i]))
        );
    if (!a || !b || typeof a !== "object" || typeof b !== "object")
        return false;
    const aa = a as Record<string, unknown>,
        bb = b as Record<string, unknown>,
        ak = Object.keys(aa).sort(),
        bk = Object.keys(bb).sort();
    return same(ak, bk) && ak.every((k) => same(aa[k], bb[k]));
}
function validateSummary(value: unknown, name: string): ValidSummary {
    const s = obj(value, name);
    exact(s, COUNT_KEYS, name);
    for (const key of COUNT_KEYS) {
        const n = s[key];
        if (RATE_KEYS.has(key)) {
            if (
                n !== null &&
                (typeof n !== "number" || !Number.isFinite(n) || n < 0 || n > 1)
            )
                fail(`${name}.${key} invalid rate`);
        } else if (key === "per_stock_event_count_median") {
            if (
                n !== null &&
                (typeof n !== "number" || !Number.isFinite(n) || n < 0)
            )
                fail(`${name}.${key} invalid`);
        } else if (!Number.isSafeInteger(n) || n < 0)
            fail(`${name}.${key} invalid count`);
    }
    if (s.hit_n + s.loss_n + s.flat_win_n !== s.known_n)
        fail(`${name} known labels do not partition`);
    if (
        s.known_n > s.event_n ||
        s.distinct_stock_n > s.event_n ||
        (s.event_n === 0 && s.distinct_stock_n !== 0)
    )
        fail(`${name} count bounds invalid`);
    if (
        s.censored_unknown_n > s.censored_n ||
        s.censored_observed_hit_n > s.censored_n ||
        s.censored_eligibility_excluded_n > s.censored_n ||
        s.censored_potential_n > s.censored_n ||
        s.full_calendar_unknown_n > s.full_calendar_n ||
        s.full_calendar_observed_hit_n > s.full_calendar_n ||
        s.full_eligibility_excluded_n > s.full_calendar_n
    )
        fail(`${name} calendar subset count invalid`);
    for (const key of [
        "known_n",
        "unknown_n",
        "censored_n",
        "excluded_known_n",
        "hit_n",
        "loss_n",
        "flat_win_n",
        "observed_hit_n",
        "full_calendar_n",
        "full_calendar_unknown_n",
        "full_calendar_observed_hit_n",
        "censored_unknown_n",
        "censored_observed_hit_n",
        "full_main_potential_n",
        "full_eligibility_excluded_n",
        "censored_eligibility_excluded_n",
        "censored_potential_n",
    ])
        if (s[key] > s.event_n) fail(`${name}.${key} exceeds event_n`);
    if (
        s.full_calendar_n + s.censored_n !== s.event_n ||
        s.full_calendar_unknown_n + s.censored_unknown_n !== s.unknown_n ||
        s.full_calendar_n !==
            s.known_n + s.excluded_known_n + s.full_calendar_unknown_n ||
        s.observed_hit_n !==
            s.full_calendar_observed_hit_n + s.censored_observed_hit_n ||
        s.observed_hit_n > s.event_n
    )
        fail(`${name} partition bounds invalid`);
    if (
        (s.event_n === 0) !== (s.distinct_stock_n === 0) ||
        (s.event_n === 0) !== (s.per_stock_event_count_median === null) ||
        s.per_stock_event_count_max > s.event_n ||
        (s.per_stock_event_count_median !== null &&
            (s.per_stock_event_count_median > s.per_stock_event_count_max ||
                s.per_stock_event_count_median < 1))
    )
        fail(`${name} stock summaries invalid`);
    if (s.hit_n > s.known_n || s.loss_n > s.known_n || s.flat_win_n > s.known_n)
        fail(`${name} labels exceed denominator`);
    for (const key of RATE_KEYS) {
        const denominator = s[DENOMINATORS[key]];
        if (denominator === 0 && s[key] !== null)
            fail(`${name}.${key} must be null at zero denominator`);
        if (denominator > 0 && s[key] === null)
            fail(`${name}.${key} missing despite nonzero denominator`);
    }
    if (
        (s.censored_hit_lower_bound !== null &&
            s.censored_hit_upper_bound !== null &&
            s.censored_hit_lower_bound > s.censored_hit_upper_bound) ||
        (s.full_calendar_hit_lower_bound !== null &&
            s.full_calendar_hit_upper_bound !== null &&
            s.full_calendar_hit_lower_bound > s.full_calendar_hit_upper_bound)
    )
        fail(`${name} rate bounds inverted`);
    if (
        s.known_n > 0 &&
        (Math.abs(s.hit_rate - s.hit_n / s.known_n) > 1e-10 ||
            Math.abs(s.loss_rate - s.loss_n / s.known_n) > 1e-10)
    )
        fail(`${name} observed rates contradict known_n`);
    return s as ValidSummary;
}
function references(
    value: unknown,
    stocks: Set<string>,
    horizon: number,
    name: string,
    eventN: number,
    stockN: number,
) {
    if (!Array.isArray(value) || value.length > 3)
        fail(`${name} must contain at most three references`);
    const ids = new Set<string>();
    for (const raw of value) {
        const r = obj(raw, name);
        exact(r, refKeys, name);
        text(r.event_id, "event_id");
        text(r.security_id, "security_id");
        if (
            !stocks.has(r.security_id) ||
            !isoDate(r.t0) ||
            r.horizon !== horizon ||
            ids.has(r.event_id)
        )
            fail(`${name} reference invalid or duplicated`);
        ids.add(r.event_id);
    }
    const referencedSecurities = new Set(
        value.map((reference) => reference.security_id),
    );
    if (value.length > eventN || referencedSecurities.size > stockN)
        fail(`${name} references exceed summary counts`);
    return value as TraceReference[];
}
function evaluation(
    value: unknown,
    scope: string,
    name: string,
): { status: "evaluated" | "not_evaluated"; reason: string } {
    const e = obj(value, name);
    exact(e, ["status", "reason"], name);
    text(e.reason, `${name}.reason`);
    const expected =
        scope === "full"
            ? { status: "evaluated", reason: "historical_descriptive_only" }
            : {
                  status: "not_evaluated",
                  reason:
                      scope === "synthetic"
                          ? "synthetic_only"
                          : "pilot_only_no_full_research_validation",
              };
    if (!same(e, expected)) fail(`${name} conflicts with research scope`);
    return {
        status: e.status as "evaluated" | "not_evaluated",
        reason: e.reason,
    };
}
function mapSummary(
    saved: ValidSummary,
    status: "evaluated" | "not_evaluated",
    reason: string,
): Summary {
    const counts: Counts = {
        hit: saved.hit_n,
        known: saved.known_n,
        stocks: saved.distinct_stock_n,
        unknown: saved.unknown_n,
        censored: saved.censored_n,
    };
    return {
        status: status === "evaluated" ? "evaluated" : "not-evaluated",
        reason,
        saved,
        counts,
    };
}

export function adaptL1Comparison(saved: unknown, id: string): ComparisonView {
    if (!id.trim()) fail("display id required");
    const root = obj(saved, "root");
    exact(
        root,
        [
            "schema_version",
            "synthetic",
            "provenance",
            "cohort",
            "semantics",
            "horizons",
        ],
        "root",
    );
    if (root.schema_version !== "l1-volume-comparison.v1")
        fail("unknown schema");
    const p = obj(root.provenance, "provenance");
    const provenanceKeys = [
        "scope",
        "data_id",
        "definition_id",
        "code_commit",
        "source_id",
        "generation",
        "actual_selected_stocks",
        "historical_exposed",
        "validation_scope",
        "input_id",
        "base_label_version_id",
        "base_label_manifest_sha256",
    ];
    exact(p, provenanceKeys, "provenance");
    if (
        !["synthetic", "pilot", "full"].includes(p.scope) ||
        root.synthetic !== (p.scope === "synthetic") ||
        p.historical_exposed !== true
    )
        fail("scope/synthetic/exposure mismatch");
    for (const k of [
        "data_id",
        "definition_id",
        "code_commit",
        "source_id",
        "generation",
        "input_id",
        "base_label_version_id",
    ])
        text(p[k], `provenance.${k}`);
    if (
        p.source_id !== p.definition_id ||
        typeof p.base_label_manifest_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(p.base_label_manifest_sha256)
    )
        fail("source identity digest mismatch");
    const stocks = p.actual_selected_stocks;
    if (
        !Array.isArray(stocks) ||
        !stocks.length ||
        stocks.some((s) => typeof s !== "string" || !s.trim()) ||
        new Set(stocks).size !== stocks.length
    )
        fail("selected stocks invalid");
    if (
        (p.scope === "pilot" && stocks.length > 5) ||
        (p.scope === "synthetic" &&
            stocks.some((s: string) => !s.startsWith("SYNTH-")))
    )
        fail("scope stock restrictions violated");
    const validation = obj(p.validation_scope, "validation_scope");
    exact(
        validation,
        [
            "input_structure_verified",
            "full_q1_parity",
            "marginal_parity",
            "unseen_validation",
        ],
        "validation_scope",
    );
    if (
        Object.values(validation).some((v) => typeof v !== "boolean") ||
        !validation.input_structure_verified ||
        validation.unseen_validation ||
        (p.scope === "full" &&
            (!validation.full_q1_parity || !validation.marginal_parity)) ||
        (p.scope !== "full" &&
            (validation.full_q1_parity || validation.marginal_parity))
    )
        fail("validation claims conflict with scope");
    const cohort = obj(root.cohort, "cohort");
    exact(cohort, ["pattern_id", "cohort_id", "horizons", "event_n"], "cohort");
    if (
        cohort.pattern_id !== "L1" ||
        cohort.cohort_id !== "union" ||
        !same(cohort.horizons, HORIZONS) ||
        !Number.isSafeInteger(cohort.event_n) ||
        cohort.event_n < 0
    )
        fail("cohort identity invalid");
    if (!same(root.semantics, SEMANTICS)) fail("semantics unknown or changed");
    if (!Array.isArray(root.horizons) || root.horizons.length !== 2)
        fail("exact horizons required");
    const byHorizon = new Map<number, any>();
    const referenceIdentityByHorizon = new Map<number, Map<string, string>>();
    for (let hi = 0; hi < 2; hi++) {
        const h = obj(root.horizons[hi], `horizon ${hi}`);
        exact(
            h,
            ["horizon", "cohort", "cells", "unavailable"],
            `horizon ${hi}`,
        );
        const hn = HORIZONS[hi];
        if (h.horizon !== hn) fail("horizons must be exact and ordered");
        const hs = validateSummary(h.cohort, `h${hn} cohort`);
        if (
            hs.event_n !== cohort.event_n ||
            hs.distinct_stock_n > stocks.length
        )
            fail("cohort event or selected-stock count mismatch");
        if (
            !Array.isArray(h.cells) ||
            h.cells.length !== 4 ||
            !Array.isArray(h.unavailable) ||
            h.unavailable.length !== 8
        )
            fail("four cells and eight unavailable pairs required");
        const cells: Record<string, any> = {};
        const unavailable = [];
        let partition = 0;
        const additive: Record<string, number> = {};
        const seenRefIds = new Set<string>();
        const refsById = new Map<string, string>();
        for (let i = 0; i < 4; i++) {
            const c = obj(h.cells[i], "cell");
            exact(
                c,
                [
                    "cell_id",
                    "vol_a_group",
                    "g_group",
                    "summary",
                    "evaluation_status",
                    "references",
                ],
                "cell",
            );
            const vol = VOLS[Math.floor(i / 2)],
                g = GS[i % 2],
                cellId = `${vol}__${g}`;
            if (
                c.cell_id !== cellId ||
                c.vol_a_group !== vol ||
                c.g_group !== g ||
                cells[cellId]
            )
                fail("cell identity/order/duplicate invalid");
            cells[cellId] = c;
            const sum = validateSummary(c.summary, cellId);
            partition += sum.event_n;
            const evalResult = evaluation(c.evaluation_status, p.scope, cellId),
                status = evalResult.status;
            if (sum.distinct_stock_n > stocks.length)
                fail(`${cellId} stock count exceeds selection`);
            const refs = references(
                c.references,
                new Set(stocks),
                hn,
                cellId,
                sum.event_n,
                sum.distinct_stock_n,
            );
            for (const ref of refs) {
                if (seenRefIds.has(ref.event_id))
                    fail("event reference appears in multiple partitions");
                seenRefIds.add(ref.event_id);
                refsById.set(
                    ref.event_id,
                    JSON.stringify([cellId, ref.security_id, ref.t0]),
                );
            }
            for (const k of COUNT_KEYS)
                if (
                    !RATE_KEYS.has(k) &&
                    k !== "distinct_stock_n" &&
                    k !== "per_stock_event_count_median" &&
                    k !== "per_stock_event_count_max"
                )
                    additive[k] = (additive[k] ?? 0) + Number(sum[k]);
            if (
                hi === 1 &&
                byHorizon.get(126).cells[cellId].sum.event_n !== sum.event_n
            )
                fail("cell membership differs across horizons");
            cells[cellId] = { sum, status, refs: c.references };
        }
        const unavailableKeys = new Set<string>();
        for (let ui = 0; ui < h.unavailable.length; ui++) {
            const u = obj(h.unavailable[ui], "unavailable");
            exact(
                u,
                [
                    "G_status",
                    "VOL_a_status",
                    "summary",
                    "evaluation_status",
                    "references",
                    "reason_counts",
                ],
                "unavailable",
            );
            const key = `${u.G_status}|${u.VOL_a_status}`;
            if (
                !STATUSES.includes(u.G_status) ||
                !STATUSES.includes(u.VOL_a_status) ||
                key === "known|known" ||
                unavailableKeys.has(key)
            )
                fail("unavailable pair invalid/duplicate");
            unavailableKeys.add(key);
            if (key !== UNAVAILABLE_PAIRS[ui])
                fail("unavailable pairs must follow producer order");
            const sum = validateSummary(u.summary, key);
            partition += sum.event_n;
            const evalResult = evaluation(u.evaluation_status, p.scope, key),
                status = evalResult.status;
            if (sum.distinct_stock_n > stocks.length)
                fail("unavailable stock count exceeds selection");
            for (const k of COUNT_KEYS)
                if (
                    !RATE_KEYS.has(k) &&
                    k !== "distinct_stock_n" &&
                    k !== "per_stock_event_count_median" &&
                    k !== "per_stock_event_count_max"
                )
                    additive[k] = (additive[k] ?? 0) + Number(sum[k]);
            const rc = obj(u.reason_counts, "reason_counts");
            exact(rc, ["G", "VOL_a"], "reason_counts");
            const reasons: Record<
                string,
                Array<{ reason: string; event_n: number }>
            > = {};
            for (const f of ["G", "VOL_a"]) {
                if (!Array.isArray(rc[f])) fail("reason counts must be arrays");
                const featureStatus = f === "G" ? u.G_status : u.VOL_a_status;
                const seen = new Set<string>();
                reasons[f] = rc[f].map((r0: unknown) => {
                    const r = obj(r0, "reason count");
                    exact(r, ["reason", "event_n"], "reason count");
                    text(r.reason, "reason");
                    if (
                        !Number.isSafeInteger(r.event_n) ||
                        r.event_n < 1 ||
                        seen.has(r.reason)
                    )
                        fail("invalid duplicate reason count");
                    seen.add(r.reason);
                    return { reason: r.reason, event_n: r.event_n } as {
                        reason: string;
                        event_n: number;
                    };
                });
                if (
                    (featureStatus === "known" && reasons[f].length) ||
                    (featureStatus !== "known" &&
                        reasons[f].reduce((n, r) => n + r.event_n, 0) !==
                            sum.event_n)
                )
                    fail("reason totals do not match feature status partition");
            }
            const refs = references(
                u.references,
                new Set(stocks),
                hn,
                key,
                sum.event_n,
                sum.distinct_stock_n,
            );
            for (const ref of refs) {
                if (seenRefIds.has(ref.event_id))
                    fail("event reference appears in multiple partitions");
                seenRefIds.add(ref.event_id);
                refsById.set(
                    ref.event_id,
                    JSON.stringify([key, ref.security_id, ref.t0]),
                );
            }
            unavailable.push({
                id: key,
                GStatus: u.G_status,
                volStatus: u.VOL_a_status,
                summary: mapSummary(sum, status, evalResult.reason),
                reasons,
                references: refs,
            });
        }
        if (unavailableKeys.size !== 8 || partition !== hs.event_n)
            fail("status pairs or event partition incomplete");
        for (const k of Object.keys(additive))
            if (additive[k] !== hs[k])
                fail(`partitions do not add to cohort for ${k}`);
        referenceIdentityByHorizon.set(hn, refsById);
        if (hi === 1) {
            for (const [key, c] of Object.entries(cells)) {
                const prev = byHorizon.get(126).cells[key];
                if (prev.sum.event_n !== c.sum.event_n)
                    fail("cell membership differs by horizon");
            }
            for (let i = 0; i < 8; i++) {
                const earlier = root.horizons[0].unavailable[i],
                    later = h.unavailable[i];
                if (
                    earlier.summary.event_n !== later.summary.event_n ||
                    earlier.summary.distinct_stock_n !==
                        later.summary.distinct_stock_n
                )
                    fail("unavailable membership differs by horizon");
            }
            const prior = referenceIdentityByHorizon.get(126)!;
            for (const [event, identity] of refsById) {
                const older = prior.get(event);
                if (older && older !== identity)
                    fail("trace identity differs across horizons");
            }
        }
        byHorizon.set(hn, { cells, unavailable, cohort: hs });
    }
    const windows: Partial<Record<Horizon, WindowView>> = {};
    for (const hn of HORIZONS) {
        const h = byHorizon.get(hn);
        const raw = root.horizons.find((x: any) => x.horizon === hn);
        const cells: Record<string, Summary> = {},
            refs: Record<string, any> = {};
        const cellMap: Record<
            string,
            "prior-only" | "both" | "today-only" | "neither"
        > = {
            vol_le_0_7__g_ge_1_5: "both",
            vol_le_0_7__g_lt_1_5: "prior-only",
            vol_gt_0_7__g_ge_1_5: "today-only",
            vol_gt_0_7__g_lt_1_5: "neither",
        };
        for (const vol of VOLS)
            for (const g of GS) {
                const key = `${vol}__${g}`,
                    c = h.cells[key],
                    cell = cellMap[key];
                cells[cell] = mapSummary(
                    c.sum,
                    c.status,
                    raw.cells.find((x: any) => x.cell_id === key)
                        .evaluation_status.reason,
                );
                refs[cell] = c.refs;
            }
        windows[hn] = {
            all: mapSummary(
                h.cohort,
                p.scope === "full" ? "evaluated" : "not_evaluated",
                p.scope === "full"
                    ? "historical_descriptive_only"
                    : p.scope === "synthetic"
                      ? "synthetic_only"
                      : "pilot_only_no_full_research_validation",
            ),
            cells,
            complements: {},
            cases: [],
            caseCoverage:
                "Producer supplied aggregate summaries and trace references; no SavedCase records are provided.",
            unavailable: h.unavailable,
            references: refs,
        };
    }
    const source = {
        studyId: "20261013-pattern-scan",
        resultId: id,
        settingsVersion: root.schema_version,
        outcomeDefinition: `${root.semantics.outcome_source}; effective definition version not separately declared`,
        inputVersion: String(p.input_id),
        priceBasis: `Not declared by producer; source generation ${p.generation}`,
        population: `${p.scope} L1 union; ${stocks.length} selected stocks; historical exposure`,
        source: `${p.source_id}; code ${p.code_commit}; labels ${p.base_label_version_id}; manifest ${p.base_label_manifest_sha256}`,
    };
    return {
        id,
        synthetic: root.synthetic,
        source,
        windows,
        producer: {
            schemaVersion: root.schema_version,
            scope: p.scope,
            provenance: p,
            semantics: root.semantics,
        },
    };
}
