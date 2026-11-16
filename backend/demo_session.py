"""Explicitly started, demo-only follow sessions. Production signals are read-only.

No production credentials, account-mode changes, automatic adoption or startup
orders. The separate demo ledger survives restarts; starting never replays opens.
"""
from __future__ import annotations
from dataclasses import asdict
from contextlib import contextmanager,closing
from datetime import datetime,timezone
import json
import hashlib
import multiprocessing.connection
import os
from pathlib import Path
import queue
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

from .core import Invalid,now
from .demo_broker import DemoBroker
from .executor import Halt,APIError
from .live import TradeClient
from .observe import AOYING_URL,AOYING_NAME
from .runtime_lock import execution_lease
from .strategy_v2 import StrategyEngine,StrategyPolicy,RiskLimit


class PublicSource:
    def __init__(self,path):self.path=Path(path).resolve()
    @contextmanager
    def db(self):
        if not self.path.is_file():raise Invalid('Public monitoring database is unavailable; start the read-only monitor first')
        connection=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)
        connection.row_factory=sqlite3.Row
        try:yield connection
        finally:connection.close()
    def inspect(self):
        with self.db() as db:
            row=db.execute('SELECT * FROM traders WHERE id=?',('aoying',)).fetchone()
            if not row:raise Invalid('Locked trader was not found')
            trader=dict(row);monitor=json.loads(trader['signal_monitor'] or '{}');config=json.loads(trader['config'])
            if (trader['name']!=AOYING_NAME or trader['url']!=AOYING_URL or trader['source']!='binance_public'
                    or not trader['authorized'] or config.get('utc_offset_minutes')!=0
                    or monitor.get('portfolio_id')!='5075281354358777856'):
                raise Invalid('The locked public source identity or UTC configuration changed')
            stamp=monitor.get('last_poll')
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds() if stamp else None
            fresh=bool(trader['enabled'] and monitor.get('owner') and monitor.get('status')=='running'
                       and age is not None and 0<=age<60 and 0<=time.time()-monitor.get('heartbeat',0)<60)
            latest=db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE trader_id=?',('aoying',)).fetchone()[0]
            watching=bool(trader['enabled'] and monitor.get('owner') and 0<=time.time()-monitor.get('heartbeat',0)<60)
            return dict(fresh=fresh,watching=watching,status=monitor.get('status'),last_poll=stamp,age_seconds=age,
                        latest_id=latest,trader_name=AOYING_NAME,portfolio_id=monitor['portfolio_id'],error=monitor.get('last_error',''))
    def events(self,cursor):
        with self.db() as db:
            rows=db.execute('SELECT * FROM events WHERE trader_id=? AND id>? ORDER BY id LIMIT 301',('aoying',cursor)).fetchall()
            if len(rows)>300:raise Halt('Public backlog is too large; review the demo session instead of replaying blindly')
            return [dict(r) for r in rows]


