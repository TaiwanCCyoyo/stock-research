import assert from "node:assert/strict";
import { test } from "node:test";
import type {
    StudioExposure,
    StudioFill,
    StudioTrade,
} from "../../domain/strategies/types.ts";
import { tradeCalculation } from "./auditModel.ts";
import { strategyIdea } from "./presentation.ts";
import { EXPOSURE_KEYS, projectExposure } from "./exposureModel.ts";
import {
    studioAccountPath,
    studioExposurePath,
    studioRunPath,
    studioSelectionIdentity,
    studioSelectionIds,
    studioTradePath,
} from "../../api/strategyPaths.ts";
import {
    alignComparisons,
    periodMetrics,
    selectTrades,
    strategyStatus,
    walkthroughTrades,
} from "./model.ts";

const exposureRow = (
    date: string,
    overrides: Partial<StudioExposure["rows"][number]> = {},
): StudioExposure["rows"][number] => ({
    date,
    runawayWeight: 0.2,
    otherStockWeight: 0.3,
    unknownStockWeight: 0,
    otherAssetsWeight: 0.1,
    cashWeight: 0.4,
    known: true,
    verifiedAccount: true,
    ...overrides,
});
test("partial map knowledge masks the whole allocation even when some weights are known", () => {
    const row = exposureRow("2021-01-04", {
        known: false,
        unknownStockWeight: 0.1,
    });
    const projection = projectExposure([row]);
    assert.deepEqual(projection.segments, []);
    assert.deepEqual(projection.runawayValues, [null]);
    assert.deepEqual(projection.unknownRanges, [
        { fromIndex: 0, untilIndexExclusive: 1 },
    ]);
    assert.equal(projection.unknownDays, 1);
    assert.equal(row.runawayWeight, 0.2);
});
test("missing marks and any null or nonfinite required weight produce a gap, never a zero-filled stack", () => {
    for (const key of EXPOSURE_KEYS) {
        for (const value of [null, NaN, Infinity, -Infinity]) {
            const projection = projectExposure([
                exposureRow("2021-01-04", { [key]: value }),
            ]);
            assert.equal(projection.segments.length, 0, `${key}: ${value}`);
            assert.equal(projection.unknownDays, 1, `${key}: ${value}`);
            assert.deepEqual(projection.runawayValues, [null]);
        }
    }
});
test("nonpositive account value represented by null weights remains wholly unknown", () => {
    const projection = projectExposure([
        exposureRow("2021-01-04", {
            known: false,
            runawayWeight: null,
            otherStockWeight: null,
            unknownStockWeight: null,
            otherAssetsWeight: null,
            cashWeight: null,
        }),
    ]);
    assert.deepEqual(projection.segments, []);
    assert.deepEqual(projection.unknownRanges, [
        { fromIndex: 0, untilIndexExclusive: 1 },
    ]);
    assert.deepEqual(projection.runawayValues, [null]);
});
test("known true zero remains known and source weights are stacked without filling the balance", () => {
    const zero = exposureRow("2021-01-04", {
        runawayWeight: 0,
        otherStockWeight: 0,
        unknownStockWeight: 0,
        otherAssetsWeight: 0,
        cashWeight: 1,
    });
    const unchanged = Object.freeze(
        exposureRow("2021-01-05", { cashWeight: 0.2 }),
    );
    const projection = projectExposure([zero, unchanged]);
    assert.equal(projection.unknownDays, 0);
    assert.deepEqual(projection.runawayValues, [0, 0.2]);
    assert.deepEqual(projection.segments[0].points[0].layers[0], {
        key: "runawayWeight",
        start: 0,
        end: 0,
    });
    assert.ok(
        Math.abs(projection.segments[0].points[1].layers.at(-1)!.end - 0.8) <
            1e-12,
    );
    assert.equal(unchanged.cashWeight, 0.2);
});
test("known-unknown-known allocations keep separate segments and their original date slots", () => {
    const projection = projectExposure([
        exposureRow("2021-01-04"),
        exposureRow("2021-01-05", { known: false }),
        exposureRow("2021-01-06", {
            runawayWeight: 0.4,
            otherStockWeight: 0.1,
        }),
    ]);
    assert.deepEqual(
        projection.segments.map((segment) => ({
            from: segment.fromIndex,
            until: segment.untilIndexExclusive,
            indices: segment.points.map((point) => point.index),
            dates: segment.points.map((point) => point.date),
        })),
        [
            { from: 0, until: 1, indices: [0], dates: ["2021-01-04"] },
            { from: 2, until: 3, indices: [2], dates: ["2021-01-06"] },
        ],
    );
    assert.deepEqual(projection.unknownRanges, [
        { fromIndex: 1, untilIndexExclusive: 2 },
    ]);
    assert.deepEqual(projection.runawayValues, [0.2, null, 0.4]);
    assert.deepEqual(projection.segments[0].points[0].layers, [
        { key: "runawayWeight", start: 0, end: 0.2 },
        { key: "otherStockWeight", start: 0.2, end: 0.5 },
        { key: "unknownStockWeight", start: 0.5, end: 0.5 },
        { key: "otherAssetsWeight", start: 0.5, end: 0.6 },
        { key: "cashWeight", start: 0.6, end: 1 },
    ]);
});
test("all unknown dates become one full-width index range without known areas", () => {
    const projection = projectExposure([
        exposureRow("2021-01-04", { known: false }),
        exposureRow("2021-01-05", { otherStockWeight: null }),
        exposureRow("2021-01-06", { cashWeight: null }),
    ]);
    assert.deepEqual(projection.segments, []);
    assert.deepEqual(projection.unknownRanges, [
        { fromIndex: 0, untilIndexExclusive: 3 },
    ]);
    assert.deepEqual(projection.runawayValues, [null, null, null]);
    assert.equal(projection.unknownDays, 3);
});
test("a single known row retains a nonzero-width slot and finite cumulative values", () => {
    const projection = projectExposure([exposureRow("2021-01-04")]);
    assert.equal(projection.segments.length, 1);
    const segment = projection.segments[0];
    assert.equal(segment.untilIndexExclusive - segment.fromIndex, 1);
    assert.equal(segment.points.length, 1);
    assert.equal(segment.points[0].index, 0);
    assert.equal(segment.points[0].layers.at(-1)?.end, 1);
    assert.deepEqual(projection.unknownRanges, []);
});
test("empty allocation input has no areas, gaps, or invented observations", () => {
    assert.deepEqual(projectExposure([]), {
        segments: [],
        unknownRanges: [],
        runawayValues: [],
        unknownDays: 0,
    });
});

