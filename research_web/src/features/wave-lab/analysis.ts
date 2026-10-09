import type {
    AnalysisResult,
    LabCase,
    Launch,
    MethodId,
    Phase,
    Scale,
    Segment,
    Wave,
} from "./types.ts";

type Run = { start: number; end: number; values: number[] };
type Settings = {
    minSegment: number;
    penaltyFactor: number;
    lambdaFactor: number;
    small: number;
    large: number;
};

const SETTINGS: Record<Scale, Settings> = {
    fine: {
        minSegment: 6,
        penaltyFactor: 4,
        lambdaFactor: 2,
        small: 0.15,
        large: 0.3,
    },
    balanced: {
        minSegment: 10,
        penaltyFactor: 10,
        lambdaFactor: 8,
        small: 0.25,
        large: 0.4,
    },
    coarse: {
        minSegment: 16,
        penaltyFactor: 25,
        lambdaFactor: 24,
        small: 0.35,
        large: 0.5,
    },
};

const LOG_JUMP = Math.log(1.35);
const ADMM_RHO = 20;
const ADMM_MAX_ITERATIONS = 5000;
const ADMM_TOLERANCE = 1e-5;

function isUsable(value: number | null, flags: string[]): value is number {
    return (
        value !== null &&
        Number.isFinite(value) &&
        value > 0 &&
        flags.length === 0
    );
}

function runs(input: LabCase): Run[] {
    const result: Run[] = [];
    let start = -1;
    let values: number[] = [];
    const finish = () => {
        if (start >= 0)
            result.push({ start, end: start + values.length - 1, values });
        start = -1;
        values = [];
    };
    for (let i = 0; i < input.points.length; i++) {
        const point = input.points[i];
        if (!isUsable(point.adjusted, point.flags)) {
            finish();
            continue;
        }
        const value = Math.log(point.adjusted);
        // A valid corporate/action-like step remains visible, but belongs to a new fit.
        if (
            values.length &&
            Math.abs(value - values[values.length - 1]) > LOG_JUMP
        )
            finish();
        if (start < 0) start = i;
        values.push(value);
    }
    finish();
    return result;
}

function median(values: number[]): number {
    if (!values.length) return 0;
    const ordered = [...values].sort((a, b) => a - b);
    const mid = Math.floor(ordered.length / 2);
    return ordered.length % 2
        ? ordered[mid]
        : (ordered[mid - 1] + ordered[mid]) / 2;
}

function estimateNoise(allRuns: Run[]): number {
    const returns: number[] = [];
    for (const run of allRuns)
        for (let i = 1; i < run.values.length; i++)
            returns.push(run.values[i] - run.values[i - 1]);
    if (!returns.length) return 1e-4;
    const centre = median(returns);
    return Math.max(
        1e-4,
        1.4826 * median(returns.map((value) => Math.abs(value - centre))),
    );
}

function line(
    values: number[],
    from: number,
    to: number,
): { slope: number; intercept: number; sse: number } {
    const count = to - from + 1;
    if (count <= 1) return { slope: 0, intercept: values[from] ?? 0, sse: 0 };
    let sx = 0,
        sy = 0,
        sxx = 0,
        sxy = 0,
        syy = 0;
    for (let i = from; i <= to; i++) {
        const x = i - from,
            y = values[i];
        sx += x;
        sy += y;
        sxx += x * x;
        sxy += x * y;
        syy += y * y;
    }
    const denom = count * sxx - sx * sx;
    const slope = denom ? (count * sxy - sx * sy) / denom : 0;
    const intercept = (sy - slope * sx) / count;
    const sse = Math.max(
        0,
        syy -
            2 * intercept * sy -
            2 * slope * sxy +
            count * intercept * intercept +
            2 * intercept * slope * sx +
            slope * slope * sxx,
    );
    return { slope, intercept, sse };
}

