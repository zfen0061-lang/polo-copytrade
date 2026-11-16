from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend.core import Invalid
from backend.credential_store import CredentialVault,DemoCredentialVault,TradingCredentialVault
from backend.executor import APIError
from backend.production import ProductionBroker
from backend.real_session import RealSession
from backend.trading_connect import save_connection,main
from tests.test_credential_store import FakeProtection
from tests.test_production import ProductionClientFixture


class TradingConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=self.root/'real'/'state.db';self.source=self.root/'monitor'/'state.db'
        self.protection=FakeProtection()
        self.crypto=patch('backend.credential_store.WindowsUserProtection',return_value=self.protection);self.crypto.start()
        self.main_vault=CredentialVault(self.source);self.main_vault.save('fixture-main','fixture-main-secret')
        self.demo=DemoCredentialVault(self.root/'demo'/'state.db');self.demo.save('fixture-demo','fixture-demo-secret')
        self.vault=TradingCredentialVault(self.data)
        self.main_bytes=self.main_vault.path.read_bytes();self.demo_bytes=self.demo.path.read_bytes()
        self.state=dict(policy={},journal=dict(locked=False))
        self.reader=patch('backend.trading_connect.local_state',return_value=self.state);self.reader.start()
        self.client=ProductionClientFixture();self.client.key='fixture-child';self.broker=ProductionBroker(self.client)
        self.factory=Mock(return_value=self.broker)
    def tearDown(self):
        self.reader.stop();self.crypto.stop();self.temp.cleanup()
    def unchanged(self):
        self.assertEqual(self.main_vault.path.read_bytes(),self.main_bytes)
        self.assertEqual(self.demo.path.read_bytes(),self.demo_bytes)
    def test_dedicated_vault_has_no_plaintext_and_no_cross_context_fallback(self):
        self.vault.save('fixture-child','fixture-child-secret')
        self.assertNotEqual(self.vault.magic,self.main_vault.magic)
        self.assertNotEqual(self.vault.entropy,self.main_vault.entropy)
        self.assertEqual(self.vault.load(),('fixture-child','fixture-child-secret'))
        self.assertNotIn(b'fixture-child',self.vault.path.read_bytes());self.unchanged()
        self.vault.path.write_bytes(self.main_bytes)
        with self.assertRaises(Invalid):self.vault.load()
    def test_read_only_validation_saves_only_the_dedicated_child_connection(self):
        result=save_connection(self.data,self.source,'fixture-child','fixture-child-secret',self.factory)
        self.assertFalse(result['orders_started']);self.assertTrue(result['saved'])
        self.assertEqual(self.vault.load(),('fixture-child','fixture-child-secret'))
        self.assertTrue(all(method=='GET' for method,_,_ in self.client.calls));self.unchanged()
    def test_known_main_key_is_rejected_without_overwriting_any_connection(self):
        with self.assertRaisesRegex(Invalid,'main monitoring'):
            save_connection(self.data,self.source,'fixture-main','fixture-main-secret',self.factory)
        self.assertFalse(self.vault.exists());self.factory.assert_not_called();self.unchanged()
    def test_bad_credentials_keep_the_old_saved_child_and_main_connection(self):
        self.vault.save('old-child','old-secret');before=self.vault.path.read_bytes()
        self.broker.account=Mock(side_effect=APIError(-2015))
        with self.assertRaises(APIError):save_connection(self.data,self.source,'fixture-child','bad-secret',self.factory)
        self.assertEqual(self.vault.path.read_bytes(),before);self.unchanged()
    def test_different_account_cannot_replace_a_journal_with_activity(self):
        self.data.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.data.parent/'real-execution.sqlite3')) as db,db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO meta VALUES (?,?)',('fingerprint','different-account-history'))
        self.state['journal']['locked']=True
        with self.assertRaisesRegex(Invalid,'another account'):
            save_connection(self.data,self.source,'fixture-child','fixture-child-secret',self.factory)
        self.assertFalse(self.vault.exists());self.unchanged()
    def test_active_workspace_rejection_happens_before_hidden_key_prompt(self):
        with patch('backend.trading_connect.local_state',side_effect=Invalid('Stop execution')),patch('getpass.getpass') as prompt, \
                patch('backend.real_connect.main') as launch:
            with self.assertRaises(Invalid):main(['--data',str(self.data),'--source-data',str(self.source),'--no-browser'])
        prompt.assert_not_called();launch.assert_not_called();self.assertFalse(self.vault.exists());self.unchanged()
    def test_production_session_cannot_reuse_the_saved_main_connection(self):
        session=RealSession(self.data,self.source)
        try:
            self.assertFalse(session.status()['saved_connection'])
            with patch('backend.real_session.TradeClient') as client:
                with self.assertRaisesRegex(Invalid,'connect-trading-subaccount'):session.default_broker()
            client.assert_not_called();self.unchanged()
        finally:session.shutdown()


if __name__=='__main__':unittest.main()
