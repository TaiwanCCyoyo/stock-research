import type { LabCase, LabPoint } from "./types";

const DAY = 24 * 60 * 60 * 1000;

function weekdayDates(count: number): string[] {
    const dates: string[] = [];
    let time = Date.UTC(2020, 0, 1);
    while (dates.length < count) {
        const date = new Date(time);
        if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6)
            dates.push(date.toISOString().slice(0, 10));
        time += DAY;
    }
    return dates;
}

function seededNoise(index: number): number {
    const value = Math.sin((index + 17) * 12.9898) * 43758.5453;
    return value - Math.floor(value) - 0.5;
}

function series(values: (number | null)[], flags: string[] = []): LabPoint[] {
    return weekdayDates(values.length).map((date, index) => {
        const value = values[index];
        const price = value === null ? null : Number(value.toFixed(4));
        return { date, raw: price, adjusted: price, flags: [...flags] };
    });
}

function between(from: number, to: number, sessions: number): number[] {
    return Array.from(
        { length: sessions },
        (_, index) => from + ((to - from) * index) / Math.max(1, sessions - 1),
    );
}

function synthetic(
    id: string,
    name: string,
    category: string,
    question: string,
    values: (number | null)[],
): LabCase {
    const points = series(values);
    return {
        id,
        name,
        kind: "synthetic",
        category,
        question,
        points,
        source: {
            label: "合成反例：固定數學路徑，非真實市場資料",
            from: points[0].date,
            to: points.at(-1)!.date,
            priceBasis: "合成 raw/adjusted 價格",
            limitations: [
                "日期僅為決定性的週一至週五標籤，不宣稱為台灣交易日曆。",
                "此路徑只供方法檢驗，不能推論市場結果。",
            ],
        },
    };
}

const smoothSlow10x = Array.from(
    { length: 800 },
    (_, index) =>
        10 *
        Math.exp((Math.log(10) * index) / 799) *
        (1 + seededNoise(index) * 0.003),
);

const briefBurst = [
    ...between(30, 32, 80),
    ...between(32, 58, 12),
    ...between(58, 49, 28),
    ...between(49, 51, 60),
];

const deepDrawdownNewHigh = [
    ...between(20, 75, 90),
    ...between(75, 35, 45),
    ...between(35, 92, 75),
];

const userConsolidationRelaunch = [
    ...between(20, 25, 126),
    ...Array.from(
        { length: 84 },
        (_, index) => 25 + Math.sin(index * 0.55) * 1,
    ),
    ...between(26, 40, 15),
    ...between(40, 34, 12),
    ...between(34, 90, 42),
];

const failedLaunch = [
    ...between(25, 29, 70),
    ...between(29, 50, 18),
    ...between(50, 24, 45),
    ...between(24, 22, 35),
];

const flatNoiseControl = Array.from(
    { length: 220 },
    (_, index) => 40 + seededNoise(index) * 0.18,
);

const legitimateIsolatedJump = [
    ...Array.from({ length: 100 }, () => 100),
    ...Array.from({ length: 100 }, () => 170),
];

const missingQuotesWithNullGap = Array.from({ length: 180 }, (_, index) =>
    index >= 72 && index < 88 ? null : 50 + index * 0.12,
);

export const syntheticCases: LabCase[] = [
    synthetic(
        "smooth-slow-10x",
        "緩慢十倍成長（合成反例）",
        "長期平滑",
        "合成反例：長期平滑十倍路徑是否被誤判為必須有啟動點？",
        smoothSlow10x,
    ),
    synthetic(
        "brief-burst",
        "短暫急升（合成反例）",
        "短期爆發",
        "合成反例：短暫爆發是否被錯當成持續趨勢？",
        briefBurst,
    ),
    synthetic(
        "deep-drawdown-new-high",
        "深度回撤再創高（合成反例）",
        "回撤與新高",
        "合成反例：深度回撤後的新高是否保留為同一波段？",
        deepDrawdownNewHigh,
    ),
    synthetic(
        "user-consolidation-relaunch",
        "盤整後再加速（合成反例）",
        "盤整再啟動",
        "合成反例：使用者指定的盤整、回撤與再加速能否保留各階段？",
        userConsolidationRelaunch,
    ),
    synthetic(
        "failed-launch",
        "起漲後失敗（合成反例）",
        "失敗啟動",
        "合成反例：上升後失敗的啟動是否仍被保留？",
        failedLaunch,
    ),
    synthetic(
        "flat-noise-control",
        "平坦雜訊控制組（合成反例）",
        "控制組",
        "合成反例：平坦輕微雜訊是否避免產生虛假啟動？",
        flatNoiseControl,
    ),
    synthetic(
        "legitimate-isolated-jump",
        "合法孤立跳躍（合成反例）",
        "孤立跳躍",
        "合成反例：無預先回填斜坡的單日跳躍是否如實保留？",
        legitimateIsolatedJump,
    ),
    synthetic(
        "missing-quotes-null-gap",
        "缺報價空缺（合成反例）",
        "缺失報價",
        "合成反例：缺失報價是否保留為 null，而非內插？",
        missingQuotesWithNullGap,
    ),
];
