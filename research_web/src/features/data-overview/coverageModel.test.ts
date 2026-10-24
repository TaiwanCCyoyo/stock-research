import assert from "node:assert/strict";
import test from "node:test";
import {
    canUseCodeSeries,
    legacyHasNoMatch,
    legacyTarget,
    MARKS,
    listQuery,
    safeBack,
    stockHref,
    type CoveredSecurity,
} from "./coverageModel.ts";

test("presence never claims complete historical coverage", () => {
    assert.equal(MARKS.present.label, "有資料");
    assert.equal(MARKS.unknown.icon, "？");
    assert.notEqual(MARKS.unknown.label, MARKS.missing.label);
    assert.deepEqual(Object.keys(MARKS), [
        "present",
        "partial",
        "missing",
        "not_applicable",
        "unknown",
    ]);
    assert.deepEqual(
        Object.values(MARKS).map((mark) => mark.icon),
        ["●", "◐", "○", "－", "？"],
    );
});
test("queries preserve explicit all-history selection", () => {
    assert.equal(listQuery("").get("status"), "recent");
    assert.equal(listQuery("status=all&kind=&q=X123").get("status"), "all");
    assert.equal(listQuery("status=all&kind=&q=X123").get("kind"), "");
});
test("return links keep only stock-list navigation", () => {
    assert.equal(safeBack("javascript:alert(1)"), "#overview/stocks");
    const back = "#overview/stocks?status=all&q=X123&page=2";
    assert.equal(safeBack(back), back);
    const link = stockHref("s_123", "institutional", back);
    const query = new URLSearchParams(link.split("?")[1]);
    assert.equal(query.get("back"), back);
    assert.equal(query.get("dataset"), "institutional");
});

test("legacy resolver redirects unique partial results and handles zero or multiple matches", () => {
    const candidate = { key: "security:v2.2330" } as CoveredSecurity;
    assert.equal(legacyTarget("partial", [candidate]), candidate.key);
    assert.equal(legacyTarget("ok", [candidate, candidate]), null);
    assert.equal(legacyTarget("unavailable", [candidate]), null);
    assert.equal(legacyHasNoMatch("partial", []), true);
    assert.equal(legacyHasNoMatch("ok", [candidate]), false);
    assert.equal(legacyHasNoMatch("unavailable", []), false);
});

test("ambiguous identity segments cannot open code-only series viewers", () => {
    assert.equal(canUseCodeSeries("unresolved"), false);
    assert.equal(canUseCodeSeries("confirmed"), true);
});
