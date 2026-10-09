import type {
    StudioCandle,
    StudioFill,
    StudioTrade,
} from "../../domain/strategies/types.ts";

export const fillLabel = (
    fill: Pick<StudioFill, "action" | "kind" | "retry">,
) => {
    if (fill.action === "BUY")
        return fill.retry
            ? "加碼重試"
            : fill.kind === "entry"
              ? "試單買進"
              : fill.kind === "add"
                ? "加碼"
                : "買進";
    return (
        (
            {
                SELL: "賣出",
                DIVIDEND: "股息入帳",
                DIVIDEND_ENTITLEMENT: "認列應收股息",
                SPLIT: "減資／分割",
                CAPITAL_RETURN: "減資退款入帳",
                CAPITAL_RETURN_ENTITLEMENT: "認列減資退款",
            } as Record<string, string>
        )[fill.action] ?? "其他帳務事件"
    );
};
export function validCandles(candles: StudioCandle[]) {
    return candles.filter(
        (
            point,
        ): point is StudioCandle & {
            open: number;
            high: number;
            low: number;
            close: number;
        } =>
            [point.open, point.high, point.low, point.close].every(
                (value) => value !== null && Number.isFinite(value),
            ),
    );
}
export function tradeMarks(trade: StudioTrade) {
    return trade.fills
        .filter((fill) => fill.action === "BUY" || fill.action === "SELL")
        .map((fill) => ({
            date: fill.date,
            price: fill.price,
            label: fillLabel(fill),
            action: fill.action,
        }));
}
/** Verify the displayed formula from saved cash movements, without making up missing flows. */
export function tradeCalculation(trade: StudioTrade) {
    const sum = (actions: string[]) => {
        const fills = trade.fills.filter((fill) =>
            actions.includes(fill.action),
        );
        return fills.some(
            (fill) => fill.cashFlow === null || !Number.isFinite(fill.cashFlow),
        )
            ? null
            : fills.reduce((total, fill) => total + fill.cashFlow!, 0);
    };
    const buyFlow = sum(["BUY"]),
        sellIncome = sum(["SELL"]),
        dividends = sum(["DIVIDEND", "CAPITAL_RETURN"]);
    const cost = buyFlow === null ? null : -buyFlow,
        mark = trade.closeDate ? 0 : trade.mark;
    const pnl =
        cost === null ||
        sellIncome === null ||
        dividends === null ||
        mark === null
            ? null
            : sellIncome + dividends + mark - cost;
    const rate = pnl === null || cost === null || cost <= 0 ? null : pnl / cost;
    const difference =
        pnl === null || trade.pnl === null ? null : pnl - trade.pnl;
    return {
        cost,
        sellIncome,
        dividends,
        mark,
        pnl,
        return: rate,
        difference,
        verified:
            difference !== null &&
            Math.abs(difference) < 0.01 &&
            cost !== null &&
            Math.abs(cost - trade.cost) < 0.01,
    };
}
