"""Read-only service supervisor. Account credentials remain in parent/child memory.

The local authenticated control pipe never accepts an order command. Windows login
tasks can run this module independently of a browser or a ChatGPT session.
"""
from __future__ import annotations

import argparse
from contextlib import suppress
import getpass
import hashlib
import json
import multiprocessing.connection
import os
from pathlib import Path
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.request

from .core import Store,Invalid,now
from .paths import default_data_dir,resource_root
from .runtime_lock import execution_lease


def process_alive(pid):
    if not isinstance(pid,int) or pid<=0:return False
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            code=ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle),ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def control_address(data):
    identity=hashlib.sha256(str(Path(data).resolve()).lower().encode()).hexdigest()[:18]
    return (r'\\.\pipe\PoloMonitor-'+identity,'AF_PIPE') if os.name=='nt' else (str(Path(data).parent/('control-'+identity+'.sock')),'AF_UNIX')


def control_request(data,payload):
    data=Path(data)
    if payload.get('command')=='retry_observer':
        from .credential_store import migrate_pending_session
        migrate_pending_session(data)
    address,family=control_address(data)
    token=(data.parent/'supervisor-control.token').read_bytes()
    with multiprocessing.connection.Client(address,family=family,authkey=token) as connection:
        connection.send_bytes(json.dumps(payload).encode())
        if not connection.poll(10):raise Invalid('Local supervisor control timed out')
        return json.loads(connection.recv_bytes(65536))


class Child:
    def __init__(self,name,args):
        self.name,self.args=name,args
        self.process=None;self.restarts=0;self.next_start=0;self.blocked=''
    def schedule_restart(self,clock):
        self.restarts+=1
        self.next_start=clock+min(60,2**min(self.restarts,6))