test("opaque run IDs round-trip through all query endpoints without entering the pathname", () => {
    const ids = [
        "arm/candidate",
        "台股 研究",
        " ?#%&+.",
        "../nested/./strategy",
        "literal%2F%25",
        "line\nwith\ttabs",
    ];
    for (const id of ids) {
        for (const [path, pathname] of [
            [studioRunPath(id), "/run"],
            [studioAccountPath(id, "2021-01-08"), "/account"],
            [studioExposurePath(id), "/exposure"],
        ]) {
            const url = new URL(path, "https://example.test");
            assert.equal(url.pathname, pathname);
            assert.equal(url.searchParams.get("run_id"), id);
            assert.equal(url.hash, "");
            if (pathname === "/account")
                assert.equal(url.searchParams.get("date"), "2021-01-08");
        }
    }
});
test("opaque run and trade IDs are independently encoded once and retain literal escapes", () => {
    const runId = "策略/ A?x#%&+../%2F",
        tradeId = "部位/ B?y#%&+../%25";
    const url = new URL(
        studioTradePath(runId, tradeId),
        "https://example.test",
    );
    assert.equal(url.pathname, "/trade");
    assert.equal(url.searchParams.get("run_id"), runId);
    assert.equal(url.searchParams.get("trade_id"), tradeId);
    assert.equal(url.searchParams.size, 2);
    assert.equal(url.hash, "");
    assert.equal(decodeURIComponent(encodeURIComponent(runId)), runId);
    assert.equal(decodeURIComponent(encodeURIComponent(tradeId)), tradeId);
});
test("comparison selection identities preserve newlines and an empty selection without delimiter collisions", () => {
    const ids = ["策略/第一筆\n第二行", "__proto__ ?#%&+.\t"];
    assert.deepEqual(studioSelectionIds(studioSelectionIdentity(ids)), ids);
    assert.equal(studioSelectionIds(studioSelectionIdentity(ids)).length, 2);
    assert.deepEqual(studioSelectionIds(studioSelectionIdentity([])), []);
    assert.notEqual(
        studioSelectionIdentity(["first\nsecond"]),
        studioSelectionIdentity(["first", "second"]),
    );
});

