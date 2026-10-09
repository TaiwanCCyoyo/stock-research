import assert from "node:assert/strict";
import test from "node:test";
import { gunzipSync, gzipSync } from "node:zlib";
import { validateResearchBundle } from "./research.ts";
import type { SavedResearchBundle } from "./research.ts";

function fixture(): SavedResearchBundle {
    return {
        schema: "saved-research-runs.v1",
        asOf: "2026-10-04",
        sources: [{ id: "saved", label: "Saved native run" }],
        runs: [
            {
                id: "failed-candidate",
                name: "Failed candidate",
                from: "2020-01-02",
                through: "2020-01-03",
                currency: "TWD",
                initialCapital: 100,
                finalEquity: 110,
                netReturn: 0.1,
                costs: 1,
                method: {
                    taskId: "task",
                    status: "failed",
                    ruleVersion: "rules.v1",
                    rules: ["An explicitly saved rule"],
                    parameters: { approved: false },
                    conclusion:
                        "Positive profit did not meet the preregistered comparison.",
                    limitations: ["Exposed development period"],
                },
                valuationBasis: "Recorded evening raw marks",
                limitations: [],
                sourceIds: ["saved"],
                nav: [
                    { date: "2020-01-02", equity: 100 },
                    { date: "2020-01-03", equity: 110 },
                ],
                events: [
                    {
                        id: "event-0",
                        date: "2020-01-02T09:00:00+08:00",
                        action: "BUY",
                        code: "TEST",
                        quantity: 1,
                        price: 10,
                        cashFlow: -11,
                        original: {
                            date: "2020-01-02T09:00:00+08:00",
                            action: "BUY",
                            code: "TEST",
                            qty: 1,
                            price: 10,
                            total: -11,
                            commission_cents: 100,
                        },
                    },
                ],
            },
        ],
    };
}

test("positive net return never promotes a failed method; native event costs stay in original units", () => {
    const source = fixture();
    const copy = structuredClone(source);
    const parsed = validateResearchBundle(source);
    assert.equal(parsed.runs[0].method.status, "failed");
    assert.equal(parsed.runs[0].events[0].original.commission_cents, 100);
    assert.deepEqual(source, copy);
});

test("rejects summaries that contradict the retained native event", () => {
    const bundle = fixture();
    const event = bundle.runs[0].events[0];
    Object.assign(event.original, { action: "BUY", code: "1111", qty: 1 });
    Object.assign(event, { action: "SELL", code: "9999", quantity: 999 });
    assert.throws(() => validateResearchBundle(bundle), /event original/);
});

test("the summary timestamp must retain the exact original event date", () => {
    for (const side of ["summary", "original"]) {
        const bundle = fixture();
        const event = bundle.runs[0].events[0];
        if (side === "summary") event.date = "2020-01-03T09:00:00+08:00";
        else event.original.date = "2020-01-03T09:00:00+08:00";
        assert.throws(
            () => validateResearchBundle(bundle),
            /event original.date/,
        );
    }
    for (const date of [
        undefined,
        null,
        "2020-01-02T01:00:00Z",
        "2020-02-30T09:00:00+08:00",
    ]) {
        const bundle = fixture();
        if (date === undefined) delete bundle.runs[0].events[0].original.date;
        else bundle.runs[0].events[0].original.date = date;
        assert.throws(
            () => validateResearchBundle(bundle),
            /event original.date/,
        );
    }
});

test("each mapped summary and original field must agree exactly", () => {
    for (const [native, summary, changed] of [
        ["action", "action", "SELL"],
        ["code", "code", "9999"],
        ["qty", "quantity", 999],
        ["price", "price", 999],
        ["total", "cashFlow", 999],
    ] as const) {
        for (const side of ["summary", "original"]) {
            const bundle = fixture();
            const event = bundle.runs[0].events[0];
            if (side === "summary")
                Object.assign(event, { [summary]: changed });
            else event.original[native] = changed;
            assert.throws(
                () => validateResearchBundle(bundle),
                /event original/,
                `${side}.${side === "summary" ? summary : native}`,
            );
        }
    }
});

