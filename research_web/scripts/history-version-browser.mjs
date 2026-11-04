/** Synthetic-only HTTP fixture; mounts real API, hook, map and stock pages. */
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
const schema = "opportunity-history-web.v1",
    dates = ["2020-01-02", "2020-01-03", "2020-01-06"];
const pins = [
    { versionId: "synthetic/one", manifestSha256: "a".repeat(64) },
    { versionId: "synthetic/two", manifestSha256: "b".repeat(64) },
];
function saved(index, date = dates[1]) {
    const pin = pins[index],
        price = 100 + index * 100;
    const identity = {
        schema,
        catalogId: pin.manifestSha256,
        bundleIdentity: pin,
    };
    const row = {
        securityKey: "s_synthetic%/?:#",
        securityId: "TW:0000",
        code: "0000",
        name: `SYNTHETIC VERSION ${index + 1}`,
        seriesId: `series-${index}`,
        waveId: `wave-${index}`,
        start: dates[0],
        peakDate: date,
        endConfirmedAt: null,
        observedThrough: dates[2],
        leftCensored: false,
        rightCensored: true,
        scale: "large",
        gain: 1.5,
        peakGain: 2,
        raw: price,
        adjusted: price,
        reason: null,
        industry: {
            id: "unknown",
            label: "Synthetic",
            basis: "unknown",
            snapshotAt: null,
        },
        earliestCandidateId: null,
        phase: null,
        growth: {
            schema: "wave-growth.v1",
            startDate: dates[0],
            observationDate: date,
            yearDays: 365.25,
            elapsedDays: 1,
            elapsedYears: 1,
            totalGainPct: 150,
            annualizedGainPct: 150,
            sizingGainPct: 150,
            basis: "actual",
            reason: null,
        },
    };
    const metadata = {
        ...identity,
        dates,
        coverage: { stocks: 1, excluded: 0, from: dates[0], to: dates[2] },
        limitations: ["SYNTHETIC ONLY"],
        basisLabel: "synthetic adjusted",
        ruleLabel: "synthetic",
    };
    const frame = { ...identity, date, rows: [row] };
    const directory = {
        ...identity,
        method: "segments",
        methodScale: "balanced",
        rows: [
            {
                ...row,
                representativeFrom: dates[0],
                representativeUntilExclusive: "2020-01-07",
                launchCandidate: null,
                phases: [],
                peakGain: 150,
                gainAtEnd: 150,
                gainAtEndDate: date,
                growthAtEnd: row.growth,
            },
        ],
    };
    const sample = {
        id: `sample-${index}`,
        name: row.name,
        code: row.code,
        kind: "synthetic",
        category: "synthetic",
        question: "Synthetic-only versions",
        source: {
            label: "Synthetic",
            from: dates[0],
            to: dates[2],
            catalogHash: pin.manifestSha256,
            priceBasis: metadata.basisLabel,
            hash: `synthetic-series-${index}`,
            limitations: ["Not market data"],
        },
        points: dates.map((day, i) => ({
            date: day,
            raw: price + i,
            adjusted: price + i,
            flags: [],
        })),
    };
    return {
        metadata,
        frame,
        directory,
        detail: {
            ...identity,
            date,
            row,
            sample,
            results: [],
            evidence: { synthetic: true },
        },
    };
}
const app = `
import React,{useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import {FullHistoryPage} from "/src/features/full-history/FullHistoryPage.tsx";
import {WaveStockPage} from "/src/features/full-history/WaveStockPage.tsx";
import {historyMarketHref} from "/src/features/full-history/versionIdentity.ts";
const pins=${JSON.stringify(pins)};
const market=i=>historyMarketHref(pins[i])+"&date=2020-01-03&code=0000&mode=catalog";
const initialStock=location.hash.startsWith("#stock/");
if(!location.hash)history.replaceState(null,"",market(0));
function App(){const[hash,setHash]=useState(location.hash);useEffect(()=>{const f=()=>setHash(location.hash);addEventListener("hashchange",f);return()=>removeEventListener("hashchange",f)},[]);const stock=hash.startsWith("#stock/");return React.createElement(React.Fragment,null,React.createElement("div",{hidden:stock},React.createElement(FullHistoryPage,{active:!stock})),stock&&React.createElement(WaveStockPage,{hash}));}
createRoot(document.querySelector("#root")).render(React.createElement(App));
const output=document.querySelector("#result");
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async fn=>{for(let i=0;i<320;i++){if(fn())return;await pause(25)}throw Error("UI timeout")};
const check=(v,message)=>{if(!v)throw Error(message)};
const link=()=>document.querySelector('a[href^="#stock/"]');
const stock=()=>document.querySelector('.u-page .fh-detail');
const context=()=>JSON.parse(new URLSearchParams(link().getAttribute("href").split("?")[1]).get("wave"));
try{
 if(initialStock){await wait(()=>stock());check(document.querySelector('.u-page').textContent.includes("SYNTHETIC VERSION 2"),"Refresh changed version");output.textContent="PASS refresh preserved version two stock source";}
 else {
  await pause(100);location.hash=market(1);
  await wait(()=>link()&&context().bundleIdentity?.versionId===pins[1].versionId);
  await pause(1700);
  check(context().bundleIdentity.versionId===pins[1].versionId,"Late version one response replaced version two");
  check(!document.querySelector('.fh-page').textContent.includes("SYNTHETIC VERSION 1"),"Stale stock leaked into second version");
  history.back();await wait(()=>link()&&context().bundleIdentity?.versionId===pins[0].versionId);
  history.forward();await wait(()=>link()&&context().bundleIdentity?.versionId===pins[1].versionId);
  const destination=link().getAttribute("href");link().click();await wait(()=>stock());
  check(document.querySelector('.u-page').textContent.includes("SYNTHETIC VERSION 2"),"Stock reader used different version");
  document.querySelector('.u-page a[href^="#market?"]').click();
  await wait(()=>link()&&document.activeElement?.classList.contains("fh-detail-anchor"));
  check(link().getAttribute("href")===destination,"Return rewrote original source");
  const track=document.querySelector('.fh-band-track[role="slider"]');
  track.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true,cancelable:true}));
  await wait(()=>!new URLSearchParams(location.hash.split("?")[1]).has("wave"));
  check(new URLSearchParams(location.hash.split("?")[1]).get("version_id")===pins[1].versionId,"Exploration lost pinned version");
  history.back();await wait(()=>new URLSearchParams(location.hash.split("?")[1]).has("wave")&&link()&&link().getAttribute("href")===destination);
  location.hash=historyMarketHref({versionId:"synthetic/absent",manifestSha256:"f".repeat(64)});
  await wait(()=>document.querySelector('[role="alert"]')&&!document.querySelector('[data-history-version]'));
  check(!link(),"Unknown version fell back to old stock");
  location.hash=destination;await wait(()=>stock());
  output.textContent="PASS two-version switch, stale response, same-stock source, Back/Forward, return focus, pinned exploration and unavailable version; refresh to test stock reload";
 }
}catch(error){output.textContent="FAIL "+error.message;console.error(error)}
`;
const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    optimizeDeps: {
        noDiscovery: true,
        include: [
            "react",
            "react-dom",
            "react-dom/client",
            "react/jsx-runtime",
            "react/jsx-dev-runtime",
            "lightweight-charts",
        ],
    },
    server: { host: "127.0.0.1", port: 20168, strictPort: true },
    plugins: [
        {
            name: "synthetic-history-versions",
            configureServer(vite) {
                vite.middlewares.use(async (req, res, next) => {
                    const url = new URL(req.url, "http://127.0.0.1");
                    const base = "/history-api/opportunity-history/v1";
                    if (url.pathname.startsWith(base)) {
                        res.setHeader("Content-Type", "application/json");
                        const v = url.searchParams.get("version_id"),
                            sha = url.searchParams.get("manifest_sha256");
                        const index =
                            v === null && sha === null
                                ? 0
                                : pins.findIndex(
                                      (p) =>
                                          p.versionId === v &&
                                          p.manifestSha256 === sha,
                                  );
                        if (index < 0) {
                            res.statusCode = 503;
                            res.end(
                                JSON.stringify({
                                    detail: "Synthetic pinned version unavailable",
                                }),
                            );
                            return;
                        }
                        const path = url.pathname.slice(base.length),
                            bundle = saved(
                                index,
                                url.searchParams.get("date") || dates[1],
                            );
                        if (path === "/metadata" && index === 0)
                            await new Promise((r) => setTimeout(r, 1500));
                        const payload =
                            path === "/metadata"
                                ? bundle.metadata
                                : path === "/frame"
                                  ? bundle.frame
                                  : path === "/directory"
                                    ? bundle.directory
                                    : path.startsWith("/security/")
                                      ? bundle.detail
                                      : null;
                        if (!payload) {
                            res.statusCode = 404;
                            res.end("{}");
                            return;
                        }
                        res.end(JSON.stringify(payload));
                        return;
                    }
                    if (url.pathname !== "/") return next();
                    res.setHeader("Content-Type", "text/html; charset=utf-8");
                    res.end(
                        await vite.transformIndexHtml(
                            "/",
                            '<!doctype html><meta charset="utf-8"><title>Synthetic saved history versions</title><p>SYNTHETIC ONLY — two artificial versions; no market API</p><pre id="result">RUNNING</pre><div id="root"></div><script type="module">' +
                                app +
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
