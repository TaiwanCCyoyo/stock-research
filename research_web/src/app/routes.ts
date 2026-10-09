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
    | "market-preview";
export function studioRoute(hash: string): {
    page: StudioPage;
    runId: string | null;
} {
    const value = hash.replace(/^#/, "").split("?")[0];
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
    ]);
    return {
        page: pages.has(value as StudioPage) ? (value as StudioPage) : "home",
        runId: null,
    };
}
