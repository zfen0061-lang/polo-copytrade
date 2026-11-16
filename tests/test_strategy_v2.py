from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import json
import unittest
import pickle
import subprocess
import sys
import textwrap
from unittest.mock import patch

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
    def test_late_publication_uses_first_detection_for_entry_processing_deadline(self):
        event=signal('late-published',age=300)
        event['detected_time']=datetime.now(timezone.utc).isoformat()
        result=self.engine.handle(event)
        self.assertEqual(result['state'],'settled')
        self.assertEqual(self.broker.submit_count,1)
        self.assertGreater(float(result['price_check']['source_delay_seconds']),299)

    def test_absolute_three_percent_guard_rejects_both_sides_for_long_and_short(self):
        for index,(action,price) in enumerate([('OPEN_LONG','96.99'),('OPEN_LONG','103.01'),
                                               ('OPEN_SHORT','96.99'),('OPEN_SHORT','103.01')]):
            self.broker.price=D(price)
            result=self.engine.handle(signal('absolute-'+str(index),action))
            self.assertEqual(result['reason'],'entry_deviation')
            self.assertGreater(D(result['price_check']['absolute_percent']),3)
        self.assertEqual(self.broker.submit_count,0)

    def test_exact_three_percent_boundary_is_allowed_in_both_directions(self):
        for action in ('OPEN_LONG','OPEN_SHORT'):
            for price in ('97','103'):
                self.broker.price=D(price)
                intent,reason=self.engine.plan(signal('boundary-'+action+price,action))
                self.assertIsNone(reason);self.assertIsNotNone(intent)

    def test_matching_close_ignores_price_age_quote_and_leverage_entry_gates(self):
        self.engine.handle(signal('before-unconditional-exit'))
        self.broker.price=D('150')
        with patch.object(self.broker,'quote',side_effect=AssertionError('A market close needs no entry quote')), \
                patch.object(self.broker,'symbol_config',side_effect=AssertionError('Do not gate close on entry leverage')):
            result=self.engine.handle(signal('old-exit','CLOSE_LONG',age=300))
        self.assertEqual(result['state'],'settled')
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.submit_count,2)

    def test_exchange_stop_id_survives_restart_and_is_used_for_query_and_cancel(self):
        from unittest.mock import Mock
        original_place=self.broker.place_stop
        def acknowledge(params):
            state=original_place(params)
            return dict(state,algoId=987)
        self.broker.query_stop_id=Mock(side_effect=lambda order: next(iter(self.broker.stops.values())))
        self.broker.cancel_stop_id=Mock(side_effect=lambda order: self.broker.cancel_stop(next(iter(self.broker.stops))))
        with patch.object(self.broker,'place_stop',side_effect=acknowledge), \
                patch.object(self.broker,'query_stop',side_effect=AssertionError('Must use saved exchange id')):
            self.engine.handle(signal('exchange-id-open'))
            self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
            self.engine.recover()
            self.engine.handle(signal('exchange-id-close','CLOSE_LONG'))
        self.broker.query_stop_id.assert_called_with('987')
        self.broker.cancel_stop_id.assert_called_once_with('987')
        self.assertEqual(self.broker.submit_count,2)

    def test_stop_lookup_delay_is_requeried_without_another_submission(self):
        original_query=self.broker.query_stop
        queries=[0]
        def delayed(client):
            queries[0]+=1
            if queries[0]<3:raise APIError(-2013)
            return original_query(client)
        with patch.object(self.broker,'query_stop',side_effect=delayed),patch('backend.strategy_v2.time.sleep'):
            self.engine.handle(signal('delayed-stop-visibility'))
        self.assertEqual(queries[0],3)
        self.assertEqual(self.broker.submit_count,1)
        self.assertEqual(len(self.broker.stops),1)
        self.assertEqual(len(self.engine.book.positions()),1)

    def test_crossed_mark_price_stop_is_not_widened_and_demo_position_is_exited(self):
        from unittest.mock import Mock
        self.broker.mark_price=Mock(return_value='95')
        with self.assertRaisesRegex(Halt,'already crossed by mark price; no automatic stop widening'):
            self.engine.handle(signal('mark-crossed-stop'))
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.stops,{})

    def test_stop_rejection_does_not_hide_its_original_api_error(self):
        with patch.object(self.broker,'place_stop',side_effect=APIError(-2021)):
            with self.assertRaisesRegex(Halt,'Stop submission was not confirmed: Binance API code -2021; subsequent query: Binance API code -2013'):
                self.engine.handle(signal('rejected-stop'))
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.engine.book.positions(),[])
        # A missing stop is not silently treated as canceled during recovery.
        self.assertEqual(self.engine.book.db.execute('SELECT COUNT(*) FROM protection').fetchone()[0],1)

    def test_stop_cancel_accepts_delayed_terminal_status_without_resending(self):
        self.engine.handle(signal('delayed-cancel-open'))
        original_query=self.broker.query_stop
        stale=[True]
        def delayed_status(client):
            state=original_query(client)
            if state['algoStatus']=='CANCELED' and stale[0]:
                stale[0]=False
                return dict(state,algoStatus='NEW')
            return state
        with patch.object(self.broker,'query_stop',side_effect=delayed_status), \
                patch.object(self.broker,'cancel_stop',wraps=self.broker.cancel_stop) as cancel, \
                patch('backend.strategy_v2.time.sleep'):
            self.engine.handle(signal('delayed-cancel-close','CLOSE_LONG'))
        self.assertEqual(cancel.call_count,1)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.engine.book.db.execute('SELECT COUNT(*) FROM protection').fetchone()[0],0)

    def test_stop_cancel_lost_ack_is_verified_by_query(self):
        self.engine.handle(signal('cancel-ack-open'))
        original_cancel=self.broker.cancel_stop
        def cancel_then_timeout(client):
            original_cancel(client)
            raise TimeoutError('injected lost cancellation acknowledgement')
        with patch.object(self.broker,'cancel_stop',side_effect=cancel_then_timeout) as cancel:
            self.engine.handle(signal('cancel-ack-close','CLOSE_LONG'))
        self.assertEqual(cancel.call_count,1)
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.broker.open_stops('BTCUSDT'),[])

    def test_flat_position_with_unknown_cancel_retains_stop_and_reports_cleanup(self):
        self.engine.handle(signal('unknown-cancel-open'))
        with patch.object(self.broker,'cancel_stop',side_effect=TimeoutError('injected offline')), \
                patch('backend.strategy_v2.time.sleep'):
            with self.assertRaisesRegex(Halt,'flat; stop cleanup.*TimeoutError'):
                self.engine.handle(signal('unknown-cancel-close','CLOSE_LONG'))
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.engine.book.db.execute('SELECT COUNT(*) FROM protection').fetchone()[0],1)
        self.engine.recover()
        self.assertEqual(self.broker.open_stops('BTCUSDT'),[])

    def test_repeated_open_and_close_stay_deduplicated_across_restart(self):
        self.engine.handle(signal('stable-open'))
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        for _ in range(3):
            self.assertEqual(self.engine.handle(signal('stable-open'))['state'],'duplicate')
        self.assertEqual(self.broker.submit_count,1)
        self.engine.handle(signal('stable-close','CLOSE_LONG'))
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        for _ in range(3):
            self.assertEqual(self.engine.handle(signal('stable-close','CLOSE_LONG'))['state'],'duplicate')
            self.assertEqual(self.engine.handle(signal('stable-open'))['state'],'duplicate')
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.open_stops('BTCUSDT'),[])

    def test_filled_open_with_lost_ack_and_offline_query_recovers_without_resubmit(self):
        self.broker.lose_ack=True
        with patch.object(self.broker,'query',side_effect=TimeoutError('injected offline query')):
            with self.assertRaisesRegex(Halt,'unknown'):
                self.engine.handle(signal('offline-open'))
            self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
            with self.assertRaisesRegex(Halt,'no resubmission'):self.engine.recover()
            self.assertEqual(self.broker.submit_count,1)
            self.assertEqual(len(self.engine.book.pending()),1)
        self.engine.recover()
        self.assertEqual(self.broker.submit_count,1)
        self.assertEqual(self.engine.book.pending(),[])
        self.assertEqual(len(self.engine.book.positions()),1)
        self.assertEqual(len(self.broker.open_stops('BTCUSDT')),1)
        self.assertEqual(self.engine.handle(signal('offline-open'))['state'],'duplicate')

    def test_filled_close_with_lost_ack_recovers_and_cancels_remaining_stop(self):
        self.engine.handle(signal('before-offline-close'))
        self.broker.lose_ack=True
        with patch.object(self.broker,'query',side_effect=TimeoutError('injected offline query')):
            with self.assertRaisesRegex(Halt,'unknown'):
                self.engine.handle(signal('offline-close','CLOSE_LONG'))
            self.assertEqual(self.broker.submit_count,2)
            self.assertEqual(len(self.engine.book.pending()),1)
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.engine.recover()
        self.assertEqual(self.broker.submit_count,2)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.open_stops('BTCUSDT'),[])
        self.assertEqual(self.engine.handle(signal('offline-close','CLOSE_LONG'))['state'],'duplicate')

    def test_adverse_three_percent_filter_applies_to_both_entry_directions(self):
        self.broker.price=D('103.01')
        self.assertEqual(self.engine.handle(signal('too-high-long'))['reason'],'entry_deviation')
        self.broker.price=D('96.99')
        self.assertEqual(self.engine.handle(signal('too-low-short','OPEN_SHORT'))['reason'],'entry_deviation')
        self.assertEqual(self.broker.submit_count,0)

    def test_process_crash_after_exchange_fill_recovers_without_second_order(self):
        # The child has only a fake broker and a temporary journal; no API keys or network.
        exchange=Path(self.temp.name)/'fixture-exchange.pickle'
        child=textwrap.dedent('''
            import os,pickle,sys
            from tests.test_strategy_v2 import DemoFake,StrategyPolicy,StrategyEngine,signal
            policy=StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,
                {'BTCUSDT':'crypto','ETHUSDT':'crypto','ZECUSDT':'crypto','NVDAUSDT':'equity'})
            broker=DemoFake()
            engine=StrategyEngine(sys.argv[1],policy,broker)
            def crash_before_accounting(intent,response):
                with open(sys.argv[2],'wb') as output:pickle.dump(broker,output)
                os._exit(23)
            engine.settle=crash_before_accounting
            engine.handle(signal('process-crash-open'))
        ''')
        self.engine.close()
        result=subprocess.run([sys.executable,'-c',child,str(self.path),str(exchange)],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=15)
        self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.assertEqual(result.returncode,23,result.stderr.decode(errors='replace'))
        self.engine.close()
        with exchange.open('rb') as source:self.broker=pickle.load(source)
        self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.assertEqual(len(self.engine.book.pending()),1)
        self.engine.recover()
        self.assertEqual(self.broker.submit_count,1)
        self.assertEqual(self.engine.book.pending(),[])
        self.assertEqual(len(self.broker.open_stops('BTCUSDT')),1)
        self.assertEqual(self.engine.handle(signal('process-crash-open'))['state'],'duplicate')

    def test_restart_cancels_known_stop_left_after_a_verified_flat_close(self):
        self.engine.handle(signal('before-close-crash'))
        stop_id=next(iter(self.broker.stops))
        intent,_=self.engine.plan(signal('close-before-cancel','CLOSE_LONG'))
        self.engine.submit(intent)
        self.assertEqual(self.engine.book.positions(),[])
        self.assertEqual(self.broker.stops[stop_id]['algoStatus'],'NEW')
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.engine.recover()
        self.assertEqual(self.broker.stops[stop_id]['algoStatus'],'CANCELED')
        self.assertEqual(self.broker.submit_count,2)

    def test_demo_transport_rechecks_endpoint_before_account_or_market_reads(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        client=SimpleNamespace(environment='testnet',base='https://demo-fapi.binance.com',key='fake-demo',account=Mock(),quote=Mock(),rules=Mock(),sync=Mock())
        broker=DemoBroker(client);client.base='https://fapi.binance.com'
        for call in (broker.account,broker.sync,lambda:broker.rules('BTCUSDT'),lambda:broker.quote('BTCUSDT')):
            with self.assertRaises(Halt):call()
        for method in (client.account,client.sync,client.rules,client.quote):method.assert_not_called()

    def test_stop_verification_accepts_equivalent_numeric_format_and_checks_side(self):
        self.engine.handle(signal('numeric-stop'))
        stop=next(iter(self.broker.stops.values()))
        stop['triggerPrice']='96.00000000';stop['quantity']=format(D(stop['quantity']),'.8f')
        self.engine.recover()
        self.assertEqual(len(self.broker.stops),1)
        params=json.loads(self.engine.book.db.execute('SELECT params FROM protection').fetchone()[0])
        wrong=dict(stop,side='BUY')
        self.assertFalse(self.engine.stop_matches(wrong,params))
    def test_actual_stop_fill_is_reconciled_after_restart_without_reopening(self):
        self.engine.handle(signal('protected'))
        stop=next(iter(self.broker.stops.values()))
        self.broker.price=D('96')
        order=self.broker.place(dict(symbol='BTCUSDT',side='SELL',positionSide='LONG',quantity=stop['quantity'],newClientOrderId='exchange-stop-fill'))
        stop.update(algoStatus='FINISHED',actualOrderId=order['orderId'])
        def reject_cancel_finished(client):raise AssertionError('Finished stop must not be canceled')
        self.broker.cancel_stop=reject_cancel_finished
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.engine.recover()
        self.assertEqual(self.engine.book.positions(),[])
        self.assertLess(self.engine.book.capital(),D('60'))
        self.assertEqual(self.broker.submit_count,2)

    def test_replaced_stop_remains_in_journal_until_cancellation_is_confirmed(self):
        self.engine.handle(signal('replace-protection'))
        old=next(iter(self.broker.stops))
        self.broker.stops[old]['triggerPrice']='95'
        original_cancel=self.broker.cancel_stop
        def lost_cancel(client):raise TimeoutError('cancel acknowledgement unknown')
        self.broker.cancel_stop=lost_cancel
        with patch('backend.strategy_v2.time.sleep'):
            with self.assertRaisesRegex(Halt,'cancellation is not confirmed'):
                self.engine.protect('BTCUSDT','LONG','replacement')
        self.assertEqual(self.engine.book.db.execute('SELECT COUNT(*) FROM retired_stops').fetchone()[0],1)
        self.broker.cancel_stop=original_cancel
        self.engine.close();self.engine=StrategyEngine(self.path,self.policy,self.broker)
        self.engine.recover()
        self.assertEqual(self.broker.stops[old]['algoStatus'],'CANCELED')
        self.assertEqual(self.engine.book.db.execute('SELECT COUNT(*) FROM retired_stops').fetchone()[0],0)
        self.assertEqual(self.broker.submit_count,1)

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
