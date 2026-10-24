import assert from "node:assert/strict";
import { test } from "node:test";
import { studioRoute } from "./routes.ts";
import { stockHref } from "../features/data-overview/coverageModel.ts";

test("shared data accepts stock codes without unsafe route traversal", () => {
    assert.deepEqual(studioRoute("#data/2330"), {
        page: "data",
        runId: null,
        code: "2330",
    });
    assert.equal(studioRoute("#data").page, "overview");
    assert.equal(studioRoute("#data/%zz").code, undefined);
    assert.equal(studioRoute("#data/..%2Fsecret").code, undefined);
});

test("empty routes lead to home and market deep links preserve page", () => {
    assert.equal(studioRoute("").page, "home");
    assert.equal(
        studioRoute("#market?date=2021-04-29&code=2609").page,
        "market",
    );
});
test("saved strategy identifiers round-trip and malformed identifiers fall back", () => {
    const id = "stock:20261002-add-retry:normal-v1";
    assert.deepEqual(studioRoute(`#strategy/${encodeURIComponent(id)}`), {
        page: "strategy",
        runId: id,
    });
    assert.equal(studioRoute("#strategy/%zz").page, "strategies");
    assert.equal(studioRoute("#strategy/").page, "strategies");
});
test("report routes keep a safe report id and fall back to the library", () => {
    assert.equal(studioRoute("#reports").page, "studies");
    assert.equal(studioRoute("#history").page, "studies");
    assert.equal(studioRoute("#studies").page, "studies");
    assert.equal(studioRoute("#research").page, "research");
    assert.equal(studioRoute("#overview").page, "overview");
    assert.deepEqual(studioRoute("#report/20261012-hhhl-v4-variants"), {
        page: "report",
        runId: null,
        reportId: "20261012-hhhl-v4-variants",
    });
    assert.equal(studioRoute("#report/..%2Fsecret").page, "studies");
    assert.equal(studioRoute("#report/%zz").page, "studies");
    assert.equal(studioRoute("#report/").page, "studies");
});

test("coverage and opaque stock routes do not guess stock identity", () => {
    assert.equal(studioRoute("#overview/stocks?q=X123").overviewTab, "stocks");
    const key = "s_" + "a".repeat(24);
    assert.equal(studioRoute("#stock/" + key).securityKey, key);
    assert.equal(studioRoute("#stock/../../x").page, "overview");
});

test("opaque API stock keys round-trip without a frontend format assumption", () => {
    const key = "security:v2@TWSE.2330/2023-09-01";
    const href = stockHref(key);
    assert.equal(studioRoute(href).securityKey, key);
    assert.equal(studioRoute("#stock/%zz").page, "overview");
});
