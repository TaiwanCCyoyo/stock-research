import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

test("component renders all groups, truthful states, accessible controls and no invented links", async () => {
    const server = await createServer({
        configFile: false,
        server: { middlewareMode: true },
        appType: "custom",
    });
    try {
        const { ConditionComparison } = await server.ssrLoadModule(
            "/src/features/condition-comparison/ConditionComparison.tsx",
        );
        const { syntheticComparison } = await server.ssrLoadModule(
            "/src/features/condition-comparison/fixture.ts",
        );
        const render = (state) =>
            renderToStaticMarkup(
                createElement(ConditionComparison, {
                    state,
                    onSelectionChange() {},
                }),
            );
        const html = render({ status: "ready", value: syntheticComparison });
        assert.match(html, /合成展示資料/);
        assert.equal((html.match(/class="cc-card"/g) ?? []).length, 5);
        assert.equal((html.match(/對照：其餘母體/g) ?? []).length, 4);
        assert.match(html, /unknown 與 censored 可能重疊/);
        assert.match(html, /aria-label="個案分頁"/);
        assert.match(html, /個案 reader 尚未提供/);
        assert.doesNotMatch(html, /href=/);
        assert.match(render({ status: "loading" }), /aria-busy="true"/);
        assert.match(
            render({ status: "error", message: "broken saved file" }),
            /role="alert"/,
        );
        const empty = structuredClone(syntheticComparison);
        empty.windows = {};
        assert.match(render({ status: "ready", value: empty }), /尚未評估/);
        assert.match(render({ status: "ready", value: empty }), /沒有可讀個案/);
        empty.windows = {
            126: {
                all: { status: "evaluated", counts: {} },
                cells: {},
                complements: {},
                cases: [],
                caseCoverage: "empty",
            },
        };
        assert.match(render({ status: "ready", value: empty }), /缺欄位/);
    } finally {
        await server.close();
    }
});