test("native optional fields map missing or null to null, retaining zeros and original contents", () => {
    for (const [native, summary] of [
        ["code", "code"],
        ["qty", "quantity"],
        ["price", "price"],
        ["total", "cashFlow"],
    ] as const) {
        for (const state of ["missing", "null"]) {
            const bundle = fixture();
            const event = bundle.runs[0].events[0];
            if (state === "missing") delete event.original[native];
            else event.original[native] = null;
            Object.assign(event, { [summary]: null });
            const original = structuredClone(bundle);
            assert.strictEqual(validateResearchBundle(bundle), bundle);
            assert.deepEqual(bundle, original);
            Object.assign(event, {
                [summary]: summary === "code" ? "9999" : 999,
            });
            assert.throws(
                () => validateResearchBundle(bundle),
                /event original/,
            );
        }
    }
    const zero = fixture();
    Object.assign(zero.runs[0].events[0], {
        quantity: 0,
        price: 0,
        cashFlow: 0,
    });
    Object.assign(zero.runs[0].events[0].original, {
        qty: 0,
        price: 0,
        total: 0,
        unmapped: { retained: true },
    });
    const original = structuredClone(zero);
    assert.strictEqual(validateResearchBundle(zero), zero);
    assert.deepEqual(zero, original);
});

test("unmappable native fields fail rather than inventing a mapping or coercing source values", () => {
    for (const [native, invalid] of [
        ["action", undefined],
        ["action", null],
        ["action", " "],
        ["code", 1111],
        ["code", " "],
        ["qty", "1"],
        ["price", { value: 10 }],
        ["total", Infinity],
    ]) {
        const bundle = fixture();
        const event = bundle.runs[0].events[0];
        if (invalid === undefined) delete event.original[String(native)];
        else event.original[String(native)] = invalid;
        assert.throws(() => validateResearchBundle(bundle), /event original/);
    }
    const alternate = fixture();
    delete alternate.runs[0].events[0].original.qty;
    alternate.runs[0].events[0].original.quantity = 1;
    assert.throws(() => validateResearchBundle(alternate), /original.qty/);
});
test("rejects unreconciled endpoint, truncated NAV and non-finite monetary values", () => {
    const wrong = fixture();
    wrong.runs[0].netReturn = 10;
    assert.throws(() => validateResearchBundle(wrong), /net return/);
    const truncated = fixture();
    truncated.runs[0].nav.pop();
    assert.throws(() => validateResearchBundle(truncated), /final NAV/);
    const infinite = fixture();
    infinite.runs[0].events[0].cashFlow = Infinity;
    assert.throws(() => validateResearchBundle(infinite), /event number/);
});
test("rejects ambiguous event identities and NAV chronology", () => {
    const duplicated = fixture();
    duplicated.runs[0].events.push({ ...duplicated.runs[0].events[0] });
    assert.throws(() => validateResearchBundle(duplicated), /event identity/);
    const unordered = fixture();
    unordered.runs[0].nav.reverse();
    assert.throws(() => validateResearchBundle(unordered), /NAV chronology/);
});

test("NAV endpoints must match the declared run period even when final metrics reconcile", () => {
    for (const omitted of ["first", "last"]) {
        const bundle = fixture();
        const run = bundle.runs[0];
        if (omitted === "first") {
            run.nav.shift();
        } else {
            run.nav.pop();
            run.finalEquity = run.nav.at(-1)!.equity;
            run.netReturn = run.finalEquity / run.initialCapital - 1;
        }
        assert.throws(
            () => validateResearchBundle(bundle),
            /NAV period endpoints/,
        );
    }
    const oneDay = fixture();
    oneDay.runs[0].nav.shift();
    oneDay.runs[0].from = oneDay.runs[0].through;
    oneDay.runs[0].events[0].date = "2020-01-03T09:00:00+08:00";
    oneDay.runs[0].events[0].original.date = oneDay.runs[0].events[0].date;
    assert.doesNotThrow(() => validateResearchBundle(oneDay));
});

test("snapshot date must cover the latest endpoint across all runs regardless of run order", () => {
    const bundle = fixture();
    const later = structuredClone(bundle.runs[0]);
    later.id = "later-run";
    later.through = "2020-01-04";
    later.nav.push({ date: later.through, equity: later.finalEquity });
    bundle.runs.push(later);
    bundle.asOf = "2020-01-03";
    assert.throws(() => validateResearchBundle(bundle), /run.through.*asOf/);
    bundle.runs.reverse();
    assert.throws(() => validateResearchBundle(bundle), /run.through.*asOf/);
    for (const asOf of ["2020-01-04", "2020-01-05"]) {
        bundle.asOf = asOf;
        const original = structuredClone(bundle);
        assert.strictEqual(validateResearchBundle(bundle), bundle);
        assert.deepEqual(bundle, original);
    }
});

