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
        self.assertIn(b'CopyTrade Studio',self.request('/')[1])
        self.assertEqual(self.request('/app.js')[0],200)
        state=self.request('/api/state')[1]
        self.assertFalse(state['live_available'])
        self.assertEqual(state['mode'],'paper')

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

    def test_create_toggle_demo_and_export(self):
        payload=dict(name='Integration test',url='https://www.binance.com/copy-trading/lead-details/5075281354358777857',source='demo')
        status,trader=self.request('/api/traders',payload,self.token)
        self.assertEqual(status,200)
        self.assertEqual(self.request(f"/api/traders/{trader['id']}/toggle",{'enabled':True},self.token)[0],200)
        self.assertEqual(self.request(f"/api/traders/{trader['id']}/demo",{},self.token)[1]['status'],'filled')
        self.assertIn(b'first_seen',self.request('/api/events.csv')[1])
        self.assertEqual(self.request('/api/config/export')[1]['mode'],'paper')


if __name__=='__main__': unittest.main()
