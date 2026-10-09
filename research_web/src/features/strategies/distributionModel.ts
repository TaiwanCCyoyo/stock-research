type SavedTrade = {
    closeDate: string | null;
    return: number | null | undefined;
};

const intervals = [
    { label: "< −50%", from: null, until: -0.5, tone: "loss" },
    { label: "−50～−20%", from: -0.5, until: -0.2, tone: "loss" },
    { label: "−20～−10%", from: -0.2, until: -0.1, tone: "loss" },
    { label: "−10～−5%", from: -0.1, until: -0.05, tone: "loss" },
    { label: "−5～< 0%", from: -0.05, until: 0, tone: "loss" },
    { label: "0%", from: 0, until: 0, tone: "neutral" },
    { label: "> 0～< 5%", from: 0, until: 0.05, tone: "gain" },
    { label: "5～< 10%", from: 0.05, until: 0.1, tone: "gain" },
    { label: "10～< 20%", from: 0.1, until: 0.2, tone: "gain" },
    { label: "20～< 50%", from: 0.2, until: 0.5, tone: "gain" },
    { label: "50～< 100%", from: 0.5, until: 1, tone: "gain" },
    { label: "≥ 100%", from: 1, until: null, tone: "gain" },
] as const;

/** Display bins use saved closed-position returns, never reconstructed prices. */
export function savedReturnDistribution(trades: readonly SavedTrade[]) {
    const buckets = intervals.map((interval) => ({ ...interval, count: 0 }));
    let excluded = 0;
    let total = 0;
    for (const trade of trades) {
        if (trade.closeDate === null) continue;
        total++;
        const value = trade.return;
        if (value == null || !Number.isFinite(value)) {
            excluded++;
            continue;
        }
        const bucket =
            value === 0
                ? buckets[5]
                : buckets.find(
                      (candidate) =>
                          candidate.tone !== "neutral" &&
                          (candidate.from === null ||
                              value >= candidate.from) &&
                          (candidate.until === null || value < candidate.until),
                  );
        bucket!.count++;
    }
    return { buckets, excluded, total, included: total - excluded };
}
