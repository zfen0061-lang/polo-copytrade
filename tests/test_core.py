from datetime import datetime,timedelta,timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from backend.core import Store,Invalid,validate_config,validate_url
from backend.feeds import parse_public,Runner


def event(key='one',action='OPEN_LONG',price='100',age=0,symbol='BTCUSDT'):
    return dict(source_id=key,action=action,symbol=symbol,price=price,
                source_time=(datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat())


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'state.db'
        self.store=Store(self.path)
        self.store.toggle('aoying',True)

    def tearDown(self): self.temp.cleanup()

    def test_three_percent_long_boundary(self):
        self.assertEqual(self.store.process('aoying',event(),D('102.99'),D('103'))['status'],'filled')
        self.assertEqual(self.store.process('aoying',event('too-far'),D('103'),D('103.01'))['status'],'skipped')

    def test_three_percent_short_boundary(self):
        self.assertEqual(self.store.process('aoying',event(action='OPEN_SHORT'),D('97'),D('97.01'))['status'],'filled')
        self.assertEqual(self.store.process('aoying',event('too-far','OPEN_SHORT'),D('96.99'),D('97'))['status'],'skipped')

    def test_favorable_price_is_allowed(self):
        self.assertEqual(self.store.process('aoying',event(),D('94.99'),D('95'))['status'],'filled')

    def test_duplicate_and_restart(self):
        e=event()
        self.store.process('aoying',e,100,100)
        self.store=Store(self.path)
        self.assertEqual(self.store.process('aoying',e,100,100)['status'],'duplicate')
        self.assertEqual(len(self.store.snapshot()['orders']),1)

    def test_initial_public_baseline_is_not_traded(self):
        self.assertEqual(self.store.process('aoying',event(),100,100,baseline=True)['status'],'baseline')
        self.assertEqual(self.store.snapshot()['orders'],[])

    def test_stale_entry_skipped_and_late_close_reduces_only(self):
        self.assertEqual(self.store.process('aoying',event('old',age=120),100,100)['status'],'skipped')
        self.store.process('aoying',event('open'),100,100)
        before=D(self.store.snapshot()['positions'][0]['qty'])
        self.assertEqual(self.store.process('aoying',event('late-close','CLOSE_LONG',age=120),90,90)['status'],'filled')
        after=D(self.store.snapshot()['positions'][0]['qty'])
        self.assertEqual(after,before/2)

    def test_close_without_position_never_opens_reverse(self):
        self.assertEqual(self.store.process('aoying',event(action='CLOSE_SHORT'),100,100)['status'],'skipped')
        self.assertEqual(self.store.snapshot()['positions'],[])

    def test_global_entry_pause_keeps_closes_available(self):
        self.store.process('aoying',event('open'),100,100)
        self.store.pause_all(True)
        self.assertEqual(self.store.process('aoying',event('blocked'),100,100)['status'],'skipped')
        self.assertEqual(self.store.process('aoying',event('close','CLOSE_LONG'),100,100)['status'],'filled')

    def test_paper_stop_and_fees(self):
        self.store.process('aoying',event(),100,100)
        self.store.mark('aoying','BTCUSDT',97,97)
        state=self.store.snapshot()
        self.assertEqual(state['positions'],[])
        self.assertEqual(state['orders'][0]['kind'],'STOP_LOSS')
        self.assertLess(D(state['metrics']['realized_net']),D('-1.5'))
        self.assertGreater(D(state['metrics']['fees']),0)

    def test_local_stop_keeps_running_for_paused_trader(self):
        self.store.process('aoying',event(),100,100)
        self.store.toggle('aoying',False)
        self.store.mark('aoying','BTCUSDT',97,97)
        self.assertEqual(self.store.snapshot()['positions'],[])

    def test_opposite_position_is_not_implicitly_reversed(self):
        self.store.process('aoying',event(),100,100)
        self.assertEqual(self.store.process('aoying',event('reverse','OPEN_SHORT'),100,100)['status'],'skipped')

    def test_small_budget_does_not_overallocate(self):
        self.store.toggle('aoying',False)
        t=self.store.get_trader('aoying')
        self.store.save_trader(dict(t,config=dict(t['config'],budget='30',order_margin='25',max_loss='10')),'aoying')
        self.store.toggle('aoying',True)
        self.store.process('aoying',event(),100,100)
        self.assertEqual(self.store.process('aoying',event('second'),100,100)['status'],'skipped')

    def test_traders_have_isolated_ledgers(self):
        other=self.store.save_trader(dict(name='Other',url='https://www.binance.com/copy-trading/lead-details/5075281354358777857',source='demo'))
        self.store.toggle(other['id'],True)
        e=event()
        self.store.process('aoying',e,100,100)
        self.store.process(other['id'],e,100,100)
        self.store.close_paper(other['id'])
        self.assertEqual({p['trader_id'] for p in self.store.snapshot()['positions']},{'aoying'})

    def test_config_changes_are_blocked_while_active_or_holding(self):
        t=self.store.get_trader('aoying')
        with self.assertRaises(Invalid): self.store.save_trader(t,'aoying')
        self.store.process('aoying',event(),100,100)
        self.store.toggle('aoying',False)
        with self.assertRaises(Invalid): self.store.save_trader(t,'aoying')

    def test_public_access_and_timezone_required(self):
        t=self.store.get_trader('aoying')
        self.store.toggle('aoying',False)
        with self.assertRaises(Invalid): self.store.save_trader(dict(t,source='binance_public'),'aoying')
        self.store.save_trader(dict(t,source='binance_public',authorized=True),'aoying')
        with self.assertRaises(Invalid): self.store.toggle('aoying',True)

    def test_invalid_numbers_and_urls_are_rejected(self):
        for val in ['NaN','Infinity','-5']:
            with self.assertRaises(Invalid): validate_config(dict(order_margin=val))
        for url in ['http://127.0.0.1:80/','https://www.binance.com.evil.test/copy-trading/lead-details/5075281354358777856','https://user@www.binance.com/copy-trading/lead-details/5075281354358777856']:
            with self.assertRaises(Invalid): validate_url(url)
        with self.assertRaises(Invalid): validate_config({'api_secret':'must-not-be-stored'})

    def test_signal_timestamp_must_have_timezone(self):
        e=event()
        e['source_time']='2026-11-15 00:00:00'
        with self.assertRaises(Invalid): self.store.process('aoying',e,100,100)

    def test_demo_signal_and_deviation_rejection(self):
        runner=Runner(self.store)
        self.assertEqual(runner.demo_once('aoying')['status'],'filled')
        self.assertEqual(runner.demo_once('aoying','over_deviation')['status'],'skipped')

    def test_account_allocation_includes_opening_fees(self):
        with self.store.db() as db:
            db.execute("UPDATE settings SET value='25' WHERE key='starting_balance'")
        self.assertEqual(self.store.process('aoying',event(),100,100)['status'],'skipped')
        self.assertEqual(self.store.snapshot()['positions'],[])

    def test_loss_budget_disables_the_trader(self):
        self.store.toggle('aoying',False)
        t=self.store.get_trader('aoying')
        self.store.save_trader(dict(t,config=dict(t['config'],max_loss='1')),'aoying')
        self.store.toggle('aoying',True)
        self.store.process('aoying',event(),100,100)
        self.store.mark('aoying','BTCUSDT',97,97)
        self.assertFalse(self.store.get_trader('aoying')['enabled'])
        self.assertEqual(self.store.snapshot()['positions'],[])

    def test_public_parser_preserves_direction_and_quantity(self):
        rows=parse_public('11-14, 02:51:48 开多 以均价为162.78775USDT 买入开多NVDAUSDT永续合约 ，成交数量为 1,582.28NVDA，总价值为257,575USDT。',2026,0)
        self.assertEqual(rows[0]['action'],'OPEN_LONG')
        self.assertEqual(rows[0]['source_quantity'],'1582.28')
        self.assertTrue(rows[0]['source_time'].endswith('+00:00'))
        with self.assertRaises(Invalid): parse_public('暂无数据',2026,0)


if __name__=='__main__': unittest.main()