function segmentFit(
    run: Run,
    minimum: number,
    penalty: number,
): { fit: number[]; pieces: { start: number; end: number; slope: number }[] } {
    const { values } = run,
        n = values.length;
    if (n < minimum * 2) {
        const fitted = line(values, 0, n - 1);
        return {
            fit: values.map((_, i) => fitted.intercept + fitted.slope * i),
            pieces: [{ start: 0, end: n - 1, slope: fitted.slope }],
        };
    }
    // Prefix moments make every candidate line and SSE O(1), keeping DP O(n^2).
    const sx = Array<number>(n + 1).fill(0),
        sy = Array<number>(n + 1).fill(0),
        sxx = Array<number>(n + 1).fill(0),
        sxy = Array<number>(n + 1).fill(0),
        syy = Array<number>(n + 1).fill(0);
    for (let i = 0; i < n; i++) {
        sx[i + 1] = sx[i] + i;
        sy[i + 1] = sy[i] + values[i];
        sxx[i + 1] = sxx[i] + i * i;
        sxy[i + 1] = sxy[i] + i * values[i];
        syy[i + 1] = syy[i] + values[i] * values[i];
    }
    const fittedLine = (from: number, to: number) => {
        const count = to - from + 1,
            sumX = sx[to + 1] - sx[from],
            sumY = sy[to + 1] - sy[from];
        const sumXX = sxx[to + 1] - sxx[from],
            sumXY = sxy[to + 1] - sxy[from],
            sumYY = syy[to + 1] - syy[from];
        const denom = count * sumXX - sumX * sumX;
        const slope = denom ? (count * sumXY - sumX * sumY) / denom : 0;
        const intercept = (sumY - slope * sumX) / count;
        return {
            slope,
            intercept,
            sse: Math.max(
                0,
                sumYY -
                    2 * intercept * sumY -
                    2 * slope * sumXY +
                    count * intercept * intercept +
                    2 * intercept * slope * sumX +
                    slope * slope * sumXX,
            ),
        };
    };
    const dp = Array<number>(n + 1).fill(Infinity),
        previous = Array<number>(n + 1).fill(-1);
    dp[0] = -penalty;
    for (let end = minimum; end <= n; end++) {
        for (let start = 0; start <= end - minimum; start++) {
            if (!Number.isFinite(dp[start])) continue;
            const cost = dp[start] + fittedLine(start, end - 1).sse + penalty;
            if (cost < dp[end]) {
                dp[end] = cost;
                previous[end] = start;
            }
        }
    }
    if (!Number.isFinite(dp[n])) return segmentFit(run, n, penalty);
    const pieces: { start: number; end: number; slope: number }[] = [];
    for (let end = n; end > 0;) {
        const start = previous[end];
        const fitted = fittedLine(start, end - 1);
        pieces.unshift({ start, end: end - 1, slope: fitted.slope });
        end = start;
    }
    const fit = Array<number>(n);
    for (const piece of pieces) {
        const fitted = fittedLine(piece.start, piece.end);
        for (let i = piece.start; i <= piece.end; i++)
            fit[i] = fitted.intercept + fitted.slope * i;
    }
    return { fit, pieces };
}

function solveTrend(
    values: number[],
    lambda: number,
): { fit: number[]; iterations: number; converged: boolean } {
    const n = values.length;
    if (n < 3) return { fit: [...values], iterations: 0, converged: true };
    const rho = ADMM_RHO,
        m = n - 2;
    // Cholesky factors for I + rho D' D; D has [1,-2,1] rows.
    const diagonal = Array<number>(n),
        sub1 = Array<number>(n).fill(0),
        sub2 = Array<number>(n).fill(0);
    const a0 = Array<number>(n).fill(1),
        a1 = Array<number>(n).fill(0),
        a2 = Array<number>(n).fill(0);
    for (let r = 0; r < m; r++) {
        a0[r] += rho;
        a0[r + 1] += 4 * rho;
        a0[r + 2] += rho;
        a1[r + 1] -= 2 * rho;
        a1[r + 2] -= 2 * rho;
        a2[r + 2] += rho;
    }
    for (let i = 0; i < n; i++) {
        const l2 = i >= 2 ? a2[i] / diagonal[i - 2] : 0;
        const l1 =
            i >= 1
                ? (a1[i] - (i >= 2 ? l2 * sub1[i - 1] : 0)) / diagonal[i - 1]
                : 0;
        const squared = a0[i] - l1 * l1 - l2 * l2;
        diagonal[i] = Math.sqrt(Math.max(squared, 1e-12));
        sub1[i] = l1;
        sub2[i] = l2;
    }
    const solve = (rhs: number[]) => {
        const forward = Array<number>(n),
            answer = Array<number>(n);
        for (let i = 0; i < n; i++)
            forward[i] =
                (rhs[i] -
                    (i ? sub1[i] * forward[i - 1] : 0) -
                    (i > 1 ? sub2[i] * forward[i - 2] : 0)) /
                diagonal[i];
        for (let i = n - 1; i >= 0; i--)
            answer[i] =
                (forward[i] -
                    (i + 1 < n ? sub1[i + 1] * answer[i + 1] : 0) -
                    (i + 2 < n ? sub2[i + 2] * answer[i + 2] : 0)) /
                diagonal[i];
        return answer;
    };
    let z = Array<number>(m).fill(0),
        u = Array<number>(m).fill(0),
        fit = [...values];
    for (let iteration = 1; iteration <= ADMM_MAX_ITERATIONS; iteration++) {
        const rhs = [...values];
        for (let r = 0; r < m; r++) {
            const v = rho * (z[r] - u[r]);
            rhs[r] += v;
            rhs[r + 1] -= 2 * v;
            rhs[r + 2] += v;
        }
        fit = solve(rhs);
        const old = z,
            nextZ = [...z],
            d = Array<number>(m);
        let primalSquared = 0;
        const dualVector = Array<number>(n).fill(0);
        for (let r = 0; r < m; r++) {
            d[r] = fit[r] - 2 * fit[r + 1] + fit[r + 2];
            const raw = d[r] + u[r],
                threshold = lambda / rho;
            nextZ[r] = Math.sign(raw) * Math.max(0, Math.abs(raw) - threshold);
            const residual = d[r] - nextZ[r];
            u[r] += residual;
            primalSquared += residual * residual;
            const change = nextZ[r] - old[r];
            dualVector[r] += change;
            dualVector[r + 1] -= 2 * change;
            dualVector[r + 2] += change;
        }
        z = nextZ;
        const primal = Math.sqrt(primalSquared),
            dual =
                rho *
                Math.sqrt(
                    dualVector.reduce((sum, value) => sum + value * value, 0),
                );
        const scale = Math.max(
            1,
            Math.sqrt(d.reduce((sum, value) => sum + value * value, 0)),
            Math.sqrt(z.reduce((sum, value) => sum + value * value, 0)),
        );
        if (primal <= ADMM_TOLERANCE * scale && dual <= ADMM_TOLERANCE * scale)
            return { fit, iterations: iteration, converged: true };
    }
    return { fit, iterations: ADMM_MAX_ITERATIONS, converged: false };
}

