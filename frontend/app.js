import { createAccountUI } from './live-ui.js';
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const escapeHtml = (x) => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const zh = new Map($$('[data-i18n]').map(e => [e.dataset.i18n, e.innerHTML]));
const en = {
 accountWorkspace:'Account workspace',paperLab:'Paper lab',accountConnection:'Binance account connection',accountIntro:'Only balances and positions returned by the account API appear here. Connecting does not start trading.',connectAccount:'Verify local account connection',refreshAccount:'Refresh account',connectGuide:'How to enter credentials',yourCapital:'Connect your own account',accountEmpty:'Not connected. Launch account mode in your local terminal. Keys do not pass through chat or a browser form.',accountFollow:'Account auto-follow',oneLiveTrader:'This version follows one trader per account. Use one-way positions, isolated margin and single-asset USD-M Futures; do not mix manual trades.',choosePublicTrader:'Select an authorized public-source trader',configureReal:'Configure account parameters',pauseReal:'Pause new entries',stopReal:'Stop following',pauseRealNote:'Pausing entries keeps following closes. Stopping the process or session stops reading signals; already confirmed exchange stops remain.',realCodeStatus:'The execution adapter is integrated, but online Binance verification has not been completed in this environment. Validate on exchange testnet before real funds.',actualPositions:'Actual account positions',liquidation:'Estimated liquidation price',accountOrders:'Account execution records',exchangeConfirmed:'Recorded from actual order responses',connectStep1:'Press Ctrl+C in the old VS Code terminal to stop the previous server.',connectStep2:'Run python -m backend.connect or double-click connect-account.cmd.',connectStep3:'Choose production or testnet locally and enter the matching Key and Secret. Input is hidden and not saved to files.',connectStep4:'Open the dashboard, verify the local account connection and inspect environment, balance and positions before configuring execution.',credentialScope:'Use a dedicated IP-restricted key with read and Futures trading permissions, without withdrawal permission. Keys are not committed to GitHub. Re-enter them after the server exits or inject them with your own service manager.',realBudget:'Allocation limit · USDT',realMargin:'Margin per opening · USDT',realStop:'Exchange stop · price movement %',realLoss:'Dedicated-account loss budget · USDT',realStartNote:'Only newly observed operations are followed. Hidden existing positions are not copied. Configure matching leverage and isolated margin in Binance first. Existing unrelated positions or orders block startup.',startAccountFollow:'Start account following with these rules',
 workspace:'WORKSPACE',overview:'Overview',traders:'Traders',observability:'Signals & latency',settings:'Runtime & setup',
 localApp:'Running locally',localDesc:'Data stays on this computer.<br>Following stops with the server.',paperOnly:'PAPER ONLY',
 addTrader:'Add trader',notice:'The paper lab uses synthetic demo or public signals for local accounting, separately from the account workspace and real funds.',
 equity:'Paper account equity',recordedStart:'Recorded start',now:'Now',simulatedFills:'Quote-based paper fills · configured fees included',noFunding:'No depth or funding simulation',
 currentTrader:'Selected trader',parameters:'Parameters',switchNote:'Changing the selected trader does not transfer funds, close positions or pause other traders.',
 positions:'Open paper positions',stopsNote:'Local paper stops require a running process and updated quotes.',closeSelected:'Close selected trader’s paper positions',
 trader:'Trader',contract:'Contract / side',quantity:'Quantity',entry:'Entry',mark:'Paper exit quote',stop:'Stop price',unrealized:'Unrealized P&L',
 demoToolbar:'DEMO TOOLS',demoEvent:'Generate demo signal',testDeviation:'Test 3% entry rejection',recentOrders:'Recent paper orders',paperLedger:'Isolated paper ledger',
 time:'Time',type:'Type',fillPrice:'Paper fill price',fee:'Fee',realized:'Realized P&L',medianLatency:'Observed delay · median',p95Latency:'Observed delay · P95',
 latencyNote:'Observed delay = first-seen time minus source-labelled time. Results below use the selected trader only. This is not an independent measurement of platform latency.',
 signalLog:'Operation signals',exportCsv:'Export CSV',source:'Source',sourceTime:'Source-labelled time',firstSeen:'First seen',operation:'Operation',sourcePrice:'Source fill price',quote:'Decision quote',deviation:'Adverse deviation',result:'Result / reason',activity:'Activity log',
 executionMode:'Execution readiness',localBackend:'Local frontend, backend & persistent ledger',available:'Available',paperStops:'Paper orders & local paper stops',publicFeed:'Public operations collector (optional)',requiresSetup:'Requires setup & access check',liveTrading:'Account execution & exchange stops',notConnected:'Online verification pending',
 noKeys:'Keys are entered in the local terminal and kept in server-process memory. The separate account workspace connects production or exchange testnet. Complete online verification before production use.',liveBoundary:'Live integration boundary',
 dataProject:'Configuration & project',configExportNote:'Export trader settings without credentials, account funds or identity data. Review trader names and URLs before sharing.',exportConfig:'Export config JSON',runningBoundary:'Runtime boundaries',localOnly:'Bound to 127.0.0.1. Not a public multi-user service.',noCapacityBypass:'Does not bypass official copy capacity or reveal hidden positions.',publicDelay:'Public feed latency and completeness are not guaranteed.',paperRisk:'Paper results do not prove real fills or profitability.',footer:'Observe signals. Validate rules. Then consider execution.',
 demoDefaults:'Initial amounts and leverage are demonstration settings, not live-trading recommendations. Each trader is configured separately.',name:'Trader name',dataSource:'Signal source',portfolioUrl:'Binance lead portfolio URL',budget:'Paper budget · USDT',orderMargin:'Margin per opening · USDT',leverage:'Fixed leverage · ×',maxDeviation:'Max adverse entry deviation · %',stopPct:'Paper stop · price movement %',closeFraction:'Reduction on each close signal · %',maxLoss:'Paper loss budget · USDT',maxAge:'Entry signal expiry · seconds',poll:'Collection interval · seconds',feeRate:'Paper fee per side · %',symbols:'Allowed contracts · comma-separated',timezone:'Verified timezone of source timestamps',authorization:'Before public collection, I have verified my right to access and automatically retrieve this data. Not needed for demo mode.',closeRuleNote:'The reduction fraction is your own rule, not the source trader’s actual percentage. Pausing does not close existing paper positions.',cancel:'Cancel',save:'Save configuration',liveInfoText:'The paper lab remains local simulation. The separate account workspace connects production or exchange testnet and, after explicit start, sends orders and verifies exchange stops. This release uses account polling and has not completed online integration tests in this environment. Validate source access, latency, recovery and all trade rules on testnet first.',liveInfoExtra:'GitHub stores the source code. GitHub Pages will not run this Python backend. Never commit credentials or expose the local service publicly.'
};
let language = localStorage.getItem('cts-language') || 'zh';
let selected = localStorage.getItem('cts-trader') || 'aoying';
let view = 'live';
let state = null;
let csrf = '';
let editing = null;
let busy = false;
let toastTimer;
const t = (z,e) => language === 'zh' ? z : e;
const num = (x, digits=2) => Number(x || 0).toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {minimumFractionDigits:digits,maximumFractionDigits:digits});
const pct = (x) => `${num(Number(x)*100,2)}%`;
const shortTime = (s) => s ? new Date(s).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
const fullTime = (s) => s ? new Date(s).toLocaleString([], {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '—';
const action = (s) => ({OPEN_LONG:t('开多','Open long'),OPEN_SHORT:t('开空','Open short'),CLOSE_LONG:t('平多','Close long'),CLOSE_SHORT:t('平空','Close short')}[s] || s);
const sideLabel = (s) => s === 'LONG' ? t('多','LONG') : t('空','SHORT');
const badge = (label, color='subtle') => `<span class="pill ${color}">${escapeHtml(label)}</span>`;
const pnlClass = (x) => Number(x) >= 0 ? 'positive' : 'negative';
const traderName = (id) => state?.traders.find(x => x.id === id)?.name || id;
const currentTrader = () => state?.traders.find(x => x.id === selected);
const accountUI = createAccountUI({api,toast,language:()=>language});

function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 6500);
}

