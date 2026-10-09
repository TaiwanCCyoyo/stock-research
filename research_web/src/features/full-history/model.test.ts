import assert from "node:assert/strict";
import { test } from "node:test";
import {
    dateIndex,
    initialHistoryIndex,
    isCurrentRequest,
    toMapRow,
    toMapView,
    appears,
    recentEnded,
    timelineInclusiveRange,
    timelineRows,
} from "./model.ts";
import {
    HISTORY_SCHEMA,
    type HistoryDirectoryRow,
    type HistoryRow,
} from "./types.ts";

const dates = ["2010-01-04", "2010-01-05", "2010-01-08"];
test("history opens latest by default but restores exact visits from the current catalog", () => {
    assert.equal(
        initialHistoryIndex(dates, "current", () => null),
        2,
    );
    const visits = new Map([
        ["history.date.current", "2010-01-05"],
        ["history.date.old", "2010-01-04"],
    ]);
    assert.equal(
        initialHistoryIndex(dates, "current", (key) => visits.get(key) ?? null),
        1,
    );
    assert.equal(
        initialHistoryIndex(dates, "new", (key) => visits.get(key) ?? null),
        2,
    );
    assert.equal(
        initialHistoryIndex([], "current", () => null),
        -1,
    );
});
test("invalid, weekend, and removed saved dates fall back to latest without snapping", () => {
    for (const saved of [
        "",
        "invalid",
        "2010-01-09",
        "2009-12-01",
        "2010-01-07",
        "2030-01-01",
    ])
        assert.equal(
            initialHistoryIndex(dates, "current", () => saved),
            2,
        );
    assert.equal(
        initialHistoryIndex(dates.slice(1), "current", () => "2010-01-04"),
        1,
    );
});
test("a blocked storage getter or getItem cannot prevent the latest fallback", () => {
    const blocked = {
        get storage(): { getItem(key: string): string | null } {
            throw new Error("getter denied");
        },
    };
    assert.equal(
        initialHistoryIndex(dates, "current", (key) =>
            blocked.storage.getItem(key),
        ),
        2,
    );
    assert.equal(
        initialHistoryIndex(dates, "current", () => {
            throw new Error("read denied");
        }),
        2,
    );
});
test("explicit URL dates override saved visits and keep existing trading-session snapping", () => {
    assert.equal(
        initialHistoryIndex(dates, "current", () => "2010-01-04", "2010-01-08"),
        2,
    );
    assert.equal(
        initialHistoryIndex(dates, "current", () => "2010-01-04", "2010-01-07"),
        1,
    );
    assert.equal(
        initialHistoryIndex(
            dates,
            "current",
            () => {
                throw new Error("denied");
            },
            "2010-01-05",
        ),
        1,
    );
    assert.equal(
        initialHistoryIndex(
            dates,
            "current",
            () => "2010-01-05",
            "bad-url-date",
        ),
        1,
    );
});
test("calendar snaps to prior trading session and clamps both boundaries", () => {
    assert.equal(dateIndex(dates, "2009-12-01"), 0);
    assert.equal(dateIndex(dates, "2010-01-07"), 1);
    assert.equal(dateIndex(dates, "2010-01-08"), 2);
    assert.equal(dateIndex(dates, "2030-01-01"), 2);
    assert.equal(dateIndex([], "2010-01-01"), -1);
});
test("inclusive phase dates occupy trading-session slots through the last boundary", () => {
    const sessions = ["2010-01-04", "2010-01-05", "2010-01-08"];
    const oneSession = timelineInclusiveRange(
        sessions,
        "2010-01-05",
        "2010-01-05",
    );
    assert.deepEqual(oneSession, {
        left: (1 / 3) * 100,
        right: (2 / 3) * 100,
    });
    assert.ok(oneSession.right > oneSession.left);

    const multipleSessions = timelineInclusiveRange(
        sessions,
        "2010-01-04",
        "2010-01-05",
    );
    assert.deepEqual(multipleSessions, {
        left: 0,
        right: (2 / 3) * 100,
    });

    assert.deepEqual(
        timelineInclusiveRange(sessions, "2010-01-08", "2010-01-08"),
        { left: (2 / 3) * 100, right: 100 },
    );
});
test("latest request rejects stale success and failure, wrong date and cross catalog", () => {
    const current = { epoch: 3, catalogId: "catalog-a", date: dates[2] };
    const response = {
        schema: HISTORY_SCHEMA,
        catalogId: "catalog-a",
        date: dates[2],
    };
    assert.equal(isCurrentRequest(current, current, response), true);
    assert.equal(
        isCurrentRequest({ ...current, epoch: 2 }, current, response),
        false,
    );
    assert.equal(isCurrentRequest({ ...current, epoch: 2 }, current), false);
    assert.equal(
        isCurrentRequest(current, current, {
            ...response,
            catalogId: "catalog-b",
        }),
        false,
    );
    assert.equal(
        isCurrentRequest(current, current, { ...response, date: dates[0] }),
        false,
    );
    assert.equal(
        isCurrentRequest({ ...current, catalogId: "catalog-b" }, current),
        false,
    );
    assert.equal(
        isCurrentRequest(current, current, { ...response, schema: "other" }),
        false,
    );
});
const row: HistoryRow = {
    securityId: "TW:2330",
    code: "2330",
    name: "台積電",
    seriesId: "series",
    waveId: "wave",
    start: dates[0],
    peakDate: dates[2],
    endConfirmedAt: null,
    observedThrough: dates[2],
    leftCensored: false,
    rightCensored: true,
    scale: "large",
    gain: 100,
    growth: {
        schema: "wave-growth.v1",
        startDate: dates[0],
        observationDate: dates[2],
        yearDays: 365.25,
        elapsedDays: 4,
        elapsedYears: 4 / 365.25,
        totalGainPct: 100,
        annualizedGainPct: 1,
        sizingGainPct: 100,
        basis: "annualized",
        reason: null,
    },
    peakGain: 110,
    raw: 70,
    adjusted: 60,
    reason: null,
    industry: {
        id: "semi",
        label: "半導體",
        basis: "current-snapshot",
        snapshotAt: "2026-10-01",
    },
    earliestCandidateId: "candidate",
    phase: null,
};
test("map keeps raw gain and sizes full-history cells from the selected growth metric", () => {
    assert.equal(toMapRow(row).weight, 1);
    const twiceMetric = toMapRow({
        ...row,
        gain: 12,
        growth: { ...row.growth!, sizingGainPct: 200 },
    });
    assert.equal(twiceMetric.gain, 12);
    assert.equal(twiceMetric.weight, 4);
    assert.equal(
        Math.sqrt(twiceMetric.weight) / Math.sqrt(toMapRow(row).weight),
        2,
    );
    assert.equal(
        toMapRow({ ...row, growth: { ...row.growth!, sizingGainPct: 1 } })
            .weight,
        0.0001,
    );
    assert.equal(
        toMapRow({ ...row, growth: { ...row.growth!, sizingGainPct: -20 } })
            .weight,
        0,
    );
    const unknown = toMapRow({ ...row, gain: 400, growth: undefined });
    assert.equal(unknown.gain, 400);
    assert.equal(unknown.displayMetric?.basis, "unknown");
    assert.equal(unknown.displayMetric?.gain, null);
    assert.equal(unknown.weight, 0);
    assert.equal(toMapRow(row).wave.launch, null);
    assert.equal("prices" in toMapRow(row).security, false);
    assert.equal(
        toMapRow(row).security.classificationSnapshot?.observedAt,
        "2026-10-01",
    );
});
test("catalog display keeps unknown classification but excludes confirmed end day", () => {
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "catalog-a",
        date: dates[2],
        rows: [
            row,
            {
                ...row,
                securityId: "other",
                waveId: "ended",
                endConfirmedAt: dates[2],
                industry: { ...row.industry, basis: "unknown" as const },
            },
        ],
    };
    const view = toMapView(frame, "catalog");
    assert.equal(view.date, dates[2]);
    assert.equal(view.catalogId, "catalog-a");
    assert.equal(view.active.length, 1);
    assert.equal(view.ended.length, 0);
    assert.equal(view.industries[0].rows.length, 1);
    assert.equal(view.industries[0].maxGain, 100);
});

