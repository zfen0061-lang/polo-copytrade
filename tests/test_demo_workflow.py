import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend.core import Invalid
from backend.credential_store import CredentialVault,DemoCredentialVault,WindowsUserProtection
from backend.demo_session import DemoSession
from tests.test_credential_store import FakeProtection
from tests import test_demo_session as session_fixtures


class DemoVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'state.db'
        self.protection=FakeProtection()
    def tearDown(self):self.temp.cleanup()
    def test_demo_and_real_credentials_have_distinct_files_and_contexts(self):
        real=CredentialVault(self.data,self.protection);demo=DemoCredentialVault(self.data,self.protection)
        real.save('fake-real-key','fake-real-secret');demo.save('fake-demo-key','fake-demo-secret')
        self.assertNotEqual(real.path,demo.path)
        self.assertNotEqual(real.entropy,demo.entropy)
        self.assertEqual(real.load(),('fake-real-key','fake-real-secret'))
        self.assertEqual(demo.load(),('fake-demo-key','fake-demo-secret'))
        self.assertNotIn(b'fake-demo-secret',demo.path.read_bytes())
        demo.path.write_bytes(real.path.read_bytes())
        with self.assertRaises(Invalid):demo.load()
    def test_saved_demo_reconnects_without_starting_orders(self):
        demo=DemoCredentialVault(self.data,self.protection);demo.save('fake-demo-key','fake-demo-secret')
        with patch('backend.credential_store.WindowsUserProtection',return_value=self.protection):
            session=DemoSession(self.data,self.data.parent/'source'/'state.db',factory=Mock())
        state=session.status()
        self.assertTrue(state['configured']);self.assertTrue(state['saved_demo_connection'])
        self.assertFalse(state['connected']);self.assertFalse(state['running'])
        self.assertNotIn('fake-demo-secret',json.dumps(state));session.factory.assert_not_called()
    @unittest.skipUnless(os.name=='nt','Windows user-scoped encryption')
    def test_native_demo_dpapi_context_cannot_be_opened_as_production(self):
        data=WindowsUserProtection(DemoCredentialVault.entropy).protect(b'fake-demo-content')
        self.assertEqual(WindowsUserProtection(DemoCredentialVault.entropy).unprotect(data),b'fake-demo-content')
        with self.assertRaises(Invalid):WindowsUserProtection().unprotect(data)


class BackgroundVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=session_fixtures.DemoSessionTests();self.fixture.setUp();self.session=self.fixture.session
        self.session.vault.exists=Mock(return_value=True)
    def tearDown(self):self.fixture.tearDown()
    def test_worker_uses_saved_demo_keys_without_keys_in_arguments_or_environment(self):
        process=Mock();process.poll.return_value=None
        with patch.dict('os.environ',{'POLO_BINANCE_API_KEY':'fake-real','POLO_DEMO_API_SECRET':'fake-demo'}), \
                patch('backend.demo_session.subprocess.Popen',return_value=process) as launch:
            state=self.session.verify_stop('VERIFY DEMO STOP',2)
        args=launch.call_args.args[0];kwargs=launch.call_args.kwargs
        self.assertIn('--saved',args);self.assertIn('--no-handoff',args)
        self.assertNotIn('fake-real',str(args));self.assertNotIn('fake-demo',str(args))
        self.assertNotIn('POLO_BINANCE_API_KEY',kwargs['env']);self.assertNotIn('POLO_DEMO_API_SECRET',kwargs['env'])
        self.assertTrue(state['verification']['active']);self.assertFalse(state['running'])
        with self.assertRaisesRegex(Invalid,'stop check'):self.session.start('START DEMO')
        with self.assertRaisesRegex(Invalid,'stop check'):self.session.inspect()
        with self.assertRaises(Invalid):self.session.verify_stop('VERIFY DEMO STOP',2)
        self.assertEqual(self.fixture.broker.submit_count,0)
    def test_worker_report_is_visible_without_auto_starting_following(self):
        process=Mock();process.poll.return_value=0
        with patch('backend.demo_session.subprocess.Popen',return_value=process):
            self.session.verify_stop('VERIFY DEMO STOP',2)
        self.session.verification_folder.mkdir()
        report=dict(status='passed',stop_triggered=True,flat_verified=True,protection_cleared=True)
        (self.session.verification_folder/'result.json').write_text(json.dumps(report))
        state=self.session.status()
        self.assertEqual(state['verification']['result'],report)
        self.assertFalse(state['running']);self.assertFalse(state['entries_enabled'])
    def test_background_checks_require_confirmation_storage_and_bounded_wait(self):
        with self.assertRaises(Invalid):self.session.verify_stop('START REAL',2)
        with self.assertRaises(Invalid):self.session.verify_stop('VERIFY DEMO STOP',1000)
        self.session.vault.exists.return_value=False
        with self.assertRaisesRegex(Invalid,'Remember'):self.session.verify_stop('VERIFY DEMO STOP',2)
