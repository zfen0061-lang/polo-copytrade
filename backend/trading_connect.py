"""Local hidden entry for the dedicated trading account. Never starts execution."""
import argparse
from contextlib import closing
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import urllib.request
import urllib.error
import webbrowser

from .core import Invalid
from .credential_store import CredentialVault,TradingCredentialVault,validate_pair
from .executor import Halt,APIError
from .paths import default_data_dir
from .production import ProductionBroker
from .runtime_lock import execution_lease


def local_state(data):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8767/api/real-v2/state',timeout=5) as response:
        if not response.headers.get('Server','').startswith('PoloCopyTrade/'):
            raise Invalid('Port 8767 is not the expected local workspace')
        state=json.load(response)
    expected=hashlib.sha256(str(Path(data).resolve()).lower().encode()).hexdigest()[:16]
    if (state.get('workspace_id')!=expected or state.get('endpoint')!='https://fapi.binance.com'
            or state.get('connection_role')!='dedicated_trading'):
        raise Invalid('Reload the dedicated production workspace before entering account keys')
    if state.get('running') or state.get('execution_armed'):
        raise Invalid('Stop production execution before changing its connection')
    journal=state.get('journal',{})
    if journal.get('positions') or journal.get('pending_count') or journal.get('protection_count'):
        raise Invalid('Existing exposure, protection or unknown orders require review before a connection change')
    return state


def save_connection(data,source_data,key,secret,broker_factory=None):
    from .live import TradeClient
    validate_pair(key,secret);data=Path(data).resolve();source_data=Path(source_data).resolve()
    if data.parent in (source_data.parent,source_data.parent/'demo-v2'):
        raise Invalid('A separate production trading directory is required')
    with execution_lease(source_data.parent/'real-execution.lock'):
        state=local_state(data)
        # Comparing locally is not proof of sub-account ownership, but catches
        # accidentally re-entering the already known main monitoring API key.
        main_pair=CredentialVault(source_data).load()
        if main_pair and key==main_pair[0]:
            raise Invalid('This is the saved main monitoring API key. Enter the API verified under the intended sub-account in Binance')
        broker=(broker_factory(key,secret) if broker_factory else
                ProductionBroker(TradeClient(key=key,secret=secret,environment='production')))
        broker.assert_endpoint();broker.sync();account=broker.account()
        if account['positions']:
            raise Invalid('This connection has existing positions; check that the API belongs to the empty intended trading sub-account')
        journal=data.parent/'real-execution.sqlite3'
        if journal.exists():
            with closing(sqlite3.connect(journal.as_uri()+'?mode=ro',uri=True)) as db:
                fingerprint=db.execute("SELECT value FROM meta WHERE key='fingerprint'").fetchone()
                expected=hashlib.sha256(json.dumps([broker.identity(),state['policy']],sort_keys=True).encode()).hexdigest()
                if state['journal'].get('locked') and fingerprint and fingerprint[0]!=expected:
                    raise Invalid('This journal belongs to another account/policy; do not replace its connection or erase its history')
        local_state(data)
        TradingCredentialVault(data).save(key,secret)
        return dict(saved=True,position_count=len(account['positions']),
                    account_tag=broker.identity()[:8],orders_started=False)


def refresh_workspace(data):
    local_state(data)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base='http://127.0.0.1:8767'
    with opener.open(base+'/api/session',timeout=5) as response:token=json.load(response)['csrf_token']
    request=urllib.request.Request(base+'/api/real-v2/inspect',data=b'{}',method='POST',
        headers={'Content-Type':'application/json','X-CSRF-Token':token})
    with opener.open(request,timeout=45) as response:state=json.load(response)
    return dict(connected=state['connected'],execution_armed=state['execution_armed'],blockers=state['review']['blockers'])


def main(argv=None):
    parser=argparse.ArgumentParser(description='Remember the dedicated production sub-account connection locally; no orders')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'real-v2'/'studio.sqlite3')
    parser.add_argument('--source-data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args(argv)
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW('Polo - Sub-account API connection / hidden input')
    try:local_state(args.data)
    except (urllib.error.URLError,TimeoutError):
        from .real_connect import main as open_workspace
        open_workspace(['--data',str(args.data),'--source-data',str(args.source_data),'--no-browser'])
        local_state(args.data)
    print('Polo - Dedicated SUB-ACCOUNT connection. Account orders remain OFF.')
    print('Verify this API is listed under your intended sub-account in Binance first.')
    print('Input is hidden. Keys are encrypted for this Windows user only.')
    print('The saved main-account and Demo connections are not changed.')
    key=getpass.getpass('Sub-account API Key (hidden): ').strip()
    secret=getpass.getpass('Sub-account API Secret (hidden): ').strip()
    result=save_connection(args.data,args.source_data,key,secret)
    key=secret=None
    print('Account reads verified; dedicated connection encrypted locally. No order placed.')
    try:
        state=refresh_workspace(args.data)
        print('Workspace connection restored. Execution remains OFF.')
        for item in state['blockers']:print('Before starting: '+item)
    except Exception:
        print('Connection saved. Reopen the workspace and click read-only inspection; execution remains OFF.')
    if not args.no_browser:webbrowser.open('http://127.0.0.1:8767')
    return result


if __name__=='__main__':
    try:main()
    except APIError as exc:
        print('Binance rejected the account check: '+str(exc))
        print('Check the sub-account API Key/Secret, Futures activation, API permissions and IP restrictions. No order was placed.')
        raise SystemExit(1)
    except (Invalid,Halt) as exc:print('Connection not completed: '+str(exc));raise SystemExit(1)
    except Exception as exc:print('Connection not completed: '+type(exc).__name__);raise SystemExit(1)
