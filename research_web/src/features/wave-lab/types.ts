export type MethodId = "segments" | "filter";
export type Scale = "fine" | "balanced" | "coarse";
export type Phase = "falling" | "flat" | "rising" | "fast";
export interface LabPoint {
    date: string;
    raw: number | null;
    adjusted: number | null;
    flags: string[];
}
export interface LabWaveBoundary {
    start: string;
    peakDate: string;
    endConfirmedAt: string | null;
    observedThrough: string;
    scale: string;
    leftCensored: boolean;
    rightCensored: boolean;
}
export interface LabOpportunitySelection extends LabWaveBoundary {
    securityId: string;
    waveId: string;
    sourceId: string;
    launch: {
        date: string;
        rangeFrom: string;
        rangeUntil: string;
        sourceId: string;
    } | null;
}
export interface LabCase {
    id: string;
    name: string;
    code?: string;
    kind: "historical" | "synthetic";
    category: string;
    question: string;
    points: LabPoint[];
    /** Saved map evidence, separate from locally recomputed method candidates. */
    selectedOpportunity?: LabOpportunitySelection;
    source: {
        label: string;
        from: string;
        to: string;
        priceBasis: string;
        hash?: string;
        catalogHash?: string;
        limitations: string[];
    };
}
export interface Segment {
    start: number;
    end: number;
    slope: number;
    phase: Phase;
}
export interface Launch {
    id: string;
    index: number;
    rangeStart: number;
    rangeEnd: number;
    kind: "reversal" | "breakout" | "acceleration";
    preSlope: number;
    postSlope: number;
    sustainSessions: number;
    relativeStrength: number | null;
    forwardGain: number | null;
    forwardEnd: number;
    drawdown: number | null;
    outcome: "continued" | "failed" | "unresolved";
    support: number;
}
export interface Wave {
    id: string;
    start: number;
    peak: number;
    end: number | null;
    observedThrough: number;
    gain: number;
    maxDrawdown: number;
    scale: "small" | "large";
    parentId?: string;
    leftCensored: boolean;
    rightCensored: boolean;
}
export interface AnalysisResult {
    method: MethodId;
    scale: Scale;
    fit: (number | null)[];
    segments: Segment[];
    launches: Launch[];
    waves: Wave[];
    warnings: string[];
    diagnostics: {
        iterations: number;
        converged: boolean;
        penalty: number;
        noise: number;
    };
}
export interface LabBundle {
    schema: "wave-lab-cases.v1";
    projectionHash: string;
    catalogHash: string;
    cases: LabCase[];
}
