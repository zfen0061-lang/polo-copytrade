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
  function record(raw){try{return JSON.parse(raw||'{}');}catch{return {};}}
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
    const connected=account.connected,live=account.environment==='production',readOnly=account.execution_allowed===false;
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
    $('#account-updated').textContent=a?text('账户最近成功更新：','Last successful account update: ')+new Date(a.updated).toLocaleString()+(accountRefresh.busy?text(' · 正在读取币安账户…',' · Reading Binance account…'):accountRefreshError?text(' · 刷新异常，稍后自动重试',' · Refresh failed; automatic retry pending'):account.watching?text(' · 跟随运行期间由后台更新',' · Updated by the following worker'):text(' · 页面打开时约每 10 秒自动刷新',' · Automatically refreshed about every 10 seconds while this page is open')):'';
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
      if(account.connected&&!account.watching)void accountRefresh.request();
    }catch(e){$('#account-error').textContent=e.message;}
  }
  function updateApp(state){
    app=state;
    const planned=app.traders.find(t=>record(t.execution_draft).status==='draft');
    draftCard.classList.toggle('hidden',!planned);
    if(planned){
      const draft=record(planned.execution_draft);
      draftCard.innerHTML=`<div class="section-head"><h2>${safe(planned.name)} · ${text('跟单资金草案','Strategy capital draft')}</h2><span class="pill subtle">${text('待启用 · 未划转资金','DRAFT · NO TRANSFER')}</span></div><p>${text('初始分配','Initial allocation')}: <strong>${n(draft.initial_capital_usdt)} USDT</strong> · ${text('使用本策略可用资金滚动复投，不再每次取一半。','Compound the allocated strategy pool; do not halve it on each entry.')}</p><p class="small muted">${text('平仓：只全平对应合约、方向的本程序仓位。加密货币最高10倍，股票类最高5倍。','Close only the matching bot-owned symbol and side. Crypto cap: 10x; equity cap: 5x.')}<br>${text('待完成：止损、亏损上限、股票杠杆规则、已有仓位归属及复投执行验证。当前草案不会触发下单。','Pending: stop, loss cap, equity leverage rule, existing-position ownership and verified compounding execution. This draft cannot send orders.')}</p>`;
    }
    const tracked=app.traders.find(t=>sourceMonitor(t).mode==='observe');
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
