export function createAccountUI({api,toast,language}) {
  const $=s=>document.querySelector(s);
  const text=(z,e)=>language()==='zh'?z:e;
  const safe=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=(x,d=2)=>Number(x||0).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
  let account=null,app=null,view='live';
  function render(){
    if(!account)return;
    const connected=account.connected,live=account.environment==='production';
    $('#account-environment').textContent=connected?(live?text('真实账户 / Production','PRODUCTION ACCOUNT'):text('交易所测试网','EXCHANGE TESTNET')):text('未连接','NOT CONNECTED');
    $('#account-environment').className='pill '+(connected?(live?'blue':'green'):'subtle');
    $('#account-empty').classList.toggle('hidden',connected);
    $('#real-metrics').classList.toggle('hidden',!connected);
    $('#account-error').textContent=account.error||'';
    $('#connect-account').disabled=account.watching;
    $('#refresh-account').disabled=!connected;
    $('#configure-live').disabled=!connected||account.watching||!$('#live-trader-select').value;
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
    $('#account-updated').textContent=a?text('账户快照更新于 ','Account snapshot at ')+new Date(a.updated).toLocaleString()+text('；启动跟随后约每5秒及操作检查后刷新。','; refreshed around every 5 seconds and after signal checks while following.') :'';
    $('#actual-positions').innerHTML=a?.positions?.length?a.positions.map(p=>`<tr><td><strong>${safe(p.symbol)}</strong> ${Number(p.positionAmt)>0?text('多','LONG'):text('空','SHORT')}</td><td>${n(Math.abs(Number(p.positionAmt)),6)}</td><td>${n(p.entryPrice,4)}</td><td>${n(p.markPrice,4)}</td><td class="${Number(p.unRealizedProfit)>=0?'positive':'negative'}">${n(p.unRealizedProfit)}</td><td>${n(p.liquidationPrice,4)}</td></tr>`).join(''):`<tr><td class="empty" colspan="6">${connected?text('账户当前没有仓位。','No open positions on the connected account.'):text('连接账户后显示实际仓位。','Connect to display actual account positions.')}</td></tr>`;
    $('#actual-orders').innerHTML=account.orders?.length?account.orders.map(j=>`<tr><td>${safe(j.id.slice(0,12))}</td><td>${safe(j.order?.symbol||'—')} ${safe(j.order?.side||'')}</td><td>${safe(j.order?.type||'—')}</td><td>${j.result?.executedQty?n(j.result.executedQty,6):'—'}</td><td>${j.result?.avgPrice?n(j.result.avgPrice,4):'—'}</td><td>${safe(j.state)}<span class="cell-sub">${safe(j.reason||j.result?.status||'')}</span></td></tr>`).join(''):`<tr><td class="empty" colspan="6">${text('没有账户执行记录；模拟订单在模拟实验室。','No account execution records. Paper orders are in the paper lab.')}</td></tr>`;
    if(view==='live'){
      $('#mode-badge').textContent=connected?(live?(account.watching?text('实盘跟随已启用','LIVE FOLLOWING'):text('真实账户 · 跟随未启动','REAL ACCOUNT · IDLE')):text('交易所测试网','EXCHANGE TESTNET')):text('账户未连接','ACCOUNT DISCONNECTED');
      $('#mode-badge').className='pill '+(connected&&live?'blue':'subtle');
      $('#notice-text').textContent=live?text('账户工作台与模拟实验室独立。真实账户连接后显示实际资金；主动启动跟随后，操作会向币安发送真实订单。','The account workspace is separate from the paper lab. A production connection displays real funds; explicitly starting following will send real Binance orders.'):text('当前选择交易所测试网，与模拟实验室不同；订单提交到测试网，不操作真实资金。','Exchange testnet is selected. Orders are sent to the testnet, independently of the local paper lab.');
    }else{
      $('#mode-badge').textContent=text('模拟实验室','PAPER LAB');$('#mode-badge').className='pill green';
    }
  }
  async function refresh(){
    try{account=await api('/api/live/state');render();}catch(e){$('#account-error').textContent=e.message;}
  }
  function updateApp(state){
    app=state;
    const select=$('#live-trader-select'),selected=account?.watching?account.trader_id:select.value;
    select.innerHTML='<option value="">'+text('请选择公开数据源交易员','Choose a public-source trader')+'</option>'+app.traders.filter(t=>t.source==='binance_public'&&t.authorized).map(t=>`<option value="${safe(t.id)}">${safe(t.name)}</option>`).join('');
    select.value=app.traders.some(t=>t.id===selected)?selected:'';
    render();
  }
  async function action(path,payload={}){try{account=await api(path,payload);render();}catch(e){toast(e.message);await refresh();}}
  $('#connect-account').addEventListener('click',()=>action('/api/live/connect'));
  $('#refresh-account').addEventListener('click',()=>action('/api/live/refresh'));
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
