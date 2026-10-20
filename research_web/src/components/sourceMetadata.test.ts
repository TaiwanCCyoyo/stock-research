import assert from "node:assert/strict";
import test from "node:test";
import { snapshotDescription, type SnapshotSource } from "./sourceMetadata.ts";

const source: SnapshotSource = {
    kind: "saved-snapshot",
    mode: "local-private",
    schema: "saved-research-studio.v1",
    version: "a".repeat(64),
    asOf: "2023-12-29",
    from: "2019-01-02",
    through: "2023-12-29",
    historyThrough: "2026-10-09",
};
test("saved account dates and history registration dates stay distinct", () => {
    assert.match(
        snapshotDescription(source),
        /帳戶期間 2019-01-02 至 2023-12-29/,
    );
    assert.match(snapshotDescription(source, true), /研究登錄截至 2026-10-09/);
    assert.doesNotMatch(snapshotDescription(source, true), /帳戶期間/);
    assert.match(snapshotDescription(source), /固定研究快照不會隨共用資料更新/);
});
test("synthetic and unversioned responses cannot acquire a private or current label", () => {
    assert.match(
        snapshotDescription({ ...source, mode: "public-synthetic" }),
        /合成示範/,
    );
    assert.match(snapshotDescription(undefined), /無法確認/);
});
