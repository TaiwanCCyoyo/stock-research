import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import fixture from "../../scripts/tests/fixtures/l1-volume-comparison.synthetic.v1.json" with { type: "json" };
import { adaptL1Comparison } from "../src/features/condition-comparison/l1Adapter.ts";
import { initialSelection } from "../src/features/condition-comparison/model.ts";
import {
    comparisonHref,
    parseComparisonLocation,
    validateComparisonLocation,
} from "../src/features/condition-comparison/journey.ts";
import {
    L1_SYNTHETIC_RESULT_ID,
    readRegisteredComparison,
} from "../src/features/condition-comparison/registry.ts";

test("producer fixture is registered directly, preserves URL identity, and never exposes references as cases", () => {
    const state = readRegisteredComparison(L1_SYNTHETIC_RESULT_ID);
    assert.equal(state.status, "ready");
    const view = state.value;
    assert.deepEqual(view.producer.provenance, fixture.provenance);
    for (const horizon of [126, 252]) {
        const selected = { ...initialSelection(view), horizon, group: "both" };
        const href = comparisonHref(selected, "#studies?q=L1");
        const route = parseComparisonLocation(href);
        assert.equal(validateComparisonLocation(view, route), undefined);
        assert.equal(comparisonHref(route.selection, route.back), href);
        assert.deepEqual(view.windows[horizon].cases, []);
        assert.deepEqual(view.windows[horizon].complements, {});
        assert.throws(() =>
            validateComparisonLocation(view, {
                ...route,
                openCase: "trace-pointer",
                selection: { ...selected, eventId: "trace-pointer" },
            }),
        );
    }
    assert.equal(readRegisteredComparison("unregistered-l1").status, "error");
});

test("mounted renderer retains four cells, eight unavailable partitions, unevaluated counts and null rates", async () => {
    const server = await createServer({
        configFile: false,
        server: { middlewareMode: true },
        appType: "custom",
    });
    try {
        const { ConditionComparison } = await server.ssrLoadModule(
            "/src/features/condition-comparison/ConditionComparison.tsx",
        );
        const view = adaptL1Comparison(fixture, L1_SYNTHETIC_RESULT_ID);
        for (const horizon of [126, 252]) {
            const html = renderToStaticMarkup(
                createElement(ConditionComparison, {
                    state: { status: "ready", value: view },
                    selection: {
                        ...initialSelection(view),
                        horizon,
                        group: "both",
                    },
                    onSelectionChange() {},
                }),
            );
            assert.equal((html.match(/class="cc-card"/g) ?? []).length, 5);
            assert.equal((html.match(/<tr>/g) ?? []).length, 9);
            assert.match(html, /尚未評估/);
            assert.match(html, /無分母（null）/);
            assert.match(html, /不是完整或代表性案例/);
            assert.match(html, /base_label_manifest_sha256/);
            assert.match(
                html,
                /unknown 與 censored|unknown 和 censored|unknown 與|unknown.*censored/s,
            );
            assert.doesNotMatch(
                html,
                /data-comparison-event|aria-label="個案分頁"|href=/,
            );
            for (const ref of view.windows[horizon].references.both)
                assert.ok(html.includes(ref.event_id));
        }
    } finally {
        await server.close();
    }
});
