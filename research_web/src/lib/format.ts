/** Number/date formatting shared across views. */

export function fmtNum(value: number | null | undefined, digits = 0): string {
    if (value === null || value === undefined || Number.isNaN(value))
        return "—";
    return value.toLocaleString("zh-TW", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined || Number.isNaN(value))
        return "—";
    return `${fmtNum(value, digits)}%`;
}

export function fmtRatio(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value))
        return "—";
    return `${value.toFixed(2)}x`;
}

/** "2018-12-07T00:00:00.000" -> "2018-12-07" */
export function dateOnly(value: string | null | undefined): string {
    if (!value) return "—";
    return String(value).slice(0, 10);
}

/** Sign class for TW market coloring (positive = red/up). */
export function signClass(value: number | null | undefined): string {
    if (
        value === null ||
        value === undefined ||
        Number.isNaN(value) ||
        value === 0
    )
        return "";
    return value > 0 ? "pos" : "neg";
}

export function tdSignClass(value: number | null | undefined): string {
    if (
        value === null ||
        value === undefined ||
        Number.isNaN(value) ||
        value === 0
    )
        return "";
    return value > 0 ? "td-pos" : "td-neg";
}

/** Known signal/event codes → user-facing labels; unknown codes fall back to underscore-stripped text. */
const SIGNAL_LABELS: Record<string, string> = {
    ma_convergence: "均線收斂",
    ma_convergence_price_strength: "均線收斂後價格轉強",
    bottom_2b: "底部 2B 收復",
    bottom_2b_ma_convergence: "底部 2B 收復且均線收斂",
    bottom_2b_add: "底部 2B 收復，加碼",
    top_2b: "頂部 2B 反轉",
    top_2b_exit: "頂部 2B 反轉，全部出場",
    stop_loss_exit: "觸發停損，全部出場",
    ma_break_partial_exit: "跌破出場均線，部分賣出",
    breakout: "突破",
    trend_break: "趨勢跌破",
    buy: "買進訊號",
    add: "加碼訊號",
    sell: "賣出訊號",
    partial_sell: "部分賣出",
    dividend: "配息",
    cash_blocked: "資金不足",
};

/** Mirrors research_lab/display.py::signal_reason_label — comma-split compounds, " + " join. */
export function translateSignal(code: string | null | undefined): string {
    const value = (code ?? "").trim();
    if (!value) return "—";
    const label = (part: string): string =>
        SIGNAL_LABELS[part] ?? part.replace(/_/g, " ");
    const parts = value
        .split(",")
        .map((part) => part.trim())
        .filter(Boolean);
    return parts.length > 1 ? parts.map(label).join(" + ") : label(value);
}

/** "2330" -> "2330 台積電" when a name is known, otherwise the bare code. */
export function stockLabel(
    code: string | null | undefined,
    names?: Record<string, string>,
): string {
    if (!code) return "—";
    const name = names?.[String(code)];
    return name ? `${code} ${name}` : String(code);
}

/** Localized label + badge style for a trade action (BUY/SELL/DIVIDEND/SPLIT/...). */
export function actionBadge(
    action: string,
    isAddOn = false,
): { label: string; cls: string } {
    switch (action.toUpperCase()) {
        case "BUY":
            return { label: isAddOn ? "加碼" : "買進", cls: "buy" };
        case "SELL":
            return { label: "賣出", cls: "sell" };
        case "DIVIDEND":
            return { label: "配息", cls: "event" };
        case "SPLIT":
            return { label: "分割", cls: "event" };
        default:
            return { label: action, cls: "event" };
    }
}
