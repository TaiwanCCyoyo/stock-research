import type { AnalysisResult, LabCase } from "../wave-lab/types.ts";

export const HISTORY_SCHEMA = "opportunity-history-web.v1";
export type HistoryPhase = "slow" | "rising" | "resting" | "retreat";
export interface HistoryCandidate {
    date: string;
    /** Saved ensuing uptrend span; this is not uncertainty around a launch date. */
    rangeFrom: string;
    rangeUntil: string;
    kind: "reversal" | "breakout" | "acceleration";
    outcome: "continued" | "failed" | "unresolved";
}
export interface HistoryPhaseInterval {
    from: string;
    /** Inclusive final source-calendar date. */
    until: string;
    phase: HistoryPhase;
}
export interface HistoryMetadata {
    schema: typeof HISTORY_SCHEMA;
    catalogId: string;
    dates: string[];
    coverage: { stocks: number; excluded: number; from: string; to: string };
    limitations: string[];
    basisLabel: string;
    ruleLabel: string;
}
export interface GrowthMetric {
    schema: "wave-growth.v1";
    startDate: string | null;
    observationDate: string | null;
    yearDays: 365.25;
    elapsedDays: number | null;
    elapsedYears: number | null;
    totalGainPct: number | null;
    annualizedGainPct: number | null;
    sizingGainPct: number | null;
    basis: "actual" | "annualized" | "unknown";
    reason: string | null;
}
export interface HistoryRow {
    securityId: string;
    code: string;
    name: string;
    seriesId: string;
    waveId: string;
    start: string;
    peakDate: string;
    endConfirmedAt: string | null;
    observedThrough: string;
    leftCensored: boolean;
    rightCensored: boolean;
    scale: string;
    gain: number | null;
    growth?: GrowthMetric | null;
    peakGain: number | null;
    raw: number | null;
    adjusted: number | null;
    reason: string | null;
    industry: {
        id: string;
        label: string;
        basis: "current-snapshot" | "unknown";
        snapshotAt: string | null;
    };
    earliestCandidateId: string | null;
    launchCandidate?: HistoryCandidate | null;
    startAdjusted?: number | null;
    launchAdjusted?: number | null;
    launchGain?: number | null;
    phase: HistoryPhase | null;
    sourcePhase?: string | null;
    sparkline?: { date: string; adjusted: number | null }[];
    phases?: HistoryPhaseInterval[];
}
export interface HistoryFrame {
    schema: typeof HISTORY_SCHEMA;
    catalogId: string;
    date: string;
    rows: HistoryRow[];
}
export interface HistoryDetail {
    schema: typeof HISTORY_SCHEMA;
    catalogId: string;
    date: string;
    row: HistoryRow | null;
    sample: LabCase;
    results: AnalysisResult[];
    evidence: Record<string, unknown>;
}
export interface HistoryDirectoryRow {
    securityId: string;
    code: string;
    name: string;
    industry: HistoryRow["industry"];
    waveId: string;
    start: string;
    peakDate: string;
    endConfirmedAt: string | null;
    observedThrough: string;
    representativeFrom: string;
    representativeUntilExclusive: string;
    launchCandidate: HistoryCandidate | null;
    phases: HistoryPhaseInterval[];
    scale: string;
    leftCensored: boolean;
    rightCensored: boolean;
    peakGain: number | null;
    gainAtEnd: number | null;
    gainAtEndDate: string | null;
    growthAtEnd?: GrowthMetric | null;
}
export interface HistoryDirectory {
    schema: typeof HISTORY_SCHEMA;
    catalogId: string;
    method: "segments";
    methodScale: "balanced";
    rows: HistoryDirectoryRow[];
}
export interface HistoryOptions {
    schema: typeof HISTORY_SCHEMA;
    catalogId: string;
    date: string;
    rows: {
        id: string;
        label: string;
        method: string;
        methodScale: string;
        condition: string;
        count: number;
    }[];
}
