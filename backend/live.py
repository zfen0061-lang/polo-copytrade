"""Account connection and explicit live/testnet sessions. No network I/O on import."""
from __future__ import annotations

from datetime import datetime,timezone
from contextlib import closing
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import Invalid,dec,now,validate_config
from .executor import Binance,Engine,Halt,APIError,quantize,D


class TradeClient(Binance):
    def __init__(self,key=None,secret=None,environment=None):
        self.live=True
        self.key=key if key is not None else os.environ.get('POLO_BINANCE_API_KEY','')
        self.secret=secret if secret is not None else os.environ.get('POLO_BINANCE_API_SECRET','')
        self.environment=environment or os.environ.get('POLO_BINANCE_ENV','production')
        if self.environment not in ('production','testnet'):
            raise Halt('环境必须为 production 或 testnet。')
        if not self.key or not self.secret:
            raise Halt('请在本机运行 connect-account.cmd 输入密钥，再启动服务；不要把密钥发到聊天。')
        self.base='https://fapi.binance.com' if self.environment=='production' else 'https://demo-fapi.binance.com'
        from .executor import NoRedirect
        self.opener=urllib.request.build_opener(NoRedirect())
        self.offset=0
        self.blocked_until=0

    def request(self,method,path,params=None,signed=False):
        if time.monotonic()<self.blocked_until:
            raise Halt('币安请求受限，等待后再重试；不会绕过访问限制。')
        params=dict(params or {})
        headers={}
        if signed:
            params.update(timestamp=int(time.time()*1000+self.offset),recvWindow=5000)
            headers['X-MBX-APIKEY']=self.key
        query=urllib.parse.urlencode(params)
        if signed:
            query+='&signature='+hmac.new(self.secret.encode(),query.encode(),hashlib.sha256).hexdigest()
        address=self.base+path
        data=None
        if method in ('GET','DELETE'):
            if query:address+='?'+query
        else:
            data=query.encode()
            headers['Content-Type']='application/x-www-form-urlencoded'
        try:
            with self.opener.open(urllib.request.Request(address,data=data,headers=headers,method=method),timeout=12) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (418,429):
                try:delay=max(10,min(86400,int(error.headers.get('Retry-After','60'))))
                except ValueError:delay=60
                self.blocked_until=time.monotonic()+delay
            try:code=json.loads(error.read()).get('code',error.code)
            except Exception:code=error.code
            raise APIError(code) from None
        except Exception:
            # Never propagate a signed URL or HTTP request repr into a log/browser.
            raise Halt('网络请求失败或超时。下单结果需查单确认；不会直接重发。') from None

    def sync(self):
        before=time.time()*1000
        server=self.request('GET','/fapi/v1/time')['serverTime']
        self.offset=int(server-(before+time.time()*1000)/2)

    def account(self):
        config=self.request('GET','/fapi/v1/accountConfig',signed=True)
        account=self.request('GET','/fapi/v3/account',signed=True)
        positions=self.request('GET','/fapi/v3/positionRisk',signed=True)
        return dict(environment=self.environment,can_trade=bool(config.get('canTrade')),
                    hedge_mode=bool(config.get('dualSidePosition')),multi_assets=bool(config.get('multiAssetsMargin')),
                    wallet_balance=account.get('totalWalletBalance','0'),equity=account.get('totalMarginBalance','0'),
                    available=account.get('availableBalance','0'),unrealized=account.get('totalUnrealizedProfit','0'),
                    positions=[{k:p.get(k) for k in ('symbol','positionSide','positionAmt','entryPrice','markPrice','unRealizedProfit','liquidationPrice','initialMargin')}
                               for p in positions if dec(p.get('positionAmt','0'))!=0],updated=now())

    def preflight(self,symbols,ledger,leverage):
        super().preflight(symbols,ledger,leverage)
        snapshot=self.account()
        if snapshot['hedge_mode'] or snapshot['multi_assets'] or not snapshot['can_trade']:
            raise Halt('第一版需要可交易的单向、单资产 U 本位账户。')
        for p in snapshot['positions']:
            if p['symbol'] not in ledger or dec(p['positionAmt'])!=ledger[p['symbol']]:
                raise Halt('发现本程序以外的持仓；请使用独立账户并停止手动混合交易。')
        for symbol in symbols:
            algos=self.request('GET','/fapi/v1/openAlgoOrders',dict(symbol=symbol),signed=True)
            if isinstance(algos,dict):algos=[algos]
            if any(not str(a.get('clientAlgoId','')).startswith('ps_') for a in algos):
                raise Halt('发现其他条件挂单，停止以避免干扰手动止损。')
            if algos and (ledger.get(symbol,D('0'))==0 or len(algos)>1):
                raise Halt('发现孤立或重复保护单，请先到币安核对处理。')


