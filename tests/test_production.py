"""Offline exchange fixtures only. No real keys, HTTP trading or real money."""
from datetime import datetime,timezone
from decimal import Decimal as D
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.core import Store,Invalid,now
from backend.executor import Halt,APIError
from backend.demo_broker import DemoBroker
from backend.futures_broker import WriteBlocked
from backend.production import ProductionBroker,ProductionEngine,ExecutionPermit,policy_digest
from backend.real_session import RealSession
from backend.runtime_lock import execution_lease
from backend.strategy_v2 import StrategyPolicy,StrategyEngine
from tests.test_strategy_v2 import DemoFake,signal


class ProductionClientFixture:
    environment='production';base='https://fapi.binance.com';key='offline-fixture-key'
    def __init__(self):
        self.exchange=DemoFake(hedge=False,multi=False);self.calls=[];self.configs={};self.external_orders=[]
        self.available='10000';self.can_trade=True;self.quote_sequence=[];self.fee_burn=False
    def sync(self):pass
    def account(self):
        return dict(self.exchange.account(),environment='production',available=self.available,
                    available_usdt=self.available,can_trade=self.can_trade,wallet_balance=self.available)
    def config(self,symbol):return self.configs.setdefault(symbol,dict(symbol=symbol,leverage=20,marginType='CROSSED',isAutoAddMargin=False))
    def rules(self,symbol):return self.exchange.rules(symbol)
    def quote(self,symbol):
        price=self.quote_sequence.pop(0) if self.quote_sequence else self.exchange.price
        return D(price),D(price)
    def request(self,method,path,params=None,signed=False):
        p=dict(params or {});self.calls.append((method,path,p))
        if path=='/fapi/v3/account':return {'assets':[{'asset':'USDT','availableBalance':self.available}]}
        if path=='/fapi/v1/symbolConfig':return [self.config(p['symbol']).copy()]
        if path=='/fapi/v1/commissionRate':return {'takerCommissionRate':'0.001'}
        if path=='/fapi/v1/feeBurn':return {'feeBurn':self.fee_burn}
        if path=='/fapi/v1/exchangeInfo':
            return {'symbols':[dict(symbol=s,status='TRADING',quoteAsset='USDT',marginAsset='USDT',contractType='PERPETUAL',
                underlyingType='EQUITY' if s=='NVDAUSDT' else 'COIN',underlyingSubType=[],
                orderTypes=['LIMIT','MARKET','STOP_MARKET'],timeInForce=['IOC']) for s in ('BTCUSDT','ETHUSDT','NVDAUSDT')]}
        if path=='/fapi/v1/openOrders':return self.external_orders
        if path=='/fapi/v1/openAlgoOrders':return [v for v in self.exchange.stops.values() if v['algoStatus']=='NEW' and (not p.get('symbol') or v['symbol']==p['symbol'])]
        if path=='/fapi/v1/premiumIndex':return {'markPrice':str(self.exchange.price)}
        if path=='/fapi/v1/income':return []
        if path=='/fapi/v1/userTrades':return self.exchange.fills(p['symbol'],p['orderId'])
        if path=='/fapi/v1/leverage':self.config(p['symbol'])['leverage']=p['leverage'];return {'leverage':p['leverage']}
        if path=='/fapi/v1/marginType':self.config(p['symbol'])['marginType']=p['marginType'];return {'code':200}
        if path=='/fapi/v1/order':
            if method=='POST':return self.exchange.place(p)
            if 'orderId' in p:return self.exchange.query_order_id(p['symbol'],p['orderId'])
            return self.exchange.query(p['symbol'],p['origClientOrderId'])
        if path=='/fapi/v1/algoOrder':
            if method=='POST':
                result=self.exchange.place_stop(p);result['algoId']=len(self.exchange.stops)+100
                return result
            client=p.get('clientAlgoId') or next((k for k,v in self.exchange.stops.items() if str(v.get('algoId'))==str(p.get('algoId'))),None)
            if client is None:raise APIError(-2013)
            if method=='DELETE':self.exchange.cancel_stop(client)
            return self.exchange.query_stop(client)
        raise AssertionError((method,path))


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.net=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Real network forbidden in this fixture'))
        self.net.start();self.addCleanup(self.net.stop)
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.client=ProductionClientFixture();self.broker=ProductionBroker(self.client,entry_guard=lambda:True)
        self.policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,{'BTCUSDT':'crypto','ETHUSDT':'crypto','NVDAUSDT':'equity'})
        self.path=self.root/'real.sqlite3';self.engine=None;self.session=None
    def tearDown(self):
        if self.session:self.session.shutdown()
        if self.engine:self.engine.close()
        self.temp.cleanup()
    def activate(self):
        permit=ExecutionPermit(self.broker.identity(),policy_digest(self.policy),str(self.path.resolve()))
        self.engine=ProductionEngine(self.path,self.policy,self.broker,permit)
        return self.engine
    def session_fixture(self):
        self.source=Store(self.root/'source'/'state.db');t=self.source.get_trader('aoying')
        self.source.save_trader(dict(t,source='binance_public',authorized=True,config=dict(t['config'],utc_offset_minutes=0)),'aoying')
        monitor=dict(mode='observe',owner='offline',heartbeat=time.time(),last_poll=now(),status='running',portfolio_id='5075281354358777856')
        with self.source.db() as db:db.execute('UPDATE traders SET enabled=1,signal_monitor=? WHERE id=?',(json.dumps(monitor),'aoying'))
        self.session=RealSession(self.root/'real'/'state.db',self.source.path,factory=lambda:self.broker)
        self.broker.entry_guard=self.session.entry_guard
        self.session.configure(self.policy.public())
        return self.session
    def test_endpoint_separation_cannot_be_overridden_by_switching_demo_keys(self):
        with self.assertRaises(Halt):DemoBroker(self.client)
        with self.assertRaises(Halt):StrategyEngine(self.path,self.policy,self.broker)
        self.assertFalse(self.path.exists());self.assertEqual(self.client.calls,[])
    def test_opening_and_inspecting_workspace_never_arms_or_writes(self):
        session=self.session_fixture();state=session.inspect()
        self.assertFalse(state['running']);self.assertFalse(state['execution_armed']);self.assertFalse(state['review']['blockers'])
        self.assertTrue(all(method=='GET' for method,_,_ in self.client.calls));self.assertIsNone(self.broker.permit)
        with self.assertRaises(WriteBlocked):self.broker.place({'symbol':'BTCUSDT'})
    def test_wrong_expired_or_changed_review_cannot_start(self):
        session=self.session_fixture();review=session.inspect()['review']
        with self.assertRaises(Invalid):session.start({'confirmation':'START DEMO','nonce':review['nonce']})
        session.review['deadline']=0
        with self.assertRaises(Invalid):session.start({'confirmation':review['confirmation'],'nonce':review['nonce']})
        review=session.inspect()['review'];session.configure(self.policy.public())
        with self.assertRaises(Invalid):session.start({'confirmation':review['confirmation'],'nonce':review['nonce']})
        self.assertEqual(self.client.exchange.submit_count,0)
    def test_manual_positions_or_orders_block_start_without_adoption(self):
        session=self.session_fixture();self.client.exchange.positions[('BTCUSDT','LONG')]=(D('1'),D('100'))
        self.assertTrue(session.inspect()['review']['blockers']);self.assertEqual(session.journal_state()['positions'],[])
        self.client.exchange.positions.clear();self.client.external_orders=[{'symbol':'ETHUSDT'}]
        self.assertTrue(session.inspect()['review']['blockers']);self.assertEqual(self.client.exchange.submit_count,0)
    def test_one_way_single_asset_and_available_budget_are_required(self):
        session=self.session_fixture();self.client.exchange.hedge=True
        self.assertTrue(session.inspect()['review']['blockers'])
        self.client.exchange.hedge=False;self.client.available='59'
        self.assertTrue(session.inspect()['review']['blockers'])
    def test_real_long_full_exit_compounding_and_duplicate_use_shared_policy(self):
        engine=self.activate();result=engine.handle(signal('real-open'))
        self.assertEqual(result['state'],'settled');qty=engine.book.positions()[0]['qty']
        self.assertEqual(self.client.config('BTCUSDT')['marginType'],'ISOLATED')
        self.assertEqual(self.client.config('BTCUSDT')['leverage'],10)
        self.assertEqual(engine.handle(signal('real-open'))['state'],'duplicate')
        self.client.exchange.price=D('110');engine.handle(signal('real-close','CLOSE_LONG',age=7200))
        self.assertEqual(self.client.exchange.last_params['quantity'],qty)
        self.assertEqual(self.client.exchange.last_params['reduceOnly'],'true')
        self.assertEqual(engine.book.positions(),[]);self.assertGreater(engine.book.capital(),60)
        self.assertEqual(self.client.exchange.submit_count,2)
        self.assertFalse(self.broker.all_open_stops())
    def test_short_and_equity_receive_the_reviewed_leverage(self):
        engine=self.activate();engine.handle(signal('equity-open','OPEN_SHORT','NVDAUSDT'))
        self.assertEqual(self.client.config('NVDAUSDT')['leverage'],3)
        self.client.exchange.price=D('120');engine.handle(signal('equity-close','CLOSE_SHORT','NVDAUSDT'))
        self.assertEqual(engine.book.positions(),[])
    def test_outside_three_percent_open_is_skipped(self):
        engine=self.activate();self.client.exchange.price=D('103.01')
        self.assertEqual(engine.handle(signal('over-price'))['reason'],'entry_deviation')
        self.assertEqual(self.client.exchange.submit_count,0)
    def test_automatic_extra_margin_is_blocked_without_changing_it(self):
        engine=self.activate();self.client.config('BTCUSDT')['isAutoAddMargin']=True
        with self.assertRaisesRegex(Halt,'automatic margin'):engine.handle(signal('extra-margin'))
        self.assertEqual(self.client.exchange.submit_count,0)
        self.assertFalse(any(method!='GET' for method,_,_ in self.client.calls))
    def test_non_usdt_fee_mode_blocks_start_with_no_configuration_write(self):
        session=self.session_fixture();self.client.fee_burn=True
        state=session.inspect();self.assertIn('BNB',state['review']['blockers'][0])
        self.assertTrue(all(method=='GET' for method,_,_ in self.client.calls))
    def test_quote_leaving_band_before_post_is_skipped_without_phantom_pending(self):
        engine=self.activate();self.client.quote_sequence=['100','104']
        result=engine.handle(signal('late-price'))
        self.assertEqual(result['reason'],'entry_deviation_before_submission')
        self.assertEqual(engine.book.pending(),[]);self.assertEqual(self.client.exchange.submit_count,0)
    def test_lost_acknowledgement_is_queried_once_without_repeating_order(self):
        engine=self.activate();self.client.exchange.lose_ack=True
        self.assertEqual(engine.handle(signal('lost-reply'))['state'],'settled')
        self.assertEqual(self.client.exchange.submit_count,1);self.assertEqual(engine.book.pending(),[])
    def test_unknown_outcome_survives_restart_and_never_resends(self):
        engine=self.activate();self.client.exchange.unknown=True
        with self.assertRaises(Halt):engine.handle(signal('uncertain'))
        self.assertEqual(len(engine.book.pending()),1);engine.close();self.engine=None
        engine=self.activate()
        with self.assertRaises(Halt):engine.recover()
        self.assertEqual(self.client.exchange.submit_count,1)
    def test_actual_stop_fill_accounting_is_exercised_only_in_offline_fixture(self):
        engine=self.activate();engine.handle(signal('stop-open'));position=engine.book.positions()[0]
        stop=next(iter(self.client.exchange.stops.values()));self.client.exchange.price=D('96')
        result=self.client.exchange.place(dict(symbol='BTCUSDT',side='SELL',positionSide='BOTH',type='MARKET',
            reduceOnly='true',quantity=position['qty'],newClientOrderId='fixture-exchange-trigger'))
        stop.update(algoStatus='FINISHED',actualOrderId=result['orderId'])
        engine.recover();self.assertEqual(engine.book.positions(),[]);self.assertEqual(engine.book.pending(),[])
        self.assertLess(engine.book.capital(),60)
    def test_protection_failure_attempts_only_owned_emergency_exit(self):
        engine=self.activate();self.client.exchange.stop_failure=True
        with self.assertRaisesRegex(Halt,'Protection failed'):engine.handle(signal('missing-stop'))
        self.assertEqual(self.client.exchange.submit_count,2);self.assertEqual(engine.book.positions(),[])
    def test_revocation_and_endpoint_mutation_block_new_requests(self):
        engine=self.activate();self.broker.permit.revoked.set()
        with self.assertRaises(Halt):engine.handle(signal('revoked'))
        self.assertEqual(self.client.exchange.submit_count,0)
        self.client.base='https://demo-fapi.binance.com'
        with self.assertRaises(Halt):self.broker.account()
    def test_arbitrary_writes_and_external_stop_cancellation_are_blocked(self):
        self.activate()
        for method,path,params in [('POST','/fapi/v1/positionSide/dual',{'dualSidePosition':'true'}),
                ('POST','/fapi/v1/order',{'newClientOrderId':'arbitrary'}),
                ('DELETE','/fapi/v1/algoOrder',{'clientAlgoId':'manual-stop'})]:
            with self.subTest(path=path),self.assertRaises(WriteBlocked):self.broker.request(method,path,params)
        self.assertEqual(self.client.calls,[])
    def test_existing_manual_quantity_cannot_be_closed_after_it_changes(self):
        engine=self.activate();engine.handle(signal('open'));qty,entry=self.client.exchange.positions[('BTCUSDT','LONG')]
        self.client.exchange.positions[('BTCUSDT','LONG')]=(qty+1,entry)
        with self.assertRaises(Halt):engine.handle(signal('close','CLOSE_LONG'))
        self.assertEqual(self.client.exchange.submit_count,1)
    def test_running_state_uses_fixture_only_and_restart_does_not_auto_resume(self):
        session=self.session_fixture();review=session.inspect()['review']
        session.start({'confirmation':review['confirmation'],'nonce':review['nonce']})
        until=time.monotonic()+3
        while session.phase=='starting' and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(session.phase,'running');session.shutdown()
        restored=RealSession(session.data,self.source.path,factory=lambda:self.broker)
        try:self.assertFalse(restored.status()['execution_armed']);self.assertFalse(restored.running)
        finally:restored.shutdown()
        self.assertEqual(self.client.exchange.submit_count,0)
    def test_legacy_execution_lease_blocks_another_production_session(self):
        session=self.session_fixture();review=session.inspect()['review']
        with execution_lease(self.source.path.parent/'real-execution.lock'):
            session.start({'confirmation':review['confirmation'],'nonce':review['nonce']});session.thread.join(3)
        self.assertEqual(session.phase,'error');self.assertFalse(session.running)
        self.assertIsNone(self.broker.permit);self.assertEqual(self.client.exchange.submit_count,0)
    def test_demo_and_monitor_directories_are_rejected(self):
        session=self.session_fixture()
        for path in (self.source.path,self.source.path.parent/'demo-v2'/'state.db'):
            with self.assertRaises(Invalid):RealSession(path,self.source.path)
    def test_production_cannot_adopt_manual_positions(self):
        engine=self.activate()
        with self.assertRaises(Halt):engine.adopt({'symbol':'BTCUSDT','side':'LONG','qty':'1','entry':'100'})


if __name__=='__main__':unittest.main()
