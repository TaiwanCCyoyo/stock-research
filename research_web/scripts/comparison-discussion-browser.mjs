/** From research_web: node scripts/comparison-discussion-browser.mjs; open localhost.
 * Mounts the real comparison page and discussion renderer. Only direction API
 * responses are synthetic. No tasks files, private API, storage or writes.
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
const html = await readFile(
    new URL("../discussion-kit/v1/index.html", import.meta.url),
    "utf8",
);
const model = JSON.parse(
    html.match(
        /<script id="discussion-data" type="application\/json">([\s\S]*?)<\/script>/,
    )[1],
);
const api = `
const original = ${JSON.stringify(model)};
const ids = ["20990101-synthetic-first", "20990102-synthetic-second"];
const revision = "a".repeat(40);
export async function fetchDirectionIndex() {
    return {schema:"direction-drafts.v1", mode:"local-private", items: (location.search.includes("empty") ? [] : ids).map(taskId => ({taskId, revision, status:"ready", title:"SYNTHETIC test", message:null}))};
}
export async function fetchDirectionDetail(taskId) {
    // Deliberately ignore cancellation to exercise the resource's stale-response guard.
    await new Promise(resolve => setTimeout(resolve, taskId === ids[0] ? 300 : 10));
    if (location.search.includes("error")) throw new Error("SYNTHETIC read failure");
    const source = {taskId, draftPath:"tasks/"+taskId+"/direction-draft.md", revision:location.search.includes("stale") ? "b".repeat(40) : revision};
    return {schema:"direction-draft.v1", mode:"local-private", taskId, revision:source.revision, status:"ready", message:null, draftMarkdown:"SYNTHETIC ONLY — no real draft exists", model:{...original, demo:false, source, ownerPurpose:"SYNTHETIC integration test — not research"}};
}`;
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {ComparisonPage} from "/src/features/condition-comparison/ComparisonPage.tsx";
const output = document.getElementById("result");
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const wait = async predicate => { for(let i=0;i<100;i++){if(predicate()) return; await sleep(20);} throw new Error("Timed out"); };
const button = text => [...document.querySelectorAll("button")].find(x => x.textContent === text);
const edit = (node, value) => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node), "value").set.call(node, value);
    node.dispatchEvent(new Event("input", {bubbles:true}));
    node.dispatchEvent(new Event("change", {bubbles:true}));
};
const check = (condition, message) => {if(!condition) throw new Error(message);};
history.replaceState(null,"", location.pathname + location.search + "#condition-comparison?result=synthetic-component-v1");
createRoot(document.getElementById("root")).render(React.createElement(ComparisonPage));
try {
    await wait(() => document.querySelector("textarea"));
    edit(document.querySelector("textarea"), "SYNTHETIC question with <script> literal text");
    await wait(() => button("帶來源討論下一步")?.disabled === false);
    button("帶來源討論下一步").click();
    await wait(() => button("選擇同版本方向討論"));
    button("選擇同版本方向討論").click();
    if (location.search.includes("empty")) {
        await wait(() => document.body.textContent.includes("目前沒有可核對版本"));
        check(!button("把問題放入此版本討論"), "Empty list created a target");
        output.textContent = "PASS: empty list keeps the question without creating a draft";
    } else {
    await wait(() => [...document.querySelectorAll("select")].find(x => x.textContent.includes("請選擇")));
    const select = [...document.querySelectorAll("select")].find(x => x.textContent.includes("請選擇"));
    edit(select, "20990101-synthetic-first");
    await sleep(30);
    edit(select, "20990102-synthetic-second");
    if (location.search.includes("stale") || location.search.includes("error")) {
        await wait(() => document.querySelector('[role="alert"]'));
        check(!button("把問題放入此版本討論"), "Invalid revision/read must not open renderer");
        output.textContent = "PASS: blocked " + location.search + " without mounting discussion";
    } else {
        await wait(() => button("把問題放入此版本討論"));
        await sleep(350);
        check(document.querySelector('[aria-label="同版本方向討論交接"]').textContent.includes("20990102-synthetic-second"), "Late first response replaced selected task");
        button("把問題放入此版本討論").click();
        await wait(() => document.querySelector(".dd-notes"));
        const notes = document.querySelector(".dd-notes");
        check(notes.value.includes("SYNTHETIC question"), "Missing question");
        check(notes.value.includes("settingsVersion") && notes.value.includes("synthetic-component-v1"), "Missing provenance");
        check([...document.querySelectorAll(".dd-option")].every(x => x.getAttribute("aria-pressed") === "false"), "Implicit option selection");
        edit(notes, notes.value + "\\nUser edited note");
        button("整理我的想法").click();
        const exported = document.querySelector("textarea.dd-export");
        check(exported.value.includes("User edited note") && exported.value.includes("20990102"), "Feedback lost edit or target");
        check(exported.value.includes("a".repeat(40)), "Feedback lost full SHA");
        button("關閉交接（清除未匯出修改）").click();
        await wait(() => !document.querySelector(".dd-notes"));
        check(document.body.textContent.includes("SYNTHETIC question"), "Closing handoff lost comparison question");
        output.textContent = "PASS: comparison → exact revision → editable proposed feedback → close; rapid switch ignores stale response";
    }
    }
} catch(error) { output.textContent = "FAIL: " + error.message; console.error(error); }
`;
const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    server: { host: "127.0.0.1", port: 20165, strictPort: true },
    plugins: [
        {
            name: "synthetic-discussion-regression",
            transform(_code, id) {
                if (
                    id
                        .replaceAll("\\", "/")
                        .endsWith("/features/direction-discussion/api.ts")
                )
                    return api;
            },
            configureServer(vite) {
                vite.middlewares.use(async (req, res, next) => {
                    if (req.url?.split("?")[0] !== "/") return next();
                    res.setHeader("Content-Type", "text/html; charset=utf-8");
                    res.end(
                        await vite.transformIndexHtml(
                            req.url,
                            '<!doctype html><title>SYNTHETIC handoff regression</title><pre id="result">RUNNING — synthetic only</pre><div id="root"></div><script type="module">' +
                                entry +
                                "</script>",
                        ),
                    );
                });
            },
        },
    ],
});
await server.listen();
server.printUrls();
