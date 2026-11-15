from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from backend.core import Invalid
from backend.executor import Halt,APIError
from backend.strategy_v2 import StrategyPolicy,StrategyEngine
from backend.demo_broker import DemoBroker


def signal(key,action='OPEN_LONG',symbol='BTCUSDT',age=0):
    return dict(id=key,action=action,symbol=symbol,price='100',
                source_time=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat())


class DemoFake:
    environment='testnet';base='https://demo-fapi.binance.com'
    def __init__(self,hedge=True,multi=True):
        self.hedge,self.multi=hedge,multi;self.positions={};self.orders={};self.by_id={};self.trades={};self.stops={}
        self.price=D('100');self.next_order=1;self.submit_count=0;self.lose_ack=False;self.unknown=False
        self.stop_failure=False;self.partial=D('1');self.fee_asset='USDT';self.last_params=None
    def identity(self):return 'demo-fixture-only'
    def account(self):
        return dict(hedge_mode=self.hedge,multi_assets=self.multi,available_usdt='10000',can_trade=True,
            positions=[dict(symbol=s,positionSide=side if self.hedge else 'BOTH',
                positionAmt=str(q if side=='LONG' else -q),entryPrice=str(entry),
                unRealizedProfit=str((self.price-entry)*q*(1 if side=='LONG' else -1)))
                for (s,side),(q,entry) in self.positions.items() if q])
    def symbol_config(self,symbol):return {'leverage':3 if symbol=='NVDAUSDT' else 10}
    def fee_rate(self,symbol):return '0.001'
    def open_orders(self,symbol):return []
    def open_stops(self,symbol):return [p for p in self.stops.values() if p['symbol']==symbol and p['algoStatus']=='NEW']
    def rules(self,symbol):return {'LOT_SIZE':dict(stepSize='0.01',minQty='0.01',maxQty='1000'),
        'MARKET_LOT_SIZE':dict(stepSize='0.01',minQty='0.01',maxQty='1000'),
        'PRICE_FILTER':dict(tickSize='0.01'),'MIN_NOTIONAL':dict(notional='5')}
    def quote(self,symbol):return self.price,self.price
    def place(self,params):
        self.submit_count+=1;self.last_params=dict(params)
        if self.unknown:raise TimeoutError('unknown demo order')
        symbol=params['symbol'];side=params['positionSide']
        if side=='BOTH':
            current=next((k[1] for k,v in self.positions.items() if k[0]==symbol and v[0]),None)
            side=current if params.get('reduceOnly')=='true' else ('LONG' if params['side']=='BUY' else 'SHORT')
        opening=(side=='LONG' and params['side']=='BUY') or (side=='SHORT' and params['side']=='SELL')
        qty=D(params['quantity'])*(self.partial if opening else 1)
        old,entry=self.positions.get((symbol,side),(D('0'),D('0')))
        realized=D('0')
        if opening:
            new_entry=(old*entry+qty*self.price)/(old+qty)
            self.positions[(symbol,side)]=(old+qty,new_entry)
        else:
            if qty>old:raise AssertionError('Would close more than owned')
            realized=(self.price-entry)*qty*(1 if side=='LONG' else -1)
            self.positions[(symbol,side)]=(old-qty,entry)
        order=self.next_order;self.next_order+=1
        response=dict(orderId=order,clientOrderId=params['newClientOrderId'],executedQty=str(qty),
                      status='EXPIRED' if self.partial<1 and opening else 'FILLED',avgPrice=str(self.price))
        self.orders[params['newClientOrderId']]=response;self.by_id[str(order)]=response
        self.trades[order]=[dict(id=order,orderId=order,symbol=symbol,qty=str(qty),price=str(self.price),
            realizedPnl=str(realized),commission=str(qty*self.price*D('0.001')),commissionAsset=self.fee_asset,
            time=int(datetime.now(timezone.utc).timestamp()*1000))]
        if self.lose_ack:self.lose_ack=False;raise TimeoutError('lost acknowledgement')
        return response
    def query(self,symbol,client):
        if client not in self.orders:raise APIError(-2013)
        return self.orders[client]
    def query_order_id(self,symbol,order):return self.by_id[str(order)]
    def fills(self,symbol,order):return self.trades[order]
    def place_stop(self,params):
        if self.stop_failure:raise TimeoutError('demo stop unavailable')
        self.stops[params['clientAlgoId']]=dict(params,algoStatus='NEW')
        return self.stops[params['clientAlgoId']]
    def query_stop(self,client):
        if client not in self.stops:raise APIError(-2013)
        return self.stops[client]
    def cancel_stop(self,client):self.stops[client]['algoStatus']='CANCELED'


