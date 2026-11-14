import unittest
from backend.awake import AwakeRequest,CONTINUOUS,SYSTEM_REQUIRED
from backend.core import Invalid
from backend.policy_draft import make_compounding_draft,preview_pool_margin,set_margin_stop_target


class RuntimePolicyTests(unittest.TestCase):
    def test_compounding_uses_only_allocated_pool_and_verified_net_profit(self):
        self.assertEqual(preview_pool_margin('60','0','0','1','117'),59)
        self.assertEqual(preview_pool_margin('60','60','0','1','177'),119)
        self.assertEqual(preview_pool_margin('60','-15','0','1','102'),44)
        self.assertEqual(preview_pool_margin('60','0','60','1','117'),0)
        self.assertEqual(preview_pool_margin('60','0','0','1','30'),29)

    def test_draft_does_not_enable_execution_or_invent_risk_values(self):
        draft=make_compounding_draft('60')
        self.assertFalse(draft['execution_enabled'])
        self.assertEqual(draft['use_available_pool_fraction'],'1')
        self.assertEqual(draft['close_rule'],'full_owned_symbol_and_side')
        self.assertEqual(draft['close_fraction'],'1')
        self.assertIsNone(draft['price_stop_pct'])
        self.assertIsNone(draft['equity_leverage_policy'])
        self.assertEqual(draft['crypto_leverage_cap'],10)
        self.assertEqual(draft['equity_leverage_cap'],5)
        with self.assertRaises(Invalid):make_compounding_draft('-1')

    def test_margin_stop_target_records_user_percentage_without_enabling_orders(self):
        original=make_compounding_draft('60')
        updated=set_margin_stop_target(original,'0.40')
        self.assertEqual(updated['margin_stop_loss_fraction'],'0.40')
        self.assertEqual(updated['stop_mode'],'margin_loss_target')
        self.assertFalse(updated['execution_enabled'])
        self.assertIsNone(updated['max_loss_usdt'])
        self.assertIsNone(updated['price_stop_pct'])
        self.assertIn('verified_margin_stop_execution',updated['blockers'])
        self.assertNotIn('margin_stop_loss_fraction',original)
        for value in ('0','1','-0.1','NaN'):
            with self.assertRaises(Invalid):set_margin_stop_target(original,value)

    def test_sleep_guard_only_holds_on_ac_during_observation_and_releases(self):
        class Power:
            def __init__(self):self.flags=[]
            def set_state(self,flags):self.flags.append(flags)
        power=Power();guard=AwakeRequest(power)
        self.assertFalse(guard.update(False,True))
        self.assertTrue(guard.update(True,True))
        guard.update(True,True)
        self.assertEqual(power.flags,[CONTINUOUS|SYSTEM_REQUIRED])
        self.assertFalse(guard.update(False,True))
        self.assertFalse(guard.update(True,False))
        guard.update(True,True);guard.close()
        self.assertEqual(power.flags[-1],CONTINUOUS)