async function session() {
  const response = await fetch('/api/session');
  if (!response.ok) throw new Error(t('本地服务未连接','Local service unavailable'));
  csrf = (await response.json()).csrf_token;
}

async function api(path, payload, retry=true) {
  const response = await fetch(path, payload === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
  if (response.status === 403 && payload !== undefined && retry) {
    await session();
    return api(path,payload,false);
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
  return result;
}

function setLanguage() {
  document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en';
  $$('[data-i18n]').forEach(e => e.innerHTML = language === 'zh' ? zh.get(e.dataset.i18n) : (en[e.dataset.i18n] || zh.get(e.dataset.i18n)));
  $('#language').textContent = language === 'zh' ? 'EN' : '中文';
  setView(view);
  if (state) render();
}

function setView(next) {
  view = next;
  $$('.view').forEach(e => e.classList.toggle('hidden',e.id !== `view-${view}`));
  $$('.nav-item').forEach(e => e.classList.toggle('active',e.dataset.view === view));
  const titles = {
    live:[t('Polo，连接你的交易账户。','Polo. Your account, your rules.'),t('账户资金、真实执行与模拟研究，分别管理。','Separate account funds, execution and paper research.')],
    overview:[t('让每次跟随，都有规则。','Give every follow a clear rule.'),t('统一管理交易员、跟随参数与模拟订单。','One workspace for traders, rules and paper orders.')],
    traders:[t('选择交易员，独立配置。','Different traders. Separate rules.'),t('添加带单主页，为每位交易员保存独立的预算和规则。','Add portfolio URLs and configure each trader independently.')],
    observability:[t('每一条信号，都可追溯。','A clear trail for every signal.'),t('所选交易员的来源时间、首次发现、价格偏离和执行原因。','Source time, first seen, price deviation and execution decisions.')],
    settings:[t('明确状态，再接入交易。','Know what is connected.'),t('查看实际能力、配置导出与实盘接入边界。','Runtime capabilities, configuration exports and live integration boundaries.')]
  };
  $('#page-title').textContent = titles[view][0];
  $('#page-description').textContent = titles[view][1];
  $('#breadcrumb').textContent = ({live:'Account workspace',overview:'Paper lab',traders:'Traders',observability:'Signals & latency',settings:'Runtime & setup'})[view];
  accountUI.setView(view);
}

function empty(columns, text) { return `<tr><td class="empty" colspan="${columns}">${escapeHtml(text)}</td></tr>`; }

function signalMonitor(trader) {
  try { return JSON.parse(trader?.signal_monitor || '{}'); } catch { return {}; }
}

function renderSignalObservation(trader,events) {
  const monitor=signalMonitor(trader);
  if(monitor.mode==='observe') {
    const labels={starting:t('正在连接','CONNECTING'),running:t('真实信号追踪中','OBSERVING'),paused:t('已暂停','PAUSED'),retrying:t('连接重试中','RETRYING'),error:t('采集异常','ERROR'),stopped:t('已停止','STOPPED')};
    $('#trader-detail').innerHTML=`<div class="trader-identity"><span class="avatar">${escapeHtml(trader.name.slice(0,1))}</span><div><strong>${escapeHtml(trader.name)}</strong>${badge(t('公开信号 · 仅观察','PUBLIC · OBSERVE ONLY'),'blue')} ${badge(labels[monitor.status]||monitor.status,'subtle')}</div></div><p class="small muted">${t('已锁定此交易员。历史记录作为基线；新操作仅记录，不创建订单。','Locked to this trader. Historical baseline and new observations never create orders.')}</p>`;
    $('#toggle-trader').textContent=trader.enabled?t('暂停信号追踪','Pause signals'):t('恢复信号追踪','Resume signals');
    $('#toggle-trader').disabled=!monitor.owner||Date.now()/1000-monitor.heartbeat>180;
    $('#edit-trader').disabled=true;
  } else {
    $('#toggle-trader').disabled=false;
  }
  for(const card of $('#trader-cards').children) {
    const id=card.querySelector('.select-trader')?.dataset.id;
    const item=state.traders.find(x=>x.id===id);
    const m=signalMonitor(item);
    if(m.mode==='observe') {
      card.querySelector('.edit-card').disabled=true;
      card.querySelector('.trader-rules').innerHTML=`<p class="small muted">${t('真实公开信号 · 仅观察，不创建订单','Real public signals · observation only')}<br>${t('历史基线','Baseline')}: ${num(m.baseline_count,0)} · ${t('新操作','New')}: ${num(m.new_count,0)}<br>${t('最近采集','Last poll')}: ${m.last_poll?fullTime(m.last_poll):'—'}</p>`;
    }
  }
  Array.from($('#events-body').children).forEach((row,index)=>{
    const event=events[index];
    if(!event||row.children.length!==8)return;
    if(event.source_quantity!=null) {
      const info=document.createElement('span');info.className='cell-sub';
      info.textContent=t('成交数量 ','Filled quantity ')+num(event.source_quantity,6)+t(' · 杠杆未公开',' · Leverage unavailable');
      row.children[3].appendChild(info);
    }
    if(event.quote_price==null)row.children[5].textContent='—';
    if(event.deviation==null)row.children[6].textContent='—';
    if(event.status==='observed')row.children[7].querySelector('.pill').textContent=t('已观察 · 未下单','OBSERVED · NO ORDER');
  });
}

function chart() {
  const values = state.equity.map(x => Number(x.value));
  if (!values.length) values.push(Number(state.metrics.equity),Number(state.metrics.equity));
  if (values.length === 1) values.unshift(values[0]);
  const low = Math.min(...values), high = Math.max(...values);
  const range = Math.max(high-low,1);
  const points = values.map((v,i) => [i/(values.length-1)*660,130-(v-low)/range*100]);
  const line = points.map(([x,y],i) => `${i?'L':'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  $('#chart-line').setAttribute('d',line);
  $('#chart-area').setAttribute('d',`${line} L660,160 L0,160 Z`);
}

function render() {
  if (!state.traders.some(x => x.id === selected)) selected=state.traders[0]?.id;
  const tr=currentTrader();
  const active=state.traders.filter(x=>x.enabled).length;
  const metrics=[
    [t('运行中的交易员','Running traders'),`${active}<small>/ ${state.traders.length}</small>`,t('独立参数 · 独立模拟仓位','Separate rules and paper positions'),'◎'],
    [t('已实现净盈亏','Realized net P&L'),num(state.metrics.realized_net),t('已扣模拟手续费','Configured paper fees deducted'),'↗'],
    [t('未实现盈亏','Unrealized P&L'),num(state.metrics.unrealized),t('按最后已知模拟报价','Based on last paper quotes'),'⌁'],
    [t('累计模拟手续费','Paper fees paid'),`${num(state.metrics.fees)}<small>USDT</small>`,t('资金费未纳入','Funding fees excluded'),'≋']
  ];
  $('#metrics').innerHTML=metrics.map(([label,value,foot,icon],i)=>`<div class="metric"><div class="metric-top">${escapeHtml(label)}<span class="metric-icon">${icon}</span></div><div class="metric-value ${i===1?pnlClass(state.metrics.realized_net):i===2?pnlClass(state.metrics.unrealized):''}">${value}</div><div class="metric-foot">${escapeHtml(foot)}</div></div>`).join('');
  $('#equity-value').innerHTML=`${num(state.metrics.equity)}<span>USDT</span>`;
  const change=Number(state.metrics.equity)-Number(state.metrics.balance);
  $('#equity-change').className=`small ${pnlClass(change)}`;
  $('#equity-change').textContent=`${change>=0?'+':''}${num(change)} USDT · ${t('相对模拟初始资金','vs. initial paper capital')}`;
  const select=$('#trader-select');
  const options=state.traders.map(x=>`<option value="${escapeHtml(x.id)}">${escapeHtml(x.name)} · ${x.source==='demo'?t('演示','DEMO'):t('公开源','PUBLIC')}</option>`).join('');
  if(select.innerHTML!==options) select.innerHTML=options;
  select.value=selected;
  if(tr){
    const c=tr.config;
    $('#trader-detail').innerHTML=`<div class="trader-identity"><span class="avatar">${escapeHtml(tr.name.slice(0,1))}</span><div><strong>${escapeHtml(tr.name)}</strong>${badge(tr.source==='demo'?t('合成演示数据','SYNTHETIC DEMO'):t('公开源 → 模拟执行','PUBLIC → PAPER'),tr.source==='demo'?'subtle':'blue')} ${badge(tr.enabled?t('运行中','RUNNING'):t('已暂停','PAUSED'),tr.enabled?'green':'subtle')}</div></div><div class="trader-rules"><div class="rule"><span>${t('每笔保证金','Margin per entry')}</span><strong>${num(c.order_margin)} <small>USDT</small></strong></div><div class="rule"><span>${t('最大不利跟随价差','Max entry deviation')}</span><strong>${pct(c.max_deviation)}</strong></div><div class="rule"><span>${t('杠杆 / 价格止损','Leverage / price stop')}</span><strong>${c.leverage}× <small>/ ${pct(c.stop_loss_pct)}</small></strong></div><div class="rule"><span>${t('每次平仓信号减仓','Reduction per close signal')}</span><strong>${pct(c.close_fraction)}</strong></div></div>`;
    $('#toggle-trader').textContent=tr.enabled?t('暂停该交易员','Pause trader'):t('启动模拟跟随','Start paper following');
    $('#edit-trader').disabled=tr.enabled;
    $('#demo-event').disabled=tr.source!=='demo'||!tr.enabled;
    $('#demo-reject').disabled=tr.source!=='demo'||!tr.enabled;
    $('#close-all').disabled=!state.positions.some(p=>p.trader_id===selected);
  }
  $('#global-pause').textContent=state.paused?t('恢复全部新增仓位','Resume all entries'):t('暂停全部新增仓位','Pause all entries');
  $('#positions-body').innerHTML=state.positions.length?state.positions.map(p=>`<tr><td><strong>${escapeHtml(traderName(p.trader_id))}</strong><span class="cell-sub">PAPER</span></td><td><strong>${escapeHtml(p.symbol)}</strong> ${badge(sideLabel(p.side),p.side==='LONG'?'green':'red')}<span class="cell-sub">${p.leverage}×</span></td><td>${num(p.qty,6)}</td><td>${num(p.entry,4)}</td><td>${num(p.mark,4)}</td><td>${num(p.stop,4)}</td><td class="${pnlClass(p.unrealized)}">${num(p.unrealized)}</td><td><button class="ghost danger position-close" data-trader="${escapeHtml(p.trader_id)}" data-symbol="${escapeHtml(p.symbol)}" data-side="${escapeHtml(p.side)}">${t('平模拟仓','Close paper')}</button></td></tr>`).join(''):empty(8,t('还没有模拟仓位。启动演示跟随，即可观察规则执行。','No paper positions. Start a demo trader to observe the rules.'));
  const kindLabel={OPEN:t('开仓','OPEN'),CLOSE:t('信号减仓','SIGNAL CLOSE'),STOP_LOSS:t('模拟止损','PAPER STOP'),LOSS_LIMIT:t('亏损预算','LOSS LIMIT'),MANUAL_CLOSE:t('手动模拟平仓','MANUAL CLOSE')};
  $('#orders-body').innerHTML=state.orders.length?state.orders.slice(0,12).map(o=>`<tr><td>${shortTime(o.created)}</td><td>${escapeHtml(traderName(o.trader_id))}</td><td><strong>${escapeHtml(o.symbol)}</strong> ${badge(sideLabel(o.side),o.side==='LONG'?'green':'red')}</td><td>${escapeHtml(kindLabel[o.kind]||o.kind)}</td><td>${num(o.qty,6)}</td><td>${num(o.price,4)}</td><td>${num(o.fee,4)}</td><td class="${pnlClass(o.pnl)}">${num(o.pnl)}</td></tr>`).join(''):empty(8,t('订单将在这里显示；当前没有真实交易。','Paper orders will appear here. No real trades are sent.'));
  $('#trader-cards').innerHTML=state.traders.map(x=>`<article class="card trader-card"><div class="trader-identity"><span class="avatar">${escapeHtml(x.name.slice(0,1))}</span><div><strong>${escapeHtml(x.name)}</strong>${badge(x.enabled?t('运行中','RUNNING'):t('已暂停','PAUSED'),x.enabled?'green':'subtle')} ${badge(x.source==='demo'?'DEMO':'PUBLIC')}</div></div><p class="small muted">${escapeHtml(x.url)}</p><div class="trader-rules"><div class="rule"><span>${t('模拟预算','Paper budget')}</span><strong>${num(x.config.budget)}</strong></div><div class="rule"><span>${t('跟随价差','Entry deviation')}</span><strong>${pct(x.config.max_deviation)}</strong></div><div class="rule"><span>${t('已实现净盈亏','Realized net')}</span><strong class="${pnlClass(x.realized_net)}">${num(x.realized_net)}</strong></div><div class="rule"><span>${t('最近发现信号','Last signal seen')}</span><strong>${shortTime(x.last_seen)}</strong></div></div><div class="button-row"><button class="primary select-trader" data-id="${escapeHtml(x.id)}">${t('查看工作台','Open workspace')}</button><button class="secondary edit-card" data-id="${escapeHtml(x.id)}" ${x.enabled?'disabled':''}>${t('配置','Configure')}</button></div></article>`).join('');
  const selectedEvents=state.events.filter(e=>e.trader_id===selected);
  const delays=selectedEvents.filter(e=>e.status!=='baseline'&&e.delay_ms>=0).map(e=>e.delay_ms).sort((a,b)=>a-b);
  const latency=v=>v===undefined?'—':`${num(v/1000,2)} s`;
  $('#latency-median').textContent=latency(delays[Math.floor(delays.length/2)]);
  $('#latency-p95').textContent=latency(delays[Math.min(delays.length-1,Math.floor(delays.length*.95))]);
  const statusLabels={filled:t('模拟成交','PAPER FILL'),skipped:t('已跳过','SKIPPED'),baseline:t('历史基线','BASELINE'),pending:t('处理中','PENDING')};
  $('#events-body').innerHTML=selectedEvents.length?selectedEvents.map(e=>`<tr><td>${badge(tr?.source==='demo'?'DEMO':'PUBLIC')}</td><td>${fullTime(e.source_time)}</td><td>${fullTime(e.first_seen)}<span class="cell-sub">${num(e.delay_ms/1000,2)} s</span></td><td><strong>${escapeHtml(e.symbol)}</strong><span class="cell-sub">${escapeHtml(action(e.action))}</span></td><td>${num(e.source_price,4)}</td><td>${num(e.quote_price,4)}</td><td class="${Number(e.deviation)>Number(tr?.config.max_deviation)?'negative':''}">${pct(e.deviation)}</td><td>${badge(statusLabels[e.status]||e.status,e.status==='filled'?'green':e.status==='skipped'?'red':'subtle')}<span class="cell-sub">${escapeHtml(e.reason)}</span></td></tr>`).join(''):empty(8,t('还没有该交易员的信号记录。','No signals recorded for this trader.'));
  $('#logs').innerHTML=state.logs.length?state.logs.map(l=>`<div class="log-row"><time>${shortTime(l.created)}</time>${badge(l.level.toUpperCase(),l.level==='error'?'red':l.level==='warning'?'blue':'subtle')}<span>${escapeHtml(l.message)}</span></div>`).join(''):`<p class="muted small">${t('暂无日志','No activity yet')}</p>`;
  $('#updated').textContent=t('更新于 ','Updated ')+shortTime(new Date().toISOString());
  chart();
    renderSignalObservation(tr,selectedEvents);
  accountUI.updateApp(state);
}

async function refresh() {
  if(busy)return;
  busy=true;
  try {
    state=await api('/api/state');
    render();
    await accountUI.refresh();
    $('.connection').classList.remove('offline');
    $('#connection-label').textContent=t('本地服务已连接','Local service connected');
  } catch(error) {
    $('.connection').classList.add('offline');
    $('#connection-label').textContent=t('服务已断开','Server disconnected');
  } finally { busy=false; }
}

function editor(trader=null) {
  editing=trader?.id||null;
  const form=$('#trader-form');
  form.reset();
  const defaults={name:'',url:'',source:'demo',config:{budget:1000,order_margin:25,leverage:2,max_deviation:.03,stop_loss_pct:.02,close_fraction:.5,max_loss:100,max_signal_age:60,poll_seconds:15,fee_rate:.0004,symbols:['BTCUSDT','ETHUSDT'],utc_offset_minutes:null}};
  const item=trader||defaults;
  ['name','url','source'].forEach(k=>form.elements[k].value=item[k]);
  Object.entries(item.config).forEach(([key,val])=>{
    if(!form.elements[key])return;
    form.elements[key].value=key==='symbols'?val.join(', '):['max_deviation','stop_loss_pct','close_fraction','fee_rate'].includes(key)?Number(val)*100:val??'';
  });
  form.elements.authorized.checked=Boolean(item.authorized);
  $('#dialog-title').textContent=editing?t('编辑交易员参数','Edit trader parameters'):t('添加交易员','Add trader');
  $('#form-error').textContent='';
  $('#trader-dialog').showModal();
}

$('#trader-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const form=event.currentTarget;
  const data=Object.fromEntries(new FormData(form).entries());
  const config={};
  ['budget','order_margin','max_loss'].forEach(k=>config[k]=data[k]);
  ['leverage','max_signal_age','poll_seconds'].forEach(k=>config[k]=Number(data[k]));
  ['max_deviation','stop_loss_pct','close_fraction','fee_rate'].forEach(k=>config[k]=String(Number(data[k])/100));
  config.symbols=data.symbols.split(',').map(x=>x.trim().toUpperCase()).filter(Boolean);
  config.utc_offset_minutes=data.utc_offset_minutes===''?null:Number(data.utc_offset_minutes);
  const payload={name:data.name,url:data.url,source:data.source,authorized:form.elements.authorized.checked,config};
  try {
    const result=await api(editing?`/api/traders/${editing}/config`:'/api/traders',payload);
    selected=result.id;
    localStorage.setItem('cts-trader',selected);
    $('#trader-dialog').close();
    toast(t('配置已保存，仍为模拟模式。','Configuration saved. Paper mode remains active.'));
    await refresh();
  } catch(error) { $('#form-error').textContent=error.message; }
});

async function act(path,payload,success) {
  try { await api(path,payload);if(success)toast(success);await refresh(); }
  catch(error){toast(error.message);}
}
$$('.nav-item').forEach(e=>e.addEventListener('click',()=>setView(e.dataset.view)));
$('#language').addEventListener('click',()=>{language=language==='zh'?'en':'zh';localStorage.setItem('cts-language',language);setLanguage();});
$('#add-trader').addEventListener('click',()=>editor());
$('#edit-trader').addEventListener('click',()=>editor(currentTrader()));
$('#close-dialog').addEventListener('click',()=>$('#trader-dialog').close());
$('#cancel-dialog').addEventListener('click',()=>$('#trader-dialog').close());
$('#trader-select').addEventListener('change',e=>{selected=e.target.value;localStorage.setItem('cts-trader',selected);render();});
$('#toggle-trader').addEventListener('click',()=>act(`/api/traders/${selected}/toggle`,{enabled:!currentTrader().enabled}));
$('#demo-event').addEventListener('click',()=>act(`/api/traders/${selected}/demo`,{},t('已处理一条合成演示信号。','Processed one synthetic demo signal.')));
$('#demo-reject').addEventListener('click',()=>act(`/api/traders/${selected}/demo`,{scenario:'over_deviation'},t('已生成超出当前价差阈值的演示信号，请查看信号记录。','Generated a demo signal beyond the configured deviation limit. Inspect the signal log.')));
$('#global-pause').addEventListener('click',()=>act('/api/pause',{paused:!state.paused}));
$('#close-all').addEventListener('click',()=>act(`/api/traders/${selected}/close`,{},t('已平掉所选交易员的模拟仓位。','Closed the selected trader’s paper positions.')));
$('#positions-body').addEventListener('click',e=>{const b=e.target.closest('.position-close');if(b)act(`/api/traders/${b.dataset.trader}/close`,{symbol:b.dataset.symbol,side:b.dataset.side});});
$('#trader-cards').addEventListener('click',e=>{
  const b=e.target.closest('[data-id]');if(!b)return;
  if(b.classList.contains('select-trader')){selected=b.dataset.id;localStorage.setItem('cts-trader',selected);render();setView('overview');}
  if(b.classList.contains('edit-card'))editor(state.traders.find(x=>x.id===b.dataset.id));
});
$('#live-info').addEventListener('click',()=>$('#info-dialog').showModal());
$('#close-info').addEventListener('click',()=>$('#info-dialog').close());
setLanguage();
$('#startup-status')?.remove();
session().then(refresh).catch(e=>toast(e.message));
setInterval(refresh,2000);
