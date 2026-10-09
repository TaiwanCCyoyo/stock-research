import type { SavedResearchBundle } from "../domain/opportunities/research.ts";

/** Independently invented account/event controls; never derived from market archives. */
export function createSyntheticResearchBundle(): SavedResearchBundle {
    const date = "2020-01-02T09:00:00+08:00";
    return {
        schema: "saved-research-runs.v1",
        asOf: "2020-01-03",
        sources: [
            { id: "public-synthetic", label: "合成示範：虛構帳戶、股票與成交" },
        ],
        runs: [
            {
                id: "public-synthetic-account.v1",
                name: "合成示範帳戶（非研究結果）",
                from: "2020-01-02",
                through: "2020-01-03",
                currency: "TWD",
                initialCapital: 1000,
                finalEquity: 1010,
                netReturn: 0.01,
                costs: 0,
                method: {
                    taskId: "public-synthetic",
                    status: "exploratory",
                    ruleVersion: "fictional-account-control.v1",
                    rules: ["用虛構成交與淨值展示介面，不執行市場研究。"],
                    parameters: { synthetic: true },
                    conclusion: "合成示範，不能作為策略績效或投資依據。",
                    limitations: ["所有數值皆為虛構，沒有真實行情來源。"],
                },
                valuationBasis: "虛構帳戶控制值",
                limitations: ["合成示範，非歷史研究證據。"],
                sourceIds: ["public-synthetic"],
                nav: [
                    { date: "2020-01-02", equity: 1000 },
                    { date: "2020-01-03", equity: 1010 },
                ],
                events: [
                    {
                        id: "synthetic-buy-1",
                        date,
                        action: "BUY",
                        code: "SYNTHETIC-01",
                        quantity: 1,
                        price: 100,
                        cashFlow: -100,
                        original: {
                            date,
                            action: "BUY",
                            code: "SYNTHETIC-01",
                            qty: 1,
                            price: 100,
                            total: -100,
                            synthetic: true,
                        },
                    },
                ],
            },
        ],
    };
}
