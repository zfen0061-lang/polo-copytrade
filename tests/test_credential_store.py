import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.core import Invalid
from backend.credential_store import CredentialVault,WindowsUserProtection,migrate_pending_session,validate_pair,MAGIC
from backend.supervisor import MonitorSupervisor


class FakeProtection:
    def __init__(self):self.values={}
    def protect(self,value):
        token=b'fake-encrypted-'+str(len(self.values)).encode();self.values[token]=value;return token
    def unprotect(self,value):
        if value not in self.values:raise Invalid('Cannot unlock')
        return self.values[value]


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name)/'state.db'
        self.protection=FakeProtection();self.vault=CredentialVault(self.data,self.protection)
    def tearDown(self):self.temp.cleanup()

    def test_storage_contains_no_plaintext_and_roundtrip_is_exact(self):
        self.vault.save('fake-API-key','fake-API-secret')
        content=self.vault.path.read_bytes()
        self.assertNotIn(b'fake-API-key',content);self.assertNotIn(b'fake-API-secret',content)
        self.assertEqual(self.vault.load(),('fake-API-key','fake-API-secret'))
        self.vault.forget();self.assertIsNone(self.vault.load())

    def test_failed_replacement_keeps_previously_saved_connection(self):
        self.vault.save('fake-key','fake-secret')
        with patch.object(self.protection,'protect',side_effect=Invalid('Failed')):
            with self.assertRaises(Invalid):self.vault.save('other-key','other-secret')
        self.assertEqual(self.vault.load(),('fake-key','fake-secret'))

    def test_corrupt_or_wrong_context_data_fails_closed(self):
        self.vault.path.write_bytes(MAGIC+b'corrupt')
        with self.assertRaises(Invalid):self.vault.load()
        self.vault.path.write_bytes(b'plaintext-or-unknown-version')
        with self.assertRaises(Invalid):self.vault.load()

    def test_masked_credentials_are_not_saved(self):
        for secret in ('****','••••','....','bad secret','secret\n'):
            with self.subTest(secret=secret),self.assertRaises(Invalid):validate_pair('fake-key',secret)
        self.assertFalse(self.vault.exists())

    def test_supervisor_restores_saved_credentials_without_exposing_them(self):
        self.vault.save('fake-key','fake-secret')
        with patch('backend.credential_store.WindowsUserProtection',return_value=self.protection):
            supervisor=MonitorSupervisor(self.data)
        state=supervisor.snapshot()
        self.assertTrue(state['account_credentials_in_memory']);self.assertTrue(state['saved_connection'])
        self.assertFalse(state['auto_trading']);self.assertNotIn('fake-secret',json.dumps(state))
        self.assertEqual(state['credential_storage'],'windows_dpapi_user')

    def test_only_a_verified_readonly_client_can_be_remembered(self):
        from backend.live import LiveManager
        from backend.core import Store
        from tests.test_live import FakeAccount
        account=FakeAccount();account.base='https://fapi.binance.com';account.environment='production'
        account.key='fake-key';account.secret='fake-secret'
        manager=LiveManager(Store(self.data),factory=lambda:account,execution_allowed=False)
        with self.assertRaises(Invalid):manager.remember_connection()
        manager.connect()
        with patch('backend.credential_store.WindowsUserProtection',return_value=self.protection):
            self.assertTrue(manager.remember_connection()['saved'])
        self.assertEqual(self.vault.load(),('fake-key','fake-secret'));self.assertEqual(account.orders,[])
        manager.execution_allowed=True
        with self.assertRaises(Invalid):manager.remember_connection()

    def test_unlock_failure_preserves_public_monitoring_and_blocks_account_restore(self):
        self.vault.path.write_bytes(MAGIC+b'corrupt')
        with patch('backend.credential_store.WindowsUserProtection',return_value=self.protection):supervisor=MonitorSupervisor(self.data)
        self.assertIsNone(supervisor.credentials);self.assertTrue(supervisor.credential_error)
        self.assertFalse(supervisor.snapshot()['auto_trading'])

    def test_one_time_upgrade_is_explicit_local_and_expires(self):
        pending=self.data.parent/'remember-account-request.json'
        pending.write_text(json.dumps(dict(request_id='a'*32,expires_at=time.time()+30)))
        fake_env=dict(POLO_BINANCE_API_KEY='fake-key',POLO_BINANCE_API_SECRET='fake-secret',POLO_BINANCE_ENV='production')
        with patch.dict(os.environ,fake_env),patch.object(sys,'argv',['server','--read-only-account','--auto-connect-readonly']),patch('backend.credential_store.WindowsUserProtection',return_value=self.protection):
            migrate_pending_session(self.data)
        self.assertFalse(pending.exists());self.assertEqual(self.vault.load(),('fake-key','fake-secret'))
        receipt=json.loads((self.data.parent/'remember-account-result.json').read_text())
        self.assertTrue(receipt['saved']);self.assertNotIn('fake-secret',json.dumps(receipt))
        self.vault.forget()
        pending.write_text(json.dumps(dict(request_id='a'*32,expires_at=time.time()-1)))
        with patch.object(sys,'argv',['server','--read-only-account','--auto-connect-readonly']):migrate_pending_session(self.data)
        self.assertFalse(self.vault.exists())

    def test_regular_or_non_readonly_calls_cannot_save_a_connection(self):
        migrate_pending_session(self.data)
        pending=self.data.parent/'remember-account-request.json'
        pending.write_text(json.dumps(dict(request_id='a'*32,expires_at=time.time()+30)))
        with patch.object(sys,'argv',['server']):migrate_pending_session(self.data)
        self.assertFalse(self.vault.exists())

    @unittest.skipUnless(os.name=='nt','Native Windows DPAPI integration')
    def test_native_windows_roundtrip_and_tamper_rejection(self):
        native=CredentialVault(self.data)
        native.save('native-fake-key','native-fake-secret')
        self.assertEqual(native.load(),('native-fake-key','native-fake-secret'))
        content=bytearray(native.path.read_bytes());self.assertNotIn(b'native-fake-secret',content)
        content[-1]^=1;native.path.write_bytes(content)
        with self.assertRaises(Invalid):native.load()
