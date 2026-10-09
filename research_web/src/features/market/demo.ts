import type { AtlasData } from "./model";

// Synthetic fixtures for interaction design; never mixed with the historical source.
export function demoAtlas(): AtlasData {
    const groups = [
        "晶片與運算",
        "海洋運輸",
        "綠色能源",
        "智慧工業",
        "數位生活",
        "醫療創新",
        "材料科學",
        "基礎建設",
    ].map((label, i) => ({ id: `demo-${i}`, label }));
    const dates: string[] = [];
    for (let day = 0; day < 520; day++) {
        const d = new Date(Date.UTC(2020, 0, 1 + day));
        if (![0, 6].includes(d.getUTCDay()))
            dates.push(d.toISOString().slice(0, 10));
    }
    const stocks = Array.from({ length: 64 }, (_, i) => {
        const g = i % 8,
            phase = g * 0.73,
            base = 25 + i * 2;
        const raw = dates.map((_, t) =>
            Number(
                (
                    base *
                    Math.exp(
                        0.002 * t +
                            0.75 * Math.sin(t / 65 + phase) +
                            0.16 * Math.sin(t / 23 + i),
                    )
                ).toFixed(4),
            ),
        );
        return {
            code: `D${String(i + 1).padStart(3, "0")}`,
            name: `${["晨光", "遠山", "青禾", "雲海", "星河", "雨林", "新芽", "長風"][g]} ${Math.floor(i / 8) + 1}`,
            groupIds: [groups[g].id],
            quality: [],
            raw,
            adjusted: [...raw],
            marketCap: dates.map((_, t) =>
                Number(((50 * 10 ** (i % 4) * raw[t]) / base).toFixed(3)),
            ),
        };
    });
    return {
        schema: "market-atlas.v1",
        catalogHash: "synthetic-interaction-demo",
        classificationAsOf: "示意",
        dates,
        groups,
        stocks,
        provenance: {
            kind: "synthetic",
            description: "數學生成的假想股票，不代表歷史市場。市值單位：億元。",
        },
        limitations: [
            "所有股票、價格、市值都是互動展示資料，不能用於研究結論。",
        ],
    };
}
