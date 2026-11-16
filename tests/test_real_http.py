from pathlib import Path
import tempfile
import unittest
from backend.core import Store
from backend.feeds import Runner
from backend.server import make_handler
from backend.real_session import RealSession
from tests import test_http as helpers


class RealHTTPTests(unittest.TestCase):
    request=helpers.HTTPTests.request
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.store=Store(root/'real'/'state.db');self.runner=Runner(self.store);self.port=8767
        self.real=RealSession(self.store.path,root/'source'/'state.db')
        self.handler=make_handler(self.store,self.runner,self.port,real=self.real)
        self.token=self.request('/api/session')[1]['csrf_token']
    def tearDown(self):self.real.shutdown();self.temp.cleanup()
    def test_page_opens_disarmed_without_an_account_connection(self):
        status,page=self.request('/')
        self.assertEqual(status,200);self.assertIn('真实资金'.encode(),page)
        state=self.request('/api/real-v2/state')[1]
        self.assertFalse(state['running']);self.assertFalse(state['execution_armed']);self.assertFalse(state['connected'])
        self.assertEqual(self.request('/real-ui.js')[0],200)
    def test_csrf_origin_and_confirmation_are_required(self):
        self.assertEqual(self.request('/api/real-v2/start',{})[0],403)
        self.assertEqual(self.request('/api/real-v2/start',{},self.token,{'Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.request('/api/real-v2/start',{'confirmation':'START DEMO','nonce':'x'},self.token)[0],400)
        self.assertFalse(self.real.running)
    def test_browser_keys_legacy_controls_and_demo_orders_are_rejected(self):
        for path,payload in [('/api/real-v2/inspect',{'secret':'forbidden'}),('/api/live/start',{}),
                ('/api/demo-v2/start',{'confirmation':'START DEMO'}),('/api/real-v2/rehearsal',{}),
                ('/api/real-v2/flatten-owned',{'confirmation':'wrong'})]:
            with self.subTest(path=path):self.assertEqual(self.request(path,payload,self.token)[0],400)
    def test_default_account_workspace_does_not_expose_legacy_execution(self):
        self.handler=make_handler(self.store,self.runner,self.port)
        self.token=self.request('/api/session')[1]['csrf_token']
        self.assertFalse(self.request('/api/live/state')[1]['execution_allowed'])
        self.assertEqual(self.request('/api/live/start',{'config':{}},self.token)[0],400)


if __name__=='__main__':unittest.main()
