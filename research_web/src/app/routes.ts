export type StudioPage =
    | "home"
    | "market"
    | "strategies"
    | "strategy"
    | "compare"
    | "history"
    | "research"
    | "funds"
    | "wave-lab"
    | "market-legacy"
    | "market-preview"
    | "reports"
    | "report";
export function studioRoute(hash: string): {
    page: StudioPage;
    runId: string | null;
    reportId?: string;
} {
    const value = hash.replace(/^#/, "").split("?")[0];
    if (value.startsWith("report/")) {
        try {
            const reportId = decodeURIComponent(value.slice("report/".length));
            return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(reportId)
                ? { page: "report", runId: null, reportId }
                : { page: "reports", runId: null };
        } catch {
            return { page: "reports", runId: null };
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
        "history",
        "research",
        "funds",
        "wave-lab",
        "market-legacy",
        "market-preview",
        "reports",
    ]);
    return {
        page: pages.has(value as StudioPage) ? (value as StudioPage) : "home",
        runId: null,
    };
}
