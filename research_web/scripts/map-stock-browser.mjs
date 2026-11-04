/** Synthetic browser harness. Run from research_web with node scripts/map-stock-browser.mjs. */
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const app = `
import React,{useEffect,useState} from "react";
import{createRoot}from"react-dom/client";
import{FullHistoryPage}from"/src/features/full-history/FullHistoryPage.tsx";
import{WaveStockPage}from"/src/features/full-history/WaveStockPage.tsx";
function App(){const[h,setH]=useState(location.hash);useEffect(()=>{const f=()=>setH(location.hash);addEventListener("hashchange",f);return()=>removeEventListener("hashchange",f)},[]);const stock=h.startsWith("#stock/");return React.createElement(React.Fragment,null,React.createElement("div",{hidden:stock},React.createElement(FullHistoryPage,{active:!stock})),stock&&React.createElement(WaveStockPage,{hash:h}))};if(!location.hash)history.replaceState(null,"","#market?date=2020-01-03&code=0000&mode=catalog");createRoot(document.getElementById("root")).render(React.createElement(App));`;
const api = `
const scenario=new URLSearchParams(location.search).get("scenario")||"normal",schema="opportunity-history-web.v1",catalogId="SYNTH-CATALOG",date="2020-01-03",code="0000";
const row={securityKey:scenario==="missing-key"?undefined:"s_synthetic%/?:#",securityId:"TW:0000",code,name:"SYNTHETIC ONLY",seriesId:"s-series",waveId:"s-wave",start:"2020-01-02",peakDate:date,endConfirmedAt:null,observedThrough:"2020-01-06",leftCensored:false,rightCensored:true,scale:"large",gain:1,peakGain:2,raw:100,adjusted:100,reason:null,industry:{id:"unknown",label:"Synthetic",basis:"unknown",snapshotAt:null},earliestCandidateId:null,phase:null,growth:{schema:"wave-growth.v1",startDate:"2020-01-02",observationDate:date,yearDays:365.25,elapsedDays:1,elapsedYears:1,totalGainPct:150,annualizedGainPct:150,sizingGainPct:150,basis:"actual",reason:null}};
const second={...row,securityKey:"s_second%/?:#",securityId:"TW:0001",code:"0001",name:"SYNTHETIC SECOND",seriesId:"s-series-2",waveId:"s-wave-2"};
const metadata={schema,catalogId,dates:["2020-01-02",date,"2020-01-06"],coverage:{stocks:2,excluded:0,from:"2020-01-02",to:"2020-01-06"},limitations:["SYNTHETIC ONLY"],basisLabel:"SYNTHETIC basis",ruleLabel:"synthetic"};
const frame={schema,catalogId,date,rows:[row,second]},directory={schema,catalogId,method:"segments",methodScale:"balanced",rows:[row,second].map(r=>({securityId:r.securityId,code:r.code,name:r.name,industry:r.industry,waveId:r.waveId,start:r.start,peakDate:r.peakDate,endConfirmedAt:null,observedThrough:r.observedThrough,representativeFrom:r.start,representativeUntilExclusive:"2020-01-07",launchCandidate:null,phases:[],scale:"large",leftCensored:false,rightCensored:true,peakGain:150,gainAtEnd:150,gainAtEndDate:date,growthAtEnd:r.growth}))};
const sample={id:"s-sample",name:row.name,code,kind:"synthetic",category:"synthetic",question:"Synthetic fixture",source:{label:"SYNTHETIC ONLY",from:row.start,to:row.observedThrough,catalogHash:scenario==="stale"?"OLD-SYNTH":catalogId,priceBasis:metadata.basisLabel,hash:"synthetic-hash",limitations:["No real data"]},points:[row.start,date,row.observedThrough].map((d,i)=>({date:d,raw:100+i,adjusted:scenario==="missing-price"&&i===1?null:100+i,flags:[]}))};
export async function readHistory(path,signal){if(scenario==="delayed")await new Promise(r=>setTimeout(r,500));signal?.throwIfAborted?.();if(path==="/metadata")return metadata;if(path==="/directory")return directory;if(path.startsWith("/frame")){const d=new URLSearchParams(path.split("?")[1]).get("date");return{...frame,date:d||date}}if(path.startsWith("/security/")){const requested=decodeURIComponent(path.split("?")[0].slice("/security/".length));const found=[row,second].find(r=>r.code===requested)||row;return{schema,catalogId:scenario==="stale"?"OLD-SYNTH":catalogId,date: new URLSearchParams(path.split("?")[1]).get("date")||date,row:found,sample:{...sample,id:"sample-"+found.code,code:found.code,name:found.name},results:[],evidence:{}}}throw Error("Unexpected synthetic route "+path)}
export async function readHistoryWhenReady(path,signal,onProgress){onProgress?.({stage:"SYNTHETIC",completed:1,total:1});return readHistory(path,signal)}`;
const checks = `
const wait=async f=>{for(let i=0;i<240;i++){if(f())return;await new Promise(r=>setTimeout(r,25))}throw Error("UI timeout")};
const result=document.querySelector("#result");
const scenario=new URLSearchParams(location.search).get("scenario")||"normal";
const stock=()=>document.querySelector(".u-page .fh-detail");
const link=()=>document.querySelector('a[href^="#stock/"]');
try {
 if(location.hash.startsWith("#stock/")) {
   await wait(()=>stock()||document.querySelector('.u-page [role="alert"]'));
   result.textContent="PASS direct stock reload kept URL source";
 } else {
   await wait(()=>document.querySelectorAll("button").length>2);
   if(scenario==="missing-key") {
     await wait(()=>document.body.textContent.includes("opaque security key"));
     if(link())throw Error("Missing key exposed stock link");
     result.textContent="PASS missing opaque key fail-closed";
   } else {
     await wait(()=>link());
     const destination=link().getAttribute("href");
     if(!destination.includes("securityKey"))throw Error("no opaque key in URL");
     link().click();
     await wait(()=>location.hash.startsWith("#stock/"));
     if(scenario==="delayed") {
       await wait(()=>document.querySelector(".u-page"));
       history.back(); await wait(()=>!location.hash.startsWith("#stock/"));
       history.forward(); await wait(()=>location.hash.startsWith("#stock/"));
     }
     if(scenario==="stale"||scenario==="missing-price") {
       await wait(()=>document.querySelector('.u-page [role="alert"]'));
       if(stock())throw Error("Unavailable detail rendered chart");
       result.textContent="PASS "+scenario+" rejection";
     } else {
       await wait(()=>stock());
       if(document.querySelector('.u-page a[href^="#data/"]'))throw Error("Historical chart exposed unpinned link");
       for(let i=0;i<2;i++) {
         history.back(); await wait(()=>!location.hash.startsWith("#stock/"));
         await wait(()=>link() && document.activeElement?.classList.contains("fh-detail-anchor"));
         if(link().getAttribute("href")!==destination)throw Error("Return changed source");
         history.forward(); await wait(()=>location.hash.startsWith("#stock/")); await wait(()=>stock());
       }
       if(scenario==="explore") {
         history.back(); await wait(()=>!location.hash.startsWith("#stock/"));
         await wait(()=>link() && document.activeElement?.classList.contains("fh-detail-anchor"));
         const pinnedHash=location.hash;
         const currentContext=()=>{const href=link()?.getAttribute("href");return href?JSON.parse(new URLSearchParams(href.split("?")[1]).get("wave")):null};
         const restore=async()=>{
           history.back(); await wait(()=>location.hash===pinnedHash);
           await wait(()=>document.querySelector(".fh-page") && link()?.getAttribute("href")===destination && document.activeElement?.classList.contains("fh-detail-anchor"));
           await wait(()=>document.querySelector(".fh-band-track")?.getAttribute("aria-valuetext")==="2020-01-03");
         };
         for(const action of ["click","ArrowLeft","ArrowRight","Enter"," "]) {
           result.textContent="RUNNING exploration "+JSON.stringify(action);
           if(action==="Enter"||action===" ") {
             await wait(()=>[...document.querySelectorAll('.opportunity-stock[role="button"]')].some(el=>el.getAttribute("aria-label")?.includes("SYNTHETIC SECOND") && el.getAttribute("aria-disabled")!=="true"));
             const bubble=[...document.querySelectorAll('.opportunity-stock[role="button"]')].find(el=>el.getAttribute("aria-label")?.includes("SYNTHETIC SECOND"));
             if(!bubble)throw Error("second synthetic map bubble unavailable");
             bubble.focus(); bubble.dispatchEvent(new KeyboardEvent("keydown",{key:action,bubbles:true,cancelable:true}));
             await wait(()=>location.hash==="#market" && currentContext()?.securityId==="TW:0001");
           } else {
             const track=document.querySelector('.fh-band-track[role="slider"][aria-label*="SYNTHETIC ONLY"]');
             if(!track)throw Error("synthetic timeline track unavailable");
             track.focus();
             if(action==="click") {const rect=track.getBoundingClientRect();track.dispatchEvent(new MouseEvent("click",{clientX:rect.left+rect.width*.95,bubbles:true}));}
             else track.dispatchEvent(new KeyboardEvent("keydown",{key:action,bubbles:true,cancelable:true}));
             const expected=action==="ArrowLeft"?"2020-01-02":"2020-01-06";
             await wait(()=>location.hash==="#market" && currentContext()?.date===expected);
           }
           if(!document.querySelector(".fh-page"))throw Error(action+" stranded the map");
           await restore();
         }
         result.textContent="PASS explore: timeline click/Left/Right and bubble Enter/Space; all five Back returns preserve original source and focus";
       } else {
       document.querySelector('.u-page a[href^="#market?"]').click();
       await wait(()=>!location.hash.startsWith("#stock/"));
       await wait(()=>link() && document.activeElement?.classList.contains("fh-detail-anchor"));
       result.textContent="PASS map-stock repeated Back/Forward, explicit return and focus; synthetic only";
       }
     }
   }
 }
} catch(e){result.textContent="FAIL "+e.message;console.error(e)}
`;
const html =
    '<!doctype html><meta charset="utf-8"><title>SYNTHETIC ONLY map-stock</title><style>body:before{content:"SYNTHETIC ONLY — no live API or market data";display:block;background:#ffe680;padding:8px;font-weight:bold}</style><pre id="result">RUNNING synthetic harness</pre><div id="root"></div><script type="module">' +
    app +
    "\n" +
    checks +
    "</script>";
const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    server: { host: "127.0.0.1", port: 20166, strictPort: true },
    plugins: [
        {
            name: "synthetic-map-stock",
            transform(_code, id) {
                if (
                    id
                        .replaceAll("\\", "/")
                        .endsWith("/features/full-history/api.ts")
                )
                    return api;
            },
            configureServer(vite) {
                vite.middlewares.use(async (req, res, next) => {
                    if (req.url?.split("?")[0] !== "/") return next();
                    res.setHeader("Content-Type", "text/html; charset=utf-8");
                    const transformed = await vite.transformIndexHtml(
                        "/",
                        html,
                    );
                    res.end(transformed);
                });
            },
        },
    ],
});
await server.listen();
server.printUrls();
