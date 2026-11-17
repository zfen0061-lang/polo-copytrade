from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.core import Store,Invalid
from backend.observe import SignalObserver,AOYING_URL
from backend.feeds import PublicResponseUnavailable
from backend.connectivity import browser_network_failure


def operation(key,action='OPEN_LONG',symbol='BTCUSDT'):
    return dict(source_id=key,action=action,symbol=symbol,price='100',source_quantity='2.5',
                source_time=datetime.now(timezone.utc).isoformat())


class FakeCollector:
    def __init__(self):self.rows=[operation('old')];self.gap=False;self.closed=False
    def fetch(self,known):return self.rows,self.gap
    def close(self):self.closed=True


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'state.db')
        t=self.store.get_trader('aoying')
        self.store.save_trader(dict(t,source='binance_public',authorized=True,
                                   config=dict(t['config'],utc_offset_minutes=0)),'aoying')
        self.collector=FakeCollector()
        self.observer=SignalObserver(self.store,collector_factory=lambda:self.collector)
        self.observer.claim()
    def tearDown(self):
        self.observer.close()
        self.temp.cleanup()

    def test_baseline_new_operations_and_repeats_never_create_orders(self):
        self.assertEqual(self.observer.poll(),1)
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'baseline')
        self.collector.rows=[operation('new','CLOSE_SHORT','ZECUSDT'),*self.collector.rows]
        self.assertEqual(self.observer.poll(),1)
        self.assertEqual(self.observer.poll(),0)
        state=self.store.snapshot()
        self.assertEqual(state['events'][0]['status'],'observed')
        self.assertEqual(state['events'][0]['source_quantity'],'2.5')
        self.assertIsNone(state['events'][0]['quote_price'])
        self.assertEqual(state['orders'],[])
        self.assertEqual(state['positions'],[])
        meta=json.loads(state['traders'][0]['signal_monitor'])
        self.assertEqual(meta['new_count'],1)
        self.assertEqual(meta['polls'],3)

    def test_second_observer_cannot_claim_the_same_trader(self):
        with self.assertRaises(Invalid):SignalObserver(self.store).claim()

    def test_rebuilt_paused_observer_does_not_resume_collection(self):
        self.observer.close()
        with self.store.db() as db:
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',(json.dumps(dict(status='paused')),'aoying'))
        restarted=SignalObserver(self.store,collector_factory=lambda:self.collector)
        try:
            restarted.claim()
            self.assertFalse(self.store.get_trader('aoying')['enabled'])
            self.assertEqual(restarted.poll(),0)
            self.assertEqual(self.store.snapshot()['events'],[])
        finally:restarted.close()

    def test_crashed_browser_is_recreated_without_replaying_history(self):
        self.observer.poll()
        class TargetClosedError(RuntimeError):pass
        self.assertTrue(self.observer.recover_crashed_browser(TargetClosedError('Page crashed')))
        self.assertTrue(self.collector.closed)
        self.assertIsNone(self.observer.collector)
        replacement=FakeCollector()
        replacement.rows=[operation('after-crash'),*replacement.rows]
        self.observer.collector_factory=lambda:replacement
        self.assertEqual(self.observer.poll(),1)
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'observed')
        self.assertEqual(self.store.snapshot()['orders'],[])
        self.assertFalse(self.observer.recover_crashed_browser(Invalid('Public access restricted')))

    def test_expired_response_rebuild_preserves_cursor_and_detects_next_operation(self):
        self.observer.poll()
        self.assertTrue(self.observer.recover_crashed_browser(PublicResponseUnavailable('body expired')))
        self.assertTrue(self.observer.initialized)
        replacement=FakeCollector();replacement.rows=[operation('after-body-expiry'),*replacement.rows]
        self.observer.collector_factory=lambda:replacement
        self.assertEqual(self.observer.poll(),1)
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'observed')
        self.assertFalse(self.observer.recover_crashed_browser(Invalid('rate limited')))

    def test_restart_preserves_counts_and_rebaselines_missed_operations(self):
        self.observer.poll()
        self.observer.close()
        self.collector.rows=[operation('during-disconnection'),*self.collector.rows]
        restarted=SignalObserver(self.store,collector_factory=lambda:self.collector)
        try:
            restarted.claim();restarted.poll()
            state=self.store.snapshot()
            meta=json.loads(state['traders'][0]['signal_monitor'])
            self.assertEqual(meta['baseline_count'],2)
            self.assertEqual(meta['new_count'],0)
            self.assertEqual(len(state['events']),2)
            self.assertEqual(state['events'][0]['status'],'baseline')
            self.assertEqual(state['orders'],[])
        finally:restarted.close()

    def test_verified_transient_restart_retains_intervening_close_as_observed(self):
        self.observer.poll();self.observer.meta['restartable']=True
        self.observer.close('error','ConnectionError: temporarily busy')
        self.collector.rows=[operation('during-retry','CLOSE_LONG'),*self.collector.rows]
        restarted=SignalObserver(self.store,collector_factory=lambda:self.collector)
        try:
            restarted.claim();self.assertTrue(restarted.initialized);restarted.poll()
            self.assertEqual(self.store.snapshot()['events'][0]['status'],'observed')
            self.assertEqual(self.store.snapshot()['orders'],[])
        finally:restarted.close()

    def test_transient_failure_before_any_baseline_cannot_make_history_actionable(self):
        self.observer.meta['restartable']=True;self.observer.close('error','ConnectionError: busy')
        restarted=SignalObserver(self.store,collector_factory=lambda:self.collector)
        try:
            restarted.claim();self.assertFalse(restarted.initialized);restarted.poll()
            self.assertEqual(self.store.snapshot()['events'][0]['status'],'baseline')
        finally:restarted.close()

    def test_history_gap_stops_before_inserting_new_operations(self):
        self.observer.poll()
        self.collector.rows=[operation('new')]
        self.collector.gap=True
        with self.assertRaisesRegex(Invalid,'gap'):self.observer.poll()
        self.assertEqual(len(self.store.snapshot()['events']),1)

    def test_wifi_disconnect_keeps_retrying_and_preserves_public_history(self):
        self.observer.poll();self.observer.close()
        observer=SignalObserver(self.store,collector_factory=lambda:self.collector)
        observer.claim();observer.initialized=True
        poll=observer.poll;attempts=[];waits=[]
        def failing_poll():
            attempts.append(True)
            if len(attempts)<=7:
                raise RuntimeError('Page.goto: net::ERR_FAILED at '+AOYING_URL)
            self.collector.rows=[operation('after-wifi','CLOSE_LONG'),operation('old')]
            count=poll();observer.stop.set();return count
        def wait(seconds):waits.append(seconds);return observer.stop.is_set()
        with patch.object(observer,'claim'),patch.object(observer,'poll',side_effect=failing_poll),patch.object(observer.stop,'wait',side_effect=wait),patch('backend.observe.time.monotonic',side_effect=lambda:len(waits)*61):
            observer.run()
        self.assertEqual(len(attempts),8)
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'observed')
        self.assertEqual(self.store.snapshot()['orders'],[])
        self.assertTrue(self.collector.closed)

    def test_legacy_network_failure_can_restart_without_rebaselining_closes(self):
        self.observer.poll();self.observer.close('error','Error: Page.goto: net::ERR_FAILED at '+AOYING_URL)
        restarted=SignalObserver(self.store,collector_factory=lambda:self.collector)
        try:
            restarted.claim();self.assertTrue(restarted.initialized)
            self.collector.rows=[operation('missed-close','CLOSE_LONG'),*self.collector.rows]
            restarted.poll()
            self.assertEqual(self.store.snapshot()['events'][0]['status'],'observed')
        finally:restarted.close()

    def test_network_classification_never_bypasses_access_or_certificate_errors(self):
        self.assertTrue(browser_network_failure('Error: Page.goto: net::ERR_NETWORK_CHANGED at '+AOYING_URL))
        for message in ('Page.goto: net::ERR_CERT_AUTHORITY_INVALID','Public access restricted 403',
                        'rate limited 429','Operation history gap','parser ERR_FAILED','Page.goto: net::ERR_BLOCKED_BY_CLIENT'):
            self.assertFalse(browser_network_failure(message),message)

    def test_observer_mode_blocks_paper_execution(self):
        with self.assertRaisesRegex(Invalid,'observation only'):
            self.store.process('aoying',operation('unexpected'),100,100)
        self.assertEqual(self.store.snapshot()['orders'],[])

    def test_pause_and_resume_rebaseline_without_replaying_old_operations(self):
        self.observer.poll()
        self.store.toggle('aoying',False)
        self.assertEqual(self.observer.poll(),0)
        self.collector.rows=[operation('while-paused'),*self.collector.rows]
        self.store.toggle('aoying',True)
        self.observer.poll()
        self.assertEqual(self.store.snapshot()['events'][0]['status'],'baseline')

    def test_target_change_and_failed_read_only_guard_stop_collection(self):
        self.observer.guard=lambda:(_ for _ in ()).throw(Invalid('Guard rejected'))
        with self.assertRaisesRegex(Invalid,'Guard rejected'):self.observer.poll()
        self.assertEqual(self.store.snapshot()['events'],[])
        self.observer.guard=lambda:None
        self.store.toggle('aoying',False)
        trader=self.store.get_trader('aoying')
        self.store.save_trader(dict(trader,url=AOYING_URL[:-1]+'7'),'aoying')
        with self.assertRaisesRegex(Invalid,'target'):self.observer.poll()


if __name__=='__main__':unittest.main()
