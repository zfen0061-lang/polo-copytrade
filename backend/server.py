from __future__ import annotations

import argparse
import csv
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import signal
import sys
from urllib.parse import urlsplit

from .core import Invalid,Store
from .feeds import Runner

ROOT=Path(__file__).resolve().parents[1]


def make_handler(store,runner,port):
    token=secrets.token_urlsafe(32)
    allowed_hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        server_version='CopyTradeStudio/0.1'

        def log_message(self,format,*args):
            # Request paths only; never log bodies, configuration or credentials.
            if len(args)>1 and str(args[1]).startswith(('4','5')):
                super().log_message(format,*args)

        def send(self,status,data,kind='application/json; charset=utf-8'):
            body=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
            self.send_response(status)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self):
            if self.headers.get('Host') not in allowed_hosts:
                self.send(403,{'error':'Invalid Host'})
                return False
            return True

        def do_GET(self):
            if not self.host_ok(): return
            route=urlsplit(self.path).path
            if route=='/api/session':
                self.send(200,{'csrf_token':token})
            elif route=='/api/state':
                self.send(200,store.snapshot())
            elif route=='/api/config/export':
                self.send(200,store.export_config())
            elif route=='/api/events.csv':
                events=store.snapshot()['events']
                output=io.StringIO(newline='')
                fields=['id','trader_id','source_id','action','symbol','source_time','first_seen','source_price','quote_price','delay_ms','deviation','status','reason']
                writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore')
                writer.writeheader()
                for e in events:
                    # Neutralize spreadsheet formula prefixes in untrusted text.
                    writer.writerow({k:("'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in e.items()})
                self.send(200,('\ufeff'+output.getvalue()).encode(),'text/csv; charset=utf-8')
            else:
                files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css'}
                name=files.get(route)
                if not name:
                    self.send(404,{'error':'Not found'})
                    return
                path=ROOT/'frontend'/name
                kind={'html':'text/html','js':'text/javascript','css':'text/css'}[name.split('.')[-1]]
                self.send(200,path.read_bytes(),kind+'; charset=utf-8')

        def do_POST(self):
            if not self.host_ok(): return
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed_hosts}:
                self.send(403,{'error':'Cross-origin mutation blocked'})
                return
            if not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),token):
                self.send(403,{'error':'Missing session token'})
                return
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise Invalid('Expected application/json')
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>100_000:
                    raise Invalid('Request too large')
                payload=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(payload,dict): raise Invalid('Expected object')
                route=urlsplit(self.path).path
                parts=route.strip('/').split('/')
                if route=='/api/traders':
                    result=store.save_trader(payload)
                elif len(parts)==4 and parts[:2]==['api','traders']:
                    trader_id,action=parts[2:]
                    if action=='config': result=store.save_trader(payload,trader_id)
                    elif action=='toggle':
                        if not isinstance(payload.get('enabled'),bool): raise Invalid('enabled must be boolean')
                        store.toggle(trader_id,payload['enabled']); result={'ok':True}
                    elif action=='close':
                        store.close_paper(trader_id,payload.get('symbol'),payload.get('side'));result={'ok':True}
                    elif action=='demo':result=runner.demo_once(trader_id,payload.get('scenario'))
                    else:self.send(404,{'error':'Not found'});return
                elif route=='/api/pause':
                    if not isinstance(payload.get('paused'),bool): raise Invalid('paused must be boolean')
                    store.pause_all(payload['paused']);result={'ok':True}
                elif route=='/api/mode':
                    if payload.get('mode')!='paper':
                        self.send(409,{'error':'Live execution is not available in this App. No credentials or real orders are accepted. / 本App尚未接入实盘，不接收交易密钥，也不发送真实订单。'})
                        return
                    result={'mode':'paper'}
                else:
                    self.send(404,{'error':'Not found'});return
                self.send(200,result)
            except (Invalid,ValueError,KeyError,TypeError) as error:
                self.send(400,{'error':str(error)})
            except Exception:
                self.send(500,{'error':'Internal error; inspect local server output'})

    return Handler


def main():
    parser=argparse.ArgumentParser(description='CopyTrade Studio — local paper copy-trading dashboard')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',type=Path,default=ROOT/'data'/'studio.sqlite3')
    parser.add_argument('--no-runner',action='store_true',help='API verification without scheduled signal processing')
    args=parser.parse_args()
    if not 1024<=args.port<=65535: parser.error('Choose a port between 1024 and 65535')
    store=Store(args.data)
    runner=Runner(store)
    try:
        server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,runner,args.port))
    except OSError:
        raise SystemExit('Port unavailable; choose --port 8766 or close the previous instance.')
    if not args.no_runner: runner.start()
    print(f'CopyTrade Studio: http://127.0.0.1:{args.port}',flush=True)
    print('PAPER ONLY. Demo data is synthetic; no live orders. Press Ctrl+C to stop.',flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if not args.no_runner: runner.shutdown()
        server.server_close()


if __name__=='__main__': main()
