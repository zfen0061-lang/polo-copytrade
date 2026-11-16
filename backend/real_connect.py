"""Open a disarmed production workspace. This launcher never starts following."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .core import Invalid
from .paths import default_data_dir,resource_root


def main(argv=None):
    parser=argparse.ArgumentParser(description='Open the production workspace without enabling orders')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'real-v2'/'studio.sqlite3')
    parser.add_argument('--source-data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args(argv);args.data=args.data.resolve();args.source_data=args.source_data.resolve()
    if args.data.parent in (args.source_data.parent,args.source_data.parent/'demo-v2'):
        raise Invalid('Use a separate production execution directory')
    base='http://127.0.0.1:8767'
    identity=hashlib.sha256(str(args.data).lower().encode()).hexdigest()[:16]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def inspect():
        with opener.open(base+'/api/real-v2/state',timeout=2) as response:
            if not response.headers.get('Server','').startswith('PoloCopyTrade/'):raise Invalid('Port 8767 belongs to another service')
            state=json.load(response)
        if state.get('workspace_id')!=identity or state.get('endpoint')!='https://fapi.binance.com':
            raise Invalid('Port 8767 belongs to a different workspace')
        return state
    try:state=inspect()
    except (OSError,ValueError):
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1',8767))==0:raise Invalid('Port 8767 is occupied by an unrelated or starting service')
        args.data.parent.mkdir(parents=True,exist_ok=True)
        command=([sys.executable,'--real-server'] if getattr(sys,'frozen',False)
                 else [str(Path(sys.executable).with_name('pythonw.exe')) if os.name=='nt' else sys.executable,'-m','backend.server'])
        command+=['--real-v2','--port','8767','--data',str(args.data),'--source-data',str(args.source_data)]
        env=dict(os.environ)
        for key in ('POLO_BINANCE_API_KEY','POLO_BINANCE_API_SECRET','POLO_DEMO_API_KEY','POLO_DEMO_API_SECRET'):
            env.pop(key,None)
        with open(args.data.parent/'workspace.log','ab') as output:
            process=subprocess.Popen(command,cwd=resource_root(),env=env,stdin=subprocess.DEVNULL,
                stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        until=time.monotonic()+15
        while True:
            try:state=inspect();break
            except (OSError,ValueError):
                if process.poll() is not None or time.monotonic()>=until:raise Invalid('Production preview did not start; inspect its local workspace log')
                time.sleep(.2)
    if not args.no_browser:webbrowser.open(base)
    print(base+' / opening never enables account execution')
    return dict(url=base,running=state['running'],execution_armed=state['execution_armed'])


if __name__=='__main__':main()
