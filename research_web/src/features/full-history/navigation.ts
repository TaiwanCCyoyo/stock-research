import type { HistoryDisplayMode } from "./model.ts";

/** Explicit values override persistent map controls; absent/invalid values do not. */
export function readMarketLink(hash: string) {
    const separator = hash.indexOf("?");
    if (separator < 0 || hash.slice(0, separator) !== "#market") return null;
    const params = new URLSearchParams(hash.slice(separator + 1));
    const requestedDate = params.get("date");
    const requestedCode = params.get("code");
    const requestedThreshold = Number(params.get("threshold"));
    const requestedMode = params.get("mode");
    return {
        date:
            requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)
                ? requestedDate
                : null,
        code:
            requestedCode && /^\d{4}$/.test(requestedCode)
                ? requestedCode
                : null,
        thresholdPct: [60, 80, 100, 200].includes(requestedThreshold)
            ? requestedThreshold
            : null,
        mode:
            requestedMode === "launched" || requestedMode === "catalog"
                ? (requestedMode as HistoryDisplayMode)
                : null,
    };
}

/** Saved participation and latest-market summaries share this fixed definition. */
export function marketCaptureLink(date: string, code?: string) {
    const params = new URLSearchParams({
        date,
        threshold: "100",
        mode: "launched",
    });
    if (code) params.set("code", code);
    return `#market?${params}`;
}
