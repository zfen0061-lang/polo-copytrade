from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest

from backend.core import Store,Invalid
from backend.observe import SignalObserver,AOYING_URL


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

    def test_history_gap_stops_before_inserting_new_operations(self):
        self.observer.poll()
        self.collector.rows=[operation('new')]
        self.collector.gap=True
        with self.assertRaisesRegex(Invalid,'gap'):self.observer.poll()
        self.assertEqual(len(self.store.snapshot()['events']),1)

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
