import assert from "node:assert/strict";
import { test } from "node:test";
import { studioRoute } from "./routes.ts";

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