test("frame industry maximum preserves unknowns and negative known gains", () => {
    for (const [gains, expected] of [
        [[null, null], null],
        [[null, -15, -3], -3],
        [[-3, null, -15], -3],
        [[null, 20, -10, 60], 60],
    ] as const) {
        const frame = {
            schema: HISTORY_SCHEMA,
            catalogId: "catalog-a",
            date: dates[2],
            rows: gains.map((gain, index) => ({
                ...row,
                securityId: `stock-${index}`,
                gain,
            })),
        };
        const before = structuredClone(frame);
        const view = toMapView(frame, "catalog");
        assert.equal(view.industries[0].maxGain, expected);
        assert.equal(view.active.length, gains.length);
        assert.deepEqual(frame, before);
    }
});

test("candidate appearance is separate from complete catalog and area baseline", () => {
    const launched: HistoryRow = {
        ...row,
        launchCandidate: {
            date: dates[1],
            rangeFrom: dates[0],
            rangeUntil: dates[1],
            kind: "acceleration",
            outcome: "continued",
        },
    };
    assert.equal(appears(launched, dates[0], "launched"), false);
    assert.equal(appears(launched, dates[1], "launched"), true);
    assert.equal(appears(row, dates[1], "launched"), false);
    assert.equal(appears(row, dates[1], "catalog"), true);
    assert.equal(
        appears(
            { ...launched, endConfirmedAt: dates[2] },
            dates[2],
            "launched",
        ),
        false,
    );
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "a",
        date: dates[1],
        rows: [
            launched,
            {
                ...row,
                securityId: "other",
                industry: {
                    ...row.industry,
                    id: "unknown",
                    basis: "unknown" as const,
                },
            },
        ],
    };
    const view = toMapView(frame);
    assert.equal(view.active.length, 1);
    assert.equal(view.active[0].weight, toMapRow(launched).weight);
    assert.equal(view.active[0].wave.start, dates[0]);
    assert.equal(toMapView(frame, "catalog").industries.length, 2);
});

