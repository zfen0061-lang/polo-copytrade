"""Separate local Demo credential entry; never reads the production key vault."""
import argparse
import getpass
import hashlib
import os
import sys
import json
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path
from .credential_store import validate_pair
from .paths import default_data_dir


def main(argv=None):
    parser=argparse.ArgumentParser(description='Polo Futures Demo only; no production account orders')
    parser.add_argument('--preview',action='store_true',help='Open the demo UI without credentials or orders')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'demo-v2'/'studio.sqlite3')
    parser.add_argument('--source-data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--replace',action='store_true',help='Replace a stopped Demo session credential pair through its local pipe')
    args=parser.parse_args(argv)
    if args.data.resolve().parent==args.source_data.resolve().parent:
        raise SystemExit('Demo data directory must be separate from the real read-only monitor')
    existing=None
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8766/api/demo-v2/state',timeout=3) as response:
            if not response.headers.get('Server','').startswith('PoloCopyTrade/'):
                raise SystemExit('Port 8766 is used by another application')
            existing=json.load(response)
        if existing.get('available') is not True or existing.get('endpoint')!='https://demo-fapi.binance.com':
            raise SystemExit('Port 8766 is not a compatible Demo workspace')
        expected=hashlib.sha256(os.path.normcase(str(args.data.resolve())).encode()).hexdigest()[:16]
        if existing.get('workspace_id')!=expected:raise SystemExit('The running Demo workspace uses a different data directory; no credentials were sent')
    except (urllib.error.URLError,TimeoutError):pass
    if existing and (args.preview or (existing.get('configured') and not args.replace)):
        print('The Demo workspace is already running. Use its page; no new key input is needed.')
        if not args.no_browser:webbrowser.open('http://127.0.0.1:8766')
        return
    if existing and existing.get('running'):raise SystemExit('Stop Demo following before replacing its credentials')
    for key in ('POLO_BINANCE_API_KEY','POLO_BINANCE_API_SECRET','POLO_DEMO_API_KEY','POLO_DEMO_API_SECRET'):
        os.environ.pop(key,None)
    if not args.preview:
        print('Polo CopyTrade — BINANCE FUTURES DEMO ONLY / 仅合约模拟交易')
        print('Use separate Demo API keys. Your saved production connection is not used or changed.')
        print('Input is hidden. Opening this page never starts orders.')
        key=getpass.getpass('Demo API Key (hidden): ').strip()
        secret=getpass.getpass('Demo API Secret (hidden): ').strip()
        validate_pair(key,secret)
        if existing:
            from .supervisor import control_request
            result=control_request(args.data,dict(command='credentials',key=key,secret=secret))
            key=secret=None
            if not result.get('accepted'):raise SystemExit(result.get('error','Demo credential handoff failed'))
            print('Demo credentials delivered locally. Verify the account and explicitly start in the Demo page.')
            if not args.no_browser:webbrowser.open('http://127.0.0.1:8766')
            return
        os.environ['POLO_DEMO_API_KEY']=key;os.environ['POLO_DEMO_API_SECRET']=secret
        key=secret=None
    from .server import main as server
    options=['--demo-v2','--port','8766','--data',str(args.data),'--source-data',str(args.source_data)]
    if not args.no_browser:options.append('--open-browser')
    try:server(options)
    finally:
        os.environ.pop('POLO_DEMO_API_KEY',None);os.environ.pop('POLO_DEMO_API_SECRET',None)


if __name__=='__main__':main()
