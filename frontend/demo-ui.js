const $=selector=>document.querySelector(selector);
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let csrf='',state=null,busy=false,hydrated=false,actionError='';
const form=$('#demo-policy');
async function request(path,payload,retry=true){
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),payload===undefined?10000:45000);
  let response,result;
  try{
    response=await fetch(path,{signal:controller.signal,...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)})});
    result=await response.json();
  }catch(error){throw new Error(error.name==='AbortError'?'请求超时，请核对会话和订单状态；不要重复提交。':'无法连接测试网后台，请检查测试网窗口。');}
  finally{clearTimeout(timer);}
  if(response.status===403&&payload!==undefined&&retry){await session();return request(path,payload,false);}
  if(!response.ok)throw new Error(result.error||'请求失败');
  return result;
}
async function session(){csrf=(await request('/api/session')).csrf_token;}
function policyValues(){
  const raw=Object.fromEntries(new FormData(form));const symbols={};
  for(const [field,kind] of [['crypto_symbols','crypto'],['equity_symbols','equity'],['traditional_symbols','traditional']]){
    for(const symbol of (raw[field]||'').toUpperCase().split(/[,，\s]+/).filter(Boolean)){
      if(symbols[symbol])throw new Error('合约重复：'+symbol);symbols[symbol]=kind;
    }
  }
  return {initial_capital:raw.initial_capital,max_loss:raw.max_loss,loss_basis:raw.loss_basis,
    crypto_leverage:Number(raw.crypto_leverage),equity_leverage:Number(raw.equity_leverage),
    margin_loss_fraction:String(Number(raw.margin_stop_percent)/100),max_deviation:String(Number(raw.deviation_percent)/100),
    max_signal_age:Number(raw.max_signal_age),symbols};
}
function render(){
  if(!state)return;
  $('#demo-error').textContent=actionError||state.error||'';
  if(!state.available){$('#preview-note').textContent='请用 open-demo-preview.cmd 或 connect-demo-v2.cmd 打开独立测试网页面（8766）。';return;}
  const active=state.running&&state.phase==='running';
  const verification=state.verification||{};
  const verifying=verification.active===true;
  const progress=verification.progress||{};
  const checked=verification.result;
  $('#demo-verification-state').textContent=verifying?
    `止损检查进行中：${progress.stage||'正在启动'}${progress.remaining_seconds!==undefined?'，剩余等待 '+progress.remaining_seconds+' 秒':''}`:
    checked?`最近结果：${checked.status}；实际止损成交：${checked.stop_triggered?'已核实':'未核实'}；空仓：${checked.flat_verified?'已核实':'未核实'}；保护单清理：${checked.protection_cleared?'已核实':'未核实'}${checked.error?'；'+checked.error:''}`:
    verification.error||'尚未运行后台止损检查。';
  $('#demo-verify').disabled=state.running||verifying||!state.saved_demo_connection||!$('#demo-confirm').checked;
  $('#preview-note').textContent=state.configured?'此会话只连接合约 Demo；启动跟随或点击演练按钮后才可能提交虚拟资金订单。':'预览模式：尚未输入 Demo 密钥，不能下单。需要时关闭本测试网窗口，再双击 connect-demo-v2.cmd 本机隐藏输入 Demo 密钥；真实账户密钥不用重做。';
  $('#demo-inspect').disabled=!state.configured||state.running;
  const account=state.account;
  $('#demo-account').textContent=account?`已验证 · ${account.hedge_mode?'双向':'单向'}持仓 · ${account.multi_assets?'多资产':'单资产'}模式 · USDT 可用 ${account.available_usdt} · 更新时间 ${new Date(state.account_updated).toLocaleTimeString()}`:'尚未验证 Demo 账户';
  $('#demo-account-positions').textContent=account?'交易所实际仓位：'+(account.positions?.length?account.positions.map(p=>`${p.symbol} ${p.positionSide} ${p.positionAmt}`).join('；'):'无'):'未读取交易所持仓';
  const source=state.source;
  $('#demo-source').textContent=source.fresh?`采集正常 · 最近成功 ${new Date(source.last_poll).toLocaleString()}`:`信号尚未就绪：${source.error||source.status||'请检查只读监测后台'}`;
  const journal=state.journal;
  if(state.scope?.symbol_count)$('#demo-source').textContent+=`；候选合约 ${state.scope.symbol_count} 个；共用一个资金池`;
  $('#demo-capital').textContent=journal.capital_usdt===null?'尚未建立测试账本':`已核实策略资金 ${journal.capital_usdt??'未知'} USDT · 待核对订单 ${journal.pending_count??'未知'}`;
  const labels={idle:'未启动',starting:'正在核对',running:'测试跟随中',stopped:'已停止',error:'异常停止'};
  $('#demo-phase').textContent=labels[state.phase]||state.phase;
  if(state.running&&state.source_waiting)$('#demo-phase').textContent='等待采集恢复；保留保护单核对';
  $('#demo-phase').className='pill '+(active?'green':state.phase==='error'?'red':'subtle');
  const sourceAvailable=source.fresh||(source.watching&&['running','retrying'].includes(source.status));
  $('#demo-start').disabled=state.running||verifying||!state.connected||!state.policy||!sourceAvailable||!$('#demo-confirm').checked;
  $('#demo-pause').disabled=!active;$('#demo-stop').disabled=!state.running;$('#demo-flatten').disabled=!active||!journal.positions?.length;
  $('#demo-pause').textContent=state.entries_enabled?'暂停新开仓':'恢复新开仓';
  $('#demo-policy-state').textContent=state.policy?(journal.locked?'已锁定测试账本参数':'已保存测试参数'):'未保存';
  if(state.policy&&!hydrated){
    const p=state.policy;
    const values={...p,margin_stop_percent:Number(p.margin_loss_fraction)*100,deviation_percent:Number(p.max_deviation)*100,
      crypto_symbols:Object.keys(p.symbols).filter(s=>p.symbols[s]==='crypto').join(', '),equity_symbols:Object.keys(p.symbols).filter(s=>p.symbols[s]==='equity').join(', ')};
    values.traditional_symbols=Object.keys(p.symbols).filter(s=>p.symbols[s]==='traditional').join(', ');
    for(const [key,value] of Object.entries(values))if(form.elements[key])form.elements[key].value=value;
    hydrated=true;
  }
  for(const control of form.elements)control.disabled=state.running||verifying||journal.locked===true;
  const options=Object.keys(state.policy?.symbols||{}).map(symbol=>`<option>${escape(symbol)}</option>`).join('');
  if($('#rehearsal-symbol').innerHTML!==options)$('#rehearsal-symbol').innerHTML=options;
  document.querySelectorAll('[data-demo-action]').forEach(button=>{button.disabled=!active||(!state.entries_enabled&&button.dataset.demoAction.startsWith('OPEN'));});
  $('#demo-positions').innerHTML=journal.positions?.length?journal.positions.map(p=>`<tr><td>${escape(p.symbol)} / ${escape(p.side)}</td><td>${escape(p.qty)}</td><td>${escape(p.entry)}</td><td>${escape(p.leverage)}×</td><td>${escape(p.origin)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">没有本程序管理的 Demo 仓位</td></tr>';
  $('#demo-logs').innerHTML=state.logs.length?state.logs.map(log=>`<div class="log-row"><time>${escape(new Date(log.time).toLocaleTimeString())}</time><span class="pill ${log.level==='error'?'red':'subtle'}">${escape(log.origin||log.level)}</span><span>${escape(log.message)} ${escape(log.symbol||'')} ${escape(log.action||'')} ${escape(log.result||'')} ${escape(log.reason||'')} ${escape(log.price_check ? '价差 ' + Number(log.price_check.signed_percent).toFixed(3) + '%' : '')}</span></div>`).join(''):'<p class="small muted">尚未启动测试交易。</p>';
}
async function refresh(){
  if(busy)return;busy=true;
  try{state=await request('/api/demo-v2/state');render();$('#demo-connection').textContent='测试网后台已连接';$('#demo-connection').className='pill green';}
  catch(error){$('#demo-connection').textContent='测试网后台已断开';$('#demo-connection').className='pill red';$('#demo-error').textContent=error.message;}
  finally{busy=false;}
}
async function action(name,payload={}){
  try{await request('/api/demo-v2/'+name,payload);actionError='';await refresh();}
  catch(error){actionError=error.message;$('#demo-error').textContent=actionError;}
}
form.addEventListener('submit',event=>{event.preventDefault();try{void action('configure',policyValues());}catch(error){$('#demo-error').textContent=error.message;}});
$('#demo-confirm').addEventListener('change',render);
$('#demo-inspect').addEventListener('click',()=>action('inspect'));
$('#demo-verify').addEventListener('click',()=>action('verify-stop',{confirmation:'VERIFY DEMO STOP',max_wait:180}));
$('#demo-start').addEventListener('click',()=>action('start',{confirmation:'START DEMO'}));
$('#demo-pause').addEventListener('click',()=>action('pause',{paused:state.entries_enabled}));
$('#demo-stop').addEventListener('click',()=>action('stop'));
$('#demo-flatten').addEventListener('click',()=>action('flatten-owned',{confirmation:'CLOSE OWNED DEMO'}));
document.querySelectorAll('[data-demo-action]').forEach(button=>button.addEventListener('click',()=>action('rehearsal',{symbol:$('#rehearsal-symbol').value,action:button.dataset.demoAction})));
session().then(refresh).catch(error=>{$('#demo-error').textContent=error.message;});
setInterval(refresh,3000);
