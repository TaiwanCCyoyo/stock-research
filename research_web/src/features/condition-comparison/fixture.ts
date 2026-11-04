import type { ComparisonView, SavedCase } from "./model.ts";

/** Component fixture ONLY. Not L1 evidence, a producer schema, or a public artifact. */
const cases: SavedCase[] = [
    {
        eventId: "demo-01",
        securityId: "合成甲",
        date: "2020-01-02",
        group: "both",
        effectiveLabel: "hit",
        eventMainEligible: true,
        censored: false,
        reasons: [],
        readerRef: "synthetic:demo-01",
    },
    {
        eventId: "demo-02",
        securityId: "合成乙",
        date: "2020-01-03",
        group: "neither",
        effectiveLabel: "loss",
        eventMainEligible: true,
        censored: false,
        reasons: [],
        readerRef: "synthetic:demo-02",
    },
    {
        eventId: "demo-03",
        securityId: "合成丙",
        date: "2020-01-04",
        group: "prior-only",
        effectiveLabel: "unknown",
        eventMainEligible: false,
        censored: true,
        reasons: ["合成：品質缺漏；觀察不足"],
    },
    {
        eventId: "demo-04",
        securityId: "合成丁",
        date: "2020-01-05",
        group: "today-only",
        effectiveLabel: "flat-win",
        eventMainEligible: true,
        censored: false,
        reasons: [],
    },
    {
        eventId: "demo-05",
        securityId: "合成戊",
        date: "2020-01-06",
        group: "both",
        effectiveLabel: "loss",
        eventMainEligible: true,
        censored: false,
        reasons: [],
    },
    {
        eventId: "demo-06",
        securityId: "合成己",
        date: "2020-01-07",
        group: "neither",
        effectiveLabel: "unknown",
        eventMainEligible: false,
        censored: false,
        reasons: ["合成：結果品質未知"],
    },
];
export const syntheticComparison: ComparisonView = {
    id: "synthetic-component-v1",
    synthetic: true,
    source: {
        studyId: "synthetic-only",
        resultId: "synthetic-component-v1",
        settingsVersion: "synthetic-settings-v1",
        outcomeDefinition:
            "pattern_scan_event_outcomes_v1 effective_label (display vocabulary only)",
        inputVersion: "no-market-data",
        priceBasis: "synthetic-not-a-price-series",
        population: "展示：原固定冷卻事件；不是實際 L1 母體",
        source: "component fixture.ts",
    },
    windows: {
        126: {
            all: {
                status: "evaluated",
                counts: {
                    hit: 1,
                    known: 4,
                    stocks: 6,
                    unknown: 2,
                    censored: 1,
                },
            },
            cells: {
                neither: {
                    status: "evaluated",
                    counts: {
                        hit: 0,
                        known: 1,
                        stocks: 2,
                        unknown: 1,
                        censored: 0,
                    },
                },
                "prior-only": {
                    status: "evaluated",
                    counts: {
                        hit: 0,
                        known: 0,
                        stocks: 1,
                        unknown: 1,
                        censored: 1,
                    },
                },
                "today-only": {
                    status: "evaluated",
                    counts: {
                        hit: 0,
                        known: 1,
                        stocks: 1,
                        unknown: 0,
                        censored: 0,
                    },
                },
                both: {
                    status: "evaluated",
                    counts: {
                        hit: 1,
                        known: 2,
                        stocks: 2,
                        unknown: 0,
                        censored: 0,
                    },
                },
            },
            complements: {
                neither: {
                    status: "evaluated",
                    counts: {
                        hit: 1,
                        known: 3,
                        stocks: 4,
                        unknown: 1,
                        censored: 1,
                    },
                },
                "prior-only": {
                    status: "evaluated",
                    counts: {
                        hit: 1,
                        known: 4,
                        stocks: 5,
                        unknown: 1,
                        censored: 0,
                    },
                },
                "today-only": {
                    status: "evaluated",
                    counts: {
                        hit: 1,
                        known: 3,
                        stocks: 5,
                        unknown: 2,
                        censored: 1,
                    },
                },
                both: {
                    status: "evaluated",
                    counts: {
                        hit: 0,
                        known: 2,
                        stocks: 4,
                        unknown: 2,
                        censored: 1,
                    },
                },
            },
            cases,
            caseCoverage: "合成清單：6 筆；完整展示 fixture，非研究涵蓋率。",
        },
        252: {
            all: {
                status: "evaluated",
                counts: {
                    hit: 1,
                    known: 1,
                    stocks: 6,
                    unknown: 5,
                    censored: 5,
                },
            },
            cells: {},
            complements: {},
            cases: cases.map((item) =>
                item.eventId === "demo-01"
                    ? item
                    : {
                          ...item,
                          effectiveLabel: "unknown",
                          eventMainEligible: false,
                          censored: true,
                          reasons: ["合成：較長視窗尚未完整"],
                      },
            ),
            caseCoverage:
                "合成 H252：四格統計刻意未提供，測試未評估狀態；不可推論真實結果。",
        },
    },
};