function phase(slope: number): Phase {
    if (Math.abs(slope) < 0.0003) return "flat";
    if (slope > 0.005) return "fast";
    return slope > 0 ? "rising" : "falling";
}

function segmentsFromFit(
    fit: (number | null)[],
    allRuns: Run[],
    methodPieces: Map<number, { start: number; end: number; slope: number }[]>,
    noise: number,
): Segment[] {
    const result: Segment[] = [];
    for (const run of allRuns) {
        let pieces = methodPieces.get(run.start);
        if (!pieces) {
            const local = fit.slice(run.start, run.end + 1) as number[];
            pieces = [];
            let start = 0,
                previous = local.length > 1 ? local[1] - local[0] : 0;
            const tolerance = Math.max(0.0003, noise * 0.2);
            for (let i = 1; i < local.length - 1; i++) {
                const next = local[i + 1] - local[i];
                if (Math.abs(next - previous) > tolerance && i - start >= 2) {
                    pieces.push({
                        start,
                        end: i,
                        slope:
                            (local[i] - local[start]) / Math.max(1, i - start),
                    });
                    start = i;
                }
                previous = next;
            }
            pieces.push({
                start,
                end: local.length - 1,
                slope:
                    (local[local.length - 1] - local[start]) /
                    Math.max(1, local.length - 1 - start),
            });
        }
        // A one-day leftover is absorbed so it cannot become a named phase.
        for (const piece of pieces) {
            const start = run.start + piece.start,
                end = run.start + piece.end;
            if (
                result.length &&
                result[result.length - 1].end + 1 === start &&
                end === start
            ) {
                result[result.length - 1].end = end;
                continue;
            }
            result.push({
                start,
                end,
                slope: piece.slope,
                phase: phase(piece.slope),
            });
        }
    }
    return result;
}

export function pathDrawdown(values: number[]): number {
    let peak = values[0],
        worst = 0;
    for (const value of values) {
        peak = Math.max(peak, value);
        worst = Math.min(worst, (value / peak - 1) * 100);
    }
    return worst;
}