test("growth threshold includes eligible short waves, excludes sub-threshold long waves and unknowns", () => {
    const shortWave: HistoryRow = {
        ...row,
        launchCandidate: {
            date: dates[0],
            rangeFrom: dates[0],
            rangeUntil: dates[1],
            kind: "breakout",
            outcome: "continued",
        },
        growth: {
            ...row.growth!,
            elapsedDays: 36,
            sizingGainPct: 100,
            basis: "actual",
        },
    };
    const longWave: HistoryRow = {
        ...shortWave,
        securityId: "long-wave",
        growth: {
            ...row.growth!,
            elapsedDays: 1290,
            sizingGainPct: 36.49,
            basis: "annualized",
        },
    };
    assert.equal(appears(shortWave, dates[2], "launched"), true);
    assert.equal(appears(longWave, dates[2], "launched"), false);
    assert.equal(
        appears({ ...shortWave, growth: undefined }, dates[2], "catalog"),
        false,
    );
    assert.equal(
        appears(
            {
                ...shortWave,
                growth: {
                    ...row.growth!,
                    sizingGainPct: 100 - 1e-7,
                    basis: "actual",
                },
            },
            dates[2],
            "catalog",
        ),
        false,
    );
    assert.equal(
        appears(
            {
                ...shortWave,
                growth: {
                    ...row.growth!,
                    sizingGainPct: 100 - 1e-14,
                    basis: "actual",
                },
            },
            dates[2],
            "catalog",
        ),
        true,
    );
    assert.equal(
        appears({ ...shortWave, growth: row.growth }, dates[0], "launched"),
        true,
    );
    assert.equal(
        appears(
            { ...shortWave, endConfirmedAt: dates[2] },
            dates[2],
            "catalog",
        ),
        false,
    );
});

