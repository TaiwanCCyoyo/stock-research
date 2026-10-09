/** Read-only saved accounting evidence. Money is TWD; returns/weights are fractions. */
export interface StudioCandle {
    date: string;
    open: number | null;
    high: number | null;
    low: number | null;
    close: number | null;
    sourceId: string;
    name?: string | null;
}
export interface StudioCandidate {
    code: string;
    affordability: string;
}
export interface StudioFill {
    id: string;
    date: string;
    timestamp: string;
    action: string;
    quantity: number | null;
    price: number | null;
    cashFlow: number | null;
    fee: number | null;
    tax: number | null;
    penalty: number | null;
    kind: "entry" | "add" | "retry" | "sell" | "corporate-action" | "unknown";
    decisionDate: string | null;
    orderId: string | null;
    retry: boolean;
    entryCandidates: StudioCandidate[] | null;
    dailyRank: number | null;
    rankMissingReason: string;
    dayOpen: number | null;
    dayClose: number | null;
    original: Record<string, unknown>;
    addSignal?: {
        economicReturn: number | null;
        reason: string | null;
        orderId: string | null;
        original: Record<string, unknown>;
    } | null;
}
export interface StudioCapture {
    days: number | null;
    knownDays: number;
    totalDays: number;
    bestMetric: number | null;
    missingReason: string | null;
}
export interface StudioTrade {
    id: string;
    code: string;
    name: string;
    openDate: string;
    closeDate: string | null;
    nameSourceId?: string | null;
    nameBasis?: string;
    cost: number;
    inflow: number;
    mark: number | null;
    markPrice: number | null;
    quantityEnd: number;
    remainingCost: number;
    pnl: number | null;
    realizedPnl: number | null;
    unrealizedPnl: number | null;
    return: number | null;
    days: number;
    capture: StudioCapture;
    fills: StudioFill[];
    candles: StudioCandle[];
    missingReasons: string[];
    whySell: string;
    formula: string;
    pendingAssets?: {
        entitlementId: string;
        date: string;
        action: string;
        amount: number | null;
        qualifiedQuantity: number | null;
        eventId: string;
    }[];
}
export interface StudioNav {
    date: string;
    equity: number;
    benchmarkEquity: number | null;
    drawdown: number;
}
export interface StudioHolding {
    code: string;
    name: string;
    quantity: number;
    price: number | null;
    marketValue: number | null;
    nameSourceId?: string | null;
    nameBasis?: string;
    sourceId: string | null;
    observedAt: string | null;
    availableAt: string | null;
    modeled: boolean | null;
    missingReason: string | null;
    onMap: boolean | null;
}
export interface StudioAccount {
    date: string;
    timestamp: string;
    cash: number;
    holdings: StudioHolding[];
    otherAssets: number | null;
    receivables: unknown[];
    shareClaims: unknown[];
    reconstructedEquity: number | null;
    recordedEquity: number;
    difference: number | null;
    verified: boolean;
    reasons: string[];
}
export interface StudioStatistics {
    maxDrawdown: number;
    longestUnderwater: {
        days: number;
        from: string | null;
        until: string | null;
    };
    longestLosingStreak: {
        count: number;
        pnl: number;
        from: string | null;
        until: string | null;
    };
    monthlyReturns: { month: string; return: number }[];
    winRate: number | null;
    meanGain: number | null;
    meanLoss: number | null;
    topFiveProfitShare: number | null;
    topFiveShareDefinition: string;
    histogram: { from: number | null; until: number | null; count: number }[];
}
export interface StudioReconciliation {
    closedPnl: number;
    openPnl: number | null;
    otherAssets: number | null;
    totalPnl: number | null;
    accountIncrease: number;
    difference: number | null;
    verified: boolean;
    reasons: string[];
}
export interface StudioCaptureCoverage {
    closedTradeTotal: number;
    confirmedCapturedClosedTradeCount: number;
    confirmedNotCapturedClosedTradeCount: number;
    undeterminedClosedTradeCount: number;
    completeExposureDays: number;
    totalExposureDays: number;
    knownDayAverageWeight: number | null;
}
export interface StudioSummary {
    id: string;
    name: string;
    plainTitle: string;
    plainIdea: string;
    ownerAdopted: boolean | null;
    studyStatus: "exploratory" | "failed" | "accepted";
    initialCapital: number;
    finalEquity: number;
    from: string;
    through: string;
    netReturn: number;
    maxDrawdown: number;
    longestUnderwater: StudioStatistics["longestUnderwater"];
    winRate: number | null;
    costs: number;
    closedTradeCount: number;
    capturedClosedTradeCount: number | null;
    captureAvgWeight: number | null;
    captureCoverage?: StudioCaptureCoverage;
    nav: StudioNav[];
    limitations: string[];
    captureState: "loading" | "ready" | "failed";
}
export interface StudioRun extends StudioSummary {
    positions: StudioTrade[];
    statistics: StudioStatistics;
    reconciliation: StudioReconciliation;
    method: { rules: string[]; conclusion: string; [key: string]: unknown };
    benchmark: {
        code: string;
        label: string;
        basis: string;
        missingReason: string | null;
    };
    sourceIds: string[];
    accountDates: string[];
}
export interface StudioIndex {
    synthetic?: boolean;
    dataMode?: "public-synthetic" | "local-private";
    schema: "saved-research-studio.v1";
    captureState: "loading" | "ready" | "failed";
    runs: StudioSummary[];
}
export interface StudioHistoryItem {
    id: string;
    date: string;
    title: string;
    section?: "method" | "market" | "design";
    savedTitle?: string;
    originalTitleUnavailable?: boolean;
    legacyPresentationTitle?: string | null;
    titleSourceRevision?: string;
    status: string;
    conclusion: string;
    originalSummary: string;
    reportPath: string | null;
    reviewConfirmed: boolean;
    evidenceState: string;
    registryEventIds: string[];
    dateBasis?: string;
    outcome?: string | null;
    draftStatus?: string | null;
    summarySource?: "formal-report" | "presentation-metadata" | "mission";
    sourceNote?: string | null;
}
export interface StudioHistory {
    schema: "saved-research-history.v1";
    historyComplete: false;
    items: StudioHistoryItem[];
}
export interface StudioExposure {
    runId: string;
    basis: string;
    captureState: "loading" | "ready" | "failed";
    rows: {
        date: string;
        runawayWeight: number | null;
        otherStockWeight: number | null;
        cashWeight: number | null;
        otherAssetsWeight: number | null;
        unknownStockWeight: number | null;
        known: boolean;
        verifiedAccount: boolean;
    }[];
}
