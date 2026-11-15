export function previewStopRisk({capital,margin,leverage,stopPercent,stopUnit='price',riskPercent=2,drawdownPercent=10}) {
  const values=[capital,margin,leverage,stopPercent,riskPercent].map(Number);
  const [pool,stake,multiple,stop,risk]=values;
  const drawdown=drawdownPercent===''||drawdownPercent==null?null:Number(drawdownPercent);
  if(values.some(x=>!Number.isFinite(x)||x<=0)||stake>pool||!Number.isInteger(multiple)||multiple>10||stop>=100||risk>100||(drawdown!==null&&(!Number.isFinite(drawdown)||drawdown<=0||drawdown>100))||!['price','margin'].includes(stopUnit))throw Error('Enter valid positive amounts and percentages.');
  const priceStop=(stopUnit==='margin'?stop/multiple:stop)/100;
  const expectedLoss=stake*multiple*priceStop;
  return {priceStopPercent:priceStop*100,marginLossPercent:multiple*priceStop*100,
    notional:stake*multiple,expectedLoss,poolLossPercent:expectedLoss/pool*100,
    riskBudget:pool*risk/100,maxMarginForRisk:Math.min(pool,pool*risk/100/(multiple*priceStop)),
    drawdownLimit:drawdown===null?null:pool*drawdown/100,drawdownStopEquity:drawdown===null?null:pool*(1-drawdown/100)};
}

export function createAccountRefresher({load,onSuccess,onError,onChange=()=>{},clock=()=>Date.now(),interval=10000}) {
  let task=null,nextAt=0,failures=0;
  return {
    get busy(){return task!==null;},
    request(force=false){
      if(task)return task;
      if(!force&&clock()<nextAt)return Promise.resolve(null);
      task=Promise.resolve().then(load).then(result=>{
        failures=0;onSuccess(result);return result;
      }).catch(error=>{failures+=1;onError(error);return null;}).finally(()=>{
        nextAt=clock()+Math.min(60000,interval*2**failures);
        task=null;onChange();
      });
      onChange();
      return task;
    },
  };
}

