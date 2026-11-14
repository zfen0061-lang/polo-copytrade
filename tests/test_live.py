from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import itertools

from backend.core import Store,Invalid,DEFAULTS
from backend.executor import Halt,APIError
from backend.live import LiveManager,ProtectedEngine


class FakeAccount:
    live=True
    key='unit-test-key-not-a-real-key'
    secret='unit-test-secret-not-a-real-secret'
    environment='testnet'
    def __init__(self):
        self.qty=D('0');self.orders=[];self.stops={};self.fail_stop=False;self.uncertain=False
    def sync(self):pass
    def account(self):
        return dict(environment=self.environment,can_trade=True,hedge_mode=False,multi_assets=False,
                    wallet_balance='1000',equity='1000',available='1000',unrealized='0',updated=datetime.now(timezone.utc).isoformat(),
                    positions=[dict(symbol='BTCUSDT',positionSide='BOTH',positionAmt=str(self.qty),entryPrice='100',markPrice='100',unRealizedProfit='0',initialMargin='25',liquidationPrice='50')] if self.qty else [])
    def rules(self,symbol):
        return {'LOT_SIZE':dict(stepSize='0.01',minQty='0.01',maxQty='1000'),
                'MARKET_LOT_SIZE':dict(stepSize='0.01',minQty='0.01',maxQty='1000'),
                'PRICE_FILTER':dict(tickSize='0.01'),'MIN_NOTIONAL':dict(notional='5')}
    def quote(self,symbol):return D('100'),D('100')
    def preflight(self,symbols,ledger,leverage):
        if self.qty!=ledger.get('BTCUSDT',D('0')):raise Halt('Position mismatch')
    def place(self,p):
        self.orders.append(p)
        qty=D(p['quantity'])
        self.qty+=qty if p['side']=='BUY' else -qty
        result=dict(status='FILLED',executedQty=str(qty),avgPrice='100',clientOrderId=p['newClientOrderId'])
        self.last=result
        if self.uncertain:
            self.uncertain=False
            raise TimeoutError()
        return result
    def query(self,*args):return self.last
    def request(self,method,path,params=None,signed=False):
        if path!='/fapi/v1/algoOrder':raise AssertionError(path)
        key=params['clientAlgoId']
        if method=='POST':
            if self.fail_stop:raise APIError(-1)
            self.stops[key]=dict(params,algoStatus='NEW')
            return self.stops[key]
        if key not in self.stops:raise APIError(-2013)
        if method=='DELETE':self.stops[key]['algoStatus']='CANCELED'
        return self.stops[key]