function launches(
    segments: Segment[],
    input: LabCase,
    noise: number,
): Launch[] {
    const result: Launch[] = [];
    const joinsSameRun = (left: Segment, right: Segment) => {
        if (right.start === left.end) return true;
        if (right.start !== left.end + 1) return false;
        const beforeValue = input.points[left.end]?.adjusted,
            afterValue = input.points[right.start]?.adjusted;
        return (
            beforeValue !== null &&
            afterValue !== null &&
            beforeValue !== undefined &&
            afterValue !== undefined &&
            Math.abs(Math.log(afterValue / beforeValue)) <= LOG_JUMP
        );
    };
    for (let i = 1; i < segments.length; i++) {
        const before = segments[i - 1],
            after = segments[i];
        if (
            !joinsSameRun(before, after) ||
            after.slope <= 0.0005 ||
            after.slope - before.slope <= Math.max(0.0005, noise * 0.12)
        )
            continue;
        let kind: Launch["kind"] | null = null;
        if (before.slope < -0.0003) kind = "reversal";
        else if (Math.abs(before.slope) < 0.0003) kind = "breakout";
        else if (after.slope >= Math.max(0.0003, before.slope * 1.6))
            kind = "acceleration";
        if (!kind) continue;
        const startValue = input.points[after.start].adjusted;
        const endValue = input.points[after.end].adjusted;
        const isLast =
            i === segments.length - 1 || !joinsSameRun(after, segments[i + 1]);
        const drawdown = pathDrawdown(
            input.points
                .slice(after.start, after.end + 1)
                .map((point) => point.adjusted!),
        );
        const gain =
            startValue !== null && endValue !== null
                ? (endValue / startValue - 1) * 100
                : null;
        result.push({
            id: `launch-${after.start}-${kind}`,
            index: after.start,
            rangeStart: after.start,
            rangeEnd: after.end,
            kind,
            preSlope: before.slope,
            postSlope: after.slope,
            sustainSessions: after.end - after.start,
            relativeStrength:
                noise > 0 ? (after.slope - before.slope) / noise : null,
            forwardGain: gain,
            forwardEnd: after.end,
            drawdown: startValue === null ? null : drawdown,
            outcome: isLast
                ? "unresolved"
                : gain !== null && gain >= 5
                  ? "continued"
                  : "failed",
            support: 1,
        });
    }
    return result;
}

function waves(allRuns: Run[], scale: Scale): Wave[] {
    const result: Wave[] = [];
    let serial = 0;
    const add = (threshold: number, size: Wave["scale"]) => {
        for (const run of allRuns) {
            let trough = 0,
                peak = 0,
                rising = false;
            const maxDrawdownThrough = (from: number, through: number) => {
                let runningPeak = run.values[from],
                    worst = 0;
                for (let i = from + 1; i <= through; i++) {
                    if (run.values[i] > runningPeak)
                        runningPeak = run.values[i];
                    else
                        worst = Math.min(
                            worst,
                            (Math.exp(run.values[i] - runningPeak) - 1) * 100,
                        );
                }
                return worst;
            };
            for (let i = 1; i < run.values.length; i++) {
                if (!rising) {
                    if (run.values[i] < run.values[trough]) {
                        trough = i;
                        peak = i;
                        continue;
                    }
                    if (
                        Math.exp(run.values[i] - run.values[trough]) - 1 >=
                        threshold
                    ) {
                        rising = true;
                        peak = i;
                    }
                    continue;
                }
                if (run.values[i] > run.values[peak]) {
                    peak = i;
                    continue;
                }
                const fall = 1 - Math.exp(run.values[i] - run.values[peak]);
                if (fall >= threshold) {
                    const gain =
                        Math.exp(run.values[peak] - run.values[trough]) - 1;
                    // Directional confirmation controls the cut; the 60% floor only
                    // controls whether a completed candidate is displayed.
                    if (gain >= 0.6)
                        result.push({
                            id: `wave-${size}-${serial++}`,
                            start: run.start + trough,
                            peak: run.start + peak,
                            end: run.start + i,
                            observedThrough: run.start + i,
                            gain: gain * 100,
                            maxDrawdown: maxDrawdownThrough(trough, i),
                            scale: size,
                            leftCensored: trough === 0,
                            rightCensored: false,
                        });
                    trough = i;
                    peak = i;
                    rising = false;
                }
            }
            const gain = Math.exp(run.values[peak] - run.values[trough]) - 1;
            if (rising && gain >= 0.6) {
                result.push({
                    id: `wave-${size}-${serial++}`,
                    start: run.start + trough,
                    peak: run.start + peak,
                    end: null,
                    observedThrough: run.end,
                    gain: gain * 100,
                    maxDrawdown: maxDrawdownThrough(
                        trough,
                        run.values.length - 1,
                    ),
                    scale: size,
                    leftCensored: trough === 0,
                    rightCensored: true,
                });
            }
        }
    };
    add(SETTINGS[scale].small, "small");
    add(SETTINGS[scale].large, "large");
    const large = result.filter((wave) => wave.scale === "large");
    for (const child of result.filter((wave) => wave.scale === "small")) {
        const childEnd = child.end ?? child.observedThrough;
        const parent = large
            .filter((wave) => {
                const parentEnd = wave.end ?? wave.observedThrough;
                return (
                    wave.start <= child.start &&
                    parentEnd >= childEnd &&
                    (wave.start !== child.start || parentEnd !== childEnd)
                );
            })
            .sort(
                (a, b) =>
                    (a.end ?? a.observedThrough) -
                    a.start -
                    ((b.end ?? b.observedThrough) - b.start),
            )[0];
        if (parent) child.parentId = parent.id;
    }
    return result;
}

