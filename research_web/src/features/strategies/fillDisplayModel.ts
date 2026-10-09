import { money } from "./format.ts";

/** Dividend recognition and receipt are accounting events, not trade executions. */
export function transactionCost(
    value: number | null | undefined,
    action: string,
): string {
    if (
        value == null &&
        (action === "DIVIDEND" || action === "DIVIDEND_ENTITLEMENT")
    )
        return "—";
    return money(value, true);
}

export const dividendCostNote =
    "— 表示股息紀錄不適用這些交易成本；未保存的買賣成本仍標示未知。";
