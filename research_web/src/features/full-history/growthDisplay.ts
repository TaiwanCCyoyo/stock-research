import type { HistoryRow } from "./types.ts";

export function growthBasisLabel(growth: HistoryRow["growth"]): string {
    if (growth?.basis === "annualized") return "年化報酬";
    if (growth?.basis === "actual") return "實際漲幅 · 未滿一年";
    return "時間指標待核對";
}

export function growthDurationLabel(growth: HistoryRow["growth"]): string {
    if (growth?.elapsedDays == null) return "起訖時間未知";
    return growth.elapsedYears != null && growth.elapsedYears >= 1
        ? `歷時 ${growth.elapsedYears.toFixed(2)} 年（${growth.elapsedDays.toLocaleString()} 天）`
        : `歷時 ${growth.elapsedDays.toLocaleString()} 天`;
}

export function growthUnknownExplanation(growth: HistoryRow["growth"]): string {
    if (growth?.reason === "left-censored-start")
        return "起點可能被資料截斷，尚不能確認完整行情的時間指標。";
    if (growth?.reason === "unknown-gain")
        return "價格或連續性證據不足，漲幅保留未知。";
    if (growth?.reason === "invalid-interval") return "起訖日期尚待核對。";
    return "時間調整資料尚在準備，請待資料服務更新後重新讀取。";
}
