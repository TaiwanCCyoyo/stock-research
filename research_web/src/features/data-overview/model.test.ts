import assert from "node:assert/strict";
import test from "node:test";
import {
    countLabel,
    datasetHref,
    groupDatasets,
    periodLabel,
    statusLabel,
    updatedLabel,
    validateDataStatus,
    type DatasetStatus,
} from "./model.ts";

const dataset = (over: Partial<DatasetStatus> = {}): DatasetStatus => ({
    id: "monthly_revenue",
    source: "producer",
    name: "月營收",
    data_period: { from: "2013-01", to: "2026-09" },
    last_updated: "2026-10-24T02:09:03+00:00",
    symbols: 1984,
    rows: 288479,
    status: "ok",
    ...over,
});

test("dataset discovery links only use supported coverage filters", () => {
    assert.match(datasetHref(dataset())!, /dataset=monthly_revenue/);
    assert.equal(
        datasetHref(dataset({ id: "synthetic-prices" })),
        "#overview/stocks?kind=&status=all",
    );
});

test("unknown counts stay unknown while zero stays a measured zero", () => {
    assert.equal(countLabel(null, "筆"), "未知");
    assert.equal(countLabel(0, "筆"), "0 筆");
    assert.equal(countLabel(2353, "檔"), "2,353 檔");
    assert.equal(countLabel(288479, "筆"), "29 萬筆");
    assert.equal(countLabel(28029043, "筆"), "2803 萬筆");
    assert.equal(countLabel(280000000, "筆"), "2.8 億筆");
});

test("periods and update times read as plain dates", () => {
    assert.equal(
        periodLabel({ from: "2010-01-04", to: "2026-10-22" }),
        "2010/01 – 2026/10",
    );
    assert.equal(periodLabel(null), "期間未知");
    assert.equal(updatedLabel(null), "更新時間未知");
    assert.match(
        updatedLabel("2026-10-24T02:09:03+00:00"),
        /^2026\/10\/24 更新$/,
    );
});

test("datasets group by source in a fixed order and empty groups are dropped", () => {
    const groups = groupDatasets([
        dataset({ id: "a", source: "catalog" }),
        dataset({ id: "b", source: "producer" }),
    ]);
    assert.deepEqual(
        groups.map((group) => group.source),
        ["producer", "catalog"],
    );
});

test("responses with another schema are rejected", () => {
    assert.throws(() => validateDataStatus({ schema: "x", datasets: [] }));
    assert.deepEqual(
        validateDataStatus({
            schema: "research-data-status.v1",
            status: "ok",
            generated_at: null,
            datasets: [],
        }).warnings,
        [],
    );
});

test("frozen catalog entries are never labelled as needing an update", () => {
    assert.equal(
        statusLabel(dataset({ source: "catalog", status: "stale" })),
        "部分保存",
    );
    assert.equal(
        statusLabel(dataset({ source: "producer", status: "stale" })),
        "需要更新",
    );
    assert.equal(statusLabel(dataset({ status: "updating" })), "更新中");
});
