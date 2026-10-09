import type { LabCase } from "./types.ts";

const IDENTITY_VERSION = "wave-lab-feedback-content.v1";

export interface FeedbackIdentityState {
    sample: LabCase;
    key: string;
}

/** An older request may complete while React is rendering a different case. */
export function readyFeedbackIdentity(
    state: FeedbackIdentityState | null,
    sample: LabCase,
): string | null {
    return state?.sample === sample ? state.key : null;
}

function canonicalCase(sample: LabCase, ruleVersion: string): string {
    if (!ruleVersion.trim())
        throw new Error("Feedback identity requires a rule version");
    const number = (value: number | null): number | null => {
        if (value !== null && !Number.isFinite(value))
            throw new Error("Feedback identity requires finite prices or null");
        return value;
    };
    const selected = sample.selectedOpportunity;
    // Declare every LabCase field in a fixed order. Incoming object property
    // order and omitted optional fields cannot change equivalent identities.
    return JSON.stringify({
        schema: IDENTITY_VERSION,
        ruleVersion,
        sample: {
            id: sample.id,
            name: sample.name,
            code: sample.code ?? null,
            kind: sample.kind,
            category: sample.category,
            question: sample.question,
            ...(selected
                ? {
                      selectedOpportunity: {
                          securityId: selected.securityId,
                          waveId: selected.waveId,
                          sourceId: selected.sourceId,
                          start: selected.start,
                          peakDate: selected.peakDate,
                          endConfirmedAt: selected.endConfirmedAt,
                          observedThrough: selected.observedThrough,
                          scale: selected.scale,
                          leftCensored: selected.leftCensored,
                          rightCensored: selected.rightCensored,
                          launch: selected.launch
                              ? {
                                    date: selected.launch.date,
                                    rangeFrom: selected.launch.rangeFrom,
                                    rangeUntil: selected.launch.rangeUntil,
                                    sourceId: selected.launch.sourceId,
                                }
                              : null,
                      },
                  }
                : {}),
            source: {
                label: sample.source.label,
                from: sample.source.from,
                to: sample.source.to,
                priceBasis: sample.source.priceBasis,
                hash: sample.source.hash ?? null,
                catalogHash: sample.source.catalogHash ?? null,
                limitations: [...sample.source.limitations],
            },
            points: sample.points.map((point) => ({
                date: point.date,
                raw: number(point.raw),
                adjusted: number(point.adjusted),
                flags: [...point.flags],
            })),
        },
    });
}

/** Hash the actual content, including price basis, rather than trusting source.hash. */
export async function createFeedbackIdentity(
    sample: LabCase,
    ruleVersion: string,
    subtle: Pick<SubtleCrypto, "digest"> | undefined = globalThis.crypto
        ?.subtle,
): Promise<string> {
    if (!subtle) throw new Error("SHA-256 is unavailable in this browser");
    const bytes = new TextEncoder().encode(canonicalCase(sample, ruleVersion));
    const digest = await subtle.digest("SHA-256", bytes);
    const hex = Array.from(new Uint8Array(digest), (byte) =>
        byte.toString(16).padStart(2, "0"),
    ).join("");
    return `${IDENTITY_VERSION}:sha256:${hex}`;
}
