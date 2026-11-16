"""Shared strategy accounting. Concrete engines enforce separate endpoint gates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .core import Invalid,dec
from .executor import Halt,APIError,quantize
from .futures_broker import WriteBlocked,EntrySkipped

ZERO=dec('0')
TERMINAL={'FILLED','CANCELED','EXPIRED','EXPIRED_IN_MATCH','REJECTED'}


class RiskLimit(Halt):
    """A verified strategy loss threshold; callers may close owned demo positions."""


@dataclass(frozen=True)
class StrategyPolicy:
    initial_capital: str
    margin_loss_fraction: str
    crypto_leverage: int
    equity_leverage: int
    max_deviation: str
    max_loss: str
    loss_basis: str
    max_signal_age: int
    symbols: dict

    def __post_init__(self):
        for value in (self.initial_capital,self.max_loss):
            if dec(value)<=0:raise Invalid('Capital and cumulative loss limit must be positive')
        if dec(self.max_loss)>dec(self.initial_capital):raise Invalid('Loss budget exceeds initial allocation')
        for value in (self.margin_loss_fraction,self.max_deviation):
            if not 0<dec(value)<1:raise Invalid('Stop/deviation must be a fraction between zero and one')
        if type(self.crypto_leverage) is not int or not 1<=self.crypto_leverage<=10:
            raise Invalid('Crypto leverage must be 1–10')
        if type(self.equity_leverage) is not int or not 1<=self.equity_leverage<=5:
            raise Invalid('Equity leverage must be 1–5')
        if self.loss_basis not in ('initial_net_loss','peak_drawdown'):
            raise Invalid('Select initial-net-loss or peak-drawdown cumulative loss basis')
        if type(self.max_signal_age) is not int or not 1<=self.max_signal_age<=3600:
            raise Invalid('Choose an entry signal age from 1 to 3600 seconds')
        import re
        if not self.symbols or len(self.symbols)>1000 or any(
                not re.fullmatch(r'[A-Z0-9_]{1,24}USDT',s) or kind not in ('crypto','equity','traditional')
                for s,kind in self.symbols.items()):
            raise Invalid('Explicit USDT crypto/equity symbol classification is required')

    def leverage(self,symbol):
        if symbol not in self.symbols:raise Halt('Symbol is not authorized by the strategy policy')
        return self.crypto_leverage if self.symbols[symbol]=='crypto' else self.equity_leverage

    def public(self):return dict(self.__dict__)


class CapitalBook:
    def __init__(self,path,policy,identity):
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS positions(symbol TEXT,side TEXT,qty TEXT,entry TEXT,leverage INTEGER,
            opened_ms INTEGER,origin TEXT,PRIMARY KEY(symbol,side));
          CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,client_id TEXT UNIQUE,state TEXT,
            payload TEXT,result TEXT);
          CREATE TABLE IF NOT EXISTS cash(id TEXT PRIMARY KEY,kind TEXT,amount TEXT,asset TEXT,
            symbol TEXT,exchange_ms INTEGER);
          CREATE TABLE IF NOT EXISTS intervals(symbol TEXT,side TEXT,start_ms INTEGER,end_ms INTEGER);
          CREATE TABLE IF NOT EXISTS protection(symbol TEXT,side TEXT,client_id TEXT,params TEXT,
            PRIMARY KEY(symbol,side));
          CREATE TABLE IF NOT EXISTS retired_stops(client_id TEXT PRIMARY KEY,symbol TEXT,side TEXT);
          CREATE TABLE IF NOT EXISTS protection_ack(client_id TEXT PRIMARY KEY,algo_id TEXT NOT NULL);
        ''')
        fingerprint=hashlib.sha256(json.dumps([identity,policy.public()],sort_keys=True).encode()).hexdigest()
        previous=self.get('fingerprint')
        if previous and previous!=fingerprint:
            self.db.close();raise Halt('Strategy/account settings changed; use a separate reviewed journal')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('fingerprint',fingerprint))
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('initial',str(dec(policy.initial_capital))))
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('peak',str(dec(policy.initial_capital))))
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('started_ms',str(int(time.time()*1000))))

    def get(self,key):
        row=self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    def positions(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM positions WHERE CAST(qty AS REAL)>0')]

    def capital(self):
        return dec(self.get('initial'))+sum((dec(r[0]) for r in self.db.execute('SELECT amount FROM cash')),ZERO)

    def pending(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM intents WHERE state IN ('submitting','uncertain','accounting')")]

    def public(self):
        return dict(capital_usdt=str(self.capital()),positions=self.positions(),
                    intents=[dict(id=r['id'],state=r['state']) for r in self.db.execute('SELECT id,state FROM intents ORDER BY rowid DESC LIMIT 30')],
                    peak_usdt=self.get('peak'),pending_count=len(self.pending()))

    def funding(self,records):
        with self.db:
            for item in records:
                if item.get('incomeType')!='FUNDING_FEE':continue
                if item.get('asset')!='USDT':raise Halt('Funding currency conversion is not implemented')
                stamp=int(item['time']);symbol=item['symbol']
                owned=self.db.execute('SELECT 1 FROM intervals WHERE symbol=? AND start_ms<=? '
                    'AND (end_ms IS NULL OR end_ms>=?)',(symbol,stamp,stamp)).fetchone()
                if owned:
                    key='funding:'+symbol+':'+str(item['tranId'])
                    self.db.execute('INSERT OR IGNORE INTO cash VALUES (?,?,?,?,?,?)',
                        (key,'funding',str(dec(item['income'])),'USDT',symbol,stamp))


class FuturesStrategyEngine:
    def __init__(self,path,policy,broker,prepare_demo_leverage=False):
        self.validate_broker(broker)
        self.policy,self.broker=policy,broker
        if type(prepare_demo_leverage) is not bool:raise Halt('Demo leverage preparation must be explicit')
        self.prepare_demo_leverage=prepare_demo_leverage
        self.price_check=None
        self.book=CapitalBook(path,policy,broker.identity())

    def validate_broker(self,broker):raise Halt('Choose an explicitly gated strategy engine')

    def prepare_contract(self,symbol,leverage):
        if int(self.broker.symbol_config(symbol)['leverage'])!=leverage:
            self.broker.prepare_leverage(symbol,leverage)
        if int(self.broker.symbol_config(symbol)['leverage'])!=leverage:
            raise Halt('Leverage could not be read back after preparation')

    def close(self):self.book.db.close()

    @staticmethod
    def stop_matches(status,params):
        try:
            return (dec(status['triggerPrice'])==dec(params['triggerPrice'])
                and dec(status['quantity'])==dec(params['quantity'])
                and all(status.get(k)==params[k] for k in ('symbol','side','positionSide','workingType'))
                and status.get('orderType',status.get('type'))==params['type']
                and str(status.get('reduceOnly',False)).lower()==str(params.get('reduceOnly','false')).lower()
                and str(status.get('closePosition',False)).lower()=='false')
        except (KeyError,Invalid):return False

    @staticmethod
    def actual_positions(account):
        actual={}
        for position in account['positions']:
            qty=dec(position['positionAmt'])
            if not qty:continue
            side=position['positionSide'] if position['positionSide'] in ('LONG','SHORT') else ('LONG' if qty>0 else 'SHORT')
            actual[(position['symbol'],side)]=(abs(qty),position)
        return actual

    def check_account(self,allow_unowned=False):
        account=self.broker.account()
        actual=self.actual_positions(account)
        owned={(p['symbol'],p['side']):dec(p['qty']) for p in self.book.positions()}
        for key,qty in owned.items():
            if actual.get(key,(ZERO,None))[0]!=qty:
                raise Halt('Owned quantity changed; reconcile stop fills or manual actions before continuing')
        if not allow_unowned and any(key not in owned for key in actual):
            raise Halt('Unowned positions exist; manual positions are never adopted automatically')
        return account

    def adopt(self,snapshot):
        if self.book.positions() or self.book.pending():raise Halt('Adoption requires an empty, settled strategy')
        account=self.broker.account();actual=self.actual_positions(account)
        key=(snapshot['symbol'],snapshot['side'])
        if len(actual)!=1 or key not in actual:raise Halt('Adoption requires one explicitly reviewed position')
        qty,position=actual[key]
        if qty!=dec(snapshot['qty']) or dec(position['entryPrice'])!=dec(snapshot['entry']):
            raise Halt('Adoption snapshot is stale')
        leverage=self.policy.leverage(key[0])
        if int(self.broker.symbol_config(key[0])['leverage'])!=leverage:
            raise Halt('Existing leverage differs from policy; leverage is never changed automatically')
        if self.broker.open_orders(key[0]) or self.broker.open_stops(key[0]):
            raise Halt('Review existing orders/stops before adoption')
        stamp=int(time.time()*1000)
        with self.book.db:
            self.book.db.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?)',
                (*key,str(qty),str(dec(snapshot['entry'])),leverage,stamp,'adopted'))
            self.book.db.execute('INSERT INTO intervals VALUES (?,?,?,NULL)',(*key,stamp))
        try:self.protect(key[0],key[1],'adopt-'+str(stamp))
        except Exception:raise Halt('Adopted testnet position lacks confirmed protection; review manually') from None
        return self.book.public()

    def risk_check(self,account):
        equity=self.book.capital()
        actual=self.actual_positions(account)
        for p in self.book.positions():
            equity+=dec(actual[(p['symbol'],p['side'])][1].get('unRealizedProfit','0'))
        peak=max(dec(self.book.get('peak')),equity)
        with self.book.db:self.book.db.execute('UPDATE meta SET value=? WHERE key=?',(str(peak),'peak'))
        reference=dec(self.policy.initial_capital) if self.policy.loss_basis=='initial_net_loss' else peak
        if reference-equity>=dec(self.policy.max_loss):raise RiskLimit('Strategy cumulative loss limit reached; new entries stopped')
        if equity<=0:raise RiskLimit('Strategy capital is exhausted')

    def plan(self,event):
        symbol,action=event['symbol'],event['action']
        mapping={'OPEN_LONG':('BUY','LONG',True),'OPEN_SHORT':('SELL','SHORT',True),
                 'CLOSE_LONG':('SELL','LONG',False),'CLOSE_SHORT':('BUY','SHORT',False)}
        if action not in mapping:raise Halt('Unknown signal action')
        if symbol not in self.policy.symbols:return None,'symbol_not_allowed'
        side,position_side,opening=mapping[action]
        stamp=datetime.fromisoformat(event['source_time'])
        if stamp.utcoffset() is None:raise Halt('Signal timezone is required')
        age=(datetime.now(timezone.utc)-stamp).total_seconds()
        if age < -5:raise Halt('Future signal timestamp')
        if opening:
            detected=datetime.fromisoformat(event.get('detected_time') or event['source_time'])
            if detected.utcoffset() is None:raise Halt('Detection timezone is required')
            detection_age=(datetime.now(timezone.utc)-detected).total_seconds()
            if detection_age < -5:raise Halt('Future detection timestamp')
            if detection_age>self.policy.max_signal_age:return None,'entry_expired'
        account=self.check_account()
        owned=next((p for p in self.book.positions() if (p['symbol'],p['side'])==(symbol,position_side)),None)
        if not opening and not owned:return None,'no_matching_owned_position'
        if self.book.pending():raise Halt('An unresolved order must be queried before any new order')
        if opening:
            self.risk_check(account)
            if self.book.positions():return None,'allocated_pool_in_use'
            if self.broker.open_orders(symbol) or self.broker.open_stops(symbol):raise Halt('Unowned orders exist')
            if self.prepare_demo_leverage and self.broker.symbol_class(symbol)!=self.policy.symbols[symbol]:
                return None,'symbol_not_tradeable_or_class_changed'
        leverage=self.policy.leverage(symbol) if opening else owned['leverage']
        if opening:
            if self.prepare_demo_leverage:self.prepare_contract(symbol,leverage)
            elif int(self.broker.symbol_config(symbol)['leverage'])!=leverage:
                raise Halt('Symbol leverage differs from policy; configure it before execution')
        rules=self.broker.rules(symbol);lot=rules['LOT_SIZE'] if opening else rules.get('MARKET_LOT_SIZE',rules['LOT_SIZE'])
        client='pv2_'+hashlib.sha256(event['id'].encode()).hexdigest()[:28]
        params=dict(symbol=symbol,side=side,positionSide=position_side if account['hedge_mode'] else 'BOTH',
                    newClientOrderId=client,newOrderRespType='RESULT')
        if opening:
            bid,ask=self.broker.quote(symbol);bid,ask=dec(bid),dec(ask)
            if not 0<bid<=ask:raise Halt('Invalid quote')
            reference=dec(event['price']);deviation=dec(self.policy.max_deviation)
            if reference<=0:raise Halt('Invalid reference price')
            quote=ask if side=='BUY' else bid
            signed_deviation=(quote-reference)/reference
            self.price_check=dict(reference_price=str(reference),executable_quote=str(quote),
                signed_percent=str(signed_deviation*100),absolute_percent=str(abs(signed_deviation)*100),
                source_delay_seconds=str(age),decision_time=datetime.now(timezone.utc).isoformat())
            if abs(signed_deviation)>deviation:return None,'entry_deviation'
            limit=quantize(reference*(1+deviation if side=='BUY' else 1-deviation),rules['PRICE_FILTER']['tickSize'],up=side=='SELL')
            if (side=='BUY' and ask>limit) or (side=='SELL' and bid<limit):return None,'entry_deviation'
            fee=dec(self.broker.fee_rate(symbol))
            if not 0<=fee<dec('0.02'):raise Halt('Unverified fee rate')
            # Multi-assets collateral is not counted as spendable USDT.
            available=dec(account['available_usdt'])
            pool=max(ZERO,min(self.book.capital(),available))
            margin=pool/(1+2*leverage*fee)
            qty=quantize(margin*leverage/max(limit,ask),lot['stepSize'])
            if qty*limit<dec(rules.get('MIN_NOTIONAL',{}).get('notional','0')):return None,'below_minimum_notional'
            params.update(type='LIMIT',timeInForce='IOC',price=format(limit,'f'))
        else:
            qty=quantize(owned['qty'],lot['stepSize'])
            if qty!=dec(owned['qty']):raise Halt('Owned residual does not fit quantity step; manual review required')
            params['type']='MARKET'
            if not account['hedge_mode']:params['reduceOnly']='true'
        if not dec(lot['minQty'])<=qty<=dec(lot['maxQty']):
            if not opening:raise Halt('Full owned close does not fit exchange quantity limits; review the demo position')
            return None,'quantity_filter'
        params['quantity']=format(qty,'f')
        return dict(event=dict(event),params=params,position_side=position_side,opening=opening,
                    leverage=leverage,submitted_ms=int(time.time()*1000),price_check=self.price_check),None

    def settle(self,intent,response):
        if response.get('status') not in TERMINAL:raise Halt('Order is not terminal; query it before proceeding')
        params=intent['params'];symbol=params['symbol'];side=intent['position_side']
        if response.get('clientOrderId')!=params['newClientOrderId']:
            raise Halt('Order acknowledgement does not match the durable intent')
        executed=dec(response.get('executedQty','0'))
        if executed<0 or executed>dec(params['quantity']):raise Halt('Unexpected fill quantity')
        fills=self.broker.fills(symbol,response['orderId']) if executed else []
        if any(str(f.get('orderId'))!=str(response['orderId']) or f.get('symbol')!=symbol for f in fills):
            raise Halt('Fill identity does not match the submitted order')
        if sum((dec(f['qty']) for f in fills),ZERO)!=executed:raise Halt('Fill records are incomplete; accounting remains pending')
        if any(f.get('commissionAsset')!='USDT' for f in fills):raise Halt('Non-USDT fees need verified conversion')
        with self.book.db:
            current=self.book.db.execute('SELECT * FROM positions WHERE symbol=? AND side=?',(symbol,side)).fetchone()
            qty=dec(current['qty']) if current else ZERO
            entry=dec(current['entry']) if current else ZERO
            new_fills=[]
            for fill in fills:
                key='trade:'+symbol+':'+str(fill['id'])
                if self.book.db.execute('SELECT 1 FROM cash WHERE id=?',(key,)).fetchone():continue
                amount=dec(fill['realizedPnl'])-dec(fill['commission'])
                self.book.db.execute('INSERT INTO cash VALUES (?,?,?,?,?,?)',
                    (key,'fill',str(amount),'USDT',symbol,int(fill['time'])))
                new_fills.append(fill)
            filled=sum((dec(f['qty']) for f in new_fills),ZERO)
            if intent['opening'] and filled:
                entry=(qty*entry+sum((dec(f['qty'])*dec(f['price']) for f in new_fills),ZERO))/(qty+filled)
                if not qty:self.book.db.execute('INSERT INTO intervals VALUES (?,?,?,NULL)',(symbol,side,intent['submitted_ms']))
                qty+=filled
            elif not intent['opening']:
                if filled>qty:raise Halt('Close would exceed owned quantity')
                qty-=filled
                if not qty:self.book.db.execute('UPDATE intervals SET end_ms=? WHERE symbol=? AND side=? AND end_ms IS NULL',
                    (max((int(f['time']) for f in new_fills),default=int(time.time()*1000)),symbol,side))
            if current or filled:
                self.book.db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?)',
                    (symbol,side,str(qty),str(entry),intent['leverage'],current['opened_ms'] if current else intent['submitted_ms'],current['origin'] if current else 'new'))
            self.book.db.execute('UPDATE intents SET state=?,result=? WHERE id=?',
                ('settled',json.dumps(response),intent['event']['id']))
        self.check_account()
        return response

    def submit(self,intent):
        key=intent['event']['id'];params=intent['params']
        with self.book.db:
            self.book.db.execute('INSERT INTO intents VALUES (?,?,?,?,NULL)',
                (key,params['newClientOrderId'],'submitting',json.dumps(intent)))
        try:response=self.broker.place(params)
        except WriteBlocked as exc:
            with self.book.db:self.book.db.execute('UPDATE intents SET state=?,result=? WHERE id=?',
                ('skipped' if isinstance(exc,EntrySkipped) else 'rejected',json.dumps(dict(reason=str(exc))),key))
            raise
        except Exception:
            with self.book.db:self.book.db.execute('UPDATE intents SET state=? WHERE id=?',('uncertain',key))
            try:response=self.broker.query(params['symbol'],params['newClientOrderId'])
            except Exception:raise Halt('Order outcome is unknown; it will be queried, never blindly resent') from None
        with self.book.db:self.book.db.execute('UPDATE intents SET state=?,result=? WHERE id=?',('accounting',json.dumps(response),key))
        return self.settle(intent,response)

    def recover(self):
        for job in self.book.pending():
            intent=json.loads(job['payload']);params=intent['params']
            try:response=self.broker.query(params['symbol'],params['newClientOrderId'])
            except Exception:raise Halt('Pending order remains unknown; no resubmission') from None
            self.settle(intent,response)
        self.reconcile_stops()
        owned={(p['symbol'],p['side']):p for p in self.book.positions()}
        targets=set(owned)|{(r['symbol'],r['side']) for r in self.book.db.execute('SELECT symbol,side FROM protection')}
        for symbol,side in targets:
            self.protect(symbol,side,'recovery-'+str(owned.get((symbol,side),{}).get('opened_ms',0)))
        self.cleanup_retired_stops()

    def query_protection(self,client):
        saved=self.book.db.execute('SELECT algo_id FROM protection_ack WHERE client_id=?',(client,)).fetchone()
        for attempt in range(3):
            try:
                state=(self.broker.query_stop_id(saved['algo_id']) if saved and hasattr(self.broker,'query_stop_id')
                       else self.broker.query_stop(client))
                if state.get('clientAlgoId',client)!=client:
                    raise Halt('Stop acknowledgement identity does not match its durable intent')
                return state
            except APIError as exc:
                if exc.code!=-2013 or attempt==2:raise
                time.sleep(.25*(attempt+1))

    def cancel_protection(self,client):
        saved=self.book.db.execute('SELECT algo_id FROM protection_ack WHERE client_id=?',(client,)).fetchone()
        if saved and hasattr(self.broker,'cancel_stop_id'):return self.broker.cancel_stop_id(saved['algo_id'])
        return self.broker.cancel_stop(client)

    def confirm_stop_canceled(self,client):
        """Query after a single cancel; tolerate a lost reply or delayed status.

        Never forget an unresolved protection id, and never treat a triggered
        stop as canceled: its actual fill still requires reconciliation.
        """
        terminal={'CANCELED','FINISHED','EXPIRED'}
        status=self.query_protection(client)
        if status.get('algoStatus') in terminal:return
        if status.get('algoStatus')!='NEW':
            raise Halt('Stop cancellation is not confirmed; status='+str(status.get('algoStatus')))
        cancel_error=None
        try:self.cancel_protection(client)
        except Exception as exc:cancel_error=exc
        for attempt in range(3):
            try:
                status=self.query_protection(client)
                if status.get('algoStatus') in terminal:return
            except Exception as exc:cancel_error=exc
            if attempt<2:time.sleep(.25*(attempt+1))
        detail=(str(cancel_error) if isinstance(cancel_error,(Halt,APIError,Invalid))
                else type(cancel_error).__name__) if cancel_error else 'status='+str(status.get('algoStatus'))
        raise Halt('Stop cancellation is not confirmed; '+detail)

    def cleanup_retired_stops(self):
        for row in self.book.db.execute('SELECT * FROM retired_stops').fetchall():
            self.confirm_stop_canceled(row['client_id'])
            with self.book.db:self.book.db.execute('DELETE FROM retired_stops WHERE client_id=?',(row['client_id'],))

    def reconcile_stops(self):
        actual=self.actual_positions(self.broker.account())
        for position in self.book.positions():
            symbol,side=position['symbol'],position['side']
            if actual.get((symbol,side),(ZERO,None))[0]==dec(position['qty']):continue
            stored=self.book.db.execute('SELECT * FROM protection WHERE symbol=? AND side=?',(symbol,side)).fetchone()
            if not stored:raise Halt('Position changed without a known exchange stop')
            state=self.query_protection(stored['client_id'])
            if state.get('algoStatus') not in ('FINISHED','TRIGGERED') or not state.get('actualOrderId'):
                raise Halt('Position change is not a verified stop fill; manual review required')
            response=self.broker.query_order_id(symbol,state['actualOrderId'])
            key='stop:'+stored['client_id']
            params=dict(symbol=symbol,quantity=position['qty'],newClientOrderId=response['clientOrderId'])
            intent=dict(event={'id':key},params=params,position_side=side,opening=False,
                        leverage=position['leverage'],submitted_ms=position['opened_ms'])
            with self.book.db:self.book.db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,?,NULL)',
                (key,response['clientOrderId'],'accounting',json.dumps(intent)))
            self.settle(intent,response)
            self.protect(symbol,side,key)

    def protect(self,symbol,side,reference):
        position=next((p for p in self.book.positions() if (p['symbol'],p['side'])==(symbol,side)),None)
        old=self.book.db.execute('SELECT * FROM protection WHERE symbol=? AND side=?',(symbol,side)).fetchone()
        if not position:
            if old:
                self.confirm_stop_canceled(old['client_id'])
                with self.book.db:self.book.db.execute('DELETE FROM protection WHERE symbol=? AND side=?',(symbol,side))
            return
        account=self.check_account();rules=self.broker.rules(symbol)
        distance=dec(self.policy.margin_loss_fraction)/position['leverage']
        trigger=quantize(dec(position['entry'])*(1-distance if side=='LONG' else 1+distance),rules['PRICE_FILTER']['tickSize'],up=side=='LONG')
        params=dict(symbol=symbol,algoType='CONDITIONAL',type='STOP_MARKET',side='SELL' if side=='LONG' else 'BUY',
                    positionSide=side if account['hedge_mode'] else 'BOTH',quantity=position['qty'],
                    triggerPrice=format(trigger,'f'),workingType='MARK_PRICE')
        if not account['hedge_mode']:params['reduceOnly']='true'
        if old:
            status=self.query_protection(old['client_id'])
            if status.get('algoStatus')=='NEW' and self.stop_matches(status,params):
                return
        if hasattr(self.broker,'mark_price'):
            mark=dec(self.broker.mark_price(symbol))
            if mark<=0:raise Halt('Invalid mark price; stop submission blocked')
            if (side=='LONG' and mark<=trigger) or (side=='SHORT' and mark>=trigger):
                raise Halt('Configured stop is already crossed by mark price; no automatic stop widening: '
                           +'mark='+str(mark)+', trigger='+str(trigger))
        client='ps2_'+hashlib.sha256((reference+symbol+side+position['qty']).encode()).hexdigest()[:28]
        params['clientAlgoId']=client
        submission_error=None
        # Persist protection intent before submission. Recovery queries its stable id.
        if not old or old['client_id']!=client:
            with self.book.db:
                if old:self.book.db.execute('INSERT OR IGNORE INTO retired_stops VALUES (?,?,?)',(old['client_id'],symbol,side))
                self.book.db.execute('INSERT OR REPLACE INTO protection VALUES (?,?,?,?)',(symbol,side,client,json.dumps(params)))
            try:
                acknowledgement=self.broker.place_stop(params)
                if acknowledgement.get('algoId') is not None:
                    if acknowledgement.get('clientAlgoId',client)!=client:
                        raise Halt('Stop submission acknowledged a different client identity')
                    with self.book.db:self.book.db.execute('INSERT OR REPLACE INTO protection_ack VALUES (?,?)',
                                                          (client,str(acknowledgement['algoId'])))
            except Exception as exc:submission_error=exc
        try:status=self.query_protection(client)
        except Exception as exc:
            if submission_error is not None:
                def detail(error):
                    return str(error) if isinstance(error,(Halt,APIError,Invalid)) else type(error).__name__
                raise Halt('Stop submission was not confirmed: '+detail(submission_error)
                           +'; subsequent query: '+detail(exc)) from None
            raise
        if status.get('algoStatus')!='NEW' or not self.stop_matches(status,params):
            raise Halt('Exchange stop is not confirmed; no new orders allowed')
        self.cleanup_retired_stops()

    def skip(self,event,reason):
        detail=dict(reason=reason)
        if self.price_check:detail['price_check']=self.price_check
        with self.book.db:
            inserted=self.book.db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,?,?)',
                (event['id'],'skip_'+hashlib.sha256(event['id'].encode()).hexdigest()[:28],
                 'skipped','{}',json.dumps(detail)))
        return dict(state='skipped' if inserted.rowcount else 'duplicate',**detail)

    def handle(self,event):
        self.validate_broker(self.broker)
        self.price_check=None
        self.recover()
        if self.book.db.execute('SELECT 1 FROM intents WHERE id=?',(event['id'],)).fetchone():return dict(state='duplicate')
        intent,reason=self.plan(event)
        if intent is None:return self.skip(event,reason)
        try:response=self.submit(intent)
        except EntrySkipped as exc:return dict(state='skipped',reason=str(exc),price_check=self.price_check)
        try:self.protect(event['symbol'],intent['position_side'],event['id'])
        except Exception as exc:
            # Emergency exits are also durable, quantity-bounded, demo-only intents.
            positions=self.book.positions()
            target=next((p for p in positions if p['symbol']==event['symbol'] and p['side']==intent['position_side']),None)
            detail=str(exc) if isinstance(exc,(Halt,Invalid,APIError)) else type(exc).__name__
            if not target:
                raise Halt('Owned demo position is flat; stop cleanup needs review: '+detail) from None
            if target:
                exit_event=dict(event,id=event['id']+'-protection-exit',action='CLOSE_'+target['side'])
                try:
                    exit_intent,_=self.plan(exit_event)
                    if exit_intent:self.submit(exit_intent)
                except Exception:pass
            raise Halt('Protection failed; owned-position emergency exit attempted. Review position and stop state before restarting: '+detail) from None
        return dict(state='settled',order=response,pool=self.book.public(),price_check=self.price_check)


class StrategyEngine(FuturesStrategyEngine):
    """Existing Demo API remains locked, including after the common-core split."""
    def validate_broker(self,broker):
        if broker.environment!='testnet' or broker.base!='https://demo-fapi.binance.com':
            raise Halt('Version-two execution is locked to Binance Futures demo; production is disabled')
