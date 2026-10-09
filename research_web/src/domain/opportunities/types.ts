/** Portable, additive research/view contract. Returns use percent; weights use 0..1. */
export type HoldingState = "held" | "not-held" | "unknown";
export type PhaseKind = "slow" | "rising" | "resting" | "retreat";
export interface SourceRef {
    id: string;
    label: string;
    path?: string;
    url?: string;
    hash?: string;
    publishedAt?: string;
}
export interface PricePoint {
    date: string;
    close: number | null;
    raw?: number | null;
    flags: string[];
    marketCap?: number | null;
}
export interface IndustryMembership {
    id: string;
    label: string;
    from: string;
    untilExclusive: string | null;
    /** document-period is retrospective business grouping, not exchange-effective/PIT evidence. */
    basis: "historical" | "document-period" | "current-snapshot" | "unknown";
    sourceId: string;
}
/** Evidence references can overlap and describe multiple roles; they do not select map groups. */
export interface ClassificationReference {
    id: string;
    label: string;
    layer:
        | "official-value-chain"
        | "research-group"
        | "business-role"
        | "business-group"
        | "business-sector";
    temporalScope:
        | "snapshot"
        | "retrospective-period-summary"
        | "retrospective-event-context"
        | "undated-reference"
        | "dated-profile-reference";
    from: string | null;
    untilExclusive: string | null;
    sourceIds: string[];
}
export interface OpportunitySecurity {
    id: string;
    code: string;
    name: string;
    market: string;
    currency: string;
    /** Observed metadata only; never an effective historical membership. */
    classificationSnapshot?: {
        label: string;
        observedAt: string | null;
        sourceId: string;
    };
    classificationReferences?: ClassificationReference[];
    industry: IndustryMembership[];
    prices: PricePoint[];
    detailCaseId?: string;
}
export interface OpportunityWave {
    id: string;
    securityId: string;
    start: string;
    launch: {
        date: string;
        rangeFrom: string;
        rangeUntil: string;
        sourceId: string;
    } | null;
    launchMissingReason: string | null;
    peakDate: string;
    endConfirmedAt: string | null;
    observedThrough: string;
    leftCensored: boolean;
    rightCensored: boolean;
    scale: string;
    parentId: string | null;
    sourceId: string;
    phases: { from: string; untilExclusive: string; kind: PhaseKind }[];
}
export interface RepresentativeInterval {
    securityId: string;
    waveId: string;
    from: string;
    untilExclusive: string;
}
/** Coverage does NOT imply continuous ownership between monthly/quarterly snapshots. */
export interface CoverageInterval {
    from: string;
    untilExclusive: string;
    completeness: "full" | "partial";
    kind: "daily" | "snapshot" | "event-replay";
    sourceId: string;
}
export interface HoldingInterval {
    securityId: string;
    from: string;
    untilExclusive: string;
    sourceId: string;
    quantity?: number;
}
export interface AllocationSnapshot {
    date: string;
    completeness: "full" | "partial";
    nav: number | null;
    cashWeight: number | null;
    /** Receivables/claims and other non-stock assets; omission does not declare zero. */
    otherAssetsWeight?: number | null;
    positions: { securityId: string; weight: number }[];
    sourceId: string;
}
export interface ResearchMethod {
    taskId: string;
    status: "exploratory" | "failed" | "incomplete" | "accepted";
    ruleVersion: string;
    rules: string[];
    parameters: Record<string, string | number | boolean>;
    conclusion: string;
    missionPath?: string;
    reportPath?: string;
    limitations: string[];
}
export interface OpportunityPortfolio {
    id: string;
    name: string;
    kind: "strategy" | "tw-etf" | "us-etf";
    description: string;
    sourceIds: string[];
    coverage: CoverageInterval[];
    holdings: HoldingInterval[];
    allocations: AllocationSnapshot[];
    method?: ResearchMethod;
    limitations: string[];
}
export interface OpportunityBundle {
    schema: "opportunity-explorer.v1";
    id: string;
    label: string;
    kind: "synthetic" | "historical-preview" | "historical";
    asOf: string;
    dates: string[];
    priceBasis: string;
    catalogCoverage: "declared-universe" | "case-slice";
    ruleVersion: string;
    selectionPolicy: string;
    classificationVersion: string;
    sources: SourceRef[];
    limitations: string[];
    securities: OpportunitySecurity[];
    waves: OpportunityWave[];
    representatives: RepresentativeInterval[];
    portfolios: OpportunityPortfolio[];
}
export interface OpportunityRow {
    security: OpportunitySecurity;
    wave: OpportunityWave;
    industry: IndustryMembership;
    gain: number | null;
    launchGain: number | null;
    peakGain: number | null;
    endGain: number | null;
    price: number | null;
    phase: PhaseKind | null;
    state: "active" | "unlaunched" | "ended" | "unknown" | "outside";
    weight: number;
    reason: string | null;
}
export interface MarketView {
    date: string;
    rows: OpportunityRow[];
    active: OpportunityRow[];
    unlaunched: OpportunityRow[];
    ended: OpportunityRow[];
    unknown: OpportunityRow[];
    industries: {
        id: string;
        label: string;
        gainSum: number;
        maxGain: number;
        rows: OpportunityRow[];
    }[];
}
export interface StockParticipation {
    securityId: string;
    waveId: string;
    held: HoldingState;
    /** Descriptive close-date overlap, never realized investment profit. */
    positiveMoveShare: number | null;
    heldDayShare: number | null;
    knownDays: number;
    totalDays: number;
    reason: string | null;
}
export interface CapitalView {
    status: "known" | "partial" | "unknown";
    opportunityWeight: number | null;
    otherWeight: number | null;
    cashWeight: number | null;
    otherAssetsWeight: number | null;
    unknownWeight: number;
    industries: { id: string; label: string; weight: number }[];
    reason: string | null;
    sourceId: string | null;
}
export interface PortfolioComparison {
    portfolio: OpportunityPortfolio;
    date: string;
    capital: CapitalView;
    stocks: StockParticipation[];
    averagePositiveMoveShare: number | null;
    knownCount: number;
    unknownCount: number;
    heldCount: number;
}