test("unregistered strategy IDs use their saved idea, including prototype names", () => {
    for (const id of ["__proto__", "constructor", "toString", "new:strategy"]) {
        const plainIdea = `Saved idea for ${id}`;
        assert.equal(strategyIdea({ id, plainIdea }), plainIdea);
    }
});

test("registered strategy IDs retain their grounded presentation override", () => {
    const idea = strategyIdea({
        id: "stock:20261002-add-retry:normal-v1",
        plainIdea: "Original saved description",
    });
    assert.equal(typeof idea, "string");
    assert.notEqual(idea, "Original saved description");
});

const fill = (overrides: Partial<StudioFill> = {}): StudioFill => ({
    id: "fill",
    date: "2021-01-05",
    timestamp: "2021-01-05T09:00:00",
    action: "BUY",
    quantity: 1000,
    price: 10,
    cashFlow: -10000,
    fee: 0,
    tax: 0,
    penalty: 0,
    kind: "entry",
    decisionDate: "2021-01-04",
    orderId: "order",
    retry: false,
    entryCandidates: [{ code: "2330", affordability: "whole_lot_affordable" }],
    dailyRank: null,
    rankMissingReason: "missing",
    dayOpen: 10,
    dayClose: 11,
    original: {},
    ...overrides,
});
const trade = (
    id: string,
    overrides: Partial<StudioTrade> = {},
): StudioTrade => ({
    id,
    code: id,
    name: `name-${id}`,
    openDate: "2021-01-05",
    closeDate: "2021-01-08",
    cost: 10000,
    inflow: 11000,
    mark: null,
    markPrice: null,
    quantityEnd: 0,
    remainingCost: 0,
    pnl: 1000,
    realizedPnl: 1000,
    unrealizedPnl: null,
    return: 0.1,
    days: 3,
    capture: {
        days: 0,
        knownDays: 4,
        totalDays: 4,
        bestMetric: null,
        missingReason: null,
    },
    fills: [
        fill(),
        fill({ id: "add", kind: "add" }),
        fill({ id: "sell", action: "SELL", kind: "sell" }),
    ],
    candles: [],
    missingReasons: [],
    whySell: "",
    formula: "",
    ...overrides,
});
const nav = (
    date: string,
    equity: number,
    benchmarkEquity: number | null = equity,
) => ({ date, equity, benchmarkEquity, drawdown: 0 });

