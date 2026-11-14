import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

// Load the existing browser module without requiring Node on installed app users' machines.
const code=await readFile(new URL('../frontend/live-ui.js',import.meta.url),'utf8');
const {createAccountRefresher}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));

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
