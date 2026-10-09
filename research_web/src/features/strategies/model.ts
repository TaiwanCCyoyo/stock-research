import type {
    StudioNav,
    StudioSummary,
    StudioTrade,
} from "../../domain/strategies/types.ts";

export type StrategyStatus = "research" | "adopted" | "failed";
export function strategyStatus(
    run: Pick<StudioSummary, "ownerAdopted" | "studyStatus">,
): StrategyStatus {
    if (run.ownerAdopted === true) return "adopted";
    return run.studyStatus === "failed" ? "failed" : "research";
}
export function filterStrategies(
    runs: StudioSummary[],
    status: StrategyStatus | "all",
) {
    return status === "all"
        ? runs
        : runs.filter((run) => strategyStatus(run) === status);
}
export type TradeFilter = "all" | "gain" | "loss" | "captured" | "open";
export type TradeSort =
    | "code"
    | "openDate"
    | "closeDate"
    | "days"
    | "cost"
    | "pnl"
    | "return"
    | "captured";
export function selectTrades(
    trades: StudioTrade[],
    filter: TradeFilter,
    query: string,
    sort: TradeSort,
    direction: 1 | -1,
) {
    const needle = query.trim().toLocaleLowerCase();
    const matching = trades.filter((trade) => {
        if (
            needle &&
            !`${trade.code} ${trade.name}`.toLocaleLowerCase().includes(needle)
        )
            return false;
        if (filter === "gain")
            return trade.closeDate !== null && (trade.realizedPnl ?? 0) > 0;
        if (filter === "loss")
            return (
                trade.closeDate !== null &&
                trade.realizedPnl !== null &&
                trade.realizedPnl < 0
            );
        if (filter === "captured")
            return trade.capture.days !== null && trade.capture.days > 0;
        if (filter === "open") return trade.closeDate === null;
        return true;
    });
    return [...matching].sort((a, b) => {
        const left = sort === "captured" ? a.capture.days : a[sort];
        const right = sort === "captured" ? b.capture.days : b[sort];
        if (left === null && right !== null) return 1;
        if (right === null && left !== null) return -1;
        if (left === null || right === null) return a.id.localeCompare(b.id);
        return (
            (typeof left === "string" && typeof right === "string"
                ? left.localeCompare(right)
                : Number(left) - Number(right)) * direction ||
            a.id.localeCompare(b.id)
        );
    });
}
export type WalkthroughRole = "only" | "best" | "median" | "worst";
export interface WalkthroughPick {
    trade: StudioTrade;
    role: WalkthroughRole;
}
/** Distinct closed cycles with all four saved steps, ranked by saved realized PnL. */
export function walkthroughTrades(trades: StudioTrade[]): WalkthroughPick[] {
    const complete = trades.filter(
        (trade) =>
            trade.closeDate !== null &&
            trade.realizedPnl !== null &&
            trade.fills.some(
                (fill) => fill.kind === "add" || fill.kind === "retry",
            ) &&
            trade.fills.some((fill) => fill.action === "SELL") &&
            trade.fills.some(
                (fill) => fill.action === "BUY" && fill.entryCandidates?.length,
            ),
    );
    const sorted = [...complete].sort(
        (a, b) => b.realizedPnl! - a.realizedPnl! || a.id.localeCompare(b.id),
    );
    const seenIds = new Set<string>();
    const distinct = sorted.filter((trade) => {
        if (seenIds.has(trade.id)) return false;
        seenIds.add(trade.id);
        return true;
    });
    if (!distinct.length) return [];
    if (distinct.length === 1) return [{ trade: distinct[0], role: "only" }];
    const best: WalkthroughPick = { trade: distinct[0], role: "best" };
    const worst: WalkthroughPick = { trade: distinct.at(-1)!, role: "worst" };
    if (distinct.length === 2) return [best, worst];
    return [
        best,
        {
            trade: distinct[Math.floor((distinct.length - 1) / 2)],
            role: "median",
        },
        worst,
    ];
}
/** Align actual saved dates only, never interpolate missing benchmark observations. */
export function alignComparisons(runs: Pick<StudioSummary, "id" | "nav">[]) {
    if (runs.length < 2)
        return {
            dates: [] as string[],
            series: [] as {
                id: string;
                values: number[];
                points: StudioNav[];
            }[],
            benchmark: [] as (number | null)[],
        };
    const maps = runs.map(
        (run) => new Map(run.nav.map((point) => [point.date, point])),
    );
    const common = runs[0].nav
        .map((point) => point.date)
        .filter((date) => maps.every((map) => map.has(date)));
    const dates = common.filter((date) =>
        maps.every(
            (map) =>
                Number.isFinite(map.get(date)?.equity) &&
                (map.get(date)?.equity ?? 0) > 0,
        ),
    );
    const series = runs.map((run, index) => {
        const points = dates.map((date) => maps[index].get(date)!);
        const first = points[0]?.equity ?? 1;
        return {
            id: run.id,
            points,
            values: points.map((point) => (point.equity / first) * 100),
        };
    });
    const firstBenchmark = dates.length
        ? maps[0].get(dates[0])?.benchmarkEquity
        : null;
    const benchmark = dates.map((date) => {
        const point = maps[0].get(date)?.benchmarkEquity;
        return point == null || firstBenchmark == null || firstBenchmark <= 0
            ? null
            : (point / firstBenchmark) * 100;
    });
    return { dates, series, benchmark };
}
export function periodMetrics(points: { date: string; equity: number }[]) {
    if (!points.length || points[0].equity <= 0) return null;
    let peak = points[0].equity,
        maxDrawdown = 0,
        peakDate = points[0].date,
        longest = 0,
        underwaterFrom: string | null = null;
    for (const point of points) {
        if (point.equity >= peak) {
            if (underwaterFrom !== null) {
                const days =
                    (Date.parse(point.date) - Date.parse(underwaterFrom)) /
                    86400000;
                longest = Math.max(longest, days);
            }
            peak = point.equity;
            peakDate = point.date;
            underwaterFrom = null;
        } else {
            underwaterFrom ??= peakDate;
            const days =
                (Date.parse(point.date) - Date.parse(underwaterFrom)) /
                86400000;
            longest = Math.max(longest, days);
        }
        maxDrawdown = Math.min(maxDrawdown, point.equity / peak - 1);
    }
    return {
        return: points.at(-1)!.equity / points[0].equity - 1,
        maxDrawdown,
        longestUnderwaterDays: longest,
    };
}
