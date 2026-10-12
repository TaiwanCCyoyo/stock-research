import assert from "node:assert/strict";
import { test } from "node:test";
import {
    filterReports,
    reportFrameSrc,
    reportTags,
    statusLabel,
    validateReportIndex,
    type ReportEntry,
} from "./model.ts";

const entry = (id: string, title: string, tags: string[]): ReportEntry => ({
    id,
    title,
    summary: "",
    date: "",
    status: "",
    period: "",
    kit: "v1",
    tags,
});

test("search matches every word across title, id and tags, and a tag narrows", () => {
    const reports = [
        entry("20261012-hhhl-v4-variants", "高過高條件", ["HHHL", "型態"]),
        entry("20261020-pattern-scan", "型態寬掃", ["型態"]),
    ];
    assert.deepEqual(
        filterReports(reports, "hhhl 條件", null).map((r) => r.id),
        ["20261012-hhhl-v4-variants"],
    );
    assert.equal(filterReports(reports, "", "型態").length, 2);
    assert.equal(filterReports(reports, "寬掃", "HHHL").length, 0);
    assert.deepEqual(reportTags(reports), ["型態", "HHHL"]);
});

test("index validation rejects other shapes and labels unknown statuses plainly", () => {
    assert.throws(() => validateReportIndex({ reports: [] }));
    assert.equal(
        validateReportIndex({ schema: "research-reports.v1", reports: [] })
            .reports.length,
        0,
    );
    assert.equal(statusLabel("descriptive"), "描述性結果");
    assert.equal(statusLabel(""), "未標示");
});

test("frame source encodes the id and carries the first-paint theme", () => {
    assert.equal(
        reportFrameSrc("a b", "ocean", "dark"),
        "/reports/a%20b/index.html#palette=ocean&appearance=dark",
    );
});
