import assert from "node:assert/strict";
import { test } from "node:test";
import type {
    OpportunityBundle,
    OpportunityPortfolio,
} from "../../domain/opportunities/types.ts";
import {
    buildPortfolioComparisons,
    supportedHoldingSegments,
    rankCapitalComparisons,
} from "./comparisons.ts";
import type { HistoryRow } from "./types.ts";

const bundle = (portfolio: OpportunityPortfolio): OpportunityBundle => ({
    schema: "opportunity-explorer.v1",
    id: "saved-history-ledger",
    label: "已保存帳本測試資料",
    kind: "historical-preview",
    asOf: "2026-10-03",
    dates: ["2026-10-01", "2026-10-02", "2026-10-03"],
    priceBasis: "adjusted-close",
    catalogCoverage: "case-slice",
    ruleVersion: "rules.v1",
    selectionPolicy: "saved-evidence",
    classificationVersion: "classification.v1",
    sources: [
        { id: "ledger", label: "已登錄帳本來源" },
        { id: "unclaimed", label: "未列入策略來源清單" },
    ],
    limitations: [],
    securities: [
        {
            id: "TW:2330",
            code: "2330",
            name: "測試股票",
            market: "TW",
            currency: "TWD",
            industry: [],
            prices: [],
        },
    ],
    waves: [],
    representatives: [],
    portfolios: [portfolio],
});

const portfolio = (
    updates: Partial<OpportunityPortfolio> = {},
): OpportunityPortfolio => ({
    id: "saved-strategy",
    name: "已保存策略",
    kind: "strategy",
    description: "保存的研究帳本，非合成範例",
    sourceIds: ["ledger"],
    coverage: [],
    holdings: [],
    allocations: [],
    limitations: [],
    ...updates,
});

test("capital ranking orders same-day observed weights and leaves unknown after known zero", () => {
    const source = bundle(portfolio());
    source.portfolios = [
        portfolio({ id: "unknown" }),
        ...[0, 0.4, 0.8].map((weight) =>
            portfolio({
                id: `observed-${weight}`,
                allocations: [
                    {
                        date: "2026-10-02",
                        completeness: "full",
                        nav: 100,
                        cashWeight: 1 - weight,
                        otherAssetsWeight: 0,
                        positions: weight
                            ? [{ securityId: "TW:3324", weight }]
                            : [],
                        sourceId: "ledger",
                    },
                ],
            }),
        ),
    ];
    const comparisons = buildPortfolioComparisons(source, "2026-10-02", [
        row(),
    ]);
    const originalIds = comparisons.map((entry) => entry.portfolio.id);
    const ranked = rankCapitalComparisons(comparisons);
    assert.deepEqual(
        ranked.map((entry) => entry.capital.opportunityWeight),
        [0.8, 0.4, 0, null],
    );
    assert.deepEqual(
        comparisons.map((entry) => entry.portfolio.id),
        originalIds,
    );
    const otherDay = rankCapitalComparisons(
        buildPortfolioComparisons(source, "2026-10-03", [row()]),
    );
    assert.ok(
        otherDay.every((entry) => entry.capital.opportunityWeight === null),
    );
});

const row = (securityId = "TW:3324", code = "3324"): HistoryRow => ({
    securityId,
    code,
    name: "當日波段股票",
    seriesId: "saved-series",
    waveId: `wave-${code}`,
    start: "2026-10-01",
    peakDate: "2026-10-02",
    endConfirmedAt: null,
    observedThrough: "2026-10-03",
    leftCensored: false,
    rightCensored: true,
    scale: "large",
    gain: 35,
    peakGain: 40,
    raw: null,
    adjusted: null,
    reason: null,
    industry: {
        id: "industry",
        label: "測試分類",
        basis: "unknown",
        snapshotAt: null,
    },
    earliestCandidateId: null,
    launchCandidate: null,
    phase: "rising",
});

test("holding state uses same-day coverage and does not infer continuous ownership", () => {
    const saved = portfolio({
        coverage: [
            {
                from: "2026-10-02",
                untilExclusive: "2026-10-04",
                completeness: "full",
                kind: "daily",
                sourceId: "ledger",
            },
        ],
        holdings: [
            {
                securityId: "TW:3324",
                from: "2026-10-02",
                untilExclusive: "2026-10-03",
                sourceId: "ledger",
            },
        ],
    });
    const comparisons = (date: string) =>
        buildPortfolioComparisons(bundle(saved), date, [row()])[0];

    assert.equal(comparisons("2026-10-01").stocks[0].held, "unknown");
    assert.equal(comparisons("2026-10-02").stocks[0].held, "held");
    assert.equal(comparisons("2026-10-03").stocks[0].held, "not-held");
    assert.equal(comparisons("2026-10-03").stocks[0].heldDayShare, null);
});

