export type StudioPage =
    | "home"
    | "market"
    | "strategies"
    | "strategy"
    | "compare"
    | "studies"
    | "overview"
    | "stock"
    | "history"
    | "research"
    | "funds"
    | "wave-lab"
    | "market-legacy"
    | "market-preview"
    | "reports"
    | "data"
    | "report";
export function studioRoute(hash: string): {
    page: StudioPage;
    runId: string | null;
    reportId?: string;
    code?: string;
    securityKey?: string;
    overviewTab?: "stocks";
} {
    const value = hash.replace(/^#/, "").split("?")[0];
    if (value === "overview/stocks" || value === "data") {
        return { page: "overview", runId: null, overviewTab: "stocks" };
    }
    if (value.startsWith("stock/")) {
        const segment = value.slice("stock/".length);
        try {
            // Security keys are opaque API values. Decode the one URL segment,
            // but do not couple routing to today's key prefix or encoding.
            const securityKey = decodeURIComponent(segment);
            return securityKey &&
                !segment.includes("/") &&
                !Array.from(securityKey).some(
                    (character) =>
                        character.charCodeAt(0) < 32 ||
                        character.charCodeAt(0) === 127,
                )
                ? { page: "stock", runId: null, securityKey }
                : { page: "overview", runId: null, overviewTab: "stocks" };
        } catch {
            return { page: "overview", runId: null, overviewTab: "stocks" };
        }
    }
    if (value.startsWith("data/")) {
        try {
            const code = decodeURIComponent(value.slice("data/".length));
            return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(code)
                ? { page: "data", runId: null, code }
                : { page: "data", runId: null };
        } catch {
            return { page: "data", runId: null };
        }
    }
    if (value.startsWith("report/")) {
        try {
            const reportId = decodeURIComponent(value.slice("report/".length));
            return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(reportId)
                ? { page: "report", runId: null, reportId }
                : { page: "studies", runId: null };
        } catch {
            return { page: "studies", runId: null };
        }
    }
    if (value.startsWith("strategy/")) {
        try {
            const runId = decodeURIComponent(value.slice("strategy/".length));
            return runId
                ? { page: "strategy", runId }
                : { page: "strategies", runId: null };
        } catch {
            return { page: "strategies", runId: null };
        }
    }
    const pages = new Set<StudioPage>([
        "home",
        "market",
        "strategies",
        "compare",
        "studies",
        "overview",
        "research",
        "funds",
        "wave-lab",
        "market-legacy",
        "market-preview",
        "data",
    ]);
    // The research reports and history pages merged into one research page.
    if (value === "reports" || value === "history")
        return { page: "studies", runId: null };
    return {
        page: pages.has(value as StudioPage) ? (value as StudioPage) : "home",
        runId: null,
    };
}
