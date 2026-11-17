"""Public-page signal observation. No account keys, quotes or order execution.

Can run beside an existing read-only account server without restarting it.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import uuid

from .core import Store,Invalid,now,validate_url
from .connectivity import transient_collector_failure,browser_network_failure
from .feeds import PublicCollector,PublicResponseUnavailable
from .paths import default_data_dir

AOYING_URL='https://www.binance.com/zh-CN/copy-trading/lead-details/5075281354358777856'
AOYING_NAME='熬鹰资本'


class DashboardUnavailable(Invalid):
    """Transient local-backend failure; source access/format errors stay blocked."""


class DashboardGuard:
    def __init__(self,base):
        if base!='http://127.0.0.1:8765':
            raise Invalid('The observer must use the local read-only dashboard on port 8765')
        self.base=base
        self.token=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self,path):
        with self.opener.open(self.base+path,timeout=5) as response:
            return json.load(response)

    def __call__(self):
        try:
            state=self.get('/api/live/state')
            token=self.get('/api/session')['csrf_token']
        except Exception:
            raise DashboardUnavailable('The local read-only dashboard is unavailable; observation stopped') from None
        if state.get('execution_allowed') is not False or state.get('watching'):
            raise Invalid('Signal observation requires an idle read-only account server')
        if self.token is not None and token!=self.token:
            raise Invalid('The dashboard session changed; restart observation for the new session')
        self.token=token


class SignalObserver:
    def __init__(self,store,trader_id='aoying',guard=None,collector_factory=None):
        self.store,self.trader_id=store,trader_id
        self.guard=guard or (lambda:None)
        self.collector_factory=collector_factory or (
            lambda:PublicCollector(AOYING_URL,0,timezone_id='UTC',expected_name=AOYING_NAME))
        self.owner=uuid.uuid4().hex
        self.stop=threading.Event()
        self.initialized=False
        self.collector=None
        self.meta={}

    def trader(self):
        trader=self.store.get_trader(self.trader_id)
        if (validate_url(trader['url'])!=AOYING_URL or trader['name']!=AOYING_NAME
                or trader['source']!='binance_public' or not trader['authorized']
                or trader['config']['utc_offset_minutes']!=0):
            raise Invalid('Observer target or verified UTC configuration changed; observation stopped')
        return trader

    def claim(self):
        self.guard()
        self.trader()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT signal_monitor FROM traders WHERE id=?',(self.trader_id,)).fetchone()
            old=json.loads(row[0] or '{}')
            if old.get('owner') and time.time()-old.get('heartbeat',0)<180:
                raise Invalid('Another observer already owns this trader')
            if db.execute('SELECT 1 FROM positions WHERE trader_id=?',(self.trader_id,)).fetchone():
                raise Invalid('Close this trader\'s paper positions before enabling observation')
            # A verified transient failure may reconnect to its existing public
            # history. Do not turn intervening closes into a new historical
            # baseline while an execution workspace is still following it.
            # Manual stops/pauses and a never-initialized observer still baseline.
            self.initialized=bool(old.get('status')=='error'
                and (old.get('restartable') is True or browser_network_failure(old.get('last_error','')))
                and db.execute("SELECT 1 FROM events WHERE trader_id=? AND source_id LIKE 'public:%' LIMIT 1",
                               (self.trader_id,)).fetchone())
            self.meta=dict(mode='observe',status='starting',owner=self.owner,pid=os.getpid(),
                           heartbeat=time.time(),started_at=now(),last_poll=None,last_error='',
                           baseline_count=old.get('baseline_count',0),new_count=old.get('new_count',0),polls=0,timezone='UTC',
                           portfolio_id='5075281354358777856',interval_seconds=15,resumed_cursor=self.initialized)
            db.execute('UPDATE traders SET signal_monitor=?,enabled=1 WHERE id=?',
                       (json.dumps(self.meta),self.trader_id))
            if old.get('status')=='paused':
                db.execute('UPDATE traders SET enabled=0 WHERE id=?',(self.trader_id,))
            self.store.log(db,self.trader_id,'info','熬鹰资本真实信号追踪已启动；仅观察，不创建模拟或实盘订单。首次读取只建立历史基线。')

    def update(self,**fields):
        self.meta.update(fields,heartbeat=time.time())
        with self.store.db() as db:
            old=json.loads(db.execute('SELECT signal_monitor FROM traders WHERE id=?',(self.trader_id,)).fetchone()[0] or '{}')
            if old.get('owner')!=self.owner:
                raise Invalid('Observer ownership changed')
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',(json.dumps(self.meta),self.trader_id))

    def poll(self):
        self.guard()
        trader=self.trader()
        if not trader['enabled']:
            self.initialized=False
            self.update(status='paused')
            return 0
        if self.collector is None:
            self.collector=self.collector_factory()
        with self.store.db() as db:
            known={r[0][7:] for r in db.execute("SELECT source_id FROM events WHERE trader_id=? AND source_id LIKE 'public:%'",(self.trader_id,))}
        rows,gap=self.collector.fetch(known if self.initialized else set())
        if gap:
            raise Invalid('Public operation history has a gap; observation paused for review')
        if not rows:
            raise Invalid('No complete visible operations; this does not mean the trader is flat')
        self.guard()
        if not self.trader()['enabled']:
            self.initialized=False
            self.update(status='paused')
            return 0
        baseline=not self.initialized
        count=0
        first_seen=now()
        with self.store.db() as db:
            for row in reversed(rows):
                source_time=datetime.fromisoformat(row['source_time'])
                if source_time.utcoffset() is None or source_time.utcoffset().total_seconds()!=0:
                    raise Invalid('Unexpected source timestamp timezone')
                delay=int((datetime.now(timezone.utc)-source_time).total_seconds()*1000)
                if delay < -5000:
                    raise Invalid('Future source timestamp; observation stopped')
                inserted=db.execute('INSERT OR IGNORE INTO events '
                    '(trader_id,source_id,action,symbol,source_time,first_seen,source_price,source_quantity,delay_ms,status,reason) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (self.trader_id,'public:'+row['source_id'],row['action'],row['symbol'],row['source_time'],
                     first_seen,row['price'],row['source_quantity'],delay,'baseline' if baseline else 'observed',
                     '历史基线，不执行' if baseline else '已观察公开操作，未创建订单；公开成交数量不代表减仓比例，杠杆未知'))
                count+=inserted.rowcount
            if baseline:
                self.store.log(db,self.trader_id,'info',f'公开操作历史基线已建立：{count} 条；旧操作不会触发订单。')
            elif count:
                self.store.log(db,self.trader_id,'info',f'发现 {count} 条新的熬鹰资本公开操作；仅记录信号，未下单。')
            db.execute('UPDATE traders SET baseline=1 WHERE id=?',(self.trader_id,))
        self.initialized=True
        self.update(status='running',last_poll=first_seen,last_error='',polls=self.meta['polls']+1,
                    baseline_count=self.meta['baseline_count']+(count if baseline else 0),
                    new_count=self.meta['new_count']+(0 if baseline else count))
        return count

    def close(self,status='stopped',error=''):
        try:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT signal_monitor FROM traders WHERE id=?',(self.trader_id,)).fetchone()
                old=json.loads(row[0] or '{}') if row else {}
                if old.get('owner')==self.owner:
                    self.meta.update(status=status,last_error=error,owner=None,heartbeat=time.time())
                    db.execute('UPDATE traders SET enabled=0,signal_monitor=? WHERE id=?',
                               (json.dumps(self.meta),self.trader_id))
                    self.store.log(db,self.trader_id,'error' if error else 'info',
                                   '真实信号追踪已停止。'+error)
        finally:
            if self.collector:
                self.collector.close()
                self.collector=None

    def recover_crashed_browser(self,error):
        # A crashed/closed browser cannot recover by retrying the same page.
        # Preserve the observation cursor; never reset rate limits or access denials.
        if not isinstance(error,PublicResponseUnavailable) and type(error).__name__!='TargetClosedError' and 'Page crashed' not in str(error):
            return False
        if self.collector:
            failed=self.collector
            self.collector=None
            try:failed.close()
            except Exception:pass
        return True

    def run(self):
        self.claim()
        failures=0
        status,error='stopped',''
        try:
            while not self.stop.is_set():
                try:
                    self.poll()
                    failures=0
                    self.stop.wait(15 if self.trader()['enabled'] else 1)
                except Invalid as exc:
                    self.meta['restartable']=isinstance(exc,DashboardUnavailable)
                    status,error='error',str(exc)
                    break
                except Exception as exc:
                    crashed=self.recover_crashed_browser(exc)
                    transient=transient_collector_failure(exc)
                    if transient and self.collector:
                        failed=self.collector;self.collector=None
                        try:failed.close()
                        except Exception:pass
                    failures+=1
                    error=type(exc).__name__+': '+str(exc).split('\n')[0][:200]
                    if failures>=5 and not transient:
                        self.meta['restartable']=crashed or type(exc).__name__ in ('TimeoutError','URLError','ConnectionError')
                        status='error'
                        break
                    delay=min(60 if transient else 300,30*2**min(failures-1,4))
                    self.update(status='retrying',last_error=error,retry_seconds=delay)
                    until=time.monotonic()+delay
                    while not self.stop.wait(min(15,max(0,until-time.monotonic()))):
                        try:
                            self.guard()
                            self.update(status='retrying')
                        except Invalid as exc:
                            status,error='error',str(exc)
                            self.stop.set()
                            break
                        if time.monotonic()>=until:
                            break
        finally:
            self.close(status,error if status=='error' else '')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Observe only the selected Aoying public portfolio; never place orders')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--trader',default='aoying')
    parser.add_argument('--backend',default='http://127.0.0.1:8765')
    args=parser.parse_args(argv)
    observer=SignalObserver(Store(args.data),args.trader,DashboardGuard(args.backend))
    try:
        observer.run()
    except KeyboardInterrupt:
        observer.stop.set()


if __name__=='__main__':
    main()
