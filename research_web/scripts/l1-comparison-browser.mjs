/** Mount real comparison navigation. All data comes from the producer's single
 * tracked synthetic fixture through the production registry; no mock result. */
import { createServer } from "vite";
import { fileURLToPath } from "node:url";

const entry = `
import React,{useState,useEffect} from "react";
import {createRoot} from "react-dom/client";
import {ComparisonPage,ComparisonEntrance} from "/src/features/condition-comparison/ComparisonPage.tsx";
function App(){const [hash,setHash]=useState(location.hash);useEffect(()=>{const change=()=>setHash(location.hash);addEventListener("hashchange",change);return()=>removeEventListener("hashchange",change)},[]);return hash.startsWith("#condition-comparison")?React.createElement(ComparisonPage):React.createElement(ComparisonEntrance,{back:"#studies?q=L1"});}
if(!location.hash)history.replaceState(null,"","#studies?q=L1");
createRoot(document.getElementById("root")).render(React.createElement(App));
const out=document.querySelector("#result");
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const wait=async check=>{for(let i=0;i<150;i++){if(check())return;await sleep(25)}throw Error("UI timeout")};
const check=(value,message)=>{if(!value)throw Error(message)};
const selection=()=>new URLSearchParams(location.hash.split("?")[1]);
try {
 const refreshed=location.hash.startsWith("#condition-comparison");
 if(!refreshed){await wait(()=>document.querySelector(".direction-entrance"));document.querySelector(".direction-entrance").click();}
 await wait(()=>document.querySelectorAll(".cc-card").length===5);
 check(document.querySelectorAll("tbody tr").length===8,"Lost unavailable partitions");
 check(!document.querySelector("[data-comparison-event]"),"Trace reference became case reader");
 if(refreshed){
   check(document.querySelector("select").value===(selection().get("h")||"126"),"Reload lost horizon");
   check(document.querySelector('[data-comparison-group="'+selection().get("group")+'"]').getAttribute("aria-pressed")==="true","Reload lost cell");
   out.textContent="PASS producer fixture refresh retained exact result/horizon/cell";
 }else{
   const edit=value=>{const field=document.querySelector("select");Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value").set.call(field,value);field.dispatchEvent(new Event("change",{bubbles:true}));};
   for(const h of ["252","126","252"]){edit(h);await wait(()=>selection().get("h")===h);}
   document.querySelector('[data-comparison-group="both"]').click();await wait(()=>selection().get("group")==="both");
   check(selection().get("h")==="252","Cell selection lost latest horizon");
   const saved=location.hash;
   history.back();await wait(()=>selection().get("group")==="all");
   history.forward();await wait(()=>location.hash===saved);
   for(let i=0;i<2;i++){
     document.querySelector('a[href^="#studies"]').click();await wait(()=>document.querySelector(".direction-entrance")===document.activeElement);
     history.back();await wait(()=>location.hash===saved && document.querySelector('[data-comparison-group="both"]')?.getAttribute("aria-pressed")==="true");
   }
   check(document.querySelectorAll("tbody tr").length===8,"Return lost unavailable partitions");
   out.textContent="PASS producer fixture: rapid horizon switching, cell selection, repeated return focus and Back/Forward; refresh this page to verify reload";
 }
}catch(error){out.textContent="FAIL "+error.message;console.error(error)}
`;
const server = await createServer({
    root: fileURLToPath(new URL("../", import.meta.url)),
    configFile: false,
    optimizeDeps: {
        noDiscovery: true,
        include: [
            "react",
            "react-dom/client",
            "react/jsx-runtime",
            "react/jsx-dev-runtime",
        ],
    },
    server: {
        host: "127.0.0.1",
        port: 20167,
        strictPort: true,
        fs: { allow: [fileURLToPath(new URL("../../", import.meta.url))] },
    },
    plugins: [
        {
            name: "l1-producer-fixture-regression",
            configureServer(vite) {
                vite.middlewares.use(async (req, res, next) => {
                    if (req.url?.split("?")[0] !== "/") return next();
                    res.setHeader("Content-Type", "text/html; charset=utf-8");
                    res.end(
                        await vite.transformIndexHtml(
                            "/",
                            '<!doctype html><meta charset="utf-8"><title>L1 producer synthetic fixture</title><style>body{font-family:system-ui;margin:16px}#result{white-space:pre-wrap;background:#fff1a8;padding:12px}</style><p>SYNTHETIC ONLY — producer fixture, not market research</p><pre id="result">RUNNING</pre><div id="root"></div><script type="module">' +
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
