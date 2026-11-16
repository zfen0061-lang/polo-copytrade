"""Explicit flat-account Demo scope expansion; keep capital and history intact."""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .core import now
from .executor import Halt
from .runtime_lock import execution_lease
from .strategy_v2 import StrategyEngine,StrategyPolicy


def classify_contract(row):
    if (row.get('status')!='TRADING' or row.get('quoteAsset')!='USDT' or row.get('marginAsset')!='USDT'
            or row.get('contractType') not in ('PERPETUAL','TRADIFI_PERPETUAL')
            or not re.fullmatch(r'[A-Z0-9_]{1,24}USDT',row.get('symbol',''))
            or not {'LIMIT','MARKET','STOP_MARKET'}<=set(row.get('orderTypes',[]))
            or 'IOC' not in row.get('timeInForce',[])):return None
    kind=row.get('underlyingType');tags=set(row.get('underlyingSubType',[]))
    if kind=='COIN' and not tags.intersection({'TradFi','Pre-IPO'}):return 'crypto'
    if kind in ('EQUITY','HK_EQUITY') or (kind=='PREMARKET' and tags.intersection({'TradFi','Pre-IPO'})):
        return 'equity'
    if kind in ('INDEX','COMMODITY'):return 'traditional'
    return None


def expand_flat_scope(data,broker):
    data=Path(data).resolve();directory=data.parent
    if broker.environment!='testnet' or broker.base!='https://demo-fapi.binance.com':
        raise Halt('Scope expansion is restricted to Futures Demo')
    with execution_lease(directory/'demo-v2.lock'):
        old=StrategyPolicy(**json.loads((directory/'demo-policy.json').read_text(encoding='utf8')))
        rows=broker.catalogue()['symbols']
        symbols={row['symbol']:kind for row in rows if (kind:=classify_contract(row)) is not None}
        if any(symbols.get(s)!=kind for s,kind in old.symbols.items()):
            raise Halt('An existing authorized symbol changed classification; review before expansion')
        new=replace(old,symbols=symbols)
        engine=StrategyEngine(directory/'demo-execution.sqlite3',old,broker)
        try:
            if engine.book.positions() or engine.book.pending():raise Halt('Scope changes require a flat settled journal')
            if any(engine.book.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                   for table in ('protection','retired_stops')):
                raise Halt('Protection cleanup must be complete before expanding scope')
            if engine.check_account()['positions'] or broker.all_open_orders() or broker.all_open_stops():
                raise Halt('Scope changes require a flat Demo account with no open orders')
            before=engine.book.public();old_fingerprint=engine.book.get('fingerprint')
            backup_dir=directory/'scope-backups';backup_dir.mkdir(exist_ok=True)
            backup=backup_dir/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.sqlite3')
            target=sqlite3.connect(backup)
            try:engine.book.db.backup(target)
            finally:target.close()
            fingerprint=hashlib.sha256(json.dumps([broker.identity(),new.public()],sort_keys=True).encode()).hexdigest()
            audit=dict(time=now(),old_symbols=old.symbols,new_symbols=symbols,
                       capital_usdt=str(engine.book.capital()),peak_usdt=engine.book.get('peak'),backup=str(backup))
            key='scope_expansion:'+uuid.uuid4().hex
            with engine.book.db:
                engine.book.db.execute('UPDATE meta SET value=? WHERE key=?',(fingerprint,'fingerprint'))
                engine.book.db.execute('INSERT INTO meta VALUES (?,?)',(key,json.dumps(audit)))
            temporary=directory/'demo-policy.scope.tmp'
            try:
                temporary.write_text(json.dumps(new.public()),encoding='utf8')
                temporary.replace(directory/'demo-policy.json')
            except Exception:
                with engine.book.db:
                    engine.book.db.execute('UPDATE meta SET value=? WHERE key=?',(old_fingerprint,'fingerprint'))
                    engine.book.db.execute('DELETE FROM meta WHERE key=?',(key,))
                raise
            if engine.book.public()!=before:raise Halt('Scope expansion unexpectedly changed journal balances/history')
            config=dict(prepare_demo_leverage=True,updated_at=now(),symbol_count=len(symbols),
                        counts={kind:sum(v==kind for v in symbols.values()) for kind in ('crypto','equity','traditional')},
                        excluded_count=len(rows)-len(symbols))
            temporary=directory/'demo-scope.tmp';temporary.write_text(json.dumps(config),encoding='utf8')
            temporary.replace(directory/'demo-scope.json')
            return dict(**config,capital_usdt=str(engine.book.capital()),history_preserved=True)
        finally:engine.close()


def main():
    parser=argparse.ArgumentParser(description='Explicit Futures Demo contract scope expansion')
    parser.add_argument('--expand',action='store_true',required=True)
    args=parser.parse_args()
    from .paths import default_data_dir
    from .credential_store import DemoCredentialVault
    from .live import TradeClient
    from .demo_broker import DemoBroker
    data=default_data_dir()/'demo-v2'/'studio.sqlite3'
    pair=DemoCredentialVault(data).load()
    if not pair:raise SystemExit('Remember the separate Demo connection first')
    client=TradeClient(key=pair[0],secret=pair[1],environment='testnet');client.sync()
    print(json.dumps(expand_flat_scope(data,DemoBroker(client))))


if __name__=='__main__':main()
