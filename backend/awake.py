"""Temporary AC-only Windows idle-sleep guard for an active signal observer.

No power-plan, update-policy, credential-storage or autotrading changes.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from datetime import datetime,timezone

from .core import Store,Invalid,now
from .observe import DashboardGuard
from .paths import default_data_dir

CONTINUOUS=0x80000000
SYSTEM_REQUIRED=0x00000001


class WindowsPower:
    def __init__(self):
        if sys.platform!='win32':raise Invalid('The idle-sleep guard requires Windows')
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.SetThreadExecutionState.argtypes=[wintypes.DWORD]
        self.kernel.SetThreadExecutionState.restype=wintypes.DWORD

    def on_ac(self):
        class PowerStatus(ctypes.Structure):
            _fields_=[('ACLineStatus',wintypes.BYTE),('BatteryFlag',wintypes.BYTE),
                      ('BatteryLifePercent',wintypes.BYTE),('SystemStatusFlag',wintypes.BYTE),
                      ('BatteryLifeTime',wintypes.DWORD),('BatteryFullLifeTime',wintypes.DWORD)]
        status=PowerStatus()
        if not self.kernel.GetSystemPowerStatus(ctypes.byref(status)):
            raise Invalid('Could not read AC power state')
        return status.ACLineStatus==1

    def set_state(self,flags):
        if not self.kernel.SetThreadExecutionState(flags):
            raise Invalid('Windows did not accept the idle-sleep request')


class AwakeRequest:
    def __init__(self,power):self.power,self.active=power,False
    def update(self,on_ac,observing):
        wanted=on_ac and observing
        if wanted!=self.active:
            self.power.set_state(CONTINUOUS|SYSTEM_REQUIRED if wanted else CONTINUOUS)
            self.active=wanted
        return self.active
    def close(self):
        if self.active:
            self.power.set_state(CONTINUOUS)
            self.active=False


def supervisor_is_active(data,clock=None):
    from .supervisor import process_alive
    try:
        value=json.loads((Path(data).parent/'supervisor-status.json').read_text(encoding='utf8'))
        age=(clock or datetime.now(timezone.utc)).timestamp()-datetime.fromisoformat(value['heartbeat']).timestamp()
        return (value.get('mode')=='read_only_monitor' and value.get('auto_trading') is False
                and 0<=age<30 and process_alive(value.get('supervisor_pid')))
    except (OSError,ValueError,KeyError,TypeError):return False


def run_guard(store,trader_id='aoying',stop=None,supervised=False):
    stop=stop or threading.Event()
    dashboard=DashboardGuard('http://127.0.0.1:8765')
    dashboard()
    owner=uuid.uuid4().hex
    request=AwakeRequest(WindowsPower())
    meta=dict(owner=owner,pid=os.getpid(),status='starting',heartbeat=time.time(),started_at=now())
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT runtime_guard FROM traders WHERE id=?',(trader_id,)).fetchone()
        if not row:raise Invalid('Trader not found')
        previous=json.loads(row[0] or '{}')
        if previous.get('owner') and time.time()-previous.get('heartbeat',0)<90:
            raise Invalid('An idle-sleep guard is already running')
        db.execute('UPDATE traders SET runtime_guard=? WHERE id=?',(json.dumps(meta),trader_id))
    error=''
    try:
        while not stop.is_set():
            dashboard()
            trader=store.get_trader(trader_id)
            monitor=json.loads(trader.get('signal_monitor') or '{}')
            if supervised:
                observing=supervisor_is_active(store.path)
                if not observing:break
            else:
                if not monitor.get('owner') or time.time()-monitor.get('heartbeat',0)>180:break
                observing=trader['enabled'] and monitor.get('status') in ('starting','running','retrying')
            on_ac=request.power.on_ac()
            active=request.update(on_ac,observing)
            meta.update(status='active' if active else 'waiting_for_ac' if not on_ac else 'paused',
                        on_ac=on_ac,heartbeat=time.time(),updated_at=now(),display_can_turn_off=True,
                        prevents_restart=False,scope='supervisor' if supervised else 'observer')
            with store.db() as db:
                current=json.loads(db.execute('SELECT runtime_guard FROM traders WHERE id=?',(trader_id,)).fetchone()[0] or '{}')
                if current.get('owner')!=owner:raise Invalid('Idle-sleep guard ownership changed')
                db.execute('UPDATE traders SET runtime_guard=? WHERE id=?',(json.dumps(meta),trader_id))
            stop.wait(15)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc).split('\n')[0][:200]
    finally:
        try:request.close()
        finally:
            meta.update(status='error' if error else 'stopped',owner=None,error=error,heartbeat=time.time())
            with store.db() as db:
                current=json.loads(db.execute('SELECT runtime_guard FROM traders WHERE id=?',(trader_id,)).fetchone()[0] or '{}')
                if current.get('owner')==owner:
                    db.execute('UPDATE traders SET runtime_guard=? WHERE id=?',(json.dumps(meta),trader_id))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Keep Windows awake on AC while the signal observer runs')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'studio.sqlite3')
    parser.add_argument('--supervised',action='store_true',help='Stay awake on AC while the read-only supervisor remains active')
    args=parser.parse_args(argv)
    run_guard(Store(args.data),supervised=args.supervised)


if __name__=='__main__':main()
