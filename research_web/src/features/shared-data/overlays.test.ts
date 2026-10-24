import assert from "node:assert/strict";
import test from "node:test";
import {
    institutionalPoints,
    percentLabel,
    readSeries,
    revenueBars,
    revenueLabel,
    sharesLabel,
    type InstitutionalRow,
} from "./overlays.ts";

const row = (date: string, net: number | null): InstitutionalRow => ({
    date,
    foreign_total_net: net,
    trust_net: 0,
    dealer_total_net: null,
    three_institutions_net: net,
});

test("institutional points keep chart dates only and nulls as gaps", () => {
    const points = institutionalPoints(
        [
            row("2026-10-01", 1200),
            row("2026-10-02", null),
            row("2026-10-04", 5),
        ],
        "three_institutions_net",
        new Set(["2026-10-01", "2026-10-02"]),
    );
    assert.deepEqual(points, [
        { date: "2026-10-01", value: 1200 },
        { date: "2026-10-02", value: null },
    ]);
    assert.deepEqual(
        institutionalPoints(
            [row("2026-10-01", 9)],
            "dealer_total_net",
            new Set(["2026-10-01"]),
        ),
        [{ date: "2026-10-01", value: null }],
    );
});

test("revenue bars sort by month and skip unknown revenue", () => {
    const bars = revenueBars([
        {
            revenue_month: "2026-09",
            current_revenue_k_twd: 300,
            yoy_pct: 12.5,
            mom_pct: null,
        },
        {
            revenue_month: "2026-07",
            current_revenue_k_twd: null,
            yoy_pct: null,
            mom_pct: null,
        },
        {
            revenue_month: "2026-08",
            current_revenue_k_twd: 200,
            yoy_pct: null,
            mom_pct: null,
        },
    ]);
    assert.deepEqual(
        bars.map((bar) => bar.month),
        ["2026-08", "2026-09"],
    );
    assert.equal(bars[0]!.yoy, null);
});

test("units read plainly without changing the stored meaning", () => {
    assert.equal(sharesLabel(-1234567), "−123.5 萬股");
    assert.equal(sharesLabel(0), "0 股");
    assert.equal(sharesLabel(null), "未知");
    assert.equal(revenueLabel(250_000_000), "2500.00 億元");
    assert.equal(revenueLabel(12_345), "1,235 萬元");
    assert.equal(percentLabel(12.34), "+12.3%");
    assert.equal(percentLabel(null), "未知");
});

test("series requests use the overlay route and reject other schemas", async () => {
    let url = "";
    const fetcher = (async (input: string) => {
        url = input;
        return new Response(
            JSON.stringify({ schema: "research-data-series.v1", rows: [] }),
        );
    }) as unknown as typeof fetch;
    await readSeries(
        "institutional",
        "2330",
        "2019-01-02",
        new AbortController().signal,
        fetcher,
    );
    assert.equal(url, "/api/data-series/v1/institutional/2330?from=2019-01-02");
    const bad = (async () =>
        new Response(
            JSON.stringify({ schema: "x" }),
        )) as unknown as typeof fetch;
    await assert.rejects(
        readSeries(
            "monthly-revenue",
            "2330",
            null,
            new AbortController().signal,
            bad,
        ),
    );
});
