import type {
    OpportunityBundle,
    OpportunityPortfolio,
    OpportunitySecurity,
    OpportunityWave,
} from "./types.ts";

export function dayAfter(date: string): string {
    return new Date(Date.parse(`${date}T00:00:00Z`) + 86400000)
        .toISOString()
        .slice(0, 10);
}

/** Deterministic fictional controls. These names, prices and holdings are not research. */
export function createOpportunityFixture(): OpportunityBundle {
    const dates: string[] = [];
    for (let t = Date.UTC(2020, 0, 2); dates.length < 780; t += 86400000) {
        const d = new Date(t);
        if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6)
            dates.push(d.toISOString().slice(0, 10));
    }
    const end = dayAfter(dates.at(-1)!);
    const labels = [
        "晶片設計",
        "海運運輸",
        "綠色能源",
        "雲端設備",
        "醫療研發",
        "精密製造",
    ];
    const roots = ["星河", "遠洋", "晴日", "雲峰", "新生", "光域"];
    const starts = [10, 62, 206, 335, 460, 565];
    const securities: OpportunitySecurity[] = [];
    const waves: OpportunityWave[] = [];
    for (let g = 0; g < labels.length; g++) {
        for (let j = 0; j < 6; j++) {
            const id = `demo-${g}-${j}`;
            const start = starts[g] + j * 10;
            const launchIndex = start + 40 + j * 3;
            const peak = Math.min(779, start + 175 + j * 8);
            const confirmed = start + 270 + j * 5;
            const maximum = 1.4 + g * 0.23 + j * 0.65;
            const noLaunch = j === 5;
            const base = 20 + g * 12 + j * 3;
            const prices = dates.map((date, k) => {
                let gain = 0;
                if (k > start && k < launchIndex)
                    gain = (0.2 * (k - start)) / (launchIndex - start);
                else if (k >= launchIndex && k <= peak) {
                    const progress =
                        (k - launchIndex) / (peak - launchIndex || 1);
                    const eased =
                        progress < 0.42
                            ? progress * 1.12
                            : progress < 0.58
                              ? 0.47 + 0.015 * Math.sin(progress * 85)
                              : 0.47 + ((progress - 0.58) * 0.53) / 0.42;
                    gain = 0.2 + (maximum - 0.2) * eased;
                } else if (k > peak)
                    gain =
                        maximum *
                        (1 -
                            0.48 *
                                Math.min(
                                    1,
                                    (k - peak) / Math.max(1, confirmed - peak),
                                ));
                if (noLaunch && k > start && k <= peak)
                    gain = (maximum * (k - start)) / (peak - start);
                return {
                    date,
                    close: base * (1 + gain),
                    raw: base * (1 + gain),
                    flags: [] as string[],
                    marketCap: 100 + g * 500 + j * 30,
                };
            });
            const restFrom = Math.round(
                launchIndex + (peak - launchIndex) * 0.42,
            );
            const restEnd = Math.round(
                launchIndex + (peak - launchIndex) * 0.58,
            );
            securities.push({
                id,
                code: `S${g + 1}${j + 1}`,
                name: `${roots[g]}${j + 1}號`,
                market: "示意市場",
                currency: "TWD",
                prices,
                industry: [
                    {
                        id: `demo-group-${g}`,
                        label: labels[g],
                        from: dates[0],
                        untilExclusive: end,
                        basis: "historical",
                        sourceId: "synthetic",
                    },
                ],
            });
            waves.push({
                id: `wave-${id}`,
                securityId: id,
                start: dates[start],
                launch: noLaunch
                    ? null
                    : {
                          date: dates[launchIndex],
                          rangeFrom: dates[Math.max(start, launchIndex - 3)],
                          rangeUntil: dates[launchIndex + 3],
                          sourceId: "synthetic",
                      },
                launchMissingReason: noLaunch
                    ? "持續慢慢上漲，沒有突然加速的日期（合成對照）"
                    : null,
                peakDate: dates[peak],
                endConfirmedAt:
                    confirmed < dates.length ? dates[confirmed] : null,
                observedThrough: dates.at(-1)!,
                leftCensored: false,
                rightCensored: confirmed >= dates.length,
                scale: "synthetic-declared",
                parentId: null,
                sourceId: "synthetic",
                phases: [
                    {
                        from: dates[start],
                        untilExclusive: dates[launchIndex],
                        kind: "slow" as const,
                    },
                    {
                        from: dates[launchIndex],
                        untilExclusive: dates[restFrom],
                        kind: "rising" as const,
                    },
                    {
                        from: dates[restFrom],
                        untilExclusive: dates[restEnd],
                        kind: "resting" as const,
                    },
                    {
                        from: dates[restEnd],
                        untilExclusive: dayAfter(dates[peak]),
                        kind: "rising" as const,
                    },
                    ...(peak + 1 < dates.length
                        ? [
                              {
                                  from: dates[peak + 1],
                                  untilExclusive:
                                      confirmed < dates.length
                                          ? dates[confirmed]
                                          : end,
                                  kind: "retreat" as const,
                              },
                          ]
                        : []),
                ].filter((p) => p.from < p.untilExclusive),
            });
        }
    }
    const portfolios: OpportunityPortfolio[] = Array.from(
        { length: 21 },
        (_, i) => {
            const kind = i < 11 ? "strategy" : i < 16 ? "tw-etf" : "us-etf";
            const title =
                i < 11
                    ? `示意策略 ${String(i + 1).padStart(2, "0")}`
                    : i < 16
                      ? `示意台股 ETF ${i - 10}`
                      : `示意美股 ETF ${i - 15}`;
            const missing = i === 20;
            const partial = i === 19;
            const holdings = missing
                ? []
                : waves
                      .filter((_, n) => (n + i) % 4 === 0)
                      .map((w) => {
                          const start = dates.indexOf(
                              w.launch?.date ?? w.start,
                          );
                          const from = Math.min(779, start + (i % 5) * 12);
                          const until = Math.min(
                              780,
                              Math.max(
                                  from + 1,
                                  dates.indexOf(w.peakDate) + 30 - (i % 4) * 20,
                              ),
                          );
                          return {
                              securityId: w.securityId,
                              from: dates[from],
                              untilExclusive:
                                  until < dates.length ? dates[until] : end,
                              sourceId: "synthetic",
                              quantity: 1000,
                          };
                      });
            return {
                id: `demo-portfolio-${i}`,
                name: title,
                kind,
                description: "完全合成的持股情境，只供操作與資料不足狀態驗證。",
                sourceIds: ["synthetic"],
                coverage: missing
                    ? []
                    : [
                          {
                              from: dates[0],
                              untilExclusive: end,
                              completeness: partial ? "partial" : "full",
                              kind: "daily",
                              sourceId: "synthetic",
                          },
                      ],
                holdings,
                allocations: missing
                    ? []
                    : dates.map((date) => {
                          const held = holdings.filter(
                              (h) => h.from <= date && date < h.untilExclusive,
                          );
                          const cashWeight = held.length
                              ? 0.15 + (i % 4) * 0.1
                              : 1;
                          const positions = held.map((h) => ({
                              securityId: h.securityId,
                              weight: (1 - cashWeight) / held.length,
                          }));
                          return {
                              date,
                              completeness: partial
                                  ? ("partial" as const)
                                  : ("full" as const),
                              nav: 2000000,
                              cashWeight: partial ? null : cashWeight,
                              positions: partial
                                  ? positions.slice(0, 1)
                                  : positions,
                              sourceId: "synthetic",
                          };
                      }),
                limitations: [
                    "不是實際策略回測或任何真實 ETF 的持股。",
                    ...(missing
                        ? ["刻意保留資料缺失，驗證不知道與沒持有不同。"]
                        : []),
                ],
            };
        },
    );
    return {
        schema: "opportunity-explorer.v1",
        id: "opportunity-interaction-control.v1",
        label: "互動示意 · 36 檔虛構股票",
        kind: "synthetic",
        asOf: dates.at(-1)!,
        dates,
        priceBasis: "合成收盤價；不代表任何真實交易",
        catalogCoverage: "declared-universe",
        ruleVersion: "hand-declared-interaction-control.v1",
        selectionPolicy: "explicit-representative-launch-to-confirmation.v1",
        classificationVersion: "synthetic-groups.v1",
        sources: [
            {
                id: "synthetic",
                label: "固定且可重建的介面控制資料；股票、ETF 與持股全為合成",
            },
        ],
        limitations: [
            "所有價格、時間、產業與投資組合均為合成示意。",
            "比較結果只驗證介面與計算一致，不代表任何策略有效。",
        ],
        securities,
        waves,
        representatives: waves.map((w) => ({
            securityId: w.securityId,
            waveId: w.id,
            from: dates[0],
            untilExclusive: end,
        })),
        portfolios,
    };
}
