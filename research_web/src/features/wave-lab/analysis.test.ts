import assert from "node:assert/strict";
import { test } from "node:test";
import { analyzeCase, analyzeComparisons, pathDrawdown } from "./analysis.ts";
import type { LabCase } from "./types.ts";

function caseOf(
    values: (number | null)[],
    flags: string[][] = values.map(() => []),
): LabCase {
    const first = Date.UTC(2020, 0, 1);
    return {
        id: "synthetic",
        name: "Synthetic",
        kind: "synthetic",
        category: "test",
        question: "test",
        points: values.map((adjusted, index) => ({
            date: new Date(first + index * 86_400_000)
                .toISOString()
                .slice(0, 10),
            raw: adjusted,
            adjusted,
            flags: flags[index],
        })),
        source: {
            label: "test",
            from: "2020-01-01",
            to: "2020-12-31",
            priceBasis: "adjusted",
            limitations: [],
        },
    };
}

function runningDrawdown(
    values: (number | null)[],
    start: number,
    end: number,
): number {
    let peak = values[start]!,
        drawdown = 0;
    for (let index = start; index <= end; index++) {
        const value = values[index]!;
        if (value > peak) peak = value;
        else drawdown = Math.min(drawdown, (value / peak - 1) * 100);
    }
    return drawdown;
}

test("DP preserves a straight log line under a price-scale change", () => {
    const values = Array.from({ length: 24 }, (_, i) => Math.exp(0.01 * i));
    const base = analyzeCase(caseOf(values), "segments", "fine");
    const scaled = analyzeCase(
        caseOf(values.map((value) => value * 17)),
        "segments",
        "fine",
    );
    assert.equal(base.segments.length, 1);
    assert.ok(Math.abs(base.segments[0].slope - 0.01) < 1e-10);
    assert.ok(
        Math.abs(base.segments[0].slope - scaled.segments[0].slope) < 1e-10,
    );
    for (let i = 0; i < values.length; i++)
        assert.ok(Math.abs(scaled.fit[i]! / base.fit[i]! - 17) < 1e-10);
});

test("jump and missing rows split fits and cannot create an earlier launch", () => {
    const jump = [
        ...Array.from({ length: 10 }, (_, i) => Math.exp(-0.01 * i)),
        ...Array.from({ length: 10 }, (_, i) => 2 * Math.exp(0.02 * i)),
    ];
    const jumpResult = analyzeCase(caseOf(jump), "segments", "fine");
    assert.equal(
        jumpResult.launches.filter((launch) => launch.index < 10).length,
        0,
    );
    const gap = caseOf([1, 1.02, 1.04, null, 4, 4.1, 4.2]);
    const gapResult = analyzeCase(gap, "filter", "fine");
    assert.equal(gapResult.fit[3], null);
    assert.ok(gapResult.segments.some((segment) => segment.end === 2));
    assert.ok(gapResult.segments.some((segment) => segment.start === 4));
    assert.ok(gapResult.warnings.some((warning) => warning.includes("缺值")));
    assert.ok(jumpResult.warnings.some((warning) => warning.includes("跳躍")));
    const empty = analyzeCase(caseOf([null, null]), "segments", "fine");
    assert.ok(empty.warnings.some((warning) => warning.includes("沒有可用")));
});

test("waves require 60 percent gains, nest only by containment, and expose censored runs", () => {
    const result = analyzeCase(
        caseOf([1, 1.2, 1.5, 1.8, 1.5, 1.3, 1.5, 1.8, 2.2, 2.6, 1.9, 1.5]),
        "segments",
        "balanced",
    );
    assert.ok(
        result.waves.some((wave) => wave.scale === "small" && wave.gain >= 60),
    );
    assert.ok(
        result.waves.some((wave) => wave.scale === "large" && wave.gain >= 60),
    );
    assert.ok(result.waves.some((wave) => wave.parentId));
    assert.ok(result.waves.every((wave) => wave.maxDrawdown <= 0));
    const incomplete = analyzeCase(
        caseOf([1, 1.3, 1.7]),
        "segments",
        "fine",
    ).waves;
    assert.ok(
        incomplete.some((wave) => wave.rightCensored && wave.end === null),
    );
});

test("a sub-60 percent reversal still resets the next wave start", () => {
    const result = analyzeCase(
        caseOf([1, 1.2, 1.34, 1, 1.2, 1.5, 1.8, 1.35]),
        "segments",
        "balanced",
    );
    assert.ok(
        result.waves.some(
            (wave) =>
                wave.scale === "small" && wave.start === 3 && wave.gain >= 60,
        ),
    );
});

test("a confirmed large rise survives a deep decline below its original trough", () => {
    const result = analyzeCase(
        caseOf([100, 120, 145, 165, 145, 120, 100, 90, 80]),
        "segments",
        "balanced",
    );
    assert.ok(
        result.waves.some(
            (wave) =>
                wave.scale === "large" &&
                wave.start === 0 &&
                wave.peak === 3 &&
                wave.end === 7 &&
                wave.gain >= 60,
        ),
    );
});

test("trend filtering identifies a flat-to-rising breakpoint and reports percent outcomes", () => {
    const flat = Array<number>(14).fill(100);
    const rise = Array.from(
        { length: 10 },
        (_, index) => 100 * (1 + 0.004 * (index + 1)),
    );
    const retreat = [103.5, 103, 102.5, 102, 101.5, 101];
    const values = [...flat, ...rise, ...retreat];
    const result = analyzeCase(caseOf(values), "filter", "fine");
    assert.ok(result.diagnostics.converged);
    assert.ok(result.diagnostics.iterations < 5000);
    assert.ok(result.segments.some((segment) => segment.phase === "flat"));
    assert.ok(result.segments.some((segment) => segment.slope > 0.0005));
    const failed = result.launches.find(
        (launch) => launch.kind === "breakout" && launch.outcome === "failed",
    );
    assert.ok(failed);
    assert.ok(
        failed.forwardGain !== null &&
            failed.forwardGain > 0 &&
            failed.forwardGain < 5,
    );
    assert.ok(failed.drawdown !== null);
    assert.ok(
        Math.abs(
            failed.drawdown -
                runningDrawdown(values, failed.index, failed.forwardEnd),
        ) < 1e-12,
    );
});

test("drawdown includes retreats from intermediate peaks even above the starting price", () => {
    assert.ok(
        Math.abs(pathDrawdown([100, 130, 117, 140, 112, 150]) + 20) < 1e-12,
    );
    assert.equal(pathDrawdown([100, 110, 120]), 0);
});

test("flat paths remain flat without launches under either fitting method", () => {
    const input = caseOf(Array<number>(30).fill(100));
    for (const method of ["segments", "filter"] as const) {
        const result = analyzeCase(input, method, "fine");
        assert.equal(result.launches.length, 0);
        assert.ok(
            result.fit.every(
                (value) => value !== null && Math.abs(value - 100) < 1e-6,
            ),
        );
    }
});

test("comparison output is limited to the requested scale", () => {
    const values = Array.from({ length: 36 }, (_, i) =>
        Math.exp(
            i < 12
                ? -0.01 * i
                : i < 24
                  ? -0.12 + 0.015 * (i - 12)
                  : 0.06 + 0.004 * (i - 24),
        ),
    );
    const results = analyzeComparisons(caseOf(values), "balanced");
    assert.equal(results.length, 2);
    assert.ok(results.every((result) => result.scale === "balanced"));
    assert.ok(
        results
            .flatMap((result) => result.launches)
            .every((launch) => launch.support <= 3),
    );
});
