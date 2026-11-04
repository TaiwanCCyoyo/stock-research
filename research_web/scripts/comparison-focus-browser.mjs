/** Run from research_web: node scripts/comparison-focus-browser.mjs, then open
 * the printed URL. Uses the real mounted page with only its data hook replaced.
 * Synthetic fixtures only; no API, study calculation or private data access.
 */
import { createServer } from "vite";
import { fileURLToPath } from "node:url";

const card = {
    id: "synthetic-focus",
    date: "2020-01-01",
    question: "Synthetic focus regression card",
    answer: "Not research evidence",
    verdict: null,
    dataPeriod: null,
    keyNumbers: [],
    limitation: null,
    reportHref: null,
    accountRun: null,
    caveats: [],
    progress: null,
    details: {
        originalSummary: null,
        summaryUnconfirmed: false,
        reportPath: null,
        webReportReason: null,
        sharedData: [],
        sharedDataReason: null,
        note: null,
        numberSources: [],
    },
};
const hook = `
import {useEffect, useState} from "react";
const card = ${JSON.stringify(card)};
export function useStudyCards() {
    const [cards, setCards] = useState(() => location.search.includes("cached") ? [card] : null);
    useEffect(() => {
        const load = () => setCards([{...card}]);
        window.addEventListener("fixture-cards", load);
        return () => window.removeEventListener("fixture-cards", load);
    }, []);
    return {cards, hidden:0, partial:false, stale:false, loading:!cards, error:"", retry() {}};
}`;
const entry = `
import React from "react";
import {createRoot} from "react-dom/client";
import {flushSync} from "react-dom";
import {StudiesPage} from "/src/features/studies/StudiesPage.tsx";
const root = createRoot(document.getElementById("root"));
const output = document.getElementById("result");
const pause = () => new Promise(resolve => setTimeout(resolve, 100));
const results = [];
function check(comparison, phase) {
    const active = document.activeElement;
    const correct = comparison
        ? active?.getAttribute("href")?.startsWith("#condition-comparison?")
        : active?.id === "study-synthetic-focus";
    if (!correct) throw new Error(phase + ": unexpected focus " + active?.outerHTML);
    results.push(phase);
}
try {
    for (const cached of [false, true]) {
        for (const comparison of [true, false]) {
            const name = (cached ? "cached" : "delayed") + (comparison ? " comparison" : " ordinary study");
            history.replaceState(null, "", "/" + (cached ? "?cached" : "") +
                "#studies?study=synthetic-focus" + (comparison ? "&focus=comparison" : ""));
            flushSync(() => root.render(React.createElement(StudiesPage, {key:name})));
            await pause();
            if (cached || comparison) check(comparison, name + " initial");
            for (let refresh=1; refresh<=2; refresh++) {
                window.dispatchEvent(new Event("fixture-cards"));
                await pause();
                check(comparison, name + " response " + refresh);
                if (!document.getElementById("study-synthetic-focus")) throw new Error("Missing visible card");
            }
        }
    }
    output.textContent = "PASS: " + results.length + " mounted focus assertions\\n" + results.join("\\n");
} catch(error) {
    output.textContent = "FAIL: " + error.message;
    console.error(error);
}
`;
const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    server: { host: "127.0.0.1", port: 20164, strictPort: true },
    plugins: [
        {
            name: "synthetic-focus-regression",
            transform(_code, id) {
                if (
                    id
                        .replaceAll("\\", "/")
                        .endsWith("/features/studies/useStudyCards.ts")
                )
                    return hook;
            },
            configureServer(vite) {
                vite.middlewares.use(async (req, res, next) => {
                    if (req.url?.split("?")[0] !== "/") return next();
                    res.setHeader("Content-Type", "text/html; charset=utf-8");
                    res.end(
                        await vite.transformIndexHtml(
                            req.url,
                            '<!doctype html><title>Synthetic focus regression</title><pre id="result">RUNNING</pre><div id="root"></div><script type="module">' +
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
