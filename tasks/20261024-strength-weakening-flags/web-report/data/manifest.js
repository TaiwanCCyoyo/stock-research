"use strict";
window.REPORT_TABLES={summary:[],intervals:[],strata:[]};
window.REPORT_READY=(async()=>{
const base=new URL('.',document.currentScript.src);
for(const file of ["meta.js","summary-000.js","summary-001.js","summary-002.js","summary-003.js","summary-004.js","summary-005.js","summary-006.js","summary-007.js","summary-008.js","summary-009.js","summary-010.js","summary-011.js","summary-012.js","intervals-000.js","intervals-001.js","intervals-002.js","intervals-003.js","strata-000.js","strata-001.js","strata-002.js","strata-003.js","strata-004.js","strata-005.js","strata-006.js"]){
await new Promise((resolve,reject)=>{const script=document.createElement('script');
script.src=new URL(file,base).href;script.onload=resolve;script.onerror=()=>reject(new Error('報告資料載入失敗'));
document.head.appendChild(script);});}
return window.REPORT_TABLES;})();
