from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from contextlib import nullcontext

from backend.demo_verify import verify_stop
from backend.demo_verify import main
from tests.test_strategy_v2 import DemoFake,D


class DemoStopVerificationTests(unittest.TestCase):
    def test_tight_stop_already_crossed_by_mark_is_blocked_before_opening(self):
        self.broker.mark_price=Mock(return_value='99')
        report=verify_stop(self.broker,self.folder,3,lambda:self.clock,self.sleep)
        self.assertEqual(report['status'],'blocked')
        self.assertTrue(report['flat_verified']);self.assertTrue(report['protection_cleared'])
        self.assertEqual(self.broker.submit_count,0)
        self.assertEqual(report['reference_mark_price'],'99')

    def test_failed_run_preserves_local_diagnostics_without_starting_following(self):
        failed=dict(status='error',flat_verified=False,protection_cleared=False)
        with patch('backend.demo_verify.getpass.getpass',side_effect=['fake-demo-key','fake-demo-secret']), \
                patch('backend.demo_verify.default_data_dir',return_value=Path(self.temp.name)), \
                patch('backend.demo_verify.execution_lease',return_value=nullcontext()), \
                patch('backend.demo_verify.TradeClient'),patch('backend.demo_verify.DemoBroker'), \
                patch('backend.demo_verify.verify_stop',return_value=failed), \
                patch('backend.supervisor.control_request',return_value={'accepted':True}) as handoff:
            main([])
        handoff.assert_called_once()
        self.assertEqual(handoff.call_args.args[1]['command'],'credentials')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)/'run'
        self.broker=DemoFake();self.clock=0
    def tearDown(self):self.temp.cleanup()
    def sleep(self,seconds):self.clock+=seconds
    def test_exchange_stop_fill_is_distinct_from_manual_cleanup(self):
        def trigger(seconds):
            self.sleep(seconds)
            stop=next(s for s in self.broker.stops.values() if s['algoStatus']=='NEW')
            self.broker.price=D(stop['triggerPrice'])
            order=self.broker.place(dict(symbol='BTCUSDT',side='SELL',positionSide='LONG',
                quantity=stop['quantity'],newClientOrderId='fixture-exchange-stop'))
            stop.update(algoStatus='FINISHED',actualOrderId=order['orderId'])
        report=verify_stop(self.broker,self.folder,3,lambda:self.clock,trigger)
        self.assertEqual(report['status'],'passed')
        self.assertTrue(report['stop_triggered']);self.assertTrue(report['duplicate_checked'])
        self.assertTrue(report['flat_verified']);self.assertTrue(report['protection_cleared'])
        self.assertEqual(self.broker.submit_count,2)
        self.assertTrue((self.folder/'result.json').is_file())
    def test_timeout_closes_owned_position_but_does_not_claim_stop_fill(self):
        updates=[]
        self.broker.sync=Mock()
        report=verify_stop(self.broker,self.folder,20,lambda:self.clock,self.sleep,updates.append)
        self.assertEqual(report['status'],'timeout');self.assertFalse(report['stop_triggered'])
        self.assertTrue(report['flat_verified']);self.assertTrue(report['protection_cleared'])
        self.assertEqual(self.broker.submit_count,2)
        self.assertGreaterEqual(self.broker.sync.call_count,3)
        self.assertTrue(any(u['stage']=='waiting_for_exchange_stop' for u in updates))
        self.assertEqual(updates[-1]['stage'],'finished')
    def test_unowned_position_is_refused_without_any_order(self):
        self.broker.positions[('BTCUSDT','LONG')]=(D('1'),D('100'))
        report=verify_stop(self.broker,self.folder,3,lambda:self.clock,self.sleep)
        self.assertEqual(report['status'],'error');self.assertIn('empty account',report['error'])
        self.assertEqual(self.broker.submit_count,0)
    def test_production_transport_is_rejected(self):
        self.broker.environment='production'
        report=verify_stop(self.broker,self.folder,3,lambda:self.clock,self.sleep)
        self.assertEqual(report['status'],'error');self.assertEqual(self.broker.submit_count,0)