test("recently ended map cells use growthAtEnd and keep raw gain separate", () => {
    const directoryRow: HistoryDirectoryRow = {
        securityId: "ended-stock",
        code: "9999",
        name: "已結束個股",
        industry: row.industry,
        waveId: "ended-wave",
        start: dates[0],
        peakDate: dates[1],
        endConfirmedAt: "2010-01-20",
        observedThrough: dates[2],
        representativeFrom: dates[0],
        representativeUntilExclusive: dates[2],
        launchCandidate: {
            date: dates[0],
            rangeFrom: dates[0],
            rangeUntil: dates[1],
            kind: "breakout",
            outcome: "continued",
        },
        phases: [],
        scale: "large",
        leftCensored: false,
        rightCensored: false,
        peakGain: 220,
        gainAtEnd: 18,
        gainAtEndDate: "2010-01-20",
        growthAtEnd: {
            ...row.growth!,
            sizingGainPct: 140,
            basis: "annualized",
        },
    };
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "catalog-a",
        date: "2010-02-01",
        rows: [],
    };
    const ended = recentEnded([directoryRow], frame);
    assert.equal(ended.length, 1);
    assert.equal(ended[0].gain, 18);
    assert.equal(ended[0].displayMetric?.gain, 140);
    assert.equal(ended[0].displayMetric?.basis, "annualized");
    assert.equal(ended[0].weight, 1.96);
    assert.deepEqual(
        recentEnded([{ ...directoryRow, growthAtEnd: undefined }], frame),
        [],
    );
});

test("timeline ranking uses sizing metrics, responds to threshold, and keeps excluded catalog rows searchable", () => {
    const specifications = [
        {
            id: "short-winner",
            code: "1",
            industryId: "short-sector",
            rawGain: 110,
            sizingGain: 110,
            basis: "actual" as const,
        },
        {
            id: "medium-a",
            code: "2",
            industryId: "medium-sector",
            rawGain: 700,
            sizingGain: 70,
            basis: "annualized" as const,
        },
        {
            id: "medium-b",
            code: "3",
            industryId: "medium-sector",
            rawGain: 800,
            sizingGain: 70,
            basis: "annualized" as const,
        },
        {
            id: "long-loser",
            code: "9",
            industryId: "long-sector",
            rawGain: 1290,
            sizingGain: 36.49,
            basis: "annualized" as const,
        },
    ];
    const frameRows: HistoryRow[] = specifications.map((item) => ({
        ...row,
        securityId: item.id,
        code: item.code,
        waveId: `wave-${item.id}`,
        gain: item.rawGain,
        industry: {
            ...row.industry,
            id: item.industryId,
            label: item.industryId,
        },
        launchCandidate: {
            date: dates[0],
            rangeFrom: dates[0],
            rangeUntil: dates[1],
            kind: "breakout",
            outcome: "continued",
        },
        growth: {
            ...row.growth!,
            elapsedDays: item.basis === "actual" ? 36 : 1290,
            sizingGainPct: item.sizingGain,
            basis: item.basis,
        },
    }));
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "catalog-timeline",
        date: dates[2],
        rows: frameRows,
    };
    const directory: HistoryDirectoryRow[] = specifications.map((item) => ({
        securityId: item.id,
        code: item.code,
        name: item.id,
        industry: {
            ...row.industry,
            id: item.industryId,
            label: item.industryId,
        },
        waveId: `wave-${item.id}`,
        start: dates[0],
        peakDate: dates[1],
        endConfirmedAt: null,
        observedThrough: dates[2],
        representativeFrom: dates[0],
        representativeUntilExclusive: dates[2],
        launchCandidate: frameRows.find(
            (entry) => entry.securityId === item.id,
        )!.launchCandidate!,
        phases: [],
        scale: "large",
        leftCensored: false,
        rightCensored: true,
        peakGain: item.rawGain,
        gainAtEnd: item.rawGain,
        gainAtEndDate: dates[2],
        growthAtEnd: frameRows.find((entry) => entry.securityId === item.id)!
            .growth,
    }));

    const lowerThreshold = timelineRows(directory, frame, "", 50);
    const defaultThreshold = timelineRows(directory, frame, "", 100);
    assert.equal(lowerThreshold.length, directory.length);
    assert.equal(defaultThreshold.length, directory.length);
    assert.equal(lowerThreshold[0].industry.id, "medium-sector");
    assert.equal(defaultThreshold[0].securityId, "short-winner");
    assert.equal(
        defaultThreshold.find((entry) => entry.securityId === "long-loser")
            ?.gainAtEnd,
        1290,
    );
});
