const $=s=>document.querySelector(s);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const when=value=>value?new Date(value).toLocaleString():'尚无记录';
let token='',state=null,hydrated=false,busy=false,starting=false,policyDirty=false,actionError='';
const form=$('#policy');
async function api(path,payload){
  if(payload!==undefined&&!token)token=(await api('/api/session')).csrf_token;
  const response=await fetch(path,{cache:'no-store',...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(payload)})});
  const value=await response.json();
  if(!response.ok){if(response.status===403)token='';throw new Error(value.error||'请求失败');}
  return value;
}
function fill(policy){
  const p=policy||{initial_capital:'60',max_loss:'60',loss_basis:'initial_net_loss',crypto_leverage:10,equity_leverage:3,margin_loss_fraction:'0.40',max_deviation:'0.03',max_signal_age:60,symbols:{BTCUSDT:'crypto',ETHUSDT:'crypto',ZECUSDT:'crypto'}};
  const values={...p,margin_stop_percent:Number(p.margin_loss_fraction)*100,deviation_percent:Number(p.max_deviation)*100};
  for(const kind of ['crypto','equity','traditional'])values[kind+'_symbols']=Object.keys(p.symbols).filter(s=>p.symbols[s]===kind).join(', ');
  for(const [name,value] of Object.entries(values))if(form.elements[name])form.elements[name].value=value;
}
function policyValues(){
  const data=new FormData(form),symbols={};
  for(const kind of ['crypto','equity','traditional'])for(const symbol of String(data.get(kind+'_symbols')).toUpperCase().split(/[\s,，]+/).filter(Boolean)){
    if(symbols[symbol])throw new Error('合约分类重复：'+symbol);symbols[symbol]=kind;
  }
  return {initial_capital:data.get('initial_capital'),max_loss:data.get('max_loss'),loss_basis:data.get('loss_basis'),
    crypto_leverage:Number(data.get('crypto_leverage')),equity_leverage:Number(data.get('equity_leverage')),
    margin_loss_fraction:String(Number(data.get('margin_stop_percent'))/100),max_deviation:String(Number(data.get('deviation_percent'))/100),
    max_signal_age:Number(data.get('max_signal_age')),symbols};
}
function render(){
  if(!state)return;
  const a=state.account,s=state.source||{},j=state.journal||{},r=state.review;
  $('#account').textContent=a?`USDT 可用 ${a.available_usdt} · 账户持仓 ${a.positions.length} 笔 · ${a.hedge_mode?'双向':'单向'}持仓／${a.multi_assets?'多资产':'单资产'}`:'尚未读取真实账户';
  $('#account-time').textContent='账户更新：'+when(state.account_updated);
  $('#source').textContent=`${s.fresh?'采集正常':s.watching?'采集中，等待新鲜数据':'采集未就绪'} · 最近成功 ${when(s.last_poll)}${s.error?' · '+s.error:''}`;
  $('#capital').textContent=`策略已核实资金 ${j.capital_usdt??'未初始化'} USDT · 待核对订单 ${j.pending_count??'未知'}`;
  $('#phase').textContent=({idle:'实盘未启动',starting:'启动核对中',running:state.entries_enabled?'实盘自动跟随中':'新开仓已暂停',error:'异常停止',stopped:'已停止'})[state.phase]||state.phase;
  $('#phase').className='pill '+(state.execution_armed?'green':state.phase==='error'?'red':'subtle');
  $('#tick').textContent='策略最近更新：'+when(state.last_tick)+(state.source_waiting?' · 正等待采集恢复':'');
  $('#error').textContent=actionError||state.error||'';
  if(!hydrated){fill(state.policy||state.suggested_policy);hydrated=true;}
  $('#policy-state').textContent=state.policy?(j.locked?'已有实盘历史，参数锁定':'实盘参数已保存'):'预填草案，尚未保存';
  for(const control of form.elements)control.disabled=state.running||j.locked||busy;
  $('#inspect').disabled=state.running||busy;
  $('#review').textContent=starting?'正在核对账户与信号，请稍候…':state.running?'正在自动跟随；持仓与执行结果可在下方查看。':r?.blockers?.length?'暂不能启动：'+r.blockers.join('；'):'点击启动会自动核对账户，确认后持续跟随；无需复制或输入文字。';
  $('#start').disabled=busy||state.running;
  $('#start').textContent=starting?'正在核对…':'启动实盘自动跟随';
  $('#pause').disabled=busy||!state.running;$('#stop').disabled=busy||!state.running;
  $('#pause').textContent=state.entries_enabled?'暂停新开仓':'恢复新开仓';
  $('#close-owned').disabled=busy||!state.running||!j.positions?.length;
  $('#positions').innerHTML=j.positions?.length?j.positions.map(p=>`<tr><td>${esc(p.symbol)} / ${esc(p.side)}</td><td>${esc(p.qty)}</td><td>${esc(p.entry)}</td><td>${esc(p.leverage)}×</td></tr>`).join(''):'<tr><td colspan="4" class="empty">没有本程序持仓</td></tr>';
  $('#logs').innerHTML=state.logs.length?state.logs.map(l=>`<div class="log-row"><time>${esc(when(l.time))}</time><span class="pill ${l.level==='error'?'red':'subtle'}">${esc(l.level)}</span><span>${esc(l.message)} ${esc(l.symbol)} ${esc(l.action)} ${esc(l.result)} ${esc(l.reason)} ${l.price_check?'价差 '+esc(Number(l.price_check.signed_percent).toFixed(3))+'%':''}</span></div>`).join(''):'<p class="small muted">尚无实盘运行记录。</p>';
}
async function refresh(){
  if(busy)return;
  try{state=await api('/api/real-v2/state');render();$('#connection').textContent='本机后台已连接';$('#connection').className='pill green';}
  catch(error){$('#connection').textContent='后台连接失败';$('#connection').className='pill red';$('#error').textContent=error.message;}
}
async function action(name,payload={}){
  if(busy)return;busy=true;render();
  try{state=await api('/api/real-v2/'+name,payload);if(name==='configure')policyDirty=false;actionError='';}
  catch(error){actionError=error.message;}
  finally{busy=false;render();}
}
async function startFollowing(){
  if(busy||state?.running)return;
  let draft=null;
  if(policyDirty||!state?.policy){
    if(!form.reportValidity())return;
    try{draft=policyValues();}catch(error){actionError=error.message;render();return;}
  }
  busy=true;starting=true;actionError='';render();
  try{
    if(draft){state=await api('/api/real-v2/configure',draft);policyDirty=false;}
    state=await api('/api/real-v2/inspect',{});
    const review=state.review;
    if(!review?.valid||review.blockers.length)throw new Error(review?.blockers?.join('；')||'账户核对未完成，请重新点击启动。');
    const p=state.policy,capital=state.journal?.capital_usdt??p.initial_capital;
    const message=`启动实盘自动跟随？\n\n专用跟单账户可用：${state.account.available_usdt} USDT\n策略资金：${capital} USDT，同时最多一笔持仓\n加密货币 ${p.crypto_leverage} 倍；股票／传统资产 ${p.equity_leverage} 倍\n单笔保证金亏损止损目标 ${Number(p.margin_loss_fraction)*100}%\n开仓价差 ≤ ${Number(p.max_deviation)*100}%；匹配的平仓信号全平该跟单仓位\n\n确认后将使用真实资金自动买卖，跟随熬鹰资本的新操作。`;
    if(!window.confirm(message))return;
    state=await api('/api/real-v2/start',{confirmation:review.confirmation,nonce:review.nonce});
  }catch(error){actionError=error.message;}
  finally{busy=false;starting=false;render();}
}
form.addEventListener('input',()=>{policyDirty=true;});
form.addEventListener('submit',event=>{event.preventDefault();try{void action('configure',policyValues());}catch(error){actionError=error.message;render();}});
$('#inspect').addEventListener('click',()=>action('inspect'));
$('#start').addEventListener('click',()=>void startFollowing());
$('#pause').addEventListener('click',()=>action('pause',{paused:state.entries_enabled}));
$('#stop').addEventListener('click',()=>action('stop'));
$('#close-owned').addEventListener('click',()=>action('flatten-owned',{confirmation:'CLOSE OWNED REAL'}));
void refresh();setInterval(refresh,3000);
