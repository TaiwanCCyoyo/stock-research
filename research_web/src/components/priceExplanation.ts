const CORPORATE_ACTION_CLOSE =
    "raw: official price_daily.parquet Close, unadjusted; adjusted: Raw Close multiplied by subsequent valid permanent corporate-action price factors; cash dividends are not reinvested";

// Interpret supported source descriptions explicitly; unknown formats must not
// inherit the adjustment or dividend assumptions of another dataset.
export function priceExplanation(basis: string): string {
    return priceDescription(basis).detail;
}

export function priceSummary(basis: string): string {
    return priceDescription(basis).summary;
}

function priceDescription(basis: string) {
    switch (basis) {
        case CORPORATE_ACTION_CLOSE:
        case "收盤價經已記錄的公司行動調整；不含股息再投資":
            return {
                summary: "調整後收盤價 · 不含股息再投入",
                detail: "以調整後收盤價計算，已反映股票分割等公司行動；不含股息再投入。",
            };
        case "adjusted close":
        case "adjusted-close":
            return {
                summary: "調整後收盤價 · 股息計算待確認",
                detail: "以調整後收盤價計算；股息是否再投入尚未確認。",
            };
        case "合成收盤價；不代表任何真實交易":
        case "合成 raw/adjusted 價格":
            return {
                summary: "模擬價格 · 非真實交易",
                detail: "這是互動示意用的模擬價格，不代表真實交易。",
            };
        default:
            return {
                summary: "價格與股息計算方式待確認",
                detail: "價格調整與股息計算方式尚待確認。",
            };
    }
}