test("event timestamps require real dates, valid clocks and the native Taipei timezone", () => {
    for (const date of [
        "not-a-date",
        "2020-01-02",
        "2020-01-02T09:00:00",
        "2020-01-02T09:00+08:00",
        "2020-02-30T09:00:00+08:00",
        "2020-01-02T24:00:00+08:00",
        "2020-01-02T09:60:00+08:00",
        "2020-01-02T09:00:60+08:00",
        "2020-01-02T09:00:00+24:00",
        "2020-01-02T01:00:00Z",
        "2020-01-02T09:00:00+09:00",
        "2020-01-02T09:00:00.123+08:00",
    ]) {
        const bundle = fixture();
        bundle.runs[0].events[0].date = date;
        assert.throws(
            () => validateResearchBundle(bundle),
            /event timestamp/,
            date,
        );
    }
});

test("event dates must stay inside the declared run period", () => {
    for (const date of [
        "2020-01-01T23:59:59+08:00",
        "2020-01-04T00:00:00+08:00",
    ]) {
        const bundle = fixture();
        bundle.runs[0].events[0].date = date;
        assert.throws(() => validateResearchBundle(bundle), /event timestamp/);
    }
});

test("event chronology compares complete timestamps without sorting or rewriting equal-time events", () => {
    const bundle = fixture();
    const first = bundle.runs[0].events[0];
    bundle.runs[0].events.push({
        ...first,
        id: "event-1",
        original: structuredClone(first.original),
    });
    const original = structuredClone(bundle);
    assert.strictEqual(validateResearchBundle(bundle), bundle);
    assert.deepEqual(bundle, original);
    bundle.runs[0].events[1].date = "2020-01-02T08:59:59+08:00";
    assert.throws(() => validateResearchBundle(bundle), /chronology/);
    bundle.runs[0].events[1].date = "2020-01-02T09:00:01+08:00";
    bundle.runs[0].events[1].original.date = bundle.runs[0].events[1].date;
    assert.doesNotThrow(() => validateResearchBundle(bundle));
    bundle.runs[0].events[1].date = "2020-01-03T23:59:59+08:00";
    bundle.runs[0].events[1].original.date = bundle.runs[0].events[1].date;
    assert.doesNotThrow(() => validateResearchBundle(bundle));
});

test("known optional source and method strings reject objects, numbers and null before rendering", () => {
    for (const key of ["path", "url", "publishedAt", "hash"]) {
        for (const value of [
            { nested: "would crash a React child" },
            123,
            null,
        ]) {
            const bundle = fixture();
            Object.assign(bundle.sources[0], { [key]: value });
            assert.throws(() => validateResearchBundle(bundle), /source\./);
        }
    }
    for (const key of ["missionPath", "reportPath"]) {
        for (const value of [{ nested: true }, 123, null]) {
            const bundle = fixture();
            Object.assign(bundle.runs[0].method, { [key]: value });
            assert.throws(() => validateResearchBundle(bundle), /method\./);
        }
    }
    const extended = fixture();
    Object.assign(extended.sources[0], {
        path: "source.json",
        url: "https://example.com",
        publishedAt: "2020-01-04",
        hash: "a".repeat(64),
        extension: { retained: true },
    });
    Object.assign(extended.runs[0].method, {
        missionPath: "mission.md",
        reportPath: "report.md",
        extension: { retained: true },
    });
    assert.strictEqual(validateResearchBundle(extended), extended);
});

test("synthetic saved native research packets remain readable and unchanged", () => {
    const source = fixture();
    const second = structuredClone(source.runs[0]);
    second.id = "second-synthetic-run";
    source.runs.push(second);
    const bytes = gzipSync(JSON.stringify(source));
    const bundle = JSON.parse(gunzipSync(bytes).toString("utf8"));
    const original = structuredClone(bundle);
    const parsed = validateResearchBundle(bundle);
    assert.ok(parsed.runs.length >= 2);
    assert.deepEqual(parsed, original);
});
test("every saved run requires at least one source reference", () => {
    for (const index of [0, 1]) {
        const bundle = fixture();
        const second = structuredClone(bundle.runs[0]);
        second.id = "second-run";
        bundle.runs.push(second);
        bundle.runs[index].sourceIds = [];
        assert.throws(() => validateResearchBundle(bundle), /run provenance/);
    }
});

test("missing source reference cannot masquerade as verified evidence", () => {
    const unknown = fixture();
    unknown.runs[0].sourceIds = ["unprovided"];
    assert.throws(() => validateResearchBundle(unknown), /provenance/);
    const badHash = fixture();
    badHash.sources[0].hash = "truncated";
    assert.throws(() => validateResearchBundle(badHash), /source hash/);
});
