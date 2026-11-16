import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from backend.demo_connect import main
from backend.credential_store import DemoCredentialVault
from tests.test_credential_store import FakeProtection


class DemoConnectTests(unittest.TestCase):
    def test_remembered_demo_is_verified_before_saving_and_private_handoff(self):
        protection=FakeProtection()
        with patch('urllib.request.build_opener',return_value=self.opener()), \
                patch('getpass.getpass',side_effect=['fake-demo-key','fake-demo-secret']), \
                patch('backend.live.TradeClient') as client,patch('backend.demo_broker.DemoBroker') as broker, \
                patch('backend.credential_store.WindowsUserProtection',return_value=protection), \
                patch('backend.supervisor.control_request',return_value={'accepted':True}) as handoff:
            main([*self.options,'--remember'])
        client.assert_called_once_with(key='fake-demo-key',secret='fake-demo-secret',environment='testnet')
        broker.return_value.account.assert_called_once()
        self.assertEqual(DemoCredentialVault(self.data,protection).load(),('fake-demo-key','fake-demo-secret'))
        self.assertTrue(handoff.call_args.args[1]['remember'])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.data=self.root/'demo/state.db';self.source=self.root/'source/state.db'
        self.options=['--data',str(self.data),'--source-data',str(self.source),'--no-browser']
        self.state=dict(available=True,endpoint='https://demo-fapi.binance.com',configured=False,running=False,
            workspace_id=hashlib.sha256(os.path.normcase(str(self.data.resolve())).encode()).hexdigest()[:16])
    def tearDown(self):self.temp.cleanup()
    def opener(self):
        response=io.BytesIO(json.dumps(self.state).encode());response.headers={'Server':'PoloCopyTrade/test'}
        return Mock(open=Mock(return_value=response))

    def test_existing_configured_demo_is_reused_without_another_key_prompt(self):
        self.state['configured']=True
        with patch('urllib.request.build_opener',return_value=self.opener()),patch('getpass.getpass') as prompt,patch('backend.server.main') as server:
            main(self.options)
        prompt.assert_not_called();server.assert_not_called()

    def test_keys_are_handed_to_the_matching_local_demo_pipe_not_http_or_production(self):
        opener=self.opener()
        with patch('urllib.request.build_opener',return_value=opener),patch('getpass.getpass',side_effect=['fake-demo-key','fake-demo-secret']),patch('backend.supervisor.control_request',return_value={'accepted':True}) as handoff,patch('backend.server.main') as server:
            main(self.options)
        self.assertEqual(opener.open.call_count,1)
        handoff.assert_called_once_with(self.data,dict(command='credentials',key='fake-demo-key',secret='fake-demo-secret'))
        server.assert_not_called()

    def test_wrong_workspace_is_rejected_before_asking_for_keys(self):
        self.state['workspace_id']='different-workspace'
        with patch('urllib.request.build_opener',return_value=self.opener()),patch('getpass.getpass') as prompt,patch('backend.supervisor.control_request') as handoff:
            with self.assertRaises(SystemExit):main(self.options)
        prompt.assert_not_called();handoff.assert_not_called()

    def test_source_directory_cannot_be_used_for_demo_credential_channel(self):
        with patch('getpass.getpass') as prompt,patch('urllib.request.build_opener') as network:
            with self.assertRaises(SystemExit):main(['--data',str(self.source.parent/'other.db'),'--source-data',str(self.source)])
        prompt.assert_not_called();network.assert_not_called()

    def test_running_demo_credentials_cannot_be_replaced(self):
        self.state.update(configured=True,running=True)
        with patch('urllib.request.build_opener',return_value=self.opener()),patch('getpass.getpass') as prompt:
            with self.assertRaises(SystemExit):main([*self.options,'--replace'])
        prompt.assert_not_called()