def operation(key,action='买入开多',age=0):
    return dict(id=key,symbol='BTCUSDT',action=action,price='100',
                source_time=(datetime.now(timezone.utc)-timedelta(seconds=age)).strftime('%Y-%m-%d %H:%M:%S'))


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)
        self.store=Store(self.path/'app.db')
        self.account=FakeAccount()
        self.manager=LiveManager(self.store,factory=lambda:self.account)
        self.config=dict(mode='live',live_enabled=True,symbols=['BTCUSDT'],order_notional_usdt='50',leverage=2,
                         max_total_notional_usdt='200',close_rule='fixed_fraction_on_each_close',close_fraction='0.5',
                         source_utc_offset_minutes=0,max_signal_age_seconds=60,max_open_deviation='0.03',stop_loss_pct='0.02',
                         stop_file=str(self.path/'STOP'))
        self.engine=ProtectedEngine(self.config,self.path/'engine.db',self.account)
        self.baseline=operation('old',age=5)
        self.engine.on_poll([self.baseline])
    def tearDown(self):
        self.manager.shutdown();self.engine.db.close();self.temp.cleanup()

    def test_account_connection_is_read_only_and_masks_credentials(self):
        status=self.manager.connect()
        self.assertTrue(status['connected'])
        self.assertEqual(status['account']['wallet_balance'],'1000')
        self.assertEqual(self.account.orders,[])
        self.assertNotIn(self.account.key,json.dumps(status))
        self.assertNotIn(self.account.secret,json.dumps(status))

    def test_read_only_account_session_rejects_execution_at_backend(self):
        manager=LiveManager(self.store,factory=lambda:self.account,execution_allowed=False)
        try:
            status=manager.connect()
            self.assertTrue(status['connected'])
            self.assertFalse(status['execution_allowed'])
            with self.assertRaisesRegex(Invalid,'只读'):
                manager.start('aoying',dict(DEFAULTS,utc_offset_minutes=0),background=False)
            self.assertFalse(manager.watching)
            self.assertEqual(self.account.orders,[])
        finally:
            manager.shutdown()

    def test_demo_signals_cannot_be_armed_for_account_orders(self):
        self.manager.connect()
        c=dict(DEFAULTS,utc_offset_minutes=0)
        with self.assertRaises(Invalid):self.manager.start('aoying',c,background=False)
        self.assertEqual(self.account.orders,[])

    def test_signal_observer_cannot_be_started_as_an_account_execution_session(self):
        self.manager.connect()
        trader=self.store.get_trader('aoying')
        self.store.save_trader(dict(trader,source='binance_public',authorized=True),'aoying')
        with self.store.db() as db:
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',(json.dumps({'mode':'observe'}),'aoying'))
        with self.assertRaisesRegex(Invalid,'locked to signal observation'):
            self.manager.start('aoying',dict(DEFAULTS,utc_offset_minutes=0),background=False)
        self.assertFalse(self.manager.watching)
        self.assertEqual(self.account.orders,[])

    def test_compounding_draft_cannot_silently_use_legacy_fixed_amount_execution(self):
        from backend.policy_draft import make_compounding_draft
        self.manager.connect()
        with self.store.db() as db:
            db.execute('UPDATE traders SET execution_draft=? WHERE id=?',
                       (json.dumps(make_compounding_draft('60')),'aoying'))
        with self.assertRaisesRegex(Invalid,'compounding allocation is a draft'):
            self.manager.start('aoying',dict(DEFAULTS,utc_offset_minutes=0),background=False)
        self.assertFalse(self.manager.watching)
        self.assertEqual(self.account.orders,[])

    def test_incomplete_real_parameters_are_not_filled_with_demo_defaults(self):
        self.manager.connect()
        with self.assertRaises(Invalid):self.manager.start('aoying',{'budget':'100'},background=False)

    def test_missing_collector_is_reported_before_starting_account_session(self):
        self.manager.connect()
        trader=self.store.get_trader('aoying')
        self.store.save_trader(dict(trader,source='binance_public',authorized=True),'aoying')
        with patch('backend.doctor.collector_status',return_value=dict(installed=False,chromium=False,error='')):
            with self.assertRaisesRegex(Invalid,'setup.cmd'):
                self.manager.start('aoying',dict(DEFAULTS,utc_offset_minutes=0),background=False)
        self.assertFalse(self.manager.watching)
        self.assertEqual(self.account.orders,[])

    def test_open_fill_gets_confirmed_exchange_close_all_stop(self):
        self.engine.on_poll([operation('open'),self.baseline])
        stop=next(iter(self.account.stops.values()))
        self.assertEqual(stop['type'],'STOP_MARKET')
        self.assertEqual(stop['closePosition'],'true')
        self.assertEqual(stop['workingType'],'MARK_PRICE')
        self.assertNotIn('quantity',stop)
        self.assertNotIn('reduceOnly',stop)
        self.assertEqual(D(stop['triggerPrice']),D('98'))

    def test_partial_close_keeps_the_existing_close_all_protection(self):
        opened=operation('open')
        self.engine.on_poll([opened,self.baseline])
        previous=self.account.qty
        self.engine.on_poll([operation('close','卖出平多'),opened,self.baseline])
        self.assertEqual(self.account.qty,previous/2)
        self.assertEqual(len(self.account.stops),1)
        self.assertEqual(next(iter(self.account.stops.values()))['algoStatus'],'NEW')
        self.assertEqual(self.account.orders[-1]['reduceOnly'],'true')

    def test_full_close_cancels_owned_orphan_protection(self):
        opened=operation('open')
        self.engine.on_poll([opened,self.baseline])
        self.engine.config['close_fraction']='1'
        self.engine.on_poll([operation('close','卖出平多'),opened,self.baseline])
        self.assertEqual(self.account.qty,0)
        self.assertEqual(next(iter(self.account.stops.values()))['algoStatus'],'CANCELED')

    def test_unconfirmed_protection_attempts_reduce_only_exit_and_halts(self):
        self.account.fail_stop=True
        with self.assertRaises(Halt):self.engine.on_poll([operation('open'),self.baseline])
        self.assertEqual(self.account.qty,0)
        self.assertEqual(self.account.orders[-1]['reduceOnly'],'true')
        self.assertEqual(len(self.account.orders),2)

    def test_lost_fill_response_is_queried_and_not_resubmitted(self):
        self.account.uncertain=True
        with self.assertRaises(Halt):self.engine.on_poll([operation('open'),self.baseline])
        self.engine.recover()
        self.assertEqual(len(self.account.orders),1)
        self.assertEqual(len(self.account.stops),1)

    def test_partial_emergency_exit_preserves_remaining_position_for_review(self):
        self.account.fail_stop=True
        original=self.account.place
        def partial_exit(params):
            if params.get('reduceOnly')=='true':
                return original(dict(params,quantity=str(D(params['quantity'])/2)))
            return original(params)
        self.account.place=partial_exit
        with self.assertRaises(Halt):self.engine.on_poll([operation('open'),self.baseline])
        self.assertGreater(self.account.qty,0)
        self.assertEqual(self.engine.ledger()['BTCUSDT'],self.account.qty)
        self.assertEqual(len(self.account.orders),2)

    def test_triggered_exchange_stop_reconciles_to_flat(self):
        self.engine.on_poll([operation('open'),self.baseline])
        self.account.qty=D('0')
        next(iter(self.account.stops.values()))['algoStatus']='FINISHED'
        self.engine.reconcile()
        self.assertEqual(self.engine.ledger()['BTCUSDT'],0)

    def test_missing_account_stop_is_recovered_after_fill_persistence(self):
        self.engine.on_poll([operation('open'),self.baseline])
        with self.engine.db:self.engine.db.execute('DELETE FROM stops')
        self.account.stops.clear()
        self.engine.reconcile()
        self.assertTrue(self.account.stops)

    def test_manual_position_drift_stops_following(self):
        self.engine.on_poll([operation('open'),self.baseline])
        self.account.qty+=D('0.01')
        with self.assertRaises(Halt):self.engine.reconcile()

    def test_flat_account_can_change_explicit_parameters(self):
        self.engine.db.close()
        self.config['order_notional_usdt']='40'
        self.engine=ProtectedEngine(self.config,self.path/'engine.db',self.account)
        self.assertEqual(self.engine.config['order_notional_usdt'],'40')

    def test_open_account_cannot_change_parameters(self):
        self.engine.on_poll([operation('open'),self.baseline])
        self.config['order_notional_usdt']='40'
        with self.assertRaises(Halt):ProtectedEngine(self.config,self.path/'engine.db',self.account)

    def test_manually_flat_account_cleans_owned_stop_but_requires_review(self):
        self.engine.on_poll([operation('open'),self.baseline])
        self.account.qty=D('0')
        with self.assertRaises(Halt):self.engine.reconcile()
        self.assertEqual(self.engine.ledger()['BTCUSDT'],0)
        self.assertEqual(next(iter(self.account.stops.values()))['algoStatus'],'CANCELED')

    def test_stopping_during_a_source_fetch_does_not_submit_the_returned_signal(self):
        self.manager.connect()
        trader=self.store.get_trader('aoying')
        trader=self.store.save_trader(dict(trader,source='binance_public',authorized=True),'aoying')
        manager=self.manager
        timestamp=datetime.now(timezone.utc).isoformat()
        old=dict(source_id='source-baseline',symbol='BTCUSDT',price='100',action='OPEN_LONG',source_time=timestamp)
        new=dict(old,source_id='source-new')
        class Collector:
            count=0
            def fetch(self,known):
                self.count+=1
                if self.count==1:return [old],False
                manager.stop_event.set()
                return [new,old],False
            def close(self):pass
        self.manager.collector_factory=lambda *args:Collector()
        config=dict(self.config,budget='1000',order_margin='25',max_loss='100',poll_seconds=10)
        with patch('backend.live.time.monotonic',side_effect=itertools.count(0,100)):
            self.manager._run(trader,config)
        self.assertEqual(self.account.orders,[])


if __name__=='__main__':unittest.main()
