from pathlib import Path
import io
import json
import tempfile
import unittest

from backend.core import Store
from backend.feeds import Runner
from backend.server import make_handler


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'state.db')
        self.runner=Runner(self.store)
        # Exercise BaseHTTPRequestHandler's actual HTTP parser and response writer
        # through a byte-stream socket. This does not claim TCP/browser verification.
        self.port=8765
        self.handler=make_handler(self.store,self.runner,self.port)
        self.token=self.request('/api/session')[1]['csrf_token']

    def tearDown(self):
        self.temp.cleanup()

    def request(self,path,payload=None,token=None,headers=None):
        extra={'Host':f'127.0.0.1:{self.port}'}
        extra.update(headers or {})
        data=b''
        if payload is not None:
            data=json.dumps(payload).encode()
            extra['Content-Type']='application/json'
            if token: extra['X-CSRF-Token']=token
        extra['Content-Length']=str(len(data))
        method='POST' if payload is not None else 'GET'
        raw=(f'{method} {path} HTTP/1.0\r\n'+''.join(f'{k}: {v}\r\n' for k,v in extra.items())+'\r\n').encode()+data
        class StreamSocket:
            def __init__(self): self.output=bytearray()
            def makefile(self,*args): return io.BytesIO(raw)
            def sendall(self,value): self.output.extend(value)
        sock=StreamSocket()
        self.handler(sock,('127.0.0.1',12345),None)
        head,content=bytes(sock.output).split(b'\r\n\r\n',1)
        status=int(head.split(b'\r\n')[0].split()[1])
        return status,json.loads(content) if b'application/json' in head else content

    def test_frontend_assets_and_state(self):
        self.assertIn(b'Polo CopyTrade',self.request('/')[1])
        self.assertEqual(self.request('/app.js')[0],200)
        state=self.request('/api/state')[1]
        self.assertFalse(state['live_available'])
        self.assertEqual(state['mode'],'paper')

    def test_demo_execution_is_not_available_from_production_workspace(self):
        self.assertFalse(self.request('/api/demo-v2/state')[1]['available'])
        self.assertEqual(self.request('/api/demo-v2/start',{'confirmation':'START DEMO'},self.token)[0],400)
        self.assertEqual(self.request('/testnet.html')[0],200)
        self.assertEqual(self.request('/demo-ui.js')[0],200)
        self.assertEqual(self.store.snapshot()['orders'],[])

    def test_demo_controls_require_token_and_do_not_accept_browser_keys(self):
        from backend.demo_session import DemoSession
        demo=DemoSession(self.store.path.parent/'demo'/'state.db',self.store.path)
        self.handler=make_handler(self.store,self.runner,self.port,demo=demo)
        self.token=self.request('/api/session')[1]['csrf_token']
        self.assertEqual(self.request('/api/demo-v2/inspect',{})[0],403)
        self.assertEqual(self.request('/api/demo-v2/inspect',{'secret':'do-not-submit'},self.token)[0],400)
        self.assertEqual(self.request('/api/live/start',{},self.token)[0],400)
        self.assertEqual(self.request('/api/demo-v2/start',{'confirmation':'wrong'},self.token)[0],400)
        self.assertIn(b'FUTURES DEMO',self.request('/')[1])

    def test_mutations_require_token_and_same_origin(self):
        self.assertEqual(self.request('/api/pause',{'paused':True})[0],403)
        self.assertEqual(self.request('/api/pause',{'paused':True},self.token,{'Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.request('/api/pause',{'paused':True},self.token)[0],200)

    def test_host_and_path_boundaries(self):
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.test'})[0],403)
        self.assertEqual(self.request('/../backend/core.py')[0],404)

    def test_real_orders_are_not_enabled_by_api_switch(self):
        status,_=self.request('/api/mode',{'mode':'live'},self.token)
        self.assertEqual(status,409)
        self.assertEqual(self.store.snapshot()['orders'],[])

    def test_account_workspace_starts_disconnected_and_rejects_browser_credentials(self):
        status=self.request('/api/live/state')[1]
        self.assertFalse(status['connected'])
        self.assertFalse(status['watching'])
        self.assertIsNone(status['account'])
        self.assertEqual(self.request('/api/live/connect',{'api_secret':'do-not-submit-browser-secrets'},self.token)[0],400)
        self.assertEqual(self.request('/live-ui.js')[0],200)
        self.assertEqual(self.request('/polo-logo.png')[0],200)

    def test_remembering_rejects_browser_credentials_and_requires_a_session_token(self):
        route='/api/runtime/remember-account'
        self.assertEqual(self.request(route,{})[0],403)
        self.assertEqual(self.request(route,{'key':'fake','secret':'never-browser'},self.token)[0],400)
        self.assertEqual(self.request(route,{},self.token)[0],400)
        runtime=self.request('/api/runtime/state')[1]
        self.assertFalse(runtime['saved_connection'])

    def test_forgetting_saved_connection_does_not_start_or_disconnect_an_account(self):
        from backend.credential_store import CredentialVault
        vault=CredentialVault(self.store.path);vault.path.write_bytes(b'test-only-encrypted-placeholder')
        self.assertTrue(self.request('/api/runtime/state')[1]['saved_connection'])
        self.assertEqual(self.request('/api/runtime/forget-account',{},self.token)[0],200)
        self.assertFalse(vault.exists())
        live=self.request('/api/live/state')[1]
        self.assertFalse(live['watching']);self.assertFalse(live['connected'])

    def test_create_toggle_demo_and_export(self):
        payload=dict(name='Integration test',url='https://www.binance.com/copy-trading/lead-details/5075281354358777857',source='demo')
        status,trader=self.request('/api/traders',payload,self.token)
        self.assertEqual(status,200)
        self.assertEqual(self.request(f"/api/traders/{trader['id']}/toggle",{'enabled':True},self.token)[0],200)
        self.assertEqual(self.request(f"/api/traders/{trader['id']}/demo",{},self.token)[1]['status'],'filled')
        self.assertIn(b'first_seen',self.request('/api/events.csv')[1])
        self.assertEqual(self.request('/api/config/export')[1]['mode'],'paper')


if __name__=='__main__': unittest.main()