export function analyzeCase(
    input: LabCase,
    method: MethodId,
    scale: Scale,
): AnalysisResult {
    const allRuns = runs(input),
        noise = estimateNoise(allRuns),
        settings = SETTINGS[scale];
    const warnings: string[] = [];
    if (input.points.some((point) => !isUsable(point.adjusted, point.flags)))
        warnings.push("缺值、無效價格或來源品質旗標已隔離為不同分析段落。");
    if (
        input.points.some((point, index) => {
            const previous = input.points[index - 1];
            return (
                previous &&
                isUsable(point.adjusted, point.flags) &&
                isUsable(previous.adjusted, previous.flags) &&
                Math.abs(Math.log(point.adjusted / previous.adjusted)) >
                    LOG_JUMP
            );
        })
    )
        warnings.push("價格跳躍超過 35%，已隔離為不同分析段落。");
    if (!allRuns.length) warnings.push("沒有可用的價格段落可供分析。");
    const logFit: (number | null)[] = Array(input.points.length).fill(null);
    const pieces = new Map<
        number,
        { start: number; end: number; slope: number }[]
    >();
    let iterations = 0,
        converged = true;
    for (const run of allRuns) {
        if (method === "segments") {
            const fitted = segmentFit(
                run,
                settings.minSegment,
                noise *
                    noise *
                    Math.log(Math.max(2, run.values.length)) *
                    settings.penaltyFactor,
            );
            fitted.fit.forEach((value, i) => {
                logFit[run.start + i] = value;
            });
            pieces.set(run.start, fitted.pieces);
        } else {
            const fitted = solveTrend(
                run.values,
                noise * settings.lambdaFactor,
            );
            fitted.fit.forEach((value, i) => {
                logFit[run.start + i] = value;
            });
            iterations = Math.max(iterations, fitted.iterations);
            converged &&= fitted.converged;
        }
    }
    const segments = segmentsFromFit(logFit, allRuns, pieces, noise);
    if (!converged)
        warnings.push(
            `趨勢濾波在 ${ADMM_MAX_ITERATIONS} 次 ADMM 迭代內未收斂。`,
        );
    return {
        method,
        scale,
        fit: logFit.map((value) => (value === null ? null : Math.exp(value))),
        segments,
        launches: launches(segments, input, noise),
        waves: waves(allRuns, scale),
        warnings,
        diagnostics: {
            iterations,
            converged,
            penalty:
                method === "segments"
                    ? noise *
                      noise *
                      Math.log(Math.max(2, input.points.length)) *
                      settings.penaltyFactor
                    : noise * settings.lambdaFactor,
            noise,
        },
    };
}

export function analyzeComparisons(
    input: LabCase,
    scale: Scale,
): AnalysisResult[] {
    const results = (["segments", "filter"] as MethodId[]).flatMap((method) =>
        (["fine", "balanced", "coarse"] as Scale[]).map((candidateScale) =>
            analyzeCase(input, method, candidateScale),
        ),
    );
    for (const method of ["segments", "filter"] as MethodId[]) {
        const byScale = new Map(
            results
                .filter((result) => result.method === method)
                .map((result) => [result.scale, result.launches]),
        );
        for (const launch of byScale.get(scale) ?? []) {
            const nearby = (["fine", "balanced", "coarse"] as Scale[]).flatMap(
                (candidateScale) => {
                    const nearest = (byScale.get(candidateScale) ?? [])
                        .filter(
                            (other) =>
                                other.kind === launch.kind &&
                                Math.abs(other.index - launch.index) <= 20,
                        )
                        .sort(
                            (a, b) =>
                                Math.abs(a.index - launch.index) -
                                Math.abs(b.index - launch.index),
                        )[0];
                    return nearest ? [nearest] : [];
                },
            );
            launch.support = nearby.length;
            launch.rangeStart = Math.min(...nearby.map((other) => other.index));
            launch.rangeEnd = Math.max(...nearby.map((other) => other.index));
        }
    }
    return results.filter((result) => result.scale === scale);
}
