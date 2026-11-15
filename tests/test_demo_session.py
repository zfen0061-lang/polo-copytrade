from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from decimal import Decimal as D

from backend.core import Store,Invalid,now
from backend.demo_session import DemoSession,PublicSource
from backend.executor import Halt
from backend.observe import AOYING_NAME
from backend.strategy_v2 import StrategyEngine,RiskLimit
from tests.test_strategy_v2 import DemoFake,StrategyPolicy,signal


class SessionBroker(DemoFake):
    def __init__(self):super().__init__();self.income=[]
    def funding(self,symbol,start_ms,end_ms):return [r for r in self.income if r['symbol']==symbol and start_ms<=r['time']<=end_ms]


class DemoSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=Store(self.root/'source'/'state.db')
        t=self.source.get_trader('aoying')
        self.source.save_trader(dict(t,source='binance_public',authorized=True,config=dict(t['config'],utc_offset_minutes=0)),'aoying')
        self.monitor=dict(mode='observe',status='running',owner='fixture',pid=123,heartbeat=time.time(),last_poll=now(),portfolio_id='5075281354358777856')
        self.set_source(self.monitor)
        self.broker=SessionBroker()
        self.session=DemoSession(self.root/'demo'/'state.db',self.source.path,factory=lambda:self.broker)
        self.policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,{'BTCUSDT':'crypto','ETHUSDT':'crypto'})
        self.session.configure(self.policy.public())
        self.engine=None
    def tearDown(self):
        self.session.shutdown()
        if self.engine:self.engine.close()
        self.temp.cleanup()
    def set_source(self,monitor):
        with self.source.db() as db:db.execute('UPDATE traders SET enabled=1,signal_monitor=? WHERE id=?',(json.dumps(monitor),'aoying'))
    def event(self,key,action='OPEN_LONG',status='observed'):
        with self.source.db() as db:
            db.execute('INSERT INTO events (trader_id,source_id,action,symbol,source_time,first_seen,source_price,source_quantity,delay_ms,status,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       ('aoying','public:'+key,action,'BTCUSDT',now(),now(),'100','1',0,status,'test fixture'))
    def activate_engine(self):
        self.engine=StrategyEngine(self.session.journal,self.policy,self.broker)
        self.session.entries_enabled=True
        return self.engine

    def test_source_reader_cannot_write_production_database(self):
        self.assertTrue(self.session.source.inspect()['fresh'])
        with self.session.source.db() as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('UPDATE traders SET enabled=0')
        self.assertTrue(self.source.get_trader('aoying')['enabled'])

    def test_policy_requires_explicit_loss_basis_and_demo_keys_are_separate(self):
        raw=self.policy.public();raw['loss_basis']=''
        with self.assertRaises(Invalid):self.session.configure(raw)
        with patch.dict('os.environ',{'POLO_BINANCE_API_KEY':'fake-production','POLO_BINANCE_API_SECRET':'fake-production-secret'},clear=True):
            with self.assertRaisesRegex(Invalid,'Demo API'):self.session.default_broker()

    def test_public_signal_to_hedge_multi_demo_order_full_close_and_compounding(self):
        engine=self.activate_engine();self.event('open')
        self.session.tick(engine)
        self.assertEqual(self.broker.submit_count,1)
        qty=D(engine.book.positions()[0]['qty']);self.assertTrue(self.broker.stops)
        self.broker.price=D('110');self.event('close','CLOSE_LONG')
        self.session.tick(engine)
        self.assertEqual(engine.book.positions(),[]);self.assertGreater(engine.book.capital(),D('60'))
        self.assertEqual(self.broker.last_params['quantity'],str(qty))
        self.session.tick(engine);self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.source.snapshot()['orders'],[])

    def test_paused_entries_still_process_closes_and_do_not_replay_skipped_entries(self):
        engine=self.activate_engine();self.event('open');self.session.tick(engine)
        self.session.entries_enabled=False;self.event('close','CLOSE_LONG');self.event('paused-open')
        self.session.tick(engine)
        self.assertEqual(self.broker.submit_count,2);self.assertEqual(engine.book.positions(),[])
        self.session.entries_enabled=True;self.session.tick(engine)
        self.assertEqual(self.broker.submit_count,2)

    def test_funding_is_synchronized_and_deduplicated_in_the_session(self):
        engine=self.activate_engine();self.event('funded');self.session.tick(engine)
        started=engine.book.positions()[0]['opened_ms']
        self.broker.income=[dict(symbol='BTCUSDT',incomeType='FUNDING_FEE',asset='USDT',time=started,tranId=5,income='-1')]
        previous=engine.book.capital();self.session.sync_funding(engine);self.session.sync_funding(engine)
        self.assertEqual(engine.book.capital(),previous-1)

    def test_cumulative_limit_closes_only_owned_demo_position_and_halts(self):
        engine=self.activate_engine();self.event('risk');self.session.tick(engine)
        with engine.book.db:engine.book.db.execute('INSERT INTO cash VALUES (?,?,?,?,?,?)',('fixture-loss','fixture','-60','USDT','BTCUSDT',int(time.time()*1000)))
        with self.assertRaises(RiskLimit):self.session.tick(engine)
        self.assertFalse(self.session.entries_enabled);self.assertEqual(engine.book.positions(),[])
        self.assertEqual(self.broker.submit_count,2)

    def test_stale_source_stops_new_orders(self):
        engine=self.activate_engine();self.event('queued')
        self.set_source(dict(self.monitor,status='retrying'))
        with self.assertRaisesRegex(Halt,'stale'):self.session.tick(engine)
        self.assertEqual(self.broker.submit_count,0)

    def test_start_baselines_old_openings_and_never_adopts_manual_positions(self):
        self.event('old')
        self.session.inspect();self.session.start('START DEMO')
        deadline=time.monotonic()+2
        while self.session.phase=='starting' and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.session.phase,'running');self.session.stop();self.session.thread.join(2)
        self.assertEqual(self.broker.submit_count,0)
        self.broker.positions[('BTCUSDT','LONG')]=(D('0.013'),D('63678.9'))
        self.session.start('START DEMO');self.session.thread.join(2)
        self.assertEqual(self.session.phase,'error');self.assertIn('Unowned',self.session.error)
        self.assertEqual(self.broker.submit_count,0)

    def test_configuration_cannot_silently_reset_an_active_capital_journal(self):
        engine=self.activate_engine();self.event('configured');self.session.tick(engine)
        raw=self.policy.public();raw['crypto_leverage']=5
        with self.assertRaisesRegex(Invalid,'journal'):self.session.configure(raw)
        self.assertEqual(self.session.policy.crypto_leverage,10)

    def test_production_transport_and_shared_data_are_rejected(self):
        with self.assertRaises(Invalid):DemoSession(self.source.path,self.source.path)
        with self.assertRaises(Invalid):DemoSession(self.source.path.parent/'other.db',self.source.path)
        self.broker.environment='production'
        with self.assertRaisesRegex(Halt,'production'):self.session.inspect()
        self.assertEqual(self.broker.submit_count,0)

    def test_private_demo_input_channel_does_not_accept_order_commands(self):
        from backend.supervisor import control_request
        self.session.start_control()
        denied=control_request(self.session.data,dict(command='place_order',symbol='BTCUSDT'))
        self.assertFalse(denied['accepted'])
        result=control_request(self.session.data,dict(command='credentials',key='fake-demo-key',secret='fake-demo-secret'))
        self.assertTrue(result['accepted'])
        self.assertTrue(self.session.status()['configured']);self.assertFalse(self.session.status()['connected'])
        self.assertNotIn('fake-demo-secret',json.dumps(self.session.status()))
        self.assertEqual(self.broker.submit_count,0)
