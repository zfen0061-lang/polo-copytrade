"""Opt-in Windows user-scoped encryption; never exports plaintext credentials.

The account app encrypts its own credentials locally. The upgrade bridge accepts
only a short-lived local intent, never credentials over HTTP or from another app.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import urllib.request
from .core import Invalid
from .paths import default_data_dir

MAGIC=b'POLO-READONLY-DPAPI-V1\x00'
ENTROPY=b'PoloCopyTrade/production/read-only/credentials/v1'


def validate_pair(key,secret):
    if not all(isinstance(v,str) and 1<=len(v)<=512 and all(33<=ord(c)<=126 for c in v) for v in (key,secret)):
        raise Invalid('Complete original API credentials are required')
    if any(set(v)<=set('*?.') for v in (key,secret)):raise Invalid('Masked dots are not credentials')
    return key,secret


class WindowsUserProtection:
    def transform(self,data,decrypt=False):
        if os.name!='nt':raise Invalid('Encrypted connection storage requires Windows')
        class Blob(ctypes.Structure):
            _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
        source=ctypes.create_string_buffer(data);entropy=ctypes.create_string_buffer(ENTROPY)
        incoming=Blob(len(data),ctypes.cast(source,ctypes.POINTER(ctypes.c_ubyte)))
        extra=Blob(len(ENTROPY),ctypes.cast(entropy,ctypes.POINTER(ctypes.c_ubyte)));outgoing=Blob()
        crypto=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        function=crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
        function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        function.restype=wintypes.BOOL
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        # UI_FORBIDDEN only. LOCAL_MACHINE would permit other local users.
        if not function(ctypes.byref(incoming),None,ctypes.byref(extra),None,None,1,ctypes.byref(outgoing)):
            raise Invalid('Windows could not '+('unlock' if decrypt else 'protect')+' the saved connection')
        try:return ctypes.string_at(outgoing.data,outgoing.size)
        finally:
            if outgoing.data:
                if decrypt:ctypes.memset(outgoing.data,0,outgoing.size)
                kernel.LocalFree(ctypes.cast(outgoing.data,ctypes.c_void_p))
    def protect(self,data):return self.transform(data)
    def unprotect(self,data):return self.transform(data,True)


class CredentialVault:
    def __init__(self,data,protection=None):
        self.path=Path(data).resolve().parent/'account-readonly.dpapi'
        self.protection=protection or WindowsUserProtection()
    def exists(self):return self.path.is_file()
    def save(self,key,secret):
        validate_pair(key,secret)
        raw=json.dumps(dict(version=1,environment='production',key=key,secret=secret)).encode()
        encrypted=self.protection.protect(raw)
        if self.protection.unprotect(encrypted)!=raw:raise Invalid('Encrypted connection verification failed')
        self.path.parent.mkdir(parents=True,exist_ok=True);temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent,prefix='credential-',suffix='.tmp',delete=False) as output:
                temporary=Path(output.name);output.write(MAGIC+encrypted);output.flush();os.fsync(output.fileno())
            temporary.replace(self.path)
        finally:
            if temporary and temporary.exists():temporary.unlink()
    def load(self):
        if not self.exists():return None
        try:
            if self.path.stat().st_size>65536:raise ValueError()
            protected=self.path.read_bytes()
            if not protected.startswith(MAGIC):raise ValueError()
            value=json.loads(self.protection.unprotect(protected[len(MAGIC):]))
            if value.get('version')!=1 or value.get('environment')!='production':raise ValueError()
            return validate_pair(value.get('key'),value.get('secret'))
        except (OSError,ValueError,TypeError,AttributeError,Invalid):
            raise Invalid('Saved connection could not be unlocked; reconnect locally under the original Windows user') from None
    def forget(self):self.path.unlink(missing_ok=True)


def migrate_pending_session(data):
    """Encrypt the running pre-vault server's own credentials without exporting.

    Its existing local recheck route dynamically imports control_request. This
    narrowly scoped upgrade bridge requires an explicit expiring local intent
    and read-only server flags. It is inert during normal collector rechecks.
    """
    directory=Path(data).resolve().parent;pending=directory/'remember-account-request.json'
    if not pending.is_file():return
    if '--read-only-account' not in sys.argv or '--auto-connect-readonly' not in sys.argv:return
    request_id=None
    try:
        request=json.loads(pending.read_text(encoding='utf8'));request_id=request['request_id']
        if not isinstance(request_id,str) or len(request_id)!=32 or any(c not in '0123456789abcdef' for c in request_id):raise Invalid('Invalid local intent')
        if not 0<float(request['expires_at'])-time.time()<=60:raise Invalid('Local intent expired')
        if os.environ.get('POLO_BINANCE_ENV','production')!='production':raise Invalid('Read-only production session required')
        # This is the application's own configured pair. It never leaves this
        # process in plaintext except its existing authenticated local handoff.
        CredentialVault(data).save(os.environ.get('POLO_BINANCE_API_KEY',''),os.environ.get('POLO_BINANCE_API_SECRET',''))
        result=dict(request_id=request_id,saved=True,storage='windows_dpapi_user')
    except Exception:
        result=dict(request_id=request_id,saved=False,error='Encrypted saving failed; the current connection remains unchanged')
    finally:pending.unlink(missing_ok=True)
    (directory/'remember-account-result.json').write_text(json.dumps(result),encoding='utf8')


def remember_running_connection(data):
    base='http://127.0.0.1:8765';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(base+path,timeout=5) as response:
            if not response.headers.get('Server','').startswith('PoloCopyTrade/'):raise Invalid('Unrelated local service')
            return json.load(response)
    state=get('/api/live/state')
    if state.get('execution_allowed') is not False or state.get('watching') or not state.get('connected'):
        raise Invalid('A connected read-only account session is required')
    directory=Path(data).resolve().parent;pending=directory/'remember-account-request.json'
    receipt=directory/'remember-account-result.json';nonce=secrets.token_hex(16)
    pending.write_text(json.dumps(dict(request_id=nonce,expires_at=time.time()+60)),encoding='utf8')
    try:
        token=get('/api/session')['csrf_token']
        command=urllib.request.Request(base+'/api/runtime/retry-observer',data=b'{}',method='POST',
            headers={'Content-Type':'application/json','X-CSRF-Token':token})
        with opener.open(command,timeout=15) as response:json.load(response)
        result=json.loads(receipt.read_text(encoding='utf8')) if receipt.exists() else {}
        if result.get('request_id')!=nonce or result.get('saved') is not True:
            raise Invalid('One final local reconnect is needed to enable remembering; the current connection was kept')
        if CredentialVault(data).load() is None:raise Invalid('Encrypted connection verification failed')
        return dict(saved=True,storage='windows_dpapi_user')
    finally:pending.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Manage encrypted read-only account reconnection locally')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'studio.sqlite3')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--remember-current',action='store_true');group.add_argument('--forget',action='store_true');group.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    if args.remember_current:print(json.dumps(remember_running_connection(args.data)));return
    vault=CredentialVault(args.data)
    if args.forget:vault.forget();print('Saved connection removed. Current session unchanged.');return
    print(json.dumps(dict(saved=vault.exists(),unlock_verified=vault.load() is not None)))


if __name__=='__main__':main()
