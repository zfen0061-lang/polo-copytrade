import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

// Load the existing browser module without requiring Node on installed app users' machines.
const code=await readFile(new URL('../frontend/live-ui.js',import.meta.url),'utf8');
const {createAccountRefresher,previewStopRisk}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));

test('margin ROI stops convert to price distance according to leverage',()=>{
  const crypto=previewStopRisk({capital:60,margin:60,leverage:10,stopPercent:30,stopUnit:'margin'});
  assert.equal(crypto.priceStopPercent,3);assert.equal(crypto.expectedLoss,18);
  const equity=previewStopRisk({capital:60,margin:60,leverage:5,stopPercent:50,stopUnit:'margin'});
  assert.equal(equity.priceStopPercent,10);assert.equal(equity.expectedLoss,30);
});

test('position sizing reconciles a price stop with a pool risk budget',()=>{
  const result=previewStopRisk({capital:60,margin:60,leverage:10,stopPercent:2,riskPercent:2,drawdownPercent:10});
  assert.equal(result.expectedLoss,12);assert.equal(result.poolLossPercent,20);
  assert.ok(Math.abs(result.maxMarginForRisk-6)<1e-9);
  assert.equal(result.drawdownLimit,6);assert.equal(result.drawdownStopEquity,54);
  assert.throws(()=>previewStopRisk({capital:60,margin:61,leverage:10,stopPercent:2}));
});

test('a 40 percent margin stop compounds in dollars without inventing a cumulative limit',()=>{
  const start=previewStopRisk({capital:60,margin:60,leverage:10,stopPercent:40,stopUnit:'margin',riskPercent:40,drawdownPercent:''});
  assert.equal(start.expectedLoss,24);assert.equal(start.priceStopPercent,4);
  assert.equal(start.drawdownLimit,null);
  const grown=previewStopRisk({capital:120,margin:120,leverage:5,stopPercent:40,stopUnit:'margin',riskPercent:40,drawdownPercent:''});
  assert.equal(grown.expectedLoss,48);assert.equal(grown.priceStopPercent,8);
});

test('idle accounts refresh automatically on the interval',async()=>{
  let clock=0,calls=0,updated;
  const refresh=createAccountRefresher({clock:()=>clock,load:async()=>({updated:++calls}),
    onSuccess:value=>{updated=value.updated;},onError:error=>assert.fail(error)});
  await refresh.request();
  assert.equal(updated,1);
  clock=9999;await refresh.request();assert.equal(calls,1);
  clock=10000;await refresh.request();assert.equal(updated,2);
});

test('overlapping automatic and manual refreshes share one request',async()=>{
  let release,calls=0;
  const pending=new Promise(resolve=>{release=resolve;});
  const refresh=createAccountRefresher({load:()=>{calls++;return pending;},onSuccess:()=>{},onError:assert.fail});
  const first=refresh.request();
  assert.equal(refresh.busy,true);
  assert.equal(refresh.request(true),first);
  await Promise.resolve();assert.equal(calls,1);
  release({});await first;assert.equal(refresh.busy,false);
});

test('errors retain the previous success, back off, then recover automatically',async()=>{
  let clock=0,calls=0,updated=null,errors=0;
  const refresh=createAccountRefresher({clock:()=>clock,load:async()=>{
    calls++;if(calls===2)throw Error('offline');return {updated:calls};
  },onSuccess:value=>{updated=value.updated;},onError:()=>{errors++;}});
  await refresh.request();
  clock=10000;await refresh.request();assert.equal(updated,1);assert.equal(errors,1);
  clock=29999;await refresh.request();assert.equal(calls,2);
  clock=30000;await refresh.request();assert.equal(updated,3);
  clock=40000;await refresh.request();assert.equal(updated,4);
});