class DemoSession:
    def __init__(self,data,source_data,factory=None):
        self.data=Path(data).resolve()
        if self.data.parent==Path(source_data).resolve().parent:raise Invalid('Demo data directory must be separate from the production monitor')
        self.data.parent.mkdir(parents=True,exist_ok=True)
        self.workspace_id=hashlib.sha256(os.path.normcase(str(self.data)).encode()).hexdigest()[:16]
        self.source=PublicSource(source_data)
        self.policy_path=self.data.parent/'demo-policy.json';self.journal=self.data.parent/'demo-execution.sqlite3'
        self.factory=factory or self.default_broker;self.broker=None;self.policy=None
        self.credentials=None;self.listener=None;self.control_stop=threading.Event()
        self.lock=threading.RLock();self.io_lock=threading.RLock();self.thread=None;self.stop_event=threading.Event()
        self.commands=queue.Queue(maxsize=10);self.running=False;self.entries_enabled=False;self.error='';self.phase='idle'
        self.account=None;self.account_updated=None;self.last_tick=None;self.logs=[];self.cursor=0
        self.source_waiting=False
        self.verification_process=None;self.verification_folder=None
        self.scope_config={}
        try:self.scope_config=json.loads((self.data.parent/'demo-scope.json').read_text(encoding='utf8'))
        except (OSError,ValueError):pass
        from .credential_store import DemoCredentialVault
        self.vault=DemoCredentialVault(self.data)
        try:self.credentials=self.vault.load()
        except Invalid as exc:self.error=str(exc)
        if self.policy_path.is_file():
            try:self.policy=StrategyPolicy(**json.loads(self.policy_path.read_text(encoding='utf8')))
            except Exception:self.error='Saved demo policy is invalid; configure it again'

    def default_broker(self):
        key,secret=self.credentials or (os.environ.get('POLO_DEMO_API_KEY',''),os.environ.get('POLO_DEMO_API_SECRET',''))
        if not key or not secret:raise Invalid('Enter a separate Futures Demo API pair using connect-demo-v2.cmd')
        client=TradeClient(key=key,secret=secret,environment='testnet');client.sync()
        return DemoBroker(client)

    def start_control(self):
        """Authenticated local pipe accepts Demo credentials only, never orders."""
        from .supervisor import control_address
        from .credential_store import validate_pair
        token_path=self.data.parent/'supervisor-control.token';auth=secrets.token_bytes(32)
        with os.fdopen(os.open(token_path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600),'wb') as output:output.write(auth)
        address,family=control_address(self.data)
        if family=='AF_UNIX':Path(address).unlink(missing_ok=True)
        self.listener=multiprocessing.connection.Listener(address,family=family,authkey=auth)
        def serve():
            while not self.control_stop.is_set():
                try:
                    with self.listener.accept() as connection:
                        if not connection.poll(10):continue
                        message=json.loads(connection.recv_bytes(65536))
                        if not isinstance(message,dict) or message.get('command')!='credentials':
                            connection.send_bytes(b'{"accepted":false,"error":"Demo credential input only; no order commands"}');continue
                        try:
                            pair=validate_pair(message.get('key'),message.get('secret'))
                            with self.idle_io(),self.lock:
                                if message.get('remember') is True:self.vault.save(*pair)
                                self.credentials=pair;self.broker=None;self.account=None;self.account_updated=None;self.error=''
                            result=dict(accepted=True,environment='testnet',storage='windows_dpapi_user' if self.vault.exists() else 'session_memory')
                        except Exception:result=dict(accepted=False,error='Stop the Demo session and enter complete unmasked Demo credentials locally')
                        connection.send_bytes(json.dumps(result).encode())
                except (EOFError,OSError,ValueError,multiprocessing.context.AuthenticationError):
                    if self.control_stop.is_set():break
        threading.Thread(target=serve,name='local-demo-credential-input',daemon=True).start()

    @staticmethod
    def require_demo(broker):
        if broker.environment!='testnet' or broker.base!='https://demo-fapi.binance.com':
            raise Halt('This session accepts only Binance Futures Demo; production is blocked')

    def log(self,message,level='info',**extra):
        with self.lock:
            entry=dict(time=now(),level=level,message=message,**extra)
            self.logs=[entry,*self.logs][:80]
            with open(self.data.parent/'demo-session.jsonl','a',encoding='utf8') as output:output.write(json.dumps(entry)+'\n')

    def journal_state(self):
        if not self.journal.is_file():return dict(capital_usdt=None,positions=[],intents=[],pending_count=0,locked=False)
        with closing(sqlite3.connect(self.journal,timeout=2)) as db:
            db.row_factory=sqlite3.Row
            initial=db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()
            from .core import dec
            capital=dec(initial[0]) if initial else dec('0')
            capital+=sum((dec(r[0]) for r in db.execute('SELECT amount FROM cash')),dec('0'))
            positions=[dict(r) for r in db.execute('SELECT * FROM positions WHERE CAST(qty AS REAL)>0')]
            intents=[dict(r) for r in db.execute('SELECT id,state FROM intents ORDER BY rowid DESC LIMIT 30')]
            pending=db.execute("SELECT COUNT(*) FROM intents WHERE state IN ('submitting','uncertain','accounting')").fetchone()[0]
            locked=bool(db.execute('SELECT COUNT(*) FROM intents').fetchone()[0] or positions or db.execute('SELECT COUNT(*) FROM cash').fetchone()[0])
            return dict(capital_usdt=str(capital) if initial else None,positions=positions,intents=intents,pending_count=pending,locked=locked)

    def status(self):
        try:source=self.source.inspect()
        except Exception as exc:source=dict(fresh=False,error=self.safe_error(exc))
        try:journal=self.journal_state()
        except sqlite3.Error:journal=dict(positions=[],intents=[],pending_count=None,error='Journal temporarily unavailable')
        with self.lock:
            return dict(available=True,environment='testnet',endpoint='https://demo-fapi.binance.com',production_allowed=False,workspace_id=self.workspace_id,
                configured=bool(self.credentials) or bool(os.environ.get('POLO_DEMO_API_KEY') and os.environ.get('POLO_DEMO_API_SECRET')) or self.broker is not None,
                connected=self.broker is not None,phase=self.phase,running=self.running,entries_enabled=self.entries_enabled,
                policy=asdict(self.policy) if self.policy else None,account=self.account,account_updated=self.account_updated,
                error=self.error,last_tick=self.last_tick,source=source,journal=journal,logs=list(self.logs),cursor=self.cursor,
                source_waiting=self.source_waiting,
                saved_demo_connection=self.vault.exists(),verification=self.verification_status(),
                scope=dict(symbol_count=len(self.policy.symbols) if self.policy else 0,
                           prepare_demo_leverage=self.scope_config.get('prepare_demo_leverage') is True),
                note='Testnet orders require explicit start. No production credentials or real orders are used.')

    @staticmethod
    def safe_error(error):
        return str(error) if isinstance(error,(Invalid,Halt,APIError)) else 'Demo session error: '+type(error).__name__

    def inspect(self):
        with self.idle_io():
            if self.running:raise Invalid('Pause or stop the demo session before manual account verification')
            broker=self.factory();self.require_demo(broker)
            account=broker.account()
            with self.lock:self.broker,self.account,self.account_updated,self.error=broker,account,now(),''
            self.log('Demo account read verified; no order was placed')
        return self.status()

    def configure(self,raw):
        policy=StrategyPolicy(**json.loads(json.dumps(raw)))
        with self.idle_io(),self.lock:
            if self.running:raise Invalid('Stop the demo session before changing its policy')
            journal=self.journal_state()
            if journal.get('locked') and (not self.policy or asdict(policy)!=asdict(self.policy)):
                raise Invalid('This journal already has activity. Policy changes require a separate demo data directory; its capital is not silently reset')
            if self.journal.exists() and not journal.get('locked'):
                with closing(sqlite3.connect(self.journal)) as db,db:db.execute('DELETE FROM meta')
            temporary=self.policy_path.with_suffix('.tmp');temporary.write_text(json.dumps(asdict(policy)),encoding='utf8');temporary.replace(self.policy_path)
            self.policy=policy;self.error=''
        return self.status()

    @contextmanager
    def idle_io(self):
        if not self.io_lock.acquire(blocking=False):raise Invalid('Demo I/O is busy; stop following before manual verification or configuration')
        try:
            if self.running:raise Invalid('Stop demo following before changing account/session configuration')
            if self.verification_active():raise Invalid('The bounded Demo stop check is still active')
            yield
        finally:self.io_lock.release()

    def start(self,confirmation):
        if confirmation!='START DEMO':raise Invalid('Explicit START DEMO confirmation is required')
        with self.lock:
            if self.verification_active():raise Invalid('Wait for the Demo stop check and cleanup before following')
            if self.running or (self.thread and self.thread.is_alive()):raise Invalid('The demo session is already active')
            if not self.policy:raise Invalid('Save the complete demo policy, including the cumulative loss basis, first')
            source=self.source.inspect()
            if not source['fresh'] and not (source.get('watching') and source.get('status') in ('running','retrying')):
                raise Invalid('The locked public source is inactive; start observation before Demo following')
            while not self.commands.empty():self.commands.get_nowait()
            self.stop_event.clear();self.running=True;self.entries_enabled=True;self.phase='starting';self.error=''
            self.thread=threading.Thread(target=self.run,name='demo-v2-follow',daemon=True);self.thread.start()
        return self.status()

    def verification_active(self):
        return self.verification_process is not None and self.verification_process.poll() is None

    def verification_status(self):
        result=dict(active=self.verification_active(),progress=None,result=None)
        if self.verification_folder:
            for field,name in [('progress','progress.json'),('result','result.json')]:
                try:result[field]=json.loads((self.verification_folder/name).read_text(encoding='utf8'))
                except (OSError,ValueError):pass
            if not result['active'] and result['result'] is None:
                result['error']='Demo stop check ended without a result; inspect the local verification log'
        return result

    def verify_stop(self,confirmation,seconds=180):
        if confirmation!='VERIFY DEMO STOP':raise Invalid('Explicit VERIFY DEMO STOP confirmation is required')
        if type(seconds) is not int or not 1<=seconds<=900:raise Invalid('Choose 1-900 seconds')
        with self.idle_io(),self.lock:
            if not self.vault.exists():raise Invalid('Remember the separate Demo connection locally before background verification')
            journal=self.journal_state()
            if journal['positions'] or journal['pending_count']:
                raise Invalid('Review owned Demo positions and unresolved orders first')
            from .paths import resource_root
            folder=self.data.parent.parent/'demo-verification'/('job-'+uuid.uuid4().hex)
            folder.parent.mkdir(parents=True,exist_ok=True)
            command=([sys.executable,'--demo-verify'] if getattr(sys,'frozen',False)
                     else [sys.executable,'-m','backend.demo_verify'])
            command+=['--saved','--no-handoff','--data',str(self.data),'--report-dir',str(folder),'--max-wait',str(seconds)]
            env=dict(os.environ)
            for key in ('POLO_BINANCE_API_KEY','POLO_BINANCE_API_SECRET','POLO_DEMO_API_KEY','POLO_DEMO_API_SECRET'):
                env.pop(key,None)
            with open(folder.parent/(folder.name+'.log'),'ab') as output:
                self.verification_process=subprocess.Popen(command,cwd=resource_root(),env=env,
                    stdin=subprocess.DEVNULL,stdout=output,stderr=output,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.verification_folder=folder
            self.log('Bounded Demo stop check explicitly started; following remains off',origin='verification')
        return self.status()

    def pause(self,paused):
        if type(paused) is not bool:raise Invalid('paused must be boolean')
        with self.lock:
            if not self.running:raise Invalid('The demo session is not running')
            self.entries_enabled=not paused
        return self.status()

    def stop(self):
        self.stop_event.set()
        with self.lock:self.entries_enabled=False
        return self.status()

    def enqueue(self,kind,symbol=None,action=None):
        with self.lock:
            if not self.running or self.phase!='running':raise Invalid('Start and verify the demo session first')
            if kind=='rehearsal' and (symbol not in self.policy.symbols or action not in ('OPEN_LONG','OPEN_SHORT','CLOSE_LONG','CLOSE_SHORT')):
                raise Invalid('Choose an authorized symbol and explicit demo rehearsal action')
            if kind not in ('rehearsal','flatten_owned'):raise Invalid('Unknown demo action')
            try:self.commands.put_nowait(dict(kind=kind,symbol=symbol,action=action))
            except queue.Full:raise Invalid('Demo command queue is full') from None
        return dict(queued=True,testnet_only=True)

    def sync_funding(self,engine):
        from .signal_follow import sync_funding
        sync_funding(engine)

    def flatten_owned(self,engine,reason):
        for position in list(engine.book.positions()):
            event=dict(id='demo-flat-'+uuid.uuid4().hex,symbol=position['symbol'],action='CLOSE_'+position['side'],
                       source_time=now(),price=position['entry'])
            result=engine.handle(event);self.log(reason,origin='demo_owned_exit',symbol=position['symbol'],result=result['state'])

    def tick(self,engine,maintenance=True,funding=True):
        self.require_demo(engine.broker)
        if maintenance:
            if hasattr(engine.broker,'sync'):engine.broker.sync()
            engine.recover()
            if funding:self.sync_funding(engine)
            account=engine.check_account()
            with self.lock:self.account,self.account_updated=account,now()
            try:engine.risk_check(account)
            except RiskLimit:
                self.entries_enabled=False;self.flatten_owned(engine,'Cumulative limit: closing owned demo positions')
                raise
        source=self.source.inspect()
        while not self.commands.empty():
            if self.stop_event.is_set():return
            command=self.commands.get_nowait()
            if command['kind']=='flatten_owned':self.flatten_owned(engine,'User requested owned demo exit');continue
            action=command['action'];symbol=command['symbol']
            if action.startswith('OPEN') and not source['fresh']:
                self.log('Rehearsal entry skipped while public source is stale');continue
            if action.startswith('OPEN') and not self.entries_enabled:
                self.log('Rehearsal entry skipped while entries are paused');continue
            price='1'
            if action.startswith('OPEN'):
                bid,ask=engine.broker.quote(symbol);price=str(ask if action=='OPEN_LONG' else bid)
            event=dict(id='demo-rehearsal-'+uuid.uuid4().hex,symbol=symbol,action=action,source_time=now(),price=price)
            result=engine.handle(event);self.log('Explicit demo rehearsal',origin='rehearsal',symbol=symbol,action=action,result=result['state'],reason=result.get('reason'))
        from .signal_follow import process_public
        process_public(self,engine,source)

    def run(self):
        engine=None
        try:
            with execution_lease(self.data.parent/'demo-v2.lock'),self.io_lock:
                broker=self.broker or self.factory();self.require_demo(broker)
                if hasattr(broker,'sync'):broker.sync()
                prepare=self.scope_config.get('prepare_demo_leverage') is True
                engine=StrategyEngine(self.journal,self.policy,broker,prepare_demo_leverage=prepare)
                engine.recover();account=engine.check_account()
                if not account.get('can_trade'):raise Halt('Demo account does not permit trading')
                if not prepare:
                    for symbol in self.policy.symbols:
                        if int(broker.symbol_config(symbol)['leverage'])!=self.policy.leverage(symbol):
                            raise Halt('Set the matching leverage manually on the demo exchange for '+symbol)
                        broker.rules(symbol)
                elif not all(hasattr(broker,m) for m in ('symbol_class','prepare_leverage')):
                    raise Halt('The broker cannot prepare approved Demo contracts')
                source=self.source.inspect()
                if not source['fresh'] and not (source.get('watching') and source.get('status') in ('running','retrying')):
                    raise Halt('Public source is inactive at demo startup')
                # Do not guess what happened while stopped. Existing owned demo
                # positions require manual inspection/exit; never replay opens.
                if engine.book.positions():raise Halt('Recovered owned demo position: inspect its confirmed stop and manage it on the demo exchange before starting a new follow session')
                self.cursor=source['latest_id']
                with engine.book.db:engine.book.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('source_cursor',str(self.cursor)))
                with self.lock:self.broker,self.account,self.account_updated,self.phase=broker,account,now(),'running'
                self.source_waiting=not source['fresh']
                self.log('Demo following explicitly started; current history baselined, no old opening replay')
                next_maintenance=next_funding=0
                while not self.stop_event.is_set():
                    clock=time.monotonic()
                    maintenance=clock>=next_maintenance;funding=clock>=next_funding
                    self.tick(engine,maintenance,funding)
                    if maintenance:next_maintenance=clock+15
                    if funding:next_funding=clock+60
                    self.stop_event.wait(1)
        except Exception as exc:
            with self.lock:self.error=self.safe_error(exc);self.phase='error'
            self.log(self.error,'error')
        finally:
            if engine:engine.close()
            while not self.commands.empty():self.commands.get_nowait()
            with self.lock:
                self.running=self.entries_enabled=False
                if self.phase!='error':self.phase='stopped'

    def shutdown(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)
        self.control_stop.set()
        if self.listener:
            self.listener.close();(self.data.parent/'supervisor-control.token').unlink(missing_ok=True)