test("a development accepted result is not owner adoption", () => {
    assert.equal(
        strategyStatus({ ownerAdopted: null, studyStatus: "accepted" }),
        "research",
    );
    assert.equal(
        strategyStatus({ ownerAdopted: false, studyStatus: "failed" }),
        "failed",
    );
    assert.equal(
        strategyStatus({ ownerAdopted: true, studyStatus: "accepted" }),
        "adopted",
    );
});
test("closed gain/loss filters exclude open estimates and unknown PnL", () => {
    const rows = [
        trade("gain"),
        trade("loss", { pnl: -500, realizedPnl: -500 }),
        trade("open", { closeDate: null, realizedPnl: null, pnl: 900 }),
        trade("unknown", { realizedPnl: null, pnl: null }),
        trade("zero", { pnl: 0, realizedPnl: 0 }),
    ];
    assert.deepEqual(
        selectTrades(rows, "gain", "", "pnl", -1).map((row) => row.id),
        ["gain"],
    );
    assert.deepEqual(
        selectTrades(rows, "loss", "", "pnl", -1).map((row) => row.id),
        ["loss"],
    );
    assert.deepEqual(
        selectTrades(rows, "open", "", "pnl", -1).map((row) => row.id),
        ["open"],
    );
});
test("capture unknown stays separate from known zero; null sorts last in both directions", () => {
    const rows = [
        trade("unknown", {
            capture: {
                days: null,
                knownDays: 0,
                totalDays: 4,
                bestMetric: null,
                missingReason: "missing",
            },
        }),
        trade("zero"),
        trade("hit", {
            capture: {
                days: 2,
                knownDays: 4,
                totalDays: 4,
                bestMetric: 1.3,
                missingReason: null,
            },
        }),
    ];
    assert.deepEqual(
        selectTrades(rows, "captured", "", "captured", 1).map((row) => row.id),
        ["hit"],
    );
    assert.equal(
        selectTrades(rows, "all", "", "captured", 1).at(-1)?.id,
        "unknown",
    );
    assert.equal(
        selectTrades(rows, "all", "", "captured", -1).at(-1)?.id,
        "unknown",
    );
    assert.deepEqual(
        selectTrades(rows, "all", "NAME-HIT", "code", 1).map((row) => row.id),
        ["hit"],
    );
});
test("walkthrough selects saved complete best/median/worst cycles and never edits input", () => {
    const rows = [
        trade("best", { realizedPnl: 300 }),
        trade("middle", { realizedPnl: 100 }),
        trade("worst", { realizedPnl: -200 }),
        trade("missing", { fills: [] }),
        trade("open", { closeDate: null }),
    ];
    assert.deepEqual(
        walkthroughTrades(rows).map((pick) => [pick.trade.id, pick.role]),
        [
            ["best", "best"],
            ["middle", "median"],
            ["worst", "worst"],
        ],
    );
    assert.deepEqual(
        rows.map((row) => row.id),
        ["best", "middle", "worst", "missing", "open"],
    );
});
test("walkthrough with no complete cycles has no invented examples", () => {
    assert.deepEqual(walkthroughTrades([]), []);
    assert.deepEqual(
        walkthroughTrades([
            trade("open", { closeDate: null }),
            trade("unknown-pnl", { realizedPnl: null }),
            trade("no-candidates", {
                fills: [
                    fill({ entryCandidates: [] }),
                    fill({ kind: "add", entryCandidates: [] }),
                    fill({ action: "SELL", entryCandidates: [] }),
                ],
            }),
            trade("no-add", { fills: [fill(), fill({ action: "SELL" })] }),
            trade("no-sell", { fills: [fill(), fill({ kind: "add" })] }),
        ]),
        [],
    );
});
test("one complete walkthrough cycle has only the sole-example role", () => {
    const only = trade("__proto__", { realizedPnl: -200 });
    assert.deepEqual(
        walkthroughTrades([only, trade("incomplete", { fills: [] })]),
        [{ trade: only, role: "only" }],
    );
});
test("two complete walkthrough cycles retain distinct best and worst roles", () => {
    const best = trade("gain/台灣? # % & +\n", { realizedPnl: 300 });
    const worst = trade("constructor", { realizedPnl: -200 });
    assert.deepEqual(walkthroughTrades([worst, best]), [
        { trade: best, role: "best" },
        { trade: worst, role: "worst" },
    ]);
});
test("four walkthrough cycles preserve the saved middle-rank selection", () => {
    const rows = [
        trade("worst", { realizedPnl: -200 }),
        trade("lower-middle", { realizedPnl: 50 }),
        trade("best", { realizedPnl: 300 }),
        trade("upper-middle", { realizedPnl: 100 }),
    ];
    assert.deepEqual(
        walkthroughTrades(rows).map((pick) => [pick.trade.id, pick.role]),
        [
            ["best", "best"],
            ["upper-middle", "median"],
            ["worst", "worst"],
        ],
    );
    assert.deepEqual(
        rows.map((row) => row.id),
        ["worst", "lower-middle", "best", "upper-middle"],
    );
});
test("duplicate saved cycle entries do not multiply examples or distort median rank", () => {
    const only = trade("only");
    assert.deepEqual(walkthroughTrades([only, only]), [
        { trade: only, role: "only" },
    ]);
    const best = trade("best", { realizedPnl: 300 }),
        middle = trade("middle", { realizedPnl: 100 }),
        worst = trade("worst", { realizedPnl: -200 });
    assert.deepEqual(
        walkthroughTrades([worst, worst, best, middle, worst]).map((pick) => [
            pick.trade.id,
            pick.role,
        ]),
        [
            ["best", "best"],
            ["middle", "median"],
            ["worst", "worst"],
        ],
    );
});
test("comparison rebases distinct capitals on exact shared saved dates and preserves benchmark gaps", () => {
    const aligned = alignComparisons([
        {
            id: "a",
            nav: [
                nav("2021-01-04", 100),
                nav("2021-01-05", 110, 220),
                nav("2021-01-06", 120, null),
                nav("2021-01-08", 132, 264),
            ],
        },
        {
            id: "b",
            nav: [
                nav("2021-01-05", 500),
                nav("2021-01-06", 450),
                nav("2021-01-08", 550),
            ],
        },
    ]);
    assert.deepEqual(aligned.dates, ["2021-01-05", "2021-01-06", "2021-01-08"]);
    assert.deepEqual(aligned.series[1].values, [100, 90, 110.00000000000001]);
    assert.deepEqual(aligned.benchmark, [100, null, 120]);
});
test("no overlap or invalid equity cannot silently produce comparison values", () => {
    assert.deepEqual(
        alignComparisons([
            { id: "a", nav: [nav("2021-01-04", 100)] },
            { id: "b", nav: [nav("2021-01-05", 500)] },
        ]).dates,
        [],
    );
    assert.deepEqual(
        alignComparisons([
            { id: "a", nav: [nav("2021-01-04", 0)] },
            { id: "b", nav: [nav("2021-01-04", 500)] },
        ]).dates,
        [],
    );
});
test("interval metrics start fresh at comparison boundary and include unfinished underwater duration", () => {
    const result = periodMetrics([
        { date: "2021-01-04", equity: 100 },
        { date: "2021-01-05", equity: 80 },
        { date: "2021-01-08", equity: 90 },
    ]);
    assert.ok(result && Math.abs(result.maxDrawdown + 0.2) < 1e-10);
    assert.equal(result?.longestUnderwaterDays, 4);
    assert.ok(result && Math.abs(result.return + 0.1) < 1e-10);
    assert.equal(periodMetrics([]), null);
});
test("recovering the prior peak ends one underwater interval before a new drawdown", () => {
    const result = periodMetrics([
        { date: "2021-01-04", equity: 100 },
        { date: "2021-01-05", equity: 80 },
        { date: "2021-01-06", equity: 100 },
        { date: "2021-01-07", equity: 90 },
    ]);
    assert.equal(result?.longestUnderwaterDays, 2);
    assert.ok(result && Math.abs(result.maxDrawdown + 0.2) < 1e-10);
    assert.equal(
        periodMetrics([
            { date: "2021-01-04", equity: 100 },
            { date: "2021-01-05", equity: 100 },
            { date: "2021-01-06", equity: 100 },
        ])?.longestUnderwaterDays,
        0,
    );
});
test("trade audit derives net return from saved cashflows with fees already included", () => {
    const cycle = trade("cash", {
        cost: 10120,
        pnl: 1310,
        return: 1310 / 10120,
        fills: [
            fill({ cashFlow: -10120 }),
            fill({ action: "SELL", kind: "sell", cashFlow: 11200 }),
            fill({
                action: "DIVIDEND_ENTITLEMENT",
                kind: "corporate-action",
                cashFlow: 0,
            }),
            fill({
                action: "DIVIDEND",
                kind: "corporate-action",
                cashFlow: 230,
            }),
        ],
    });
    const audit = tradeCalculation(cycle);
    assert.equal(audit.cost, 10120);
    assert.equal(audit.pnl, 1310);
    assert.equal(audit.return, 1310 / 10120);
    assert.equal(audit.verified, true);
});
test("open partial exits use remaining mark once; missing cashflow never becomes zero", () => {
    const partial = trade("partial", {
        closeDate: null,
        cost: 20000,
        mark: 11000,
        remainingCost: 12000,
        pnl: 3500,
        realizedPnl: 4500,
        unrealizedPnl: -1000,
        fills: [
            fill({ cashFlow: -20000 }),
            fill({ action: "SELL", kind: "sell", cashFlow: 12000 }),
            fill({
                action: "DIVIDEND",
                kind: "corporate-action",
                cashFlow: 500,
            }),
        ],
    });
    assert.equal(tradeCalculation(partial).pnl, 3500);
    assert.equal(tradeCalculation(partial).verified, true);
    const missing = { ...partial, fills: [fill({ cashFlow: null })] };
    assert.equal(tradeCalculation(missing).pnl, null);
    assert.equal(tradeCalculation(missing).verified, false);
});