export function createAccountUI({api,toast,language}) {
  const $=s=>document.querySelector(s);
  const text=(z,e)=>language()==='zh'?z:e;
  const safe=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=(x,d=2)=>Number(x||0).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
  let account=null,app=null,view='live';
  let previousSignal=null;
  let runtime=null;
  let accountRefreshError='';
  const accountRefresh=createAccountRefresher({
    load:()=>api('/api/live/refresh',{}),
    onSuccess:state=>{account=state;accountRefreshError='';},
    onError:error=>{accountRefreshError=text('账户自动刷新失败，将稍后重试：','Account refresh failed; retrying: ')+error.message;},
    onChange:()=>render(),
  });
  const signalCard=document.createElement('section');
  signalCard.id='signal-source-status';signalCard.className='card hidden';
  $('#view-live').prepend(signalCard);
  const draftCard=document.createElement('section');
  draftCard.id='strategy-draft-status';draftCard.className='card hidden';
  signalCard.after(draftCard);
  const runtimeCard=document.createElement('section');
  runtimeCard.id='monitor-runtime-status';runtimeCard.className='card';
  signalCard.before(runtimeCard);
  runtimeCard.addEventListener('click',async event=>{
    const button=event.target.closest('[data-retry-collector],[data-runtime-action]');if(!button)return;
    button.disabled=true;
    const operation=button.dataset.runtimeAction||'retry-observer';
    if(!['retry-observer','remember-account','forget-account','stop'].includes(operation))return;
    try{
      await api('/api/runtime/'+operation,{});
      const messages={
        'retry-observer':['正在重新检查公开采集；不会下单。','Rechecking public collection; no orders are sent.'],
        'remember-account':['当前连接已由 Windows 加密保存，重启后可自动重连。','Connection encrypted by Windows for automatic reconnection.'],
        'forget-account':['已删除保存的连接；本次连接继续，重启后需本机输入。','Saved connection removed. This session continues; reconnect locally after restart.'],
        'stop':['后台正在停止；下次可用持续监测入口重新打开。','Stopping the background monitor. Use the continuous launcher to start it again.'],
      };
      toast(text(...messages[operation]));
      if(operation!=='stop')await refresh();
    }
    catch(error){toast(error.message);}
    finally{button.disabled=false;}
  });
  const readinessNote=document.createElement('p');readinessNote.id='execution-readiness';readinessNote.className='callout small hidden';draftCard.after(readinessNote);
  function record(raw){try{return JSON.parse(raw||'{}');}catch{return {};}}
  const riskDialog=document.createElement('dialog');
  riskDialog.id='risk-preview-dialog';
  riskDialog.innerHTML=`<form id="risk-preview-form"><div class="dialog-head"><h2>${text('风险设置与试算','Risk settings and preview')}</h2><button type="button" class="ghost" data-risk-close>${text('关闭','Close')}</button></div><p class="callout small">${text('仅用于本浏览器的试算草案。保存不会修改后台实盘参数或启动交易。金额均为费用前估算，不代表止损成交保证。','Browser-only preview draft. Saving does not change live parameters or start trading. Estimates exclude fees and do not guarantee stop fills.')}</p><div class="form-grid"><label>${text('策略资金池 / USDT','Strategy pool / USDT')}<input name="capital" type="number" min="0.01" step="0.01" required></label><label>${text('每次投入保证金 / USDT','Margin per entry / USDT')}<input name="margin" type="number" min="0.01" step="0.01" required></label><label>${text('合约类别','Asset category')}<select name="asset"><option value="crypto">${text('加密货币：上限10倍','Crypto: cap 10x')}</option><option value="equity">${text('股票类合约：上限5倍','Equity perps: cap 5x')}</option></select></label><label>${text('杠杆 / 倍','Leverage')}<input name="leverage" type="number" min="1" max="10" step="1" required></label><label>${text('止损百分比的含义','Stop percentage means')}<select name="stopUnit"><option value="price">${text('价格不利变动 %','Adverse price move %')}</option><option value="margin">${text('保证金亏损 %（近似换算）','Margin loss % (approximate)')}</option></select></label><label>${text('止损数值 / %','Stop value / %')}<input name="stopPercent" type="number" min="0.01" max="99" step="0.01" required placeholder="${text('请填写试算值','Enter a preview value')}"></label><label>${text('每笔资金池风险预算 / %（试算）','Pool risk per trade / % (preview)')}<input name="riskPercent" type="number" min="0.01" max="100" step="0.01" required></label><label>${text('资金池最大回撤 / %（试算）','Pool drawdown / % (preview)')}<input name="drawdownPercent" type="number" min="0.01" max="100" step="0.01" placeholder="待确定 / Pending"></label></div><div id="risk-preview-output" class="callout small" aria-live="polite"></div><div class="dialog-actions"><button type="button" class="secondary" data-risk-close>${text('关闭','Close')}</button><button type="submit" class="primary">${text('仅保存试算草案','Save preview only')}</button></div></form>`;
  document.body.appendChild(riskDialog);
  const riskForm=riskDialog.querySelector('form');
  let activeRiskRevision='';
  let activeEquityLeverage=5;
  function riskValues(){const raw=Object.fromEntries(new FormData(riskForm));return raw;}
  function renderRiskPreview(){
    const raw=riskValues(),cap=raw.asset==='equity'?5:10;
    riskForm.elements.leverage.max=String(cap);
    const output=$('#risk-preview-output');
    try{
      if(Number(raw.leverage)>cap)throw Error(text('超过该类别杠杆上限','Asset leverage cap exceeded'));
      const result=previewStopRisk(raw);
      output.textContent=[
        text('名义仓位：','Notional: ')+n(result.notional)+' USDT · '+text('对应价格止损：','Price stop: ')+n(result.priceStopPercent)+'%',
        text('止损亏损估算：','Estimated stop loss: ')+n(result.expectedLoss)+' USDT · '+n(result.poolLossPercent)+text('% 的策略资金','% of pool'),
        text('按所填单笔风险预算，保证金最多约：','Maximum margin for the entered risk budget: ')+n(result.maxMarginForRisk)+' USDT',
        result.drawdownLimit===null?text('累计亏损/回撤上限尚未确定；本次仅计算单笔止损。','Cumulative loss/drawdown limit is unset; only the per-trade stop is calculated.'):
          text('所填回撤对应亏损：','Entered drawdown loss: ')+n(result.drawdownLimit)+' USDT · '+text('触发净值：','Stop equity: ')+n(result.drawdownStopEquity)+' USDT',
        text('以上未计手续费、资金费、滑点和最小下单量；自动执行尚未接入。','Excludes fees, funding, slippage and minimum order sizes; automatic execution is not wired.')
      ].join('\n');
      output.style.whiteSpace='pre-line';
      if(result.marginLossPercent>=100)output.textContent+='\n'+text('该止损距离对应至少100%的保证金亏损，强平可能先发生；不能把这个价格当作有效保护。','This distance implies at least 100% margin loss; liquidation may happen first. This stop price may not provide protection.');
      riskForm.querySelector('[type="submit"]').disabled=false;
    }catch(error){output.textContent=raw.stopPercent?error.message:text('填写止损数值后查看费用前的风险估算。','Enter a stop value to preview risk before costs.');riskForm.querySelector('[type="submit"]').disabled=true;}
  }
  riskForm.addEventListener('input',renderRiskPreview);
  riskForm.elements.asset.addEventListener('change',()=>{riskForm.elements.leverage.value=riskForm.elements.asset.value==='equity'?String(activeEquityLeverage):'10';renderRiskPreview();});
  riskForm.addEventListener('submit',event=>{event.preventDefault();try{const raw=riskValues();previewStopRisk(raw);localStorage.setItem('polo-risk-preview',JSON.stringify({...raw,policyRevision:activeRiskRevision}));toast(text('试算草案已保存在本浏览器，实盘配置未改变。','Preview saved in this browser. Live configuration unchanged.'));riskDialog.close();}catch(error){toast(error.message);}});
  riskDialog.addEventListener('click',event=>{if(event.target.closest('[data-risk-close]'))riskDialog.close();});
  draftCard.addEventListener('click',event=>{
    if(!event.target.closest('[data-open-risk]'))return;
    const planned=app?.traders.find(t=>record(t.execution_draft).status==='draft');
    const draft=record(planned?.execution_draft);
    let stored={};try{stored=record(localStorage.getItem('polo-risk-preview'));}catch{}
    const initial=draft.initial_capital_usdt||'60';
    activeRiskRevision=draft.risk_policy_revision_at||draft.margin_stop_updated_at||draft.updated_at||'initial';
    activeEquityLeverage=Number(draft.equity_leverage)||5;
    if(stored.policyRevision!==activeRiskRevision)stored={};
    const confirmed=draft.margin_stop_loss_fraction!=null?String(Number(draft.margin_stop_loss_fraction)*100):'';
    const values={capital:initial,margin:initial,asset:'crypto',leverage:'10',stopUnit:confirmed?'margin':'price',stopPercent:confirmed,riskPercent:confirmed||'2',drawdownPercent:'',...stored};
    for(const [key,value] of Object.entries(values))if(riskForm.elements[key])riskForm.elements[key].value=value;
    renderRiskPreview();riskDialog.showModal();
  });
  function sourceMonitor(trader){try{return JSON.parse(trader?.signal_monitor||'{}');}catch{return {};}}
  signalCard.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.signalAction==='open')document.querySelector('.nav-item[data-view="observability"]')?.click();
    if(button.dataset.signalAction==='toggle'){
      const trader=app?.traders.find(t=>t.id===button.dataset.trader);
      if(trader)try{await api(`/api/traders/${trader.id}/toggle`,{enabled:!trader.enabled});toast(text('信号追踪状态已更新','Signal observation updated'));}catch(e){toast(e.message);}
    }
  });
  function render(){
    if(!account)return;
    const supervised=runtime?.mode==='read_only_monitor';
    const healthy=supervised&&runtime.backend_healthy&&Date.now()-Date.parse(runtime.heartbeat)<15000;
    const remembered=runtime?.saved_connection===true;
    const recoveryNote=remembered?text('连接已由 Windows 当前用户加密保存，后台重启或登录后可自动重连。','Connection encrypted for this Windows user; reconnects after worker restart or login.'):text('连接暂存本次会话；可点“记住当前连接”启用加密恢复。','Connection is in session memory; choose Remember connection for encrypted recovery.');
    runtimeCard.innerHTML=`<div class="section-head"><h2>${text('后台运行状态','Background service')}</h2><span class="pill ${healthy?'green':'subtle'}">${healthy?text('守护运行中 · 只读监测','SUPERVISED · READ ONLY'):text('后台未受守护或状态过期','UNMANAGED OR STALE')}</span></div><p class="small muted">${supervised?text('后台异常退出后会自动重启；关闭网页不影响采集。','The supervisor restarts failed workers; closing this page does not stop collection.'):text('请使用 open-continuous-monitor.cmd 启动持续监测。','Use open-continuous-monitor.cmd for continuous monitoring.')}<br>${account.configured?text('账户密钥已在本次会话中；后台独立刷新账户。','Credentials are in this session; account reads run independently.'):text('账户尚未连接：双击 reconnect-readonly-account.cmd，在本机隐藏输入密钥。','Account disconnected: run reconnect-readonly-account.cmd and enter credentials locally.')}<br>${recoveryNote}<br>${text('允许息屏；接电且后台运行时防自动睡眠。关机、手动睡眠、合盖和断网仍会中断。当前不会自动交易。','Display may turn off. AC power and a running monitor prevent idle sleep. Power off, manual sleep, lid close and lost connectivity interrupt monitoring. Automatic trading is off.')}</p>${runtime?.error?`<p class="form-error">${safe(runtime.error)}</p>`:''}`;
    if(runtime?.components?.observer?.blocked){
      runtimeCard.insertAdjacentHTML('beforeend',`<p class="form-error">${safe(runtime.components.observer.blocked)}</p><button class="secondary" data-retry-collector>${text('重新检查采集','Recheck collector')}</button>`);
    }
    const actions=document.createElement('div');actions.className='button-row';
    actions.innerHTML=`<span class="pill ${remembered?'green':'subtle'}">${remembered?text('Windows 加密保存','WINDOWS ENCRYPTED'):text('仅本次会话','SESSION ONLY')}</span>${account.connected&&!remembered?`<button class="secondary" data-runtime-action="remember-account">${text('记住当前连接','Remember connection')}</button>`:''}${remembered?`<button class="ghost" data-runtime-action="forget-account">${text('不再记住连接','Forget saved connection')}</button>`:''}${supervised?`<button class="ghost danger" data-runtime-action="stop">${text('停止后台','Stop background monitor')}</button>`:''}`;
    runtimeCard.appendChild(actions);
    if(runtime?.credential_error){const warning=document.createElement('p');warning.className='form-error';warning.textContent=runtime.credential_error;runtimeCard.appendChild(warning);}
    const connected=account.connected,live=account.environment==='production',readOnly=account.execution_allowed===false;
    readinessNote.classList.toggle('hidden',!connected);
    if(connected){
      const checks=[];
      if(account.account?.hedge_mode)checks.push(text('双向持仓模式尚未适配','hedge mode is not yet supported'));
      if(account.account?.multi_assets)checks.push(text('多资产模式尚未适配','multi-assets mode is not yet supported'));
      if(account.account?.positions?.length)checks.push(text('已有仓位归属尚需核对','existing position ownership needs review'));
      readinessNote.textContent=text('实盘尚未就绪：','Live execution is not ready: ')+(checks.length?checks.join('；')+'。 ':'')+text('当前参数为草案；复投记账、按保证金比例止损及端到端验单尚未完成。','Parameters are drafts; compounding accounting, margin-based stops and end-to-end order validation remain incomplete.');
    }
    $('#account-environment').textContent=connected?(live?(readOnly?text('真实账户 · 只读','PRODUCTION · READ ONLY'):text('真实账户 / Production','PRODUCTION ACCOUNT')):text('交易所测试网','EXCHANGE TESTNET')):text('未连接','NOT CONNECTED');
    $('#account-environment').className='pill '+(connected?(live?'blue':'green'):'subtle');
    $('#account-empty').classList.toggle('hidden',connected);
    $('#real-metrics').classList.toggle('hidden',!connected);
    $('#account-error').textContent=accountRefreshError||account.error||'';
    $('#connect-account').disabled=account.watching;
    $('#refresh-account').disabled=!connected||accountRefresh.busy;
    $('#configure-live').disabled=readOnly||!connected||account.watching||!$('#live-trader-select').value;
    $('#pause-real').disabled=!account.watching;
    $('#stop-real').disabled=!account.watching;
    $('#live-trader-select').disabled=account.watching;
    $('#pause-real').textContent=account.entries_enabled?text('暂停新增开仓','Pause new entries'):text('恢复新增开仓','Resume new entries');
    $('#live-follow-status').textContent=account.watching?(account.entries_enabled?text('账户跟随运行中','FOLLOWING'):text('新增开仓已暂停','ENTRIES PAUSED')):text('未启动','NOT STARTED');
    $('#live-follow-status').className='pill '+(account.watching?'green':'subtle');
    const c=account.active_config;
    $('#live-parameters').textContent=c?text('本次会话：','Session: ')+`${c.budget} USDT · ${c.order_margin} USDT/entry · ${c.leverage}× · ${n(Number(c.max_deviation)*100)}% max deviation · ${n(Number(c.stop_loss_pct)*100)}% price stop`:'';
    const a=account.account;
    $('#real-metrics').innerHTML=a?[[text('钱包余额','Wallet balance'),a.wallet_balance],[text('账户权益','Account equity'),a.equity],[text('可用余额','Available'),a.available],[text('未实现盈亏','Unrealized P&L'),a.unrealized]].map(([label,value])=>`<div class="metric"><div class="metric-top">${safe(label)}</div><div class="metric-value">${n(value)}<small>USDT</small></div></div>`).join(''):'';
    $('#account-updated').textContent=a?text('账户最近成功更新：','Last successful account update: ')+new Date(a.updated).toLocaleString()+(accountRefresh.busy?text(' · 正在读取币安账户…',' · Reading Binance account…'):accountRefreshError?text(' · 刷新异常，稍后自动重试',' · Refresh failed; automatic retry pending'):account.account_polling?text(' · 后台约每 10 秒自动读取，无需保持网页打开',' · Background reads about every 10 seconds; page may close'):account.watching?text(' · 跟随运行期间由后台更新',' · Updated by the following worker'):text(' · 页面打开时约每 10 秒自动刷新',' · Automatically refreshed about every 10 seconds while this page is open')):'';
    $('#actual-positions').innerHTML=a?.positions?.length?a.positions.map(p=>`<tr><td><strong>${safe(p.symbol)}</strong> ${Number(p.positionAmt)>0?text('多','LONG'):text('空','SHORT')}</td><td>${n(Math.abs(Number(p.positionAmt)),6)}</td><td>${n(p.entryPrice,4)}</td><td>${n(p.markPrice,4)}</td><td class="${Number(p.unRealizedProfit)>=0?'positive':'negative'}">${n(p.unRealizedProfit)}</td><td>${n(p.liquidationPrice,4)}</td></tr>`).join(''):`<tr><td class="empty" colspan="6">${connected?text('账户当前没有仓位。','No open positions on the connected account.'):text('连接账户后显示实际仓位。','Connect to display actual account positions.')}</td></tr>`;
    $('#actual-orders').innerHTML=account.orders?.length?account.orders.map(j=>`<tr><td>${safe(j.id.slice(0,12))}</td><td>${safe(j.order?.symbol||'—')} ${safe(j.order?.side||'')}</td><td>${safe(j.order?.type||'—')}</td><td>${j.result?.executedQty?n(j.result.executedQty,6):'—'}</td><td>${j.result?.avgPrice?n(j.result.avgPrice,4):'—'}</td><td>${safe(j.state)}<span class="cell-sub">${safe(j.reason||j.result?.status||'')}</span></td></tr>`).join(''):`<tr><td class="empty" colspan="6">${text('没有账户执行记录；模拟订单在模拟实验室。','No account execution records. Paper orders are in the paper lab.')}</td></tr>`;
    if(view==='live'){
      $('#mode-badge').textContent=connected?(live?(account.watching?text('实盘跟随已启用','LIVE FOLLOWING'):text('真实账户 · 跟随未启动','REAL ACCOUNT · IDLE')):text('交易所测试网','EXCHANGE TESTNET')):text('账户未连接','ACCOUNT DISCONNECTED');
      $('#mode-badge').className='pill '+(connected&&live?'blue':'subtle');
      $('#notice-text').textContent=live?text('账户工作台与模拟实验室独立。真实账户连接后显示实际资金；主动启动跟随后，操作会向币安发送真实订单。','The account workspace is separate from the paper lab. A production connection displays real funds; explicitly starting following will send real Binance orders.'):text('当前选择交易所测试网，与模拟实验室不同；订单提交到测试网，不操作真实资金。','Exchange testnet is selected. Orders are sent to the testnet, independently of the local paper lab.');
      if(readOnly){
        $('#mode-badge').textContent=text(live?'真实账户 · 只读模式':'测试网 · 只读模式',live?'PRODUCTION · READ ONLY':'TESTNET · READ ONLY');
        $('#notice-text').textContent=text('当前仅验证账户余额和持仓，账户下单入口已关闭。','This session reads account balances and positions only. Account order execution is disabled.');
      }
    }else{
      $('#mode-badge').textContent=text('模拟实验室','PAPER LAB');$('#mode-badge').className='pill green';
    }
  }
  async function refresh(){
    try{
      account=await api('/api/live/state');render();
      // Keep source-log rendering responsive while account reads are in flight.
      if(account.connected&&!account.watching&&!account.account_polling)void accountRefresh.request();
      try{runtime=await api('/api/runtime/state');render();}catch{runtime=null;render();}
    }catch(e){$('#account-error').textContent=e.message;}
  }
  function updateApp(state){
    app=state;
    const planned=app.traders.find(t=>record(t.execution_draft).status==='draft');
    draftCard.classList.toggle('hidden',!planned);
    if(planned){
      const draft=record(planned.execution_draft);
      draftCard.innerHTML=`<div class="section-head"><h2>${safe(planned.name)} · ${text('跟单资金草案','Strategy capital draft')}</h2><span class="pill subtle">${text('待启用 · 未划转资金','DRAFT · NO TRANSFER')}</span></div><p>${text('初始分配','Initial allocation')}: <strong>${n(draft.initial_capital_usdt)} USDT</strong> · ${text('使用本策略可用资金滚动复投，不再每次取一半。','Compound the allocated strategy pool; do not halve it on each entry.')}</p><p class="small muted">${text('平仓：只全平对应合约、方向的本程序仓位。加密货币最高10倍，股票类最高5倍。','Close only the matching bot-owned symbol and side. Crypto cap: 10x; equity cap: 5x.')}<br>${text('待完成：累计亏损规则、账户模式适配、已有仓位归属及复投/止损执行验证。当前草案不会触发下单。','Pending: cumulative loss rule, account-mode compatibility, existing-position ownership and verified compounding/stop execution. This draft cannot send orders.')}</p>`;
    }
    const tracked=app.traders.find(t=>sourceMonitor(t).mode==='observe');
    if(planned){
      const policy=record(planned.execution_draft);
      if(policy.margin_stop_loss_fraction!=null){
        const stopNote=document.createElement('p');stopNote.id='confirmed-margin-stop';stopNote.className='small muted';
        const percentage=Number(policy.margin_stop_loss_fraction)*100;
        const stockLeverage=Number(policy.equity_leverage)||5;
        stopNote.textContent=text('已记录的单笔保证金止损目标：','Recorded per-trade margin stop target: ')+n(percentage)+'% · '+text('10倍约对应价格','At 10x, approximate price distance ')+n(percentage/10)+'% · '+text('股票类','equity ')+stockLeverage+text('倍约','x ')+n(percentage/stockLeverage)+'% · '+text('费用前换算，实际亏损不保证封顶。','before costs; actual loss is not guaranteed to be capped.');
        draftCard.appendChild(stopNote);
      }
      if(policy.equity_leverage_policy==='fixed'){const equityNote=document.createElement('p');equityNote.id='confirmed-equity-leverage';equityNote.className='small muted';equityNote.textContent=text('已记录：股票类固定','Recorded: equity leverage fixed at ')+policy.equity_leverage+text('倍；仍为待启用草案。','x; remains an inactive draft.');draftCard.appendChild(equityNote);}
      const open=document.createElement('button');open.type='button';open.className='secondary';open.dataset.openRisk='true';open.textContent=text('风险设置 / 试算','Risk settings / preview');draftCard.appendChild(open);
    }
    signalCard.classList.toggle('hidden',!tracked);
    if(tracked){
      const m=sourceMonitor(tracked),alive=!!m.owner&&Date.now()/1000-m.heartbeat<180;
      if(previousSignal?.owner===m.owner&&Number(m.new_count)>previousSignal.count){
        toast(tracked.name+text('：发现新的公开操作，已记录，未下单。',': new public operation recorded; no order sent.'));
      }
      previousSignal={owner:m.owner,count:Number(m.new_count)||0};
      const labels={starting:text('正在连接公开页面','Connecting'),running:text('真实信号追踪中','Observing public operations'),paused:text('已暂停信号追踪','Observation paused'),retrying:text('采集重试中','Retrying'),error:text('采集异常，已停止','Collection stopped with error'),stopped:text('信号追踪已停止','Observation stopped')};
      const status=alive?(labels[m.status]||m.status):text('信号追踪已停止，需要重启采集','Observation stopped; restart the collector');
      signalCard.innerHTML=`<div class="section-head"><div><span class="eyebrow">PUBLIC SIGNALS / OBSERVE ONLY</span><h2>${safe(tracked.name)} · ${safe(status)}</h2></div><span class="pill blue">${text('已锁定 · 不下单','LOCKED · NO ORDERS')}</span></div><p class="small muted">${text('每轮采集完成后等待 15 秒；实际发现时间还受页面加载与平台公开延迟影响。','Waits 15 seconds after each poll; page loading and platform publication add delay.')}<br>${text('历史基线','Baseline')}: ${n(m.baseline_count,0)} · ${text('新增操作','New operations')}: ${n(m.new_count,0)} · ${text('最近成功采集','Last successful poll')}: ${m.last_poll?safe(new Date(m.last_poll).toLocaleString()):'—'}</p>${m.last_error?`<p class="form-error">${safe(m.last_error)}</p>`:''}<div class="button-row"><button class="primary" data-signal-action="open">${text('查看真实信号记录','View public signals')}</button><button class="secondary" data-signal-action="toggle" data-trader="${safe(tracked.id)}" ${alive?'':'disabled'}>${tracked.enabled?text('暂停追踪','Pause'):text('恢复追踪','Resume')}</button></div>`;
      const guard=record(tracked.runtime_guard),awake=!!guard.owner&&Date.now()/1000-guard.heartbeat<90&&guard.status==='active';
      const guardText=awake?text('接电防自动睡眠已开启，允许息屏；不能阻止手动睡眠、合盖、断电或系统重启。','AC idle-sleep prevention is active; display may turn off. Manual sleep, lid close, power loss and restart are not prevented.'):guard.status==='waiting_for_ac'?text('防自动睡眠等待接电；当前电池模式不会保持唤醒。','Idle-sleep guard is waiting for AC power.'):text('防自动睡眠未运行；睡眠、休眠或重启会中断采集。','Idle-sleep guard is inactive; sleep, hibernation or restart interrupts collection.');
      const guardNote=document.createElement('p');guardNote.id='runtime-guard-status';guardNote.className='small muted';guardNote.textContent=guardText;signalCard.appendChild(guardNote);
    }
    const select=$('#live-trader-select'),selected=account?.watching?account.trader_id:select.value;
    select.innerHTML='<option value="">'+text('请选择公开数据源交易员','Choose a public-source trader')+'</option>'+app.traders.filter(t=>t.source==='binance_public'&&t.authorized).map(t=>`<option value="${safe(t.id)}">${safe(t.name)}</option>`).join('');
    select.value=app.traders.some(t=>t.id===selected)?selected:'';
    render();
  }
  async function action(path,payload={}){try{account=await api(path,payload);render();}catch(e){toast(e.message);await refresh();}}
  $('#connect-account').addEventListener('click',()=>action('/api/live/connect'));
  $('#refresh-account').addEventListener('click',()=>{if(account?.connected)void accountRefresh.request(true);});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void refresh();});
  $('#show-connect-help').addEventListener('click',()=>$('#connect-guide').showModal());
  $('#close-connect-guide').addEventListener('click',()=>$('#connect-guide').close());
  $('#pause-real').addEventListener('click',()=>action('/api/live/pause',{paused:account.entries_enabled}));
  $('#stop-real').addEventListener('click',()=>action('/api/live/stop'));
  $('#live-trader-select').addEventListener('change',render);
  $('#configure-live').addEventListener('click',()=>{
    $('#live-config-form').reset();$('#live-form-error').textContent='';
    $('#real-mode-warning').textContent=account.environment==='production'?text('当前连接真实账户。本表为空的资金参数必须由你填写，提交会启动真实交易跟随。','A production account is connected. Fill your own capital parameters. Submitting starts real-order following.'):text('当前连接交易所测试网。填写参数后可验证真实API的下单与止损流程。','Exchange testnet connected. Configure parameters to validate order and stop APIs.');
    $('#live-config-dialog').showModal();
  });
  ['close-live-config','cancel-live-config'].forEach(id=>$('#'+id).addEventListener('click',()=>$('#live-config-dialog').close()));
  $('#live-config-form').addEventListener('submit',async e=>{
    e.preventDefault();const f=Object.fromEntries(new FormData(e.currentTarget)),c={};
    ['budget','order_margin','max_loss'].forEach(k=>c[k]=f[k]);
    ['leverage','max_signal_age','poll_seconds','utc_offset_minutes'].forEach(k=>c[k]=Number(f[k]));
    ['max_deviation','stop_loss_pct','close_fraction'].forEach(k=>c[k]=String(Number(f[k])/100));
    c.symbols=f.symbols.split(',').map(s=>s.trim().toUpperCase()).filter(Boolean);c.fee_rate='0';
    try{account=await api('/api/live/start',{trader_id:$('#live-trader-select').value,config:c});$('#live-config-dialog').close();render();toast(text('账户跟随会话正在核对账户和数据源，请观察状态与日志。','The account session is verifying the account and source. Watch status and logs.'));}
    catch(error){$('#live-form-error').textContent=error.message;}
  });
  return {refresh,updateApp,setView(v){view=v;render();}};
}
