import assert from "node:assert/strict";
import { test } from "node:test";
import { appears } from "../full-history/model.ts";
import { HISTORY_SCHEMA, type HistoryRow } from "../full-history/types.ts";
import { latestMarketSummary } from "./model.ts";
import { researchLinkHref } from "../research-history/markdownLinks.ts";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { RecentResearchNotice } from "./RecentResearchNotice.ts";

test("recent home research marks a same-ID invalid registration while preserving its old conclusion", () => {
    const previous = {
        id: "20261021-synthetic",
        status: "已保存報告",
        title: "已驗證舊標題",
        conclusion: "保留的舊結論。",
        outcome: "candidate_failed",
        evidenceState: "published_report_not_owner_adoption",
        sourceNote: "原有來源說明。",
    };
    const item = {
        ...previous,
        status: "登錄需更新",
        sourceNote: "報告 SHA-256 與登錄不符，請更新登錄。",
    };
    const before = structuredClone(item);
    const html = renderToStaticMarkup(
        createElement(RecentResearchNotice, { item }),
    );
    assert.match(html, /role="status"/);
    for (const text of ["登錄需更新", "保留舊版", item.id, item.sourceNote])
        assert.ok(html.includes(text));
    assert.equal(item.conclusion, previous.conclusion);
    assert.equal(item.outcome, previous.outcome);
    assert.deepEqual(item, before);
    assert.equal(
        renderToStaticMarkup(
            createElement(RecentResearchNotice, { item: previous }),
        ),
        "",
    );
});

test("recent home research does not claim retained evidence for a new unavailable card and escapes reason text", () => {
    const item = {
        id: "20261021-synthetic",
        status: "登錄需更新",
        evidenceState: "registration_unavailable",
        sourceNote: "<script>unsafe</script>",
    };
    const html = renderToStaticMarkup(
        createElement(RecentResearchNotice, { item }),
    );
    assert.ok(html.includes("登錄需更新"));
    assert.ok(!html.includes("保留舊版"));
    assert.ok(!html.includes("<script>"));
    assert.ok(html.includes("&lt;script&gt;"));
});

test("report file links never resolve into unavailable website routes; HTTPS sources remain navigable", () => {
    for (const href of [
        "../../docs/en/research-program.md",
        "/docs/en/research-program.md",
        "report.md",
        "#evidence",
        "//example.org/report",
        "http://example.org/report",
        "https:/example.org/report",
        "https://",
        undefined,
    ])
        assert.equal(researchLinkHref(href), null);
    assert.equal(
        researchLinkHref("https://example.org/report?q=evidence#results"),
        "https://example.org/report?q=evidence#results",
    );
    assert.equal(
        researchLinkHref("HTTPS://EXAMPLE.ORG/report"),
        "https://example.org/report",
    );
});

const row = (
    code: string,
    gain: number,
    overrides: Partial<HistoryRow> = {},
): HistoryRow => ({
    securityId: code,
    code,
    name: code,
    seriesId: code,
    waveId: code,
    start: "2020-01-01",
    peakDate: "2022-01-01",
    endConfirmedAt: null,
    observedThrough: "2021-01-08",
    leftCensored: false,
    rightCensored: true,
    scale: "balanced",
    gain,
    growth: {
        schema: "wave-growth.v1",
        startDate: "2020-01-01",
        observationDate: "2021-01-08",
        yearDays: 365.25,
        elapsedDays: 373,
        elapsedYears: 373 / 365.25,
        totalGainPct: gain,
        annualizedGainPct: gain,
        sizingGainPct: gain,
        basis: "annualized",
        reason: null,
    },
    peakGain: gain,
    raw: 20,
    adjusted: 20,
    reason: null,
    industry: {
        id: "known",
        label: "產業",
        basis: "current-snapshot",
        snapshotAt: "2026-10-01",
    },
    earliestCandidateId: "candidate",
    launchCandidate: {
        date: "2020-02-01",
        rangeFrom: "2020-02-01",
        rangeUntil: "2020-04-01",
        kind: "reversal",
        outcome: "continued",
    },
    phase: "rising",
    ...overrides,
});
test("homepage uses territory eligibility, retaining unknown classification and excluding unlaunched/end/threshold rows", () => {
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "version",
        date: "2021-01-08",
        rows: [
            row("high", 300),
            row("unknown-sector", 200, {
                industry: {
                    id: "unknown",
                    label: "分類待補",
                    basis: "unknown",
                    snapshotAt: null,
                },
            }),
            row("below", 99),
            row("unlaunched", 250, { launchCandidate: null }),
            row("ended", 500, { endConfirmedAt: "2021-01-08" }),
        ],
    };
    const summary = latestMarketSummary(frame);
    assert.equal(
        summary.count,
        frame.rows.filter((item) => appears(item, frame.date, "launched", 100))
            .length,
    );
    assert.deepEqual(
        summary.strongest.map((item) => item.code),
        ["high", "unknown-sector"],
    );
    assert.equal(summary.industries.length, 2);
    assert.equal(
        summary.industries.reduce(
            (sum, industry) => sum + industry.rows.length,
            0,
        ),
        summary.count,
    );
    assert.equal(latestMarketSummary(frame, 200).count, 2);
});
test("industry leader follows saved time metric rather than historical total gain", () => {
    const frame = {
        schema: HISTORY_SCHEMA,
        catalogId: "version",
        date: "2021-01-08",
        rows: [row("annual-high", 250), row("total-high", 130, { gain: 1300 })],
    };
    const summary = latestMarketSummary(frame);
    assert.equal(summary.industries[0].best.code, "annual-high");
});
