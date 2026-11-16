"""Bounded, explicitly invoked Futures Demo stop-fill verification.

Uses a separate small virtual allocation and journal. No production key vault,
no leverage changes, no public opening signals, and no overnight retry loop.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import getpass
import json
from pathlib import Path
import time
import uuid

from .core import Invalid,now,dec
from .credential_store import validate_pair,DemoCredentialVault
from .demo_broker import DemoBroker
from .executor import Halt,APIError,quantize
from .live import TradeClient
from .paths import default_data_dir
from .runtime_lock import execution_lease
from .strategy_v2 import StrategyEngine,StrategyPolicy


def verify_stop(broker,folder,seconds=180,clock=time.monotonic,sleeper=time.sleep,progress=None):
    if not 1<=seconds<=900:raise Invalid('Demo verification wait must be 1-900 seconds')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    report=dict(environment='testnet',started_at=now(),status='error',
        allocation_usdt='20',leverage=10,test_margin_loss_fraction='0.01',
        strategy_margin_loss_fraction_changed=False,stop_triggered=False,
        duplicate_checked=False,flat_verified=False,protection_cleared=False)
    engine=None
    def checkpoint(stage,**extra):
        value=dict(stage=stage,updated_at=now(),**extra)
        temporary=folder/'progress.tmp'
        temporary.write_text(json.dumps(value),encoding='utf8');temporary.replace(folder/'progress.json')
        if progress:progress(value)
    def event(key,action):
        price=str(broker.quote('BTCUSDT')[1]) if action.startswith('OPEN') else '1'
        return dict(id=key,action=action,symbol='BTCUSDT',price=price,source_time=now())
    def safe(exc):return str(exc) if isinstance(exc,(Halt,APIError,Invalid)) else type(exc).__name__
    try:
        checkpoint('checking_demo_account')
        if broker.environment!='testnet' or broker.base!='https://demo-fapi.binance.com':
            raise Halt('Only Binance Futures Demo is allowed')
        if hasattr(broker,'sync'):broker.sync()
        account=broker.account()
        report['account_read_verified']=True
        if account['positions']:raise Halt('Demo stop test requires an empty account; no manual positions are adopted')
        if not account.get('can_trade'):raise Halt('Demo account trading permission is unavailable')
        if broker.open_orders('BTCUSDT') or broker.open_stops('BTCUSDT'):
            raise Halt('Review existing Demo BTC orders before verification')
        if int(broker.symbol_config('BTCUSDT')['leverage'])!=10:
            raise Halt('Set BTCUSDT to 10x in Demo first')
        report.update(flat_verified=True,protection_cleared=True)
        if hasattr(broker,'mark_price'):
            bid,ask=broker.quote('BTCUSDT')
            mark=dec(broker.mark_price('BTCUSDT'))
            tick=broker.rules('BTCUSDT')['PRICE_FILTER']['tickSize']
            expected_trigger=quantize(dec(ask)*dec('0.999'),tick,up=True)
            report.update(reference_entry_price=str(ask),reference_mark_price=str(mark),
                          expected_trigger=str(expected_trigger))
            if mark<=0:raise Halt('Invalid Demo mark price')
            if mark<=expected_trigger:
                report['status']='blocked'
                raise Halt('Tight test stop is already crossed by mark price; no position opened')
        policy=StrategyPolicy('20','0.01',10,3,'0.03','20','initial_net_loss',60,{'BTCUSDT':'crypto'})
        engine=StrategyEngine(folder/'journal.sqlite3',policy,broker)
        opening=event('stop-check-'+uuid.uuid4().hex,'OPEN_LONG')
        checkpoint('opening_demo_position')
        report.update(flat_verified=False,protection_cleared=False)
        opened=engine.handle(opening)
        if opened['state']!='settled':raise Halt('Demo test entry did not settle: '+str(opened.get('reason')))
        report['duplicate_checked']=engine.handle(opening)['state']=='duplicate'
        deadline=clock()+seconds
        next_sync=clock()+15;next_progress=0
        while True:
            if clock()>=next_sync:
                if hasattr(broker,'sync'):broker.sync()
                next_sync=clock()+15
            if clock()>=next_progress:
                checkpoint('waiting_for_exchange_stop',remaining_seconds=max(0,round(deadline-clock())),
                    duplicate_checked=report['duplicate_checked'])
                next_progress=clock()+15
            engine.recover()
            row=engine.book.db.execute("SELECT 1 FROM intents WHERE id LIKE 'stop:%' AND state='settled'").fetchone()
            if row and not engine.book.positions():
                report.update(stop_triggered=True,status='passed');break
            if clock()>=deadline:
                report['status']='timeout';break
            sleeper(min(2,max(0,deadline-clock())))
    except Exception as exc:report['error']=safe(exc)
    finally:
        if engine:
            try:
                checkpoint('verifying_or_closing_demo_position')
                if hasattr(broker,'sync'):broker.sync()
                engine.recover()
                for position in list(engine.book.positions()):
                    engine.handle(event('stop-check-cleanup-'+uuid.uuid4().hex,'CLOSE_'+position['side']))
                engine.recover()
                account=engine.check_account()
                report['flat_verified']=not account['positions'] and not engine.book.positions() and not engine.book.pending()
                report['protection_cleared']=(not broker.open_stops('BTCUSDT') and not broker.open_orders('BTCUSDT'))
                report['capital_usdt']=str(engine.book.capital())
                report['pending_count']=len(engine.book.pending())
                if not report['flat_verified'] or not report['protection_cleared']:
                    report['status']='error';report['cleanup_error']='Demo position/order cleanup is incomplete; manual review required'
            except Exception as exc:
                report['status']='error';report['cleanup_error']=safe(exc)
            finally:engine.close()
        report['finished_at']=now()
        (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        checkpoint('finished',status=report['status'],flat_verified=report['flat_verified'],
                   protection_cleared=report['protection_cleared'])
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='One bounded BTC stop-fill test, Binance Futures Demo ONLY')
    parser.add_argument('--max-wait',type=int,default=180)
    parser.add_argument('--saved',action='store_true',help='Use only the separate Windows-encrypted Demo connection')
    parser.add_argument('--remember',action='store_true',help='Save locally entered Demo credentials with Windows user encryption')
    parser.add_argument('--no-handoff',action='store_true')
    parser.add_argument('--data',type=Path,default=default_data_dir()/'demo-v2'/'studio.sqlite3')
    parser.add_argument('--report-dir',type=Path)
    args=parser.parse_args(argv)
    if not 1<=args.max_wait<=900:parser.error('--max-wait must be 1-900 seconds')
    print('POLO - FUTURES DEMO STOP CHECK ONLY',flush=True)
    print('One virtual BTC test: allocation 20 USDT, 10x, temporary 1% margin stop.',flush=True)
    print('Your normal 40% margin stop is unchanged. A timeout is NOT a passed stop-fill test.',flush=True)
    vault=DemoCredentialVault(args.data)
    if args.saved:
        pair=vault.load()
        if not pair:raise SystemExit('No saved Demo connection; enter and remember it locally first')
        key,secret=pair
    else:
        print('Enter the SAME Demo API pair locally. Never use production keys.',flush=True)
        key,secret=validate_pair(getpass.getpass('Demo API Key (hidden): ').strip(),
                                 getpass.getpass('Demo API Secret (hidden): ').strip())
    print('Credentials received locally. Connecting to Demo; progress will print below.',flush=True)
    data=args.data
    folder=args.report_dir or data.parent.parent/'demo-verification'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6])
    with execution_lease(data.parent/'demo-v2.lock'):
        client=TradeClient(key=key,secret=secret,environment='testnet');client.sync()
        report=verify_stop(DemoBroker(client),folder,args.max_wait,
                           progress=lambda value:print(json.dumps(value),flush=True))
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    print('Report: '+str(folder/'result.json'),flush=True)
    if args.remember and report.get('account_read_verified'):
        vault.save(key,secret)
        print('Demo connection saved with Windows user encryption; production keys are separate.',flush=True)
    if args.no_handoff:return
    # Preserve a diagnostic connection even after failed cleanup; connecting
    # does not place orders. Start/recovery must still reject unresolved state.
    from .supervisor import control_request
    try:
        payload=dict(command='credentials',key=key,secret=secret)
        if args.remember and report.get('account_read_verified'):payload['remember']=True
        result=control_request(data,payload)
        if not result.get('accepted'):raise Invalid('Demo credential handoff was rejected')
        print('Demo diagnostic connection restored locally. Following is NOT started.',flush=True)
    except Exception:
        print('Local diagnostic connection could not be restored. No following was started.',flush=True)
    if not report['flat_verified'] or not report['protection_cleared']:
        print('Review Demo positions/orders manually before another run.',flush=True)
    key=secret=client=None


if __name__=='__main__':main()