class ProtectedEngine(Engine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS stops(symbol TEXT PRIMARY KEY,client_id TEXT NOT NULL,trigger TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_anchor(id INTEGER PRIMARY KEY CHECK(id=1),equity TEXT NOT NULL);
        ''')

    def _cancel_stop(self,symbol,client_id):
        self.broker.request('DELETE','/fapi/v1/algoOrder',dict(clientAlgoId=client_id),signed=True)

    def _ensure_stop(self,event):
        symbol=event['symbol']
        qty=self.ledger().get(symbol,D('0'))
        old=self.db.execute('SELECT * FROM stops WHERE symbol=?',(symbol,)).fetchone()
        if qty==0:
            if old:
                self._cancel_stop(symbol,old['client_id'])
                with self.db:self.db.execute('DELETE FROM stops WHERE symbol=?',(symbol,))
            return
        # A close-all stop automatically covers the remaining owned position after reductions.
        if old and event['action'] in ('卖出平多','买入平空'):
            check=self.broker.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=old['client_id']),signed=True)
            if check.get('algoStatus')=='NEW':return
        account=self.broker.account()
        position=next((p for p in account['positions'] if p['symbol']==symbol),None)
        if not position or dec(position['positionAmt'])!=qty:
            raise Halt('成交后仓位对账失败，需要立即到币安核对持仓与止损。')
        tick=self.broker.rules(symbol)['PRICE_FILTER']['tickSize']
        entry=dec(position['entryPrice'])
        stop=entry*(1-dec(self.config['stop_loss_pct']) if qty>0 else 1+dec(self.config['stop_loss_pct']))
        stop=quantize(stop,tick,up=qty>0)
        if old:stop=max(stop,dec(old['trigger'])) if qty>0 else min(stop,dec(old['trigger']))
        client_id='ps_'+hashlib.sha256(event['id'].encode()).hexdigest()[:28]
        params=dict(symbol=symbol,algoType='CONDITIONAL',type='STOP_MARKET',side='SELL' if qty>0 else 'BUY',
                    positionSide='BOTH',closePosition='true',workingType='MARK_PRICE',triggerPrice=format(stop,'f'),clientAlgoId=client_id)
        try:
            self.broker.request('POST','/fapi/v1/algoOrder',params,signed=True)
        except Exception:
            # A lost acknowledgement is not proof that protection was rejected.
            pass
        check=self.broker.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=client_id),signed=True)
        if check.get('algoStatus')!='NEW' or dec(check.get('triggerPrice','0'))!=stop:
            raise Halt('保护单未确认，需要立即核对币安账户。')
        with self.db:self.db.execute('INSERT OR REPLACE INTO stops VALUES (?,?,?)',(symbol,client_id,str(stop)))
        # New protection is confirmed before the old protection is cancelled.
        if old and old['client_id']!=client_id:self._cancel_stop(symbol,old['client_id'])

    def settle(self,event,params,response):
        result=super().settle(event,params,response)
        try:
            self._ensure_stop(event)
        except Exception:
            # Protection failures block new orders. Any known owned exposure is reduced,
            # with a durable intent and a distinct client id; uncertain exits are not resent.
            qty=self.ledger().get(event['symbol'],D('0'))
            if qty:
                emergency=dict(symbol=event['symbol'],side='SELL' if qty>0 else 'BUY',positionSide='BOTH',
                               type='MARKET',reduceOnly='true',quantity=format(abs(qty),'f'),
                               newOrderRespType='RESULT',newClientOrderId='pe_'+hashlib.sha256(event['id'].encode()).hexdigest()[:28])
                emergency_event=dict(event,id=event['id']+'-protection-exit')
                with self.db:self.db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?)',
                    (emergency_event['id'],'submitting',json.dumps(dict(event=emergency_event,order=emergency))))
                try:
                    exit_result=self.broker.place(emergency)
                except Exception:
                    exit_result=self.broker.query(event['symbol'],emergency['newClientOrderId'])
                Engine.settle(self,emergency_event,emergency,exit_result)
                if self.ledger().get(event['symbol'],D('0')):
                    raise Halt('保护异常后的退出未完全成交，已停止；请立即到币安核对剩余仓位。') from None
                # A confirmed flat position must not leave our close-all stops behind.
                candidates={'ps_'+hashlib.sha256(event['id'].encode()).hexdigest()[:28]}
                stored=self.db.execute('SELECT client_id FROM stops WHERE symbol=?',(event['symbol'],)).fetchone()
                if stored:candidates.add(stored[0])
                for stop_id in candidates:
                    try:
                        state=self.broker.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=stop_id),signed=True)
                        if state.get('algoStatus')=='NEW':self._cancel_stop(event['symbol'],stop_id)
                    except Exception:pass
                with self.db:self.db.execute('DELETE FROM stops WHERE symbol=?',(event['symbol'],))
            raise Halt('止损保护发生异常，已停止跟随并尝试只减仓退出；请立即到币安核对最终仓位。') from None
        return result

    def reconcile(self):
        self.recover()
        account=self.broker.account()
        actual={p['symbol']:dec(p['positionAmt']) for p in account['positions']}
        for symbol,qty in self.ledger().items():
            if not qty:continue
            if actual.get(symbol,D('0'))==0:
                stop=self.db.execute('SELECT * FROM stops WHERE symbol=?',(symbol,)).fetchone()
                if not stop:raise Halt('持仓消失且没有可核对的保护单，请检查手动操作。')
                state=self.broker.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=stop['client_id']),signed=True)
                if state.get('algoStatus') not in ('FINISHED','TRIGGERED'):
                    if state.get('algoStatus')=='NEW':self._cancel_stop(symbol,stop['client_id'])
                    with self.db:
                        self.db.execute('UPDATE positions SET qty=\'0\' WHERE symbol=?',(symbol,))
                        self.db.execute('DELETE FROM stops WHERE symbol=?',(symbol,))
                    raise Halt('检测到手动平仓或未知仓位变化，停止跟随以便核对。')
                with self.db:
                    self.db.execute('UPDATE positions SET qty=\'0\' WHERE symbol=?',(symbol,))
                    self.db.execute('DELETE FROM stops WHERE symbol=?',(symbol,))
            elif actual[symbol]!=qty:
                raise Halt('实际仓位和本程序账本不一致，暂停跟随。')
            else:
                stop=self.db.execute('SELECT * FROM stops WHERE symbol=?',(symbol,)).fetchone()
                if not stop:
                    # Covers a process crash after fill persistence but before stop creation.
                    self._ensure_stop(dict(symbol=symbol,id='recovery-'+symbol+'-'+str(qty),action='买入开多' if qty>0 else '卖出开空'))
                else:
                    status=self.broker.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=stop['client_id']),signed=True)
                    if status.get('algoStatus')!='NEW':raise Halt('仓位保护状态异常，停止新增并核对账户。')
        return account


class LiveManager:
    def __init__(self,store,factory=TradeClient,collector_factory=None,execution_allowed=True):
        self.store,self.factory=store,factory
        self.execution_allowed=execution_allowed
        self.collector_factory=collector_factory
        self.client=None
        self.account_cache=None
        self.error=''
        self.trader_id=None
        self.watching=False
        self.entries_enabled=False
        self.stop_event=threading.Event()
        self.thread=None
        self.lock=threading.RLock()
        self.account_io_lock=threading.RLock()
        self.account_polling=False
        self.order_db_path=None
        self.active_config=None

    def status(self):
        with self.lock:
            orders=[]
            if self.order_db_path and self.order_db_path.is_file():
                try:
                    with closing(sqlite3.connect(self.order_db_path,timeout=1)) as db:
                        for row in db.execute('SELECT id,state,payload FROM jobs ORDER BY rowid DESC LIMIT 30'):
                            p=json.loads(row[2]);orders.append(dict(id=row[0],state=row[1],order=p.get('order'),result=p.get('result'),reason=p.get('reason')))
                except sqlite3.Error:pass
            return dict(configured=bool(os.environ.get('POLO_BINANCE_API_KEY') and os.environ.get('POLO_BINANCE_API_SECRET')),
                        connected=self.client is not None,environment=getattr(self.client,'environment',os.environ.get('POLO_BINANCE_ENV','production')),
                        account=self.account_cache,error=self.error,watching=self.watching,entries_enabled=self.entries_enabled,
                        trader_id=self.trader_id,orders=orders,active_config=self.active_config,online_verified=False,
                        execution_allowed=self.execution_allowed,account_polling=self.account_polling,
                        note='账户快照来自实际API；自动执行代码尚未完成本环境的在线联调。')

    def connect(self):
        with self.account_io_lock:
            return self._connect_account()

    def _connect_account(self):
        with self.lock:
            if self.watching:raise Invalid('请先停止跟随再重新连接。')
        try:
            client=self.factory()
            client.sync()
            account=client.account()
        except Exception as e:
            with self.lock:self.error=str(e) if isinstance(e,(Halt,APIError)) else '账户连接失败，请检查本机网络、密钥权限和地区可用性。'
            raise Invalid(self.error) from None
        with self.lock:
            self.client,self.account_cache,self.error=client,account,''
        return self.status()

    def refresh_account(self):
        with self.account_io_lock:
            if not self.client:raise Invalid('请先连接账户。')
            client=self.client
            try:
                client.sync()
                account=client.account()
            except Exception as error:
                with self.lock:self.error=str(error) if isinstance(error,(Halt,APIError)) else '账户读取失败；保留上次成功快照，稍后重试。'
                raise
            with self.lock:self.account_cache,self.error=account,''
        return self.status()

    def start(self,trader_id,raw,background=True):
        if not self.execution_allowed:raise Invalid('当前为真实账户只读连接，只能读取余额和持仓，账户下单入口已关闭。')
        if not self.client:raise Invalid('账户尚未连接。')
        required={'budget','order_margin','leverage','max_deviation','stop_loss_pct','close_fraction','max_loss','max_signal_age','symbols','poll_seconds','utc_offset_minutes','fee_rate'}
        if not isinstance(raw,dict) or not required.issubset(raw):raise Invalid('请显式填写完整实盘参数，不能直接使用演示默认值。')
        c=validate_config(raw)
        if c['utc_offset_minutes'] is None:raise Invalid('请核实源操作时区。')
        trader=self.store.get_trader(trader_id)
        draft=json.loads(trader.get('execution_draft') or '{}')
        if draft.get('sizing')=='allocated_pool_compounding':
            raise Invalid('The compounding allocation is a draft; verified compounding execution and risk settings are still required')
        if json.loads(trader.get('signal_monitor') or '{}').get('mode')=='observe':
            raise Invalid('This trader is locked to signal observation; configure execution separately before starting account following')
        if trader['source']!='binance_public' or not trader['authorized']:
            raise Invalid('实盘只接收已核实权限的公开数据源，不能连接演示信号。')
        if trader['enabled']:raise Invalid('请先暂停该交易员的模拟采集，避免重复采集同一来源。')
        if self.collector_factory is None:
            from .doctor import collector_status
            setup=collector_status()
            if not setup['installed'] or not setup['chromium'] or setup['error']:
                raise Invalid('公开采集环境尚未准备好。请先在项目文件夹运行 setup.cmd，再用 check.cmd 检查；尚未启动账户跟随。')
        with self.lock:
            if self.watching:raise Invalid('同一账户只允许一个实盘跟随会话。先停止旧会话并处理仓位后再切换。')
            self.trader_id=trader_id
            self.active_config=c
            self.error=''
            self.stop_event.clear()
            self.watching,self.entries_enabled=True,True
        config=dict(mode='live',live_enabled=True,symbols=c['symbols'],order_notional_usdt=str(dec(c['order_margin'])*c['leverage']),
                    leverage=c['leverage'],max_total_notional_usdt=str(dec(c['budget'])*c['leverage']),
                    close_rule='fixed_fraction_on_each_close',close_fraction=c['close_fraction'],
                    source_utc_offset_minutes=c['utc_offset_minutes'],max_signal_age_seconds=c['max_signal_age'],
                    max_open_deviation=c['max_deviation'],stop_loss_pct=c['stop_loss_pct'],max_loss=c['max_loss'],
                    budget=c['budget'],order_margin=c['order_margin'],poll_seconds=c['poll_seconds'],trader_id=trader_id,
                    environment=self.client.environment,stop_file=str(self.store.path.parent/'STOP_REAL_TRADING'))
        if background:
            self.thread=threading.Thread(target=self._run,args=(trader,config),daemon=True,name='real-account-follow')
            self.thread.start()
        return self.status()

    def pause(self,paused):
        if not self.watching:raise Invalid('没有正在运行的账户跟随。')
        with self.lock:self.entries_enabled=not paused
        return self.status()

    def stop(self):
        with self.lock:self.entries_enabled=False
        self.stop_event.set()
        if self.thread is None or not self.thread.is_alive():
            with self.lock:self.watching=False
        return self.status()

    def _run(self,trader,config):
        from .feeds import PublicCollector
        from .runtime_lock import execution_lease
        collector=engine=None
        try:
            identity=hashlib.sha256((self.client.environment+self.client.key).encode()).hexdigest()[:16]
            with execution_lease(self.store.path.parent/'real-execution.lock'):
                path=self.store.path.parent/f'real-{identity}-{trader["id"]}.sqlite3'
                with self.lock:self.order_db_path=path
                engine=ProtectedEngine(config,path,self.client)
                account=engine.reconcile()
                self.client.preflight(config['symbols'],engine.ledger(),config['leverage'])
                if any(engine.ledger().values()):
                    raise Halt('上次会话仍有仓位。请先在币安核对并处理旧仓位，再重新开始；不会用新的历史基线盲目恢复。')
                if dec(account['available'])<dec(config['order_margin']):raise Halt('合约账户可用余额不足。')
                with engine.db:engine.db.execute('INSERT OR REPLACE INTO account_anchor VALUES (1,?)',(account['equity'],))
                collector=(self.collector_factory or PublicCollector)(trader['url'],config['source_utc_offset_minutes'])
                rows,gap=collector.fetch(set())
                # Every explicit start establishes a fresh observation baseline; never replay paused history.
                with engine.db:
                    engine.db.executemany('INSERT OR IGNORE INTO seen VALUES (?)',((r['source_id'],) for r in rows))
                    engine.db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('baseline',min(r['source_time'].replace('T',' ')[:19] for r in rows)))
                next_fetch=time.monotonic()+config['poll_seconds']
                while not self.stop_event.is_set():
                    if Path(config['stop_file']).exists():raise Halt('已检测到停止实盘跟随文件。')
                    self.client.sync()
                    account=engine.reconcile()
                    with self.lock:self.account_cache=account
                    initial=dec(engine.db.execute('SELECT equity FROM account_anchor').fetchone()[0])
                    if dec(account['equity'])-initial<=-dec(config['max_loss']):
                        self.entries_enabled=False
                        # The loss budget applies to this dedicated account, including fees/funding.
                        for symbol,qty in list(engine.ledger().items()):
                            if not qty:continue
                            e=dict(id='loss-'+symbol+'-'+str(time.time_ns()),symbol=symbol,action='卖出平多' if qty>0 else '买入平空')
                            p=dict(symbol=symbol,side='SELL' if qty>0 else 'BUY',type='MARKET',positionSide='BOTH',reduceOnly='true',
                                   quantity=format(abs(qty),'f'),newOrderRespType='RESULT',newClientOrderId='pl_'+hashlib.sha256(e['id'].encode()).hexdigest()[:28])
                            with engine.db:engine.db.execute('INSERT INTO jobs VALUES (?,?,?)',(e['id'],'submitting',json.dumps(dict(event=e,order=p))))
                            try:r=self.client.place(p)
                            except Exception:r=self.client.query(symbol,p['newClientOrderId'])
                            engine.settle(e,p,r)
                        raise Halt('已触发账户亏损预算，停止跟随；请核对实际账户。')
                    if time.monotonic()>=next_fetch:
                        rows,gap=collector.fetch(engine.known())
                        if gap:raise Halt('公开操作记录无法衔接，停止跟随。')
                        for row in reversed(rows):
                            if self.stop_event.is_set():break
                            if row['source_id'] in engine.known():continue
                            event=dict(id=row['source_id'],symbol=row['symbol'],price=row['price'],
                                       action={'OPEN_LONG':'买入开多','OPEN_SHORT':'卖出开空','CLOSE_LONG':'卖出平多','CLOSE_SHORT':'买入平空'}[row['action']],
                                       source_time=datetime.fromisoformat(row['source_time']).replace(tzinfo=None).isoformat(sep=' '))
                            opening=row['action'].startswith('OPEN')
                            if opening and not self.entries_enabled:
                                engine.finish(event,'skipped',dict(reason='新增开仓已暂停'));continue
                            self.client.preflight(config['symbols'],engine.ledger(),config['leverage'])
                            if opening:
                                balance=self.client.account()
                                used=sum((abs(q)*self.client.quote(s)[1]/config['leverage'] for s,q in engine.ledger().items() if q),D('0'))
                                if used+dec(config['order_margin'])>dec(config['budget']) or dec(balance['available'])<dec(config['order_margin'])*D('1.02'):
                                    engine.finish(event,'skipped',dict(reason='已达到分配预算或余额不足'));continue
                            else:
                                # Late close signals must not be silently filtered as stale entries.
                                age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['source_time'])).total_seconds()
                                if age>config['max_signal_age_seconds']:
                                    self.entries_enabled=False
                                    raise Halt('收到迟到的平仓记录；已暂停新增，保留交易所止损，请核对仓位后处理。')
                            params,reason=engine.plan(event)
                            if params is None:engine.finish(event,'skipped',dict(reason=reason));continue
                            if self.stop_event.is_set() or opening and not self.entries_enabled:
                                engine.finish(event,'skipped',dict(reason='会话已暂停或停止'));continue
                            with engine.db:
                                engine.db.execute('INSERT INTO jobs VALUES (?,?,?)',(event['id'],'submitting',json.dumps(dict(event=event,order=params))))
                            try:response=self.client.place(params)
                            except Exception:response=self.client.query(event['symbol'],params['newClientOrderId'])
                            engine.settle(event,params,response)
                            with self.store.db() as db:self.store.log(db,trader['id'],'info',row['symbol']+' 账户订单已核对；环境 '+self.client.environment)
                        next_fetch=time.monotonic()+config['poll_seconds']
                    self.stop_event.wait(5)
        except Exception as e:
            message=str(e) if isinstance(e,(Halt,Invalid,APIError)) else '账户跟随异常：'+type(e).__name__+'。请检查币安账户。'
            with self.lock:self.error=message
            with self.store.db() as db:self.store.log(db,trader['id'],'error',message)
        finally:
            if collector:
                try:collector.close()
                except Exception:pass
            if engine:engine.db.close()
            with self.lock:self.watching,self.entries_enabled=False,False

    def shutdown(self):
        self.stop()
        if self.thread:self.thread.join(timeout=3)


class ReadOnlyAccountPoller:
    def __init__(self,manager,interval=10):
        if manager.execution_allowed:raise Invalid('Automatic account polling requires the read-only server')
        self.manager,self.interval=manager,interval
        self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True,name='read-only-account-poller')
    def tick(self):
        if not self.manager.status()['configured']:return False
        if self.manager.client is None:self.manager.connect()
        else:self.manager.refresh_account()
        return True
    def run(self):
        failures=0
        while not self.stop_event.is_set():
            try:self.tick();failures=0
            except Exception:failures+=1
            self.stop_event.wait(min(60,self.interval*2**min(failures,3)))
    def start(self):
        self.manager.account_polling=True
        self.thread.start()
    def close(self):
        self.stop_event.set()
        self.manager.account_polling=False
        if self.thread.is_alive():self.thread.join(timeout=3)
