"""Production transport and strategy, disarmed until an explicit local start.

Imports, account inspection and policy configuration cannot submit an order.
Every write must match a durable strategy intent and a process-local permit.
"""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import threading

from .core import dec
from .executor import Halt,APIError
from .futures_broker import FuturesBroker,EntrySkipped
from .strategy_v2 import FuturesStrategyEngine


def policy_digest(policy):
    return hashlib.sha256(json.dumps(policy.public(),sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ExecutionPermit:
    account: str
    policy_hash: str
    journal: str
    pid: int=field(default_factory=os.getpid)
    revoked: threading.Event=field(default_factory=threading.Event,compare=False)

    def check(self,broker,policy,path):
        if (self.revoked.is_set() or self.pid!=os.getpid() or self.account!=broker.identity()
                or self.policy_hash!=policy_digest(policy) or self.journal!=str(Path(path).resolve())):
            raise Halt('Production execution is disarmed or its reviewed account/policy changed')


class ProductionBroker(FuturesBroker):
    environment='production'
    base='https://fapi.binance.com'

    def __init__(self,client,entry_guard=None):
        self.permit=None;self.book=None;self.policy=None;self.journal=None
        self.entry_guard=entry_guard or (lambda:False)
        self._preparing=None;self._sent=set()
        super().__init__(client)

    def assert_endpoint(self):
        if (self.environment!='production' or self.base!='https://fapi.binance.com'
                or self.client.environment!='production' or self.client.base!='https://fapi.binance.com'):
            raise Halt('Production endpoint identity changed; transport blocked')

    def identity(self):return hashlib.sha256(('production:'+self.client.key).encode()).hexdigest()

    def arm(self,permit,policy,book,path):
        self.assert_endpoint();permit.check(self,policy,path)
        self.permit,self.policy,self.book,self.journal=permit,policy,book,Path(path).resolve()

    def disarm(self):
        if self.permit:self.permit.revoked.set()
        self.permit=None

    def require_permit(self):
        self.assert_endpoint()
        if self.permit is None:raise Halt('Production execution is disarmed')
        self.permit.check(self,self.policy,self.journal)

    @staticmethod
    def require_account_mode(account):
        if not account.get('can_trade') or account.get('hedge_mode') or account.get('multi_assets'):
            raise Halt('Production requires trading permission, one-way positions and single-asset USDT mode; modes are never changed automatically')

    def require_flat(self):
        account=self.account();self.require_account_mode(account)
        if account['positions'] or self.all_open_orders() or self.all_open_stops():
            raise Halt('Production startup/entry requires a flat account without external positions or orders')
        if self.request('GET','/fapi/v1/feeBurn').get('feeBurn') is not False:
            raise Halt('Disable BNB futures fee payment on Binance before following; this allocation accounts for USDT fees only')
        return account

    def authorize_write(self,method,path,params):
        self.require_permit()
        if (method,path) in {('POST','/fapi/v1/leverage'),('POST','/fapi/v1/marginType')}:
            expected=(dict(symbol=self._preparing,leverage=self.policy.leverage(self._preparing))
                      if path.endswith('/leverage') and self._preparing else
                      dict(symbol=self._preparing,marginType='ISOLATED'))
            if not self._preparing or params!=expected:raise Halt('Unreviewed contract configuration write')
            if not self.entry_guard():raise Halt('New entries are paused or the verified source is stale')
            return
        if method=='POST' and path=='/fapi/v1/order':
            row=self.book.db.execute('SELECT state,payload FROM intents WHERE client_id=?',
                                     (params.get('newClientOrderId'),)).fetchone()
            if not row or row['state']!='submitting':raise Halt('Order has no fresh durable production intent')
            intent=json.loads(row['payload'])
            if intent['params']!=params:raise Halt('Order differs from its durable intent')
            if intent['opening']:
                if not self.entry_guard():raise EntrySkipped('entries_paused_or_source_stale')
                event=intent['event'];stamp=datetime.fromisoformat(event.get('detected_time') or event['source_time'])
                age=(datetime.now(timezone.utc)-stamp).total_seconds()
                if not -5<=age<=self.policy.max_signal_age:raise EntrySkipped('entry_expired_before_submission')
                self.require_flat()
                bid,ask=self.quote(params['symbol']);quote=ask if params['side']=='BUY' else bid
                if abs(dec(quote)/dec(event['price'])-1)>dec(self.policy.max_deviation):
                    raise EntrySkipped('entry_deviation_before_submission')
                config=self.symbol_config(params['symbol'])
                if (config.get('marginType','').upper()!='ISOLATED' or int(config['leverage'])!=intent['leverage']
                        or config.get('isAutoAddMargin') not in (False,'false')):
                    raise Halt('Production margin mode/leverage changed before submission')
                if (datetime.now(timezone.utc)-stamp).total_seconds()>self.policy.max_signal_age:
                    raise EntrySkipped('entry_expired_before_submission')
            else:self.require_owned_close(params,intent['position_side'])
            if intent['opening'] and not self.entry_guard():raise EntrySkipped('entries_paused_or_source_stale')
            key=('order',params['newClientOrderId'])
        elif method=='POST' and path=='/fapi/v1/algoOrder':
            row=self.book.db.execute('SELECT params,side FROM protection WHERE client_id=?',
                                     (params.get('clientAlgoId'),)).fetchone()
            if not row or json.loads(row['params'])!=params:raise Halt('Stop has no matching durable protection intent')
            self.require_owned_close(params,row['side'])
            if params.get('type')!='STOP_MARKET' or params.get('workingType')!='MARK_PRICE':
                raise Halt('Only the strategy mark-price stop is authorized')
            key=('stop',params['clientAlgoId'])
        elif method=='DELETE' and path=='/fapi/v1/algoOrder':
            if set(params)=={'algoId'}:
                row=self.book.db.execute('SELECT client_id FROM protection_ack WHERE algo_id=?',(str(params['algoId']),)).fetchone()
                client=row['client_id'] if row else None
            elif set(params)=={'clientAlgoId'}:client=params['clientAlgoId']
            else:raise Halt('Only one known strategy stop can be canceled')
            if not client or not (self.book.db.execute('SELECT 1 FROM protection WHERE client_id=?',(client,)).fetchone()
                    or self.book.db.execute('SELECT 1 FROM retired_stops WHERE client_id=?',(client,)).fetchone()):
                raise Halt('Cannot cancel a stop not owned by this strategy')
            # A single invocation is never retried by the transport. Later
            # reconciliation queries status before deciding on another cancel.
            return
        else:raise Halt('Production write endpoint is not authorized')
        self.require_permit()
        if key in self._sent:raise Halt('Submission was already attempted; query its outcome instead')
        self._sent.add(key)

    def require_owned_close(self,params,side):
        owned=next((p for p in self.book.positions() if (p['symbol'],p['side'])==(params['symbol'],side)),None)
        if (not owned or dec(params['quantity'])!=dec(owned['qty']) or params.get('reduceOnly')!='true'
                or params.get('positionSide')!='BOTH' or params.get('closePosition') not in (None,'false')
                or params.get('side')!=('SELL' if side=='LONG' else 'BUY')):
            raise Halt('Exit/protection must reduce exactly the matching owned position')
        account=self.account();self.require_account_mode(account)
        actual=FuturesStrategyEngine.actual_positions(account)
        if actual.get((params['symbol'],side),(dec('0'),None))[0]!=dec(owned['qty']):
            raise Halt('Owned position changed; no manual position may be closed')

    def prepare_contract(self,symbol):
        self.require_permit()
        if self.book.positions() or self.book.pending():raise Halt('Contract preparation requires an unused capital pool')
        self.require_flat()
        if self.symbol_class(symbol)!=self.policy.symbols.get(symbol):raise Halt('Production contract classification changed')
        self._preparing=symbol
        try:
            config=self.symbol_config(symbol)
            if config.get('isAutoAddMargin') not in (False,'false'):
                raise Halt('Disable automatic margin additions for this contract on Binance before following; the strategy allocation must not draw extra margin')
            if config.get('marginType','').upper()!='ISOLATED':
                try:self.request('POST','/fapi/v1/marginType',dict(symbol=symbol,marginType='ISOLATED'))
                except APIError as exc:
                    if exc.code!=-4046:raise
            if int(config['leverage'])!=self.policy.leverage(symbol):
                self.prepare_leverage(symbol,self.policy.leverage(symbol))
            verified=self.symbol_config(symbol)
            if verified.get('marginType','').upper()!='ISOLATED' or int(verified['leverage'])!=self.policy.leverage(symbol):
                raise Halt('Production isolated margin/leverage was not verified')
        finally:self._preparing=None


class ProductionEngine(FuturesStrategyEngine):
    def __init__(self,path,policy,broker,permit):
        self.validate_broker(broker);permit.check(broker,policy,path)
        super().__init__(path,policy,broker,prepare_demo_leverage=True)
        try:
            if self.book.get('environment') not in (None,'production'):
                raise Halt('A separate production journal is required')
            with self.book.db:self.book.db.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('environment','production'))
            broker.arm(permit,policy,self.book,path)
        except Exception:self.book.db.close();raise

    def validate_broker(self,broker):
        if not isinstance(broker,ProductionBroker):raise Halt('The production engine requires its explicitly gated broker')
        broker.assert_endpoint()

    def prepare_contract(self,symbol,leverage):self.broker.prepare_contract(symbol)

    def adopt(self,snapshot):raise Halt('Production manual positions cannot be adopted by this workspace')

    def close(self):
        self.broker.disarm()
        super().close()