class StrategyV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'journal.sqlite3'
        self.policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,
                                   {'BTCUSDT':'crypto','ETHUSDT':'crypto','ZECUSDT':'crypto','NVDAUSDT':'equity'})
        self.broker=DemoFake();self.engine=StrategyEngine(self.path,self.policy,self.broker)
    def tearDown(self):self.engine.close();self.temp.cleanup()

    def test_production_transport_is_rejected_before_any_order(self):
        self.broker.environment='production'
        with self.assertRaises(Halt):StrategyEngine(Path(self.temp.name)/'bad.db',self.policy,self.broker)
        with self.assertRaises(Halt):DemoBroker(self.broker)
        self.assertEqual(self.broker.submit_count,0)

    def test_loss_limit_basis_and_symbol_classification_must_be_explicit(self):
        raw=self.policy.public();raw['loss_basis']=''
        with self.assertRaises(Invalid):StrategyPolicy(**raw)
        raw=self.policy.public();raw['symbols']={'BTCUSDT':'guess'}
        with self.assertRaises(Invalid):StrategyPolicy(**raw)

    def test_hedge_multi_assets_roundtrip_compounds_only_verified_net_cash(self):
        self.engine.handle(signal('open'))
        position=self.engine.book.positions()[0];qty=D(position['qty'])
        self.assertLess(qty*100/10,60)
        stop=next(iter(self.broker.stops.values()))
        self.assertEqual(stop['positionSide'],'LONG');self.assertEqual(stop['triggerPrice'],'96.00')
        self.assertNotIn('reduceOnly',stop)
        self.broker.price=D('110');self.engine.handle(signal('close','CLOSE_LONG'))
        expected=D('60')+qty*10-qty*D('100')*D('0.001')-qty*D('110')*D('0.001')
        self.assertEqual(self.engine.book.capital(),expected)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.last_params['side'],'SELL')
        self.assertEqual(self.broker.last_params['positionSide'],'LONG')
        self.assertNotIn('reduceOnly',self.broker.last_params)
        self.broker.price=D('100')
        plan,_=self.engine.plan(signal('next'))
        self.assertGreater(D(plan['params']['quantity']),qty)
        self.assertLess(D(plan['params']['quantity'])*D(plan['params']['price'])/10,expected)

    def test_one_way_short_close_is_reduce_only_and_full_owned_quantity(self):
        self.broker.hedge=False
        self.engine.handle(signal('short','OPEN_SHORT'))
        qty=self.engine.book.positions()[0]['qty']
        self.engine.handle(signal('cover','CLOSE_SHORT'))
        self.assertEqual(self.broker.last_params['positionSide'],'BOTH')
        self.assertEqual(self.broker.last_params['side'],'BUY')
        self.assertEqual(self.broker.last_params['quantity'],qty)
        self.assertEqual(self.broker.last_params['reduceOnly'],'true')

    def test_lost_order_ack_is_queried_and_never_submitted_twice(self):
        self.broker.lose_ack=True
        self.engine.handle(signal('lost'))
        self.assertEqual(self.engine.handle(signal('lost'))['state'],'duplicate')
        self.assertEqual(self.broker.submit_count,1)

    def test_unknown_order_outcome_is_persisted_without_resubmission(self):
        self.broker.unknown=True
        with self.assertRaisesRegex(Halt,'unknown'):self.engine.handle(signal('unknown'))
        with self.assertRaises(Halt):self.engine.recover()
        self.assertEqual(self.broker.submit_count,1)
        self.assertEqual(len(self.engine.book.pending()),1)

    def test_partial_ioc_fill_is_accounted_and_protected_at_actual_quantity(self):
        self.broker.partial=D('0.5')
        self.engine.handle(signal('partial'))
        position=self.engine.book.positions()[0]
        stop=next(iter(self.broker.stops.values()))
        self.assertEqual(stop['quantity'],position['qty'])

    def test_unowned_manual_position_is_never_silently_taken_over(self):
        self.broker.positions[('BTCUSDT','LONG')]=(D('0.013'),D('63678.9'))
        with self.assertRaisesRegex(Halt,'Unowned'):self.engine.handle(signal('new'))
        self.assertEqual(self.broker.submit_count,0)

    def test_explicit_adoption_requires_exact_snapshot_and_policy_leverage(self):
        self.broker.positions[('BTCUSDT','LONG')]=(D('1'),D('100'))
        with self.assertRaisesRegex(Halt,'stale'):
            self.engine.adopt(dict(symbol='BTCUSDT',side='LONG',qty='2',entry='100'))
        self.engine.adopt(dict(symbol='BTCUSDT',side='LONG',qty='1',entry='100'))
        self.assertEqual(self.engine.book.positions()[0]['origin'],'adopted')
        self.assertEqual(self.broker.submit_count,0)

    def test_non_usdt_fees_are_not_silently_ignored(self):
        self.broker.fee_asset='BNB'
        with self.assertRaisesRegex(Halt,'conversion'):self.engine.handle(signal('bnb-fee'))
        self.assertEqual(self.engine.book.capital(),D('60'))
        self.assertEqual(len(self.engine.book.pending()),1)

    def test_funding_is_deduplicated_and_only_attributed_to_owned_intervals(self):
        self.engine.handle(signal('funded'))
        started=self.engine.book.positions()[0]['opened_ms']
        records=[dict(incomeType='FUNDING_FEE',asset='USDT',symbol='BTCUSDT',time=started+1,tranId=1,income='-1'),
                 dict(incomeType='FUNDING_FEE',asset='USDT',symbol='ETHUSDT',time=started+1,tranId=2,income='-100')]
        before=self.engine.book.capital();self.engine.book.funding(records);self.engine.book.funding(records)
        self.assertEqual(self.engine.book.capital(),before-1)

    def test_equity_uses_three_x_and_margin_stop_is_converted_per_symbol(self):
        self.engine.handle(signal('equity','OPEN_LONG','NVDAUSDT'))
        position=self.engine.book.positions()[0]
        self.assertEqual(position['leverage'],3)
        stop=next(iter(self.broker.stops.values()))
        self.assertEqual(stop['triggerPrice'],'86.67')

    def test_no_owned_position_cannot_be_opened_by_a_close_signal(self):
        result=self.engine.handle(signal('unowned-close','CLOSE_LONG'))
        self.assertEqual(result['reason'],'no_matching_owned_position')
        self.assertEqual(self.broker.submit_count,0)

    def test_stale_entries_are_skipped_and_pool_is_not_allocated_twice(self):
        self.assertEqual(self.engine.handle(signal('stale',age=120))['reason'],'entry_expired')
        self.engine.handle(signal('first'))
        self.assertEqual(self.engine.handle(signal('second','OPEN_LONG','ETHUSDT'))['reason'],'allocated_pool_in_use')

    def test_failed_stop_attempts_demo_emergency_exit_and_stops_session(self):
        self.broker.stop_failure=True
        with self.assertRaisesRegex(Halt,'Protection failed'):self.engine.handle(signal('stop-failed'))
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.submit_count,2)
