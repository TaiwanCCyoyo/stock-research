import type { ResearchMethod, SourceRef } from "./types.ts";

/** Saved native run evidence; independent of retrospective price-opportunity scores. */
export interface SavedResearchRun {
    id: string;
    name: string;
    from: string;
    through: string;
    currency: string;
    initialCapital: number;
    finalEquity: number;
    netReturn: number;
    costs: number;
    method: ResearchMethod;
    valuationBasis: string;
    limitations: string[];
    sourceIds: string[];
    nav: { date: string; equity: number }[];
    events: {
        id: string;
        date: string;
        action: string;
        code: string | null;
        quantity: number | null;
        price: number | null;
        cashFlow: number | null;
        original: Record<string, unknown>;
    }[];
}
export interface SavedResearchBundle {
    schema: "saved-research-runs.v1";
    asOf: string;
    sources: SourceRef[];
    runs: SavedResearchRun[];
}

export function validateResearchBundle(value: unknown): SavedResearchBundle {
    const fail = (reason: string): never => {
        throw new Error(`研究資料格式不符：${reason}`);
    };
    const object = (v: unknown): v is Record<string, unknown> =>
        !!v && typeof v === "object" && !Array.isArray(v);
    const str = (v: unknown): v is string =>
        typeof v === "string" && v.length > 0;
    const finite = (v: unknown): v is number =>
        typeof v === "number" && Number.isFinite(v);
    const day = (v: unknown): v is string =>
        str(v) &&
        /^\d{4}-\d{2}-\d{2}$/.test(v) &&
        Number.isFinite(Date.parse(`${v}T00:00:00Z`)) &&
        new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
    const strings = (v: unknown): v is string[] =>
        Array.isArray(v) && v.every(str);
    const timestamp = (v: unknown): v is string =>
        str(v) &&
        /^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\+08:00$/.test(
            v,
        ) &&
        day(v.slice(0, 10)) &&
        Number.isFinite(Date.parse(v));
    if (
        !object(value) ||
        value.schema !== "saved-research-runs.v1" ||
        !day(value.asOf) ||
        !Array.isArray(value.runs) ||
        !Array.isArray(value.sources)
    )
        fail("schema / dates / arrays");
    const sources = new Set<string>();
    for (const candidate of (value as { sources: unknown[] }).sources) {
        const source = object(candidate) ? candidate : fail("source identity");
        if (
            !object(source) ||
            !str(source.id) ||
            !str(source.label) ||
            sources.has(source.id)
        )
            fail("source identity");
        for (const key of ["path", "url", "publishedAt", "hash"])
            if (source[key] !== undefined && !str(source[key]))
                fail(`source.${key}`);
        if (
            source.hash !== undefined &&
            !/^[a-f0-9]{64}$/i.test(String(source.hash))
        )
            fail("source hash");
        sources.add(String(source.id));
    }
    const bundle = value as unknown as SavedResearchBundle;
    const ids = new Set<string>();
    for (const run of bundle.runs) {
        if (
            !object(run) ||
            !str(run.id) ||
            ids.has(run.id) ||
            !str(run.name) ||
            !day(run.from) ||
            !day(run.through) ||
            run.from > run.through
        )
            fail("run identity / scope");
        if (run.through > bundle.asOf)
            fail("run.through must not exceed bundle.asOf");
        ids.add(run.id);
        if (
            !finite(run.initialCapital) ||
            run.initialCapital <= 0 ||
            !finite(run.finalEquity) ||
            run.finalEquity < 0 ||
            !finite(run.netReturn) ||
            !finite(run.costs) ||
            run.costs < 0
        )
            fail("account metrics");
        if (
            Math.abs(run.finalEquity / run.initialCapital - 1 - run.netReturn) >
            1e-7
        )
            fail("net return reconciliation");
        if (
            !str(run.currency) ||
            !str(run.valuationBasis) ||
            !strings(run.limitations) ||
            !strings(run.sourceIds) ||
            run.sourceIds.length === 0 ||
            !run.sourceIds.every((id) => sources.has(id))
        )
            fail("run provenance");
        const method = run.method;
        if (
            !object(method) ||
            !str(method.taskId) ||
            !str(method.ruleVersion) ||
            !str(method.conclusion) ||
            !["exploratory", "failed", "incomplete", "accepted"].includes(
                method.status,
            ) ||
            !strings(method.rules) ||
            !strings(method.limitations) ||
            !object(method.parameters)
        )
            fail("method");
        for (const key of ["missionPath", "reportPath"] as const)
            if (method[key] !== undefined && !str(method[key]))
                fail(`method.${key}`);
        if (
            !Object.values(method.parameters).every(
                (v) =>
                    typeof v === "boolean" ||
                    typeof v === "string" ||
                    finite(v),
            )
        )
            fail("parameters");
        if (
            !Array.isArray(run.nav) ||
            !run.nav.length ||
            !Array.isArray(run.events)
        )
            fail("nav / events");
        let previous = "";
        for (const point of run.nav) {
            if (
                !object(point) ||
                !day(point.date) ||
                point.date <= previous ||
                point.date < run.from ||
                point.date > run.through ||
                !finite(point.equity) ||
                point.equity < 0
            )
                fail("NAV chronology / value");
            previous = point.date;
        }
        if (Math.abs(run.nav.at(-1)!.equity - run.finalEquity) > 0.02)
            fail("final NAV reconciliation");
        if (
            run.nav[0].date !== run.from ||
            run.nav.at(-1)!.date !== run.through
        )
            fail("NAV period endpoints must match run.from / run.through");
        const eventIds = new Set<string>();
        let previousEventTime = -Infinity;
        for (const event of run.events) {
            if (
                !object(event) ||
                !str(event.id) ||
                eventIds.has(event.id) ||
                !str(event.date) ||
                !str(event.action) ||
                !object(event.original)
            )
                fail("event identity");
            if (
                !timestamp(event.date) ||
                event.date.slice(0, 10) < run.from ||
                event.date.slice(0, 10) > run.through ||
                Date.parse(event.date) < previousEventTime
            )
                fail("event timestamp / scope / chronology");
            previousEventTime = Date.parse(event.date);
            for (const v of [event.quantity, event.price, event.cashFlow])
                if (v !== null && !finite(v)) fail("event number");
            if (event.code !== null && !str(event.code)) fail("event security");
            const original = event.original;
            if (original.date !== event.date)
                fail("event original.date / summary mismatch");
            if (
                !str(original.action) ||
                !original.action.trim() ||
                original.action !== event.action
            )
                fail("event original.action / summary mismatch");
            const originalCode = original.code ?? null;
            if (
                (originalCode !== null &&
                    (!str(originalCode) || !originalCode.trim())) ||
                originalCode !== event.code
            )
                fail("event original.code / summary mismatch");
            for (const [native, summary] of [
                ["qty", "quantity"],
                ["price", "price"],
                ["total", "cashFlow"],
            ] as const) {
                const originalValue = original[native] ?? null;
                if (
                    (originalValue !== null && !finite(originalValue)) ||
                    originalValue !== event[summary]
                )
                    fail(`event original.${native} / ${summary} mismatch`);
            }
            eventIds.add(event.id);
        }
    }
    return bundle;
}