class MonitorSupervisor:
    def __init__(self,data,port=8765):
        self.data=Path(data).resolve();self.port=port;self.store=Store(self.data)
        self.stop=threading.Event();self.commands=queue.Queue();self.credentials=None
        self.listener=None;self.ready=False;self.server_session=None
        self.health_failures=0;self.server_started=0
        self.started_at=now();self.error=''
        from .credential_store import CredentialVault
        self.vault=CredentialVault(self.data);self.credential_error=''
        try:self.credentials=self.vault.load()
        except Invalid as exc:self.credential_error=str(exc)
        self.token_path=self.data.parent/'supervisor-control.token'
        self.status_path=self.data.parent/'supervisor-status.json'
        self.children={
            'server':Child('server',['-m','backend.server','--read-only-account','--auto-connect-readonly',
                '--no-runner','--port',str(port),'--data',str(self.data)]),
            'observer':Child('observer',['-m','backend.observe','--data',str(self.data)]),
            'awake':Child('awake',['-m','backend.awake','--supervised','--data',str(self.data)]),
        }
        previous=json.loads(self.store.get_trader('aoying').get('signal_monitor') or '{}')
        if previous.get('status')=='error' and not previous.get('restartable'):
            self.children['observer'].blocked=previous.get('last_error') or 'Review collector failure'

    def health(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{self.port}/api/live/state',timeout=2) as response:
            if not response.headers.get('Server','').startswith('PoloCopyTrade/'):
                raise Invalid('Port belongs to an unrelated service')
            state=json.load(response)
        if state.get('execution_allowed') is not False or state.get('watching'):
            raise Invalid('Supervisor may manage only idle read-only account servers')
        return state

    def launch(self,child):
        env=dict(os.environ)
        for key in ('POLO_BINANCE_API_KEY','POLO_BINANCE_API_SECRET'):env.pop(key,None)
        env['POLO_BINANCE_ENV']='production'
        if child.name=='server' and self.credentials:
            env['POLO_BINANCE_API_KEY'],env['POLO_BINANCE_API_SECRET']=self.credentials
        stdout=open(self.data.parent/(child.name+'-supervised.stdout.log'),'ab')
        stderr=open(self.data.parent/(child.name+'-supervised.stderr.log'),'ab')
        try:
            child.process=subprocess.Popen([sys.executable,*child.args],cwd=resource_root(),env=env,
                stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0)
        finally:stdout.close();stderr.close()
        if child.name=='server':self.server_started=time.monotonic();self.health_failures=0

    def terminate(self,child):
        process=child.process
        if process and process.poll() is None:
            if os.name=='nt':
                subprocess.run([r'C:\Windows\System32\taskkill.exe','/PID',str(process.pid),'/T','/F'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=10)
            else:process.terminate()
            with suppress(subprocess.TimeoutExpired):process.wait(timeout=5)
        child.process=None

    def clear_dead_lease(self,column):
        with self.store.db() as db:
            value=json.loads(db.execute('SELECT '+column+' FROM traders WHERE id=?',('aoying',)).fetchone()[0] or '{}')
            if value.get('owner') and process_alive(value.get('pid')):return False
            if value.get('owner'):
                value.update(owner=None,status='paused' if value.get('status')=='paused' else 'stopped',heartbeat=time.time())
                db.execute('UPDATE traders SET '+column+'=? WHERE id=?',(json.dumps(value),'aoying'))
        return True

    def snapshot(self):
        return dict(mode='read_only_monitor',supervisor_pid=os.getpid(),started_at=self.started_at,
            heartbeat=now(),backend_healthy=self.ready,account_credentials_in_memory=self.credentials is not None,
            credential_storage='windows_dpapi_user' if self.vault.exists() else 'memory_only',
            saved_connection=self.vault.exists(),credential_error=self.credential_error,
            auto_trading=False,error=self.error,
            components={name:dict(pid=child.process.pid if child.process and child.process.poll() is None else None,
                restarts=child.restarts,blocked=child.blocked) for name,child in self.children.items()})

    def save_status(self):
        temporary=self.status_path.with_suffix('.tmp')
        try:
            temporary.write_text(json.dumps(self.snapshot()),encoding='utf8')
            temporary.replace(self.status_path)
        except OSError:
            # A transient status-file sharing error must not kill the parent or
            # discard its memory-only credentials. The UI detects stale status.
            pass

    def start_control(self):
        auth=secrets.token_bytes(32)
        handle=os.open(self.token_path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
        with os.fdopen(handle,'wb') as output:output.write(auth)
        address,family=control_address(self.data)
        if family=='AF_UNIX':
            with suppress(FileNotFoundError):Path(address).unlink()
        self.listener=multiprocessing.connection.Listener(address,family=family,authkey=auth)
        def accept():
            while not self.stop.is_set():
                try:
                    with self.listener.accept() as connection:
                        if not connection.poll(10):continue
                        command=json.loads(connection.recv_bytes(65536))
                        def reply(value):connection.send_bytes(json.dumps(value).encode())
                        if not isinstance(command,dict):reply({'ok':False});continue
                        name=command.get('command')
                        if name=='status':reply(self.snapshot())
                        elif name in ('credentials','retry_observer','stop'):
                            if name=='credentials' and not all(isinstance(command.get(k),str) and command[k] for k in ('key','secret')):
                                reply({'ok':False,'error':'Both credential values are required'});continue
                            self.commands.put(command);reply({'ok':True})
                        else:reply({'ok':False,'error':'Unsupported monitor control'})
                except (EOFError,OSError,ValueError,multiprocessing.context.AuthenticationError):
                    if self.stop.is_set():break
        threading.Thread(target=accept,name='local-monitor-control',daemon=True).start()

    def process_commands(self):
        while not self.commands.empty():
            message=self.commands.get_nowait();name=message['command']
            if name=='credentials':
                self.credentials=(message['key'],message['secret'])
                self.credential_error=''
                for child in reversed(list(self.children.values())):self.terminate(child)
                for child in self.children.values():
                    child.next_start=0
                    if child.name!='observer':child.blocked=''
                self.ready=False;self.error=''
            elif name=='retry_observer':
                self.children['observer'].blocked='';self.children['observer'].next_start=0
            elif name=='stop':self.stop.set()

    def run(self):
        with execution_lease(self.data.parent/'monitor-supervisor.lock'):
            # Do not seize an independently launched service or its credentials.
            try:self.health()
            except (OSError,ValueError):pass
            else:raise Invalid('A read-only server is already running outside this supervisor')
            self.start_control()
            try:
                while not self.stop.is_set():
                    self.process_commands();clock=time.monotonic()
                    server=self.children['server']
                    if server.process and server.process.poll() is not None:
                        for name in ('observer','awake'):self.terminate(self.children[name])
                        server.process=None;self.ready=False;server.schedule_restart(clock)
                    if server.process is None and clock>=server.next_start:self.launch(server)
                    try:self.health();self.ready=True;self.health_failures=0;self.error=''
                    except Exception as exc:
                        self.ready=False;self.health_failures+=1
                        self.error=type(exc).__name__+': '+str(exc).split('\n')[0][:180]
                        if self.health_failures>=5 and clock-self.server_started>30:
                            for name in ('observer','awake','server'):self.terminate(self.children[name])
                            server.schedule_restart(clock)
                    if self.ready:
                        trader=self.store.get_trader('aoying')
                        monitor=json.loads(trader.get('signal_monitor') or '{}')
                        eligible=(trader['source']=='binance_public' and trader['authorized'] and trader['config']['utc_offset_minutes']==0)
                        for name,column in (('observer','signal_monitor'),('awake','runtime_guard')):
                            child=self.children[name]
                            metadata=json.loads(trader.get(column) or '{}')
                            if child.process and metadata.get('owner') and time.time()-metadata.get('heartbeat',0)>180:
                                self.terminate(child);child.schedule_restart(clock)
                            if child.process and child.process.poll() is not None:
                                child.process=None;child.schedule_restart(clock)
                                if name=='observer':
                                    last=json.loads(self.store.get_trader('aoying')['signal_monitor'] or '{}')
                                    if last.get('status')=='error' and not last.get('restartable',False):child.blocked=last.get('last_error') or 'Review collector failure'
                            can_start=eligible and not child.blocked
                            if can_start and child.process is None and clock>=child.next_start:
                                if self.clear_dead_lease(column):self.launch(child)
                    self.save_status();self.stop.wait(3)
            finally:
                for child in reversed(list(self.children.values())):self.terminate(child)
                self.credentials=None
                if self.listener:self.listener.close()
                with suppress(FileNotFoundError):self.token_path.unlink()
                self.error='Supervisor stopped';self.save_status()


def enter_credentials(data,remember=False):
    from .credential_store import CredentialVault
    if not remember and CredentialVault(data).exists():
        raise Invalid('A saved connection exists. Use --remember to replace it, or explicitly forget the saved connection first')
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW('Polo CopyTrade - local read-only account connection')
    print('Enter production credentials in this local window only. Input is hidden. No trading is enabled.')
    if remember:print('This launcher saves the connection using Windows current-user encryption for automatic reconnection.')
    key=getpass.getpass('API Key: ').strip();secret=getpass.getpass('API Secret: ').strip()
    if not key or not secret or any(c.isspace() or ord(c)<33 or ord(c)>126 for c in key+secret) or set(secret)<=set('*•.'):
        raise Invalid('Use complete original credentials, not masked dots or control characters')
    if remember:
        from .credential_store import CredentialVault
        from .live import TradeClient
        client=TradeClient(key=key,secret=secret,environment='production')
        client.sync();client.account()
        CredentialVault(data).save(key,secret)
    result=control_request(data,dict(command='credentials',key=key,secret=secret))
    key=secret=None
    if not result.get('ok'):raise Invalid(result.get('error','Local credential handoff failed'))
    print('Account connected locally. '+('Windows encrypted remembering enabled.' if remember else 'Process memory only.'))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only monitor service supervisor')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--port',type=int,choices=[8765],default=8765)
    parser.add_argument('--remember',action='store_true',help='Verify and encrypt local credentials for reconnection after restart')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--connect-account',action='store_true')
    group.add_argument('--status',action='store_true')
    group.add_argument('--stop',action='store_true')
    args=parser.parse_args(argv)
    if args.remember and not args.connect_account:parser.error('--remember requires --connect-account')
    if args.connect_account:enter_credentials(args.data,args.remember);return
    if args.status:print(json.dumps(control_request(args.data,{'command':'status'})));return
    if args.stop:control_request(args.data,{'command':'stop'});return
    supervisor=MonitorSupervisor(args.data,args.port)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:supervisor.stop.set())
    supervisor.run()


if __name__=='__main__':main()
