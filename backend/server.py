from __future__ import annotations

import argparse
import csv
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import signal
import socket
import sys
import threading
import webbrowser
from urllib.parse import urlsplit

from .core import Invalid,Store
from .feeds import Runner
from .live import LiveManager,ReadOnlyAccountPoller
from .paths import VERSION,resource_root,default_data_dir

ROOT=resource_root()


class LocalHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let two instances serve the same address.
    allow_reuse_address=False

    def server_bind(self):
        if sys.platform=='win32':
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def make_handler(store,runner,port,live=None):
    live=live or LiveManager(store)
    token=secrets.token_urlsafe(32)
    allowed_hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        server_version='PoloCopyTrade/'+VERSION

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
            elif route=='/api/live/state':
                self.send(200,live.status())
            elif route=='/api/runtime/state':
                path=store.path.parent/'supervisor-status.json'
                try:runtime=json.loads(path.read_text(encoding='utf8'))
                except (OSError,ValueError):runtime={'mode':'unmanaged','auto_trading':False}
                self.send(200,runtime)
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
                files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/polo-logo.png':'polo-logo.png','/live-ui.js':'live-ui.js'}
                name=files.get(route)
                if not name:
                    self.send(404,{'error':'Not found'})
                    return
                path=ROOT/'frontend'/name
                kind={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','png':'image/png'}[name.split('.')[-1]]
                self.send(200,path.read_bytes(),kind)

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
                elif route=='/api/live/connect':
                    if payload:raise Invalid('Credentials are accepted only by the local terminal launcher / 请只在本机终端输入密钥')
                    result=live.connect()
                elif route=='/api/live/refresh':
                    result=live.refresh_account()
                elif route=='/api/live/start':
                    result=live.start(payload.get('trader_id'),payload.get('config'))
                elif route=='/api/live/pause':
                    if not isinstance(payload.get('paused'),bool):raise Invalid('paused must be boolean')
                    result=live.pause(payload['paused'])
                elif route=='/api/live/stop':
                    result=live.stop()
                elif route=='/api/runtime/retry-observer':
                    from .supervisor import control_request
                    result=control_request(store.path,{'command':'retry_observer'})
                elif len(parts)==4 and parts[:2]==['api','traders']:
                    trader_id,action=parts[2:]
                    if action=='config':
                        live_state=live.status()
                        if live_state['watching'] and live_state['trader_id']==trader_id:
                            raise Invalid('该交易员正在账户跟随，不能修改来源或参数。请先停止并处理旧仓位。')
                        result=store.save_trader(payload,trader_id)
                    elif action=='toggle':
                        if not isinstance(payload.get('enabled'),bool): raise Invalid('enabled must be boolean')
                        live_state=live.status()
                        if payload['enabled'] and live_state['watching'] and live_state['trader_id']==trader_id:
                            raise Invalid('该来源正在用于账户跟随，不能同时启动模拟采集。')
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
                        self.send(409,{'error':'Use the separate account workspace to connect, configure and explicitly start a real/testnet session. / 请到独立账户工作台连接、填写参数并启动跟随；模拟开关不能转换真实订单。'})
                        return
                    result={'mode':'paper'}
                else:
                    self.send(404,{'error':'Not found'});return
                self.send(200,result)
            except (Invalid,ValueError,KeyError,TypeError) as error:
                self.send(400,{'error':str(error)})
            except Exception as error:
                from .executor import Halt,APIError
                if isinstance(error,(Halt,APIError)):
                    self.send(400,{'error':str(error)})
                else:
                    self.send(500,{'error':'Internal error; inspect local server output'})

    return Handler


def main(argv=None):
    parser=argparse.ArgumentParser(description='Polo CopyTrade — separate account and paper workspaces')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--open-browser',action='store_true',help='Open the system browser after binding successfully')
    parser.add_argument('--read-only-account',action='store_true',help='Allow account reads but reject every account-follow start')
    parser.add_argument('--auto-connect-readonly',action='store_true',help='Reconnect and refresh read-only account snapshots in the backend')
    parser.add_argument('--no-runner',action='store_true',help='API verification without scheduled signal processing')
    args=parser.parse_args(argv)
    if args.auto_connect_readonly and not args.read_only_account:parser.error('Auto connection is available only in read-only mode')
    if not 1024<=args.port<=65535: parser.error('Choose a port between 1024 and 65535')
    store=Store(args.data)
    runner=Runner(store)
    live=LiveManager(store,execution_allowed=not args.read_only_account)
    try:
        server=LocalHTTPServer(('127.0.0.1',args.port),make_handler(store,runner,args.port,live))
    except OSError:
        raise SystemExit('Port unavailable; choose --port 8766 or close the previous instance.')
    if not args.no_runner: runner.start()
    poller=ReadOnlyAccountPoller(live) if args.auto_connect_readonly else None
    if poller:poller.start()
    print(f'Polo CopyTrade: http://127.0.0.1:{args.port}',flush=True)
    print('Account execution is OFF at startup. The paper lab is separate. Press Ctrl+C to stop.',flush=True)
    if args.open_browser:
        threading.Thread(target=webbrowser.open,args=(f'http://127.0.0.1:{args.port}',),daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if poller:poller.close()
        if not args.no_runner: runner.shutdown()
        live.shutdown()
        server.server_close()


if __name__=='__main__': main()
