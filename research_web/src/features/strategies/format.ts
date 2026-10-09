export const money = (value: number | null | undefined, precise = false) => {
    if (value == null || !Number.isFinite(value)) return "未知";
    const absolute = Math.abs(value);
    const sign = value < 0 ? "−" : "";
    return precise || absolute < 10000
        ? `${sign}${absolute.toLocaleString("zh-TW", { maximumFractionDigits: precise ? 2 : 0 })} 元`
        : `${sign}${(absolute / 10000).toLocaleString("zh-TW", { maximumFractionDigits: absolute < 1000000 ? 1 : 0 })} 萬元`;
};
export const currencyMoney = (
    value: number | null | undefined,
    currency: string,
    precise = false,
) => {
    if (value == null || !Number.isFinite(value) || currency === "TWD")
        return money(value, precise);
    return `${currency} ${value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })}`;
};
export const percentage = (value: number | null | undefined, digits = 1) =>
    value == null || !Number.isFinite(value)
        ? "未知"
        : `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value * 100).toFixed(digits)}%`;
export const ratio = (value: number | null | undefined, digits = 1) =>
    value == null || !Number.isFinite(value)
        ? "未知"
        : `${value < 0 ? "−" : ""}${Math.abs(value * 100).toFixed(digits)}%`;
export const duration = (days: number | null | undefined) =>
    days == null
        ? "未知"
        : days >= 365.25
          ? `${(days / 365.25).toFixed(1)} 年`
          : `${Math.round(days)} 天`;
export const gainClass = (value: number | null | undefined) =>
    value == null || !Number.isFinite(value)
        ? ""
        : value > 0
          ? "ss-gain"
          : value < 0
            ? "ss-loss"
            : "";
