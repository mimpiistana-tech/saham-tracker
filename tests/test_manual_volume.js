// Offline smoke test of the manual Stockbit 5m price/volume paper gate.
// This exercises the real functions embedded in index.html; no HTTP requests.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');

const html=fs.readFileSync('index.html','utf8');
const start=html.indexOf('const scannerPaperCandidates = Object.create(null);');
const end=html.indexOf('async function checkScannerTiming5m(',start);
assert(start>=0 && end>start,'Manual 5m handler must exist');
const source=html.slice(start,end);

const els=Object.create(null);
const el=(id)=>els[id]??null;
let recorded=0,confirmations=0;
const modules=new Function('document','parseStockbitPrice','compactNumber',
  'recordStockbitPaperTrigger','window',
  source+'\nreturn {scannerPaperCandidates,scannerManual5mProofs,parseStockbitVolume,manual5mAssessment,verifyManual5m,recordConfirmedScannerPaper,scanner5mForm};')(
  {getElementById:el},
  s=>Number(s),
  x=>String(x),
  ()=>{recorded++;return {ok:true,message:'Simulasi tersimpan'};},
  {confirm:()=>{confirmations++;return true;}}
);
const {parseStockbitVolume,manual5mAssessment}=modules;
assert.equal(parseStockbitVolume('83'),83);
assert.equal(parseStockbitVolume('2.56K'),2560);
assert.equal(parseStockbitVolume('2,56 K'),2560);
assert.equal(parseStockbitVolume('1.2M'),1200000);
assert(Number.isNaN(parseStockbitVolume('')));
assert(Number.isNaN(parseStockbitVolume('??')));
assert.equal(manual5mAssessment(83,2560,[true,true,true,true]).ok,false);
assert.equal(manual5mAssessment(0,2560,[true,true,true,true]).status,'WAIT_DATA');
assert.equal(manual5mAssessment(4000,2560,[true,true,true,false]).ok,false);
assert.equal(manual5mAssessment(4000,2560,[]).ok,false);
assert.equal(manual5mAssessment(4000,2560,[true,true,true,true]).status,'PAPER_WATCH_MANUAL');
assert(modules.scanner5mForm('ARCI').includes('scanner5mLast_ARCI'));

for(const [k,value] of Object.entries({
  scannerStockbitInput_ARCI:'1290',scanner5mLast_ARCI:'83',scanner5mAvg_ARCI:'2.56K'
}))els[k]={value};
for(const name of ['closed','green','break','hl'])els['scanner5m_'+name+'_ARCI']={checked:true};
els.scanner5mPaperBtn_ARCI={disabled:true};
els.scanner5mResult_ARCI={textContent:''};
els.scannerStockbitResult_ARCI={textContent:'',className:''};
modules.scannerPaperCandidates.ARCI={price:1290,savedAt:Date.now(),ctx:{}};
modules.verifyManual5m('ARCI');
assert(els.scanner5mPaperBtn_ARCI.disabled,'Weak volume must not enable paper');
modules.recordConfirmedScannerPaper('ARCI');
assert.equal(recorded,0,'Weak-volume entry was improperly recorded');

els.scanner5mLast_ARCI.value='4000';
els.scanner5m_hl_ARCI.checked=false;
modules.verifyManual5m('ARCI');
assert(els.scanner5mPaperBtn_ARCI.disabled,'Missing HL must block paper');
els.scanner5m_hl_ARCI.checked=true;
modules.verifyManual5m('ARCI');
assert.equal(els.scanner5mPaperBtn_ARCI.disabled,false,'Strong manual gate should enable paper');

els.scanner5mLast_ARCI.value='83'; // Simulate a stale proof or changed form
modules.recordConfirmedScannerPaper('ARCI');
assert.equal(recorded,0,'Changed input must invalidate manual proof');
els.scanner5mLast_ARCI.value='4000';
modules.verifyManual5m('ARCI');
els.scannerStockbitInput_ARCI.value='1300'; // Changed price
modules.recordConfirmedScannerPaper('ARCI');
assert.equal(recorded,0,'Changed price must invalidate entry');
els.scannerStockbitInput_ARCI.value='1290';
// A mismatched Stockbit price consumed the previous confirmation.
// The user must reconfirm the quote before being allowed to paper trade.
modules.scannerPaperCandidates.ARCI={price:1290,savedAt:Date.now(),ctx:{}};
modules.verifyManual5m('ARCI');
modules.recordConfirmedScannerPaper('ARCI');
assert.equal(recorded,1,'Explicit paper entry should run once after full proof');
assert.equal(confirmations,1,'An additional user consent dialog is required');
assert.equal(els.scanner5mPaperBtn_ARCI.disabled,true,'Button resets after paper');
assert(!modules.scannerPaperCandidates.ARCI,'Price confirmation is consumed');

assert(!html.includes("onclick='addPaperTrade("),'Legacy one-click single paper must not render');
assert(!html.includes("onclick='addPaperTradesBatch("),'Legacy TOP 3 paper must not render');
const confirmStart=html.indexOf('function confirmScannerStockbit(item){');
const confirmEnd=html.indexOf('async function addPaperTradesBatch(',confirmStart);
const scannerConfirm=html.slice(confirmStart,confirmEnd);
assert(!scannerConfirm.includes('recordStockbitPaperTrigger('),
  'Confirm Stockbit must never open an entry');
console.log('V2 manual Stockbit 5m gate: ALL OFFLINE CHECKS PASSED');
