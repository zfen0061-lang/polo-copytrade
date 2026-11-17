"""Offline production fixtures: read recovery never enables a real account."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.core import Store,now
from backend.executor import APIError,ReadTimestampError,ClockSyncError,ReadNetworkError,Halt
from backend.production import ProductionBroker
from backend.real_session import RealSession
from backend.strategy_v2 import StrategyPolicy
from tests.test_production import ProductionClientFixture


class ReadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.net=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Real network forbidden'))
        self.net.start();self.addCleanup(self.net.stop)
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.source=Store(root/'source'/'state.db');trader=self.source.get_trader('aoying')
        self.source.save_trader(dict(trader,source='binance_public',authorized=True,
            config=dict(trader['config'],utc_offset_minutes=0)),'aoying')
        monitor=dict(mode='observe',owner='offline-recovery',heartbeat=time.time(),last_poll=now(),status='running',portfolio_id='5075281354358777856')
        with self.source.db() as db:db.execute('UPDATE traders SET enabled=1,signal_monitor=? WHERE id=?',(json.dumps(monitor),'aoying'))
        self.client=ProductionClientFixture()
        self.broker=ProductionBroker(self.client,entry_guard=lambda:self.session.entry_guard())
        self.session=RealSession(root/'real'/'state.db',self.source.path,factory=lambda:self.broker)
        self.session.configure(StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,{'BTCUSDT':'crypto'}).public())
        self.session.broker=self.broker;self.session.running=True;self.session.entries_enabled=True

    def tearDown(self):
        self.session.shutdown();self.temp.cleanup()

    def insert_open(self,age=0):
        detected=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat()
        with self.source.db() as db:
            db.execute('INSERT INTO events (trader_id,source_id,action,symbol,source_time,first_seen,source_price,source_quantity,delay_ms,status,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('aoying','recovery-open','OPEN_LONG','BTCUSDT',now(),detected,'100','1',0,'observed','offline fixture'))

    def run_with_read_failure(self,age=0,paused=False,error=None):
        tick=self.session.tick;calls=[];waits=[]
        def fake_tick(engine,maintenance=True,funding=True):
            calls.append((self.session.phase,self.session.entry_guard(),self.session.cursor))
            if len(calls)==1:
                if paused:self.session.entries_enabled=False
                with patch.object(self.broker,'account',side_effect=error or ReadTimestampError('/fapi/v3/account')):
                    tick(engine,maintenance,funding)
            else:
                tick(engine,maintenance,funding)
                self.session.stop_event.set()
        def wait(delay):
            waits.append(delay)
            if len(waits)==1:
                self.assertEqual(self.session.phase,'recovering')
                self.assertFalse(self.session.entry_guard())
                self.assertFalse(self.session.status()['entries_allowed'])
                self.insert_open(age)
            return False
        with patch.object(self.session,'tick',side_effect=fake_tick),patch.object(self.session.stop_event,'wait',side_effect=wait):
            self.session.run()
        return calls,waits

    def test_read_recovers_with_same_cursor_and_one_entry_without_duplicate(self):
        calls,waits=self.run_with_read_failure()
        self.assertEqual(len(calls),2);self.assertEqual(calls[1],('recovering',False,0))
        self.assertEqual(waits[0],2);self.assertEqual(self.client.exchange.submit_count,1)
        self.assertEqual(len(self.client.exchange.stops),1)
        self.assertEqual(self.session.journal_state()['pending_count'],0)
        self.assertEqual(self.session.error,'');self.assertEqual(self.session.phase,'stopped')

    def test_recovery_never_refreshes_an_expired_signal_detection_time(self):
        self.run_with_read_failure(age=90)
        self.assertEqual(self.client.exchange.submit_count,0)
        record=next(log for log in self.session.logs if log.get('origin')=='public')
        self.assertEqual(record['reason'],'entry_expired')

    def test_user_entry_pause_survives_read_recovery(self):
        self.run_with_read_failure(paused=True)
        self.assertEqual(self.client.exchange.submit_count,0)
        record=next(log for log in self.session.logs if log.get('origin')=='public')
        self.assertEqual(record['reason'],'entries_paused')

    def test_repeated_planning_read_failures_keep_backoff_until_tick_succeeds(self):
        self.client.configs['BTCUSDT']=dict(symbol='BTCUSDT',leverage=10,marginType='ISOLATED',isAutoAddMargin=False)
        tick=self.session.tick;calls=[];waits=[]
        def process(engine,*args,**kwargs):
            calls.append(True)
            if len(calls)==1:self.insert_open()
            if len(calls)<=2:
                with patch.object(self.broker,'fee_rate',side_effect=ReadTimestampError('/fapi/v1/commissionRate')):
                    return tick(engine,*args,**kwargs)
            tick(engine,*args,**kwargs);self.session.stop_event.set()
        def wait(delay):waits.append(delay);return False
        with patch.object(self.session,'tick',side_effect=process),patch.object(self.session.stop_event,'wait',side_effect=wait):
            self.session.run()
        self.assertEqual(waits[:2],[2,4]);self.assertEqual(len(calls),3)
        self.assertEqual(self.client.exchange.submit_count,1);self.assertEqual(self.session.error,'')

    def test_clock_sampling_failure_uses_same_read_only_recovery(self):
        self.run_with_read_failure(error=ClockSyncError('clock sample too slow'))
        self.assertEqual(self.client.exchange.submit_count,1)

    def test_disconnected_account_get_recovers_without_a_refresh_click(self):
        self.run_with_read_failure(error=ReadNetworkError('/fapi/v3/account'))
        self.assertEqual(self.client.exchange.submit_count,1)
        self.assertEqual(self.session.error,'')

    def test_network_outage_lasts_multiple_retries_then_resumes(self):
        tick=self.session.tick;attempts=[];waits=[]
        def process(engine,*args,**kwargs):
            attempts.append(True)
            if len(attempts)<=8:raise ReadNetworkError('/fapi/v3/account')
            tick(engine,*args,**kwargs);self.session.stop_event.set()
        with patch.object(self.session,'tick',side_effect=process),patch.object(self.session.stop_event,'wait',side_effect=lambda d:waits.append(d) or False):
            self.session.run()
        self.assertEqual(waits[:8],[2,4,8,16,32,60,60,60])
        self.assertEqual(self.session.error,'');self.assertEqual(self.client.exchange.submit_count,0)

    def test_lost_entry_response_and_offline_query_are_reconciled_without_resubmit(self):
        tick=self.session.tick;request=self.client.request;calls=[];waits=[];offline=[False]
        def transport(method,path,params=None,signed=False):
            if path=='/fapi/v1/order' and method=='POST':
                response=request(method,path,params,signed);offline[0]=True
                raise Halt('lost acknowledgement')
            if path=='/fapi/v1/order' and method=='GET' and offline[0]:
                raise ReadNetworkError(path)
            return request(method,path,params,signed)
        def process(engine,*args,**kwargs):
            calls.append(True)
            if len(calls)==1:self.insert_open()
            tick(engine,*args,**kwargs)
            self.session.stop_event.set()
        def wait(delay):
            waits.append(delay)
            if delay>=2:
                self.assertEqual(self.session.phase,'recovering')
                self.assertEqual(self.session.journal_state()['pending_count'],1)
                self.assertFalse(self.session.status()['entries_allowed'])
                offline[0]=False
            return False
        with patch.object(self.client,'request',side_effect=transport),patch.object(self.session,'tick',side_effect=process),patch.object(self.session.stop_event,'wait',side_effect=wait):
            self.session.run()
        self.assertEqual(len(calls),2);self.assertEqual(waits[0],2)
        self.assertEqual(self.client.exchange.submit_count,1)
        self.assertEqual(self.session.journal_state()['pending_count'],0)
        self.assertEqual(len(self.client.exchange.stops),1);self.assertEqual(self.session.error,'')

    def test_authorization_get_outage_does_not_create_an_unknown_order(self):
        tick=self.session.tick;authorize=self.broker.authorize_write;calls=[];blocked=[False]
        def gate(method,path,params):
            if path=='/fapi/v1/order' and not blocked[0]:
                blocked[0]=True;raise ReadNetworkError('/fapi/v3/account')
            return authorize(method,path,params)
        # Contract configuration is already verified: the failed tick sends no writes.
        self.client.configs['BTCUSDT']=dict(symbol='BTCUSDT',leverage=10,marginType='ISOLATED',isAutoAddMargin=False)
        def process(engine,*args,**kwargs):
            calls.append(True)
            if len(calls)==1:self.insert_open()
            tick(engine,*args,**kwargs);self.session.stop_event.set()
        with patch.object(self.broker,'authorize_write',side_effect=gate),patch.object(self.session,'tick',side_effect=process),patch.object(self.session.stop_event,'wait',return_value=False):
            self.session.run()
        self.assertEqual(len(calls),2);self.assertEqual(self.client.exchange.submit_count,1)
        self.assertEqual(self.session.journal_state()['pending_count'],0);self.assertEqual(self.session.error,'')

    def test_account_refresh_preserves_the_worker_stop_reason(self):
        self.session.running=False;self.session.phase='error';self.session.error='Previous network failure'
        state=self.session.inspect()
        self.assertEqual(state['error'],'Previous network failure')
        self.assertFalse(state['running']);self.assertFalse(state['execution_armed'])

    def test_raw_api_error_is_not_assumed_to_be_a_read(self):
        with patch.object(self.session,'tick',side_effect=APIError(-1021)) as tick:
            self.session.run()
        tick.assert_called_once();self.assertEqual(self.session.phase,'error')
        self.assertFalse(self.session.running);self.assertIsNone(self.broker.permit)

    def test_any_write_attempt_blocks_whole_tick_replay(self):
        def tick(*args,**kwargs):
            self.broker.write_attempts+=1
            raise ReadTimestampError('/fapi/v3/account')
        with patch.object(self.session,'tick',side_effect=tick) as task:
            self.session.run()
        task.assert_called_once();self.assertEqual(self.session.phase,'error')
        self.assertEqual(self.client.exchange.submit_count,0)

    def test_pending_intent_blocks_automatic_read_recovery(self):
        def tick(engine,*args,**kwargs):
            with engine.book.db:engine.book.db.execute('INSERT INTO intents VALUES (?,?,?,?,NULL)',('unknown','unknown-client','uncertain','{}'))
            raise ReadTimestampError('/fapi/v3/account')
        with patch.object(self.session,'tick',side_effect=tick) as task:self.session.run()
        task.assert_called_once();self.assertEqual(self.session.phase,'error')
        self.assertEqual(self.session.journal_state()['pending_count'],1)

    def test_stop_interrupts_backoff_without_rearming(self):
        def wait(delay):self.session.stop_event.set();return True
        with patch.object(self.session,'tick',side_effect=ReadTimestampError('/fapi/v3/account')) as tick, \
                patch.object(self.session.stop_event,'wait',side_effect=wait):self.session.run()
        tick.assert_called_once();self.assertEqual(self.session.phase,'stopped')
        self.assertIsNone(self.broker.permit);self.assertFalse(self.session.running)
        self.assertFalse(self.session.read_recovery['active']);self.assertEqual(self.client.exchange.submit_count,0)


if __name__=='__main__':unittest.main()
