"""User-started production following. Opening/inspecting this workspace is read-only."""
from contextlib import ExitStack,closing
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from .core import Invalid,dec,now
from .credential_store import TradingCredentialVault
from .demo_session import PublicSource
from .executor import Halt,APIError,RECOVERABLE_READ_ERRORS,ReconciliationReadError
from .live import TradeClient
from .production import ExecutionPermit,ProductionBroker,ProductionEngine,policy_digest
from .runtime_lock import execution_lease
from .signal_follow import process_public,sync_funding
from .strategy_v2 import StrategyPolicy,RiskLimit


class RealSession:
    def __init__(self,data,source_data,factory=None):
        self.data=Path(data).resolve();self.source=PublicSource(source_data)
        if self.data.parent in (self.source.path.parent,self.source.path.parent/'demo-v2'):
            raise Invalid('Production execution needs a separate data directory')
        self.data.parent.mkdir(parents=True,exist_ok=True)
        self.journal=self.data.parent/'real-execution.sqlite3';self.policy_path=self.data.parent/'real-policy.json'
        self.stop_file=self.source.path.parent/'STOP_REAL_TRADING'
        self.workspace_id=hashlib.sha256(str(self.data).lower().encode()).hexdigest()[:16]
        self.vault=TradingCredentialVault(self.data)
        self.factory=factory or self.default_broker
        self.lock=threading.RLock();self.io_lock=threading.Lock();self.stop_event=threading.Event()
        self.thread=None;self.broker=None;self.policy=None;self.review=None
        self.running=False;self.entries_enabled=False;self.phase='idle';self.error=''
        self.account=None;self.account_updated=None;self.last_tick=None;self.logs=[]
        self.cursor=0;self.source_waiting=False;self.close_requested=False
        self.read_recovery=dict(active=False,attempts=0,next_retry_at=None)
        if self.policy_path.exists():self.policy=StrategyPolicy(**json.loads(self.policy_path.read_text(encoding='utf8')))
        self.suggested_policy=None
        try:
            candidate=json.loads((self.source.path.parent/'demo-v2'/'demo-policy.json').read_text(encoding='utf8'))
            self.suggested_policy=StrategyPolicy(**candidate).public()
        except (OSError,ValueError,TypeError,Invalid):pass

    def entry_guard(self):
        return (self.running and self.entries_enabled and not self.stop_event.is_set()
                and not self.read_recovery['active'] and not self.stop_file.exists() and self.source.inspect()['fresh'])

    def default_broker(self):
        pair=self.vault.load()
        if not pair:raise Invalid('Run connect-trading-subaccount.cmd and enter the intended sub-account keys locally; the main-account connection is never reused here')
        client=TradeClient(key=pair[0],secret=pair[1],environment='production')
        client.sync()
        return ProductionBroker(client,entry_guard=self.entry_guard)

    @staticmethod
    def safe_error(error):
        return str(error) if isinstance(error,(Invalid,Halt,APIError)) else 'Production session error: '+type(error).__name__

    def log(self,message,level='info',**extra):
        entry=dict(time=now(),level=level,message=message,**extra)
        with self.lock:
            self.logs=[entry,*self.logs][:80]
            with open(self.data.parent/'real-session.jsonl','a',encoding='utf8') as output:
                output.write(json.dumps(entry,ensure_ascii=False)+'\n')

    def journal_state(self):
        empty=dict(capital_usdt=None,positions=[],pending_count=0,protection_count=0,locked=False,intents=[])
        if not self.journal.exists():return empty
        with closing(sqlite3.connect(self.journal.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            db.row_factory=sqlite3.Row
            initial=db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()
            capital=dec(initial[0]) if initial else dec('0')
            capital+=sum((dec(r[0]) for r in db.execute('SELECT amount FROM cash')),dec('0'))
            return dict(capital_usdt=str(capital) if initial else None,
                positions=[dict(r) for r in db.execute('SELECT * FROM positions WHERE CAST(qty AS REAL)>0')],
                pending_count=db.execute("SELECT COUNT(*) FROM intents WHERE state IN ('submitting','uncertain','accounting')").fetchone()[0],
                protection_count=sum(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('protection','retired_stops')),
                locked=bool(db.execute('SELECT COUNT(*) FROM intents').fetchone()[0] or db.execute('SELECT COUNT(*) FROM cash').fetchone()[0]),
                intents=[dict(r) for r in db.execute('SELECT id,state FROM intents ORDER BY rowid DESC LIMIT 30')])

    def status(self):
        try:source=self.source.inspect()
        except Exception as exc:source=dict(fresh=False,watching=False,error=self.safe_error(exc))
        try:journal=self.journal_state()
        except sqlite3.Error:journal=dict(positions=[],pending_count=None,error='Journal requires review',locked=True)
        with self.lock:
            review=self.review.copy() if self.review else None
            if review:review['valid']=time.monotonic()<review.pop('deadline')
            return dict(available=True,environment='production',endpoint='https://fapi.binance.com',
                workspace_id=self.workspace_id,phase=self.phase,running=self.running,
                execution_armed=bool(self.running and self.broker and self.broker.permit and not self.broker.permit.revoked.is_set()),
                entries_enabled=self.entries_enabled,connected=self.broker is not None,saved_connection=self.vault.exists(),
                entries_allowed=bool(self.running and self.phase=='running' and self.entries_enabled and not self.read_recovery['active'] and source.get('fresh') and not self.stop_event.is_set() and not self.stop_file.exists()),
                read_recovery=dict(self.read_recovery),
                connection_role='dedicated_trading',
                account=self.account,account_updated=self.account_updated,last_tick=self.last_tick,
                source=source,source_waiting=self.source_waiting,policy=asdict(self.policy) if self.policy else None,
                suggested_policy=self.suggested_policy,journal=journal,error=self.error,review=review,logs=list(self.logs),
                note='Opening this page is read-only. An explicit local start enables automatic real orders under the reviewed policy.')

    def configure(self,raw):
        policy=StrategyPolicy(**raw)
        if not self.io_lock.acquire(blocking=False):raise Invalid('Stop production following before configuration')
        try:
            if self.running:raise Invalid('Stop production following before configuration')
            journal=self.journal_state()
            if journal['positions'] or journal['pending_count'] or journal['protection_count']:
                raise Invalid('Review existing exposure and protection before configuration')
            if journal['locked'] and (not self.policy or asdict(policy)!=asdict(self.policy)):
                raise Invalid('This allocation has history; use a separate reviewed allocation without resetting its ledger')
            if self.journal.exists() and not journal['locked']:
                with closing(sqlite3.connect(self.journal)) as db,db:db.execute('DELETE FROM meta')
            temporary=self.policy_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(asdict(policy)),encoding='utf8');temporary.replace(self.policy_path)
            with self.lock:self.policy=policy;self.review=None;self.error=''
        finally:self.io_lock.release()
        return self.status()

    def preflight(self,broker):
        if not isinstance(broker,ProductionBroker):raise Halt('A fixed production broker is required')
        broker.assert_endpoint()
        if not self.policy:raise Invalid('Save the production policy before review')
        journal=self.journal_state()
        if journal['positions'] or journal['pending_count'] or journal['protection_count']:
            raise Halt('Previous owned exposure or unresolved intents/protection require review; restart does not adopt positions')
        if self.stop_file.exists():raise Halt('STOP_REAL_TRADING exists; execution remains disabled')
        account=broker.require_flat()
        capital=dec(journal['capital_usdt'] or self.policy.initial_capital)
        if capital<=0 or dec(account['available_usdt'])<capital:
            raise Halt('Verified available USDT is below the strategy allocation')
        if not self.source.inspect()['fresh']:raise Halt('Wait for fresh verified public-source data before starting')
        return account

    def inspect(self):
        if not self.io_lock.acquire(blocking=False):raise Invalid('Production I/O is busy')
        try:
            if self.running:raise Invalid('Account monitoring is automatic while running')
            broker=self.factory();broker.assert_endpoint()
            account=broker.account()
            # Refreshing an account must not erase the reason a worker stopped.
            with self.lock:self.broker=broker;self.account=account;self.account_updated=now();self.review=None
            issues=[]
            if not account.get('can_trade'):issues.append('账户未返回可交易状态，请核对账户与合约 API 权限。')
            if account.get('hedge_mode'):issues.append('当前为双向持仓模式；此实盘版本要求单向持仓，程序不会替你切换。')
            if account.get('multi_assets'):issues.append('当前为多资产模式；此实盘版本要求单资产 USDT，程序不会替你切换。')
            if account['positions']:
                symbols=', '.join(sorted({p['symbol'] for p in account['positions']}))
                issues.append('账户已有仓位（'+symbols+'）；需要先自行核对，本程序不会接管或平掉它。')
            if not issues:
                try:self.preflight(broker)
                except (Invalid,Halt,APIError) as exc:issues.append(str(exc))
            tag=broker.identity()[:8]
            review=dict(nonce=secrets.token_urlsafe(24),deadline=time.monotonic()+120,
                confirmation='START REAL '+str(dec(self.policy.initial_capital))+' USDT '+tag if self.policy else '',
                account_tag=tag,policy_hash=policy_digest(self.policy) if self.policy else None,
                blockers=issues,checked_at=now())
            with self.lock:self.review=review
            self.log('Production read-only inspection completed; no order or setting was changed')
        finally:self.io_lock.release()
        return self.status()

    def start(self,payload):
        if set(payload)!={'confirmation','nonce'}:raise Invalid('Only the displayed production confirmation and review nonce are accepted')
        with self.lock:
            if self.running or (self.thread and self.thread.is_alive()):raise Invalid('Production following is already active')
            review=self.review
            if (not review or time.monotonic()>=review['deadline'] or review['blockers'] or not self.policy or not self.broker
                    or not secrets.compare_digest(str(payload['nonce']),review['nonce'])
                    or not secrets.compare_digest(str(payload['confirmation']),review['confirmation'])
                    or review['policy_hash']!=policy_digest(self.policy) or review['account_tag']!=self.broker.identity()[:8]):
                raise Invalid('Complete a fresh read-only review and enter its exact account-bound start phrase')
            self.review=None;self.stop_event.clear();self.running=True;self.entries_enabled=True
            self.read_recovery=dict(active=False,attempts=0,next_retry_at=None)
            self.error='';self.phase='starting'
            self.thread=threading.Thread(target=self.run,name='production-follow',daemon=True);self.thread.start()
        return self.status()

    def pause(self,paused):
        if type(paused) is not bool:raise Invalid('paused must be boolean')
        with self.lock:
            if not self.running:raise Invalid('Production following is not running')
            self.entries_enabled=not paused
        return self.status()

    def stop(self):
        with self.lock:self.entries_enabled=False;self.review=None
        self.stop_event.set()
        return self.status()

    def request_close(self,confirmation):
        if confirmation!='CLOSE OWNED REAL':raise Invalid('Explicit CLOSE OWNED REAL confirmation is required')
        with self.lock:
            if not self.running:raise Invalid('Production following is not running; inspect the exchange directly')
            self.entries_enabled=False;self.close_requested=True
        return self.status()

    def flatten_owned(self,engine,reason):
        for position in list(engine.book.positions()):
            event=dict(id='real-flat-'+uuid.uuid4().hex,symbol=position['symbol'],action='CLOSE_'+position['side'],
                       source_time=now(),price=position['entry'])
            result=engine.handle(event);self.log(reason,origin='owned_exit',symbol=position['symbol'],result=result['state'])

    def recover_read_failure(self,engine,error,write_attempts):
        # Ordinary GET recovery requires a write-free tick. The only post-write
        # exception is explicitly marked durable-order reconciliation: recover()
        # queries the existing client id and never submits that intent again.
        reconciling=isinstance(error,ReconciliationReadError)
        if not reconciling and (engine.broker.write_attempts!=write_attempts or engine.book.pending()):return False
        attempts=self.read_recovery['attempts']+1
        delay=min(60,2**min(attempts,6))
        retry_at=(datetime.now(timezone.utc)+timedelta(seconds=delay)).isoformat(timespec='milliseconds')
        with self.lock:
            self.read_recovery=dict(active=True,attempts=attempts,next_retry_at=retry_at)
            self.phase='recovering';self.last_tick=now()
            self.error=('订单结果正在自动查单核对，不会重复下单；' if reconciling else '网络或查询暂不可用，新开仓暂停；')+str(delay)+' 秒后自动重连并核对。'
        self.log('Durable order read recovery; no resubmission' if reconciling else 'Read recovery; entries held until account checks succeed','warning',
                 error_code=getattr(error,'code',None),read_path=getattr(error,'path',None),
                 retry_seconds=delay,attempt=attempts)
        self.stop_event.wait(delay)
        return True

    def complete_read_recovery(self):
        if not self.read_recovery['attempts']:return
        attempts=self.read_recovery['attempts']
        with self.lock:
            self.read_recovery=dict(active=False,attempts=0,next_retry_at=None)
            self.phase='running';self.error=''
        self.log('Account checks recovered; original signal cursor and entry-age limits retained',attempts=attempts)

    def tick(self,engine,maintenance=True,funding=True):
        if self.stop_file.exists():raise Halt('STOP_REAL_TRADING detected; stops remain on the exchange')
        if maintenance:
            engine.broker.sync();engine.recover()
            if funding:sync_funding(engine)
            account=engine.check_account();engine.broker.require_account_mode(account)
            with self.lock:self.account=account;self.account_updated=now()
            try:engine.risk_check(account)
            except RiskLimit:
                self.entries_enabled=False;self.flatten_owned(engine,'Cumulative strategy loss limit')
                raise
            if self.read_recovery['active']:
                with self.lock:
                    self.read_recovery['active']=False;self.read_recovery['next_retry_at']=None
                    self.phase='running';self.error=''
        if self.read_recovery['active']:return
        if self.close_requested:
            self.close_requested=False;self.flatten_owned(engine,'Explicit owned-position exit')
        process_public(self,engine,self.source.inspect(),prefix='real:'+self.workspace_id+':aoying:',label='production')
        self.complete_read_recovery()

    def run(self):
        engine=None
        try:
            with ExitStack() as stack:
                stack.enter_context(self.io_lock)
                # Shared with the legacy production runner, across allocations
                # under the same source workspace; the Demo lock is separate.
                stack.enter_context(execution_lease(self.source.path.parent/'real-execution.lock'))
                self.preflight(self.broker)
                permit=ExecutionPermit(self.broker.identity(),policy_digest(self.policy),str(self.journal.resolve()))
                engine=ProductionEngine(self.journal,self.policy,self.broker,permit)
                engine.recover();engine.check_account()
                self.cursor=self.source.inspect()['latest_id']
                with engine.book.db:engine.book.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('source_cursor',str(self.cursor)))
                with self.lock:self.phase='running';self.source_waiting=False
                self.log('User explicitly started production following; existing public history baselined')
                next_maintenance=next_funding=0
                while not self.stop_event.is_set():
                    clock=time.monotonic();maintenance=clock>=next_maintenance;funding=clock>=next_funding
                    write_attempts=engine.broker.write_attempts
                    try:self.tick(engine,maintenance,funding)
                    except (*RECOVERABLE_READ_ERRORS,ReconciliationReadError) as exc:
                        if not self.recover_read_failure(engine,exc,write_attempts):raise
                        next_maintenance=next_funding=0
                        continue
                    if maintenance:next_maintenance=clock+15
                    if funding:next_funding=clock+60
                    self.stop_event.wait(1)
        except Exception as exc:
            with self.lock:self.error=self.safe_error(exc);self.phase='error'
            self.log(self.error,'error')
        finally:
            if engine:engine.close()
            elif self.broker:self.broker.disarm()
            with self.lock:
                self.running=self.entries_enabled=False;self.review=None
                self.read_recovery['active']=False;self.read_recovery['next_retry_at']=None
                if self.phase!='error':self.phase='stopped'

    def shutdown(self):
        self.stop()
        if self.thread:self.thread.join(timeout=15)
