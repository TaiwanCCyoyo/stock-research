import assert from "node:assert/strict";
import { test } from "node:test";
import { studioRoute } from "./routes.ts";

test("shared data accepts stock codes without unsafe route traversal", () => {
    assert.deepEqual(studioRoute("#data/2330"), {
        page: "data",
        runId: null,
        code: "2330",
    });
    assert.equal(studioRoute("#data").page, "data");
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
    assert.equal(studioRoute("#reports").page, "reports");
    assert.deepEqual(studioRoute("#report/20261012-hhhl-v4-variants"), {
        page: "report",
        runId: null,
        reportId: "20261012-hhhl-v4-variants",
    });
    assert.equal(studioRoute("#report/..%2Fsecret").page, "reports");
    assert.equal(studioRoute("#report/%zz").page, "reports");
    assert.equal(studioRoute("#report/").page, "reports");
});
