import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.supervisor import MonitorSupervisor,Child,control_request
from backend.live import LiveManager,ReadOnlyAccountPoller
from backend.core import Store,Invalid
from tests.test_live import FakeAccount


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=Path(self.temp.name)/'state.sqlite3'
        self.supervisor=MonitorSupervisor(self.data)
    def tearDown(self):
        self.supervisor.stop.set()
        if self.supervisor.listener:self.supervisor.listener.close()
        self.temp.cleanup()

    def test_restart_delay_is_bounded(self):
        child=Child('demo',[])
        for _ in range(50):child.schedule_restart(100)
        self.assertEqual(child.next_start,160)

    def test_status_sharing_error_does_not_crash_supervisor(self):
        with patch.object(Path,'replace',side_effect=PermissionError('busy')):
            self.supervisor.save_status()

    def test_permanent_source_failure_stays_blocked_after_parent_restart(self):
        with self.supervisor.store.db() as db:
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',(json.dumps(dict(status='error',last_error='Access denied',restartable=False)),'aoying'))
        restored=MonitorSupervisor(self.data)
        self.assertEqual(restored.children['observer'].blocked,'Access denied')

    def test_old_navigation_network_failure_is_recoverable_after_upgrade(self):
        with self.supervisor.store.db() as db:
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',
                (json.dumps(dict(status='error',last_error='Error: Page.goto: net::ERR_FAILED at https://www.binance.com/',restartable=False)),'aoying'))
        restored=MonitorSupervisor(self.data)
        self.assertFalse(restored.children['observer'].blocked)

    def test_credentials_stay_in_memory_and_never_appear_in_status_or_disk(self):
        self.supervisor.children['observer'].blocked='Access denied'
        self.supervisor.commands.put(dict(command='credentials',key='fake-private-key',secret='fake-private-secret'))
        with patch.object(self.supervisor,'terminate'):
            self.supervisor.process_commands()
        self.supervisor.save_status()
        content=self.supervisor.status_path.read_text()
        self.assertNotIn('fake-private-key',content)
        self.assertNotIn('fake-private-secret',content)
        self.assertTrue(json.loads(content)['account_credentials_in_memory'])
        self.assertFalse(json.loads(content)['auto_trading'])
        self.assertEqual(self.supervisor.children['observer'].blocked,'Access denied')

    def test_only_dead_observer_lease_is_cleared(self):
        with self.supervisor.store.db() as db:
            db.execute('UPDATE traders SET signal_monitor=? WHERE id=?',(json.dumps(dict(owner='old',pid=123,status='running')),'aoying'))
        with patch('backend.supervisor.process_alive',return_value=True):
            self.supervisor.clear_dead_lease('signal_monitor')
        self.assertEqual(json.loads(self.supervisor.store.get_trader('aoying')['signal_monitor'])['owner'],'old')
        with patch('backend.supervisor.process_alive',return_value=False):
            self.supervisor.clear_dead_lease('signal_monitor')
        self.assertIsNone(json.loads(self.supervisor.store.get_trader('aoying')['signal_monitor'])['owner'])

    def test_local_control_channel_has_no_order_command(self):
        self.supervisor.start_control()
        status=control_request(self.data,{'command':'status'})
        self.assertFalse(status['auto_trading'])
        denied=control_request(self.data,{'command':'place_order','symbol':'BTCUSDT'})
        self.assertFalse(denied['ok'])

    def test_poller_reconnects_readonly_account_without_a_browser_or_orders(self):
        account=FakeAccount()
        manager=LiveManager(self.supervisor.store,factory=lambda:account,execution_allowed=False)
        poller=ReadOnlyAccountPoller(manager)
        with patch.dict('os.environ',{'POLO_BINANCE_API_KEY':'fake','POLO_BINANCE_API_SECRET':'fake'}):
            self.assertTrue(poller.tick())
            self.assertTrue(poller.tick())
        self.assertTrue(manager.status()['connected'])
        self.assertEqual(account.orders,[])
        with self.assertRaises(Invalid):ReadOnlyAccountPoller(LiveManager(self.supervisor.store))