test("timeline keeps omitted-quantity holding evidence inside the covered date intersection", () => {
    const saved = portfolio({
        coverage: [
            {
                from: "2026-10-02",
                untilExclusive: "2026-10-05",
                completeness: "full",
                kind: "daily",
                sourceId: "ledger",
            },
            {
                from: "2026-10-01",
                untilExclusive: "2026-10-06",
                completeness: "full",
                kind: "daily",
                sourceId: "unclaimed",
            },
        ],
        holdings: [
            {
                securityId: "TW:3324",
                from: "2026-10-01",
                untilExclusive: "2026-10-04",
                sourceId: "ledger",
            },
        ],
    });
    const comparison = buildPortfolioComparisons(bundle(saved), "2026-10-02", [
        row(),
    ])[0];

    assert.equal(comparison.stocks[0].held, "held");
    assert.deepEqual(
        supportedHoldingSegments(
            comparison,
            "TW:3324",
            "2026-10-03",
            "2026-10-05",
        ).map(({ from, untilExclusive, coverage }) => ({
            from,
            untilExclusive,
            coverageSource: coverage.sourceId,
        })),
        [
            {
                from: "2026-10-03",
                untilExclusive: "2026-10-04",
                coverageSource: "ledger",
            },
        ],
    );
});

test("timeline excludes explicitly nonfinite or nonpositive holding quantities", () => {
    const saved = portfolio({
        coverage: [
            {
                from: "2026-10-02",
                untilExclusive: "2026-10-04",
                completeness: "full",
                kind: "daily",
                sourceId: "ledger",
            },
        ],
        holdings: [
            {
                securityId: "TW:3324",
                from: "2026-10-02",
                untilExclusive: "2026-10-04",
                sourceId: "ledger",
            },
        ],
    });
    const comparison = buildPortfolioComparisons(bundle(saved), "2026-10-02", [
        row(),
    ])[0];

    for (const quantity of [0, -1, NaN, Infinity, -Infinity]) {
        const withQuantity = {
            ...comparison,
            portfolio: {
                ...comparison.portfolio,
                holdings: comparison.portfolio.holdings.map((holding) => ({
                    ...holding,
                    quantity,
                })),
            },
        };
        assert.deepEqual(
            supportedHoldingSegments(
                withQuantity,
                "TW:3324",
                "2026-10-01",
                "2026-10-05",
            ),
            [],
            `quantity ${quantity} should not render a holding band`,
        );
    }
});

test("uncovered dates and unclaimed holding sources remain unknown", () => {
    const saved = portfolio({
        coverage: [
            {
                from: "2026-10-02",
                untilExclusive: "2026-10-03",
                completeness: "partial",
                kind: "daily",
                sourceId: "ledger",
            },
        ],
        holdings: [
            {
                securityId: "TW:3324",
                from: "2026-10-02",
                untilExclusive: "2026-10-03",
                sourceId: "unclaimed",
            },
        ],
    });
    const comparison = buildPortfolioComparisons(bundle(saved), "2026-10-02", [
        row(),
    ])[0];

    assert.equal(comparison.stocks[0].held, "unknown");
    assert.equal(comparison.stocks[0].positiveMoveShare, null);
    assert.equal(comparison.stocks[0].heldDayShare, null);
    assert.equal(comparison.averagePositiveMoveShare, null);
    assert.equal(comparison.unknownCount, 1);
});

test("only canonical active stocks match same-day capital; ETF and absent identities stay unknown", () => {
    const saved = portfolio({
        allocations: [
            {
                date: "2026-10-02",
                completeness: "partial",
                nav: 100,
                cashWeight: 0.2,
                positions: [
                    { securityId: "TW:3324", weight: 0.3 },
                    { securityId: "TW:0050", weight: 0.25 },
                    { securityId: "TW:9999", weight: 0.15 },
                ],
                sourceId: "ledger",
            },
        ],
    });
    const comparison = buildPortfolioComparisons(bundle(saved), "2026-10-02", [
        row(),
        row("TW:0050", "0050"),
    ])[0];

    assert.equal(comparison.stocks.length, 1);
    assert.equal(comparison.capital.opportunityWeight, 0.3);
    assert.equal(comparison.capital.otherWeight, null);
    assert.equal(comparison.capital.cashWeight, 0.2);
    assert.equal(comparison.capital.otherAssetsWeight, null);
    assert.equal(comparison.capital.status, "partial");
    assert.ok(Math.abs(comparison.capital.unknownWeight - 0.5) < 1e-10);
});

test("prior allocation is never carried forward to another date", () => {
    const saved = portfolio({
        allocations: [
            {
                date: "2026-10-02",
                completeness: "full",
                nav: 100,
                cashWeight: 0.4,
                otherAssetsWeight: 0.1,
                positions: [{ securityId: "TW:3324", weight: 0.5 }],
                sourceId: "ledger",
            },
        ],
    });
    const comparison = buildPortfolioComparisons(bundle(saved), "2026-10-03", [
        row(),
    ])[0];

    assert.equal(comparison.capital.status, "unknown");
    assert.equal(comparison.capital.opportunityWeight, null);
    assert.equal(comparison.capital.cashWeight, null);
    assert.equal(comparison.capital.unknownWeight, 1);
});
