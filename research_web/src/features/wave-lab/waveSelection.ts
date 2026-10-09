import type {
    LabCase,
    LabOpportunitySelection,
    LabWaveBoundary,
    Launch,
    Wave,
} from "./types.ts";

/** A selected wave bounds both the anchor and the observation, including its cutoff. */
export function observationGain(
    sample: LabCase,
    start: number,
    end: number,
    wave?: Wave,
): number | null {
    if (end < start) return null;
    if (wave) {
        const through = Math.min(
            wave.end ?? wave.observedThrough,
            wave.observedThrough,
        );
        if (
            start < wave.start ||
            start > through ||
            end < wave.start ||
            end > through
        )
            return null;
    }
    const a = sample.points[start]?.adjusted,
        b = sample.points[end]?.adjusted;
    if (
        !a ||
        !b ||
        sample.points
            .slice(start, end + 1)
            .some((point) => point.adjusted == null || point.flags.length)
    )
        return null;
    return (b / a - 1) * 100;
}

export function waveBoundary(
    sample: LabCase,
    wave: Wave,
): LabWaveBoundary | null {
    const start = sample.points[wave.start]?.date;
    const peakDate = sample.points[wave.peak]?.date;
    const observedThrough = sample.points[wave.observedThrough]?.date;
    const endConfirmedAt =
        wave.end === null ? null : sample.points[wave.end]?.date;
    if (!start || !peakDate || !observedThrough || endConfirmedAt === undefined)
        return null;
    return {
        start,
        peakDate,
        endConfirmedAt,
        observedThrough,
        scale: wave.scale,
        leftCensored: wave.leftCensored,
        rightCensored: wave.rightCensored,
    };
}

/** Analysis-local IDs are not a cross-method identity. Require one exact boundary match. */
export function resolveLabWave(
    sample: LabCase,
    waves: readonly Wave[],
    preferred: LabWaveBoundary | null,
): Wave | undefined {
    if (!preferred)
        return waves.find((wave) => wave.scale === "large") ?? waves[0];
    const matches = waves.filter((wave) => {
        const boundary = waveBoundary(sample, wave);
        return (
            boundary &&
            boundary.start === preferred.start &&
            boundary.peakDate === preferred.peakDate &&
            boundary.endConfirmedAt === preferred.endConfirmedAt &&
            boundary.observedThrough === preferred.observedThrough &&
            boundary.scale === preferred.scale &&
            boundary.leftCensored === preferred.leftCensored &&
            boundary.rightCensored === preferred.rightCensored
        );
    });
    return matches.length === 1 ? matches[0] : undefined;
}

export function resolveLabLaunch(
    sample: LabCase,
    launches: readonly Launch[],
    preferred: LabOpportunitySelection["launch"],
): Launch | undefined {
    if (!preferred) return undefined;
    const matches = launches.filter(
        (launch) =>
            sample.points[launch.index]?.date === preferred.date &&
            sample.points[launch.rangeStart]?.date === preferred.rangeFrom &&
            sample.points[launch.rangeEnd]?.date === preferred.rangeUntil,
    );
    return matches.length === 1 ? matches[0] : undefined;
}
