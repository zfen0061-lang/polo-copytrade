"""Shared Futures reads and durable-order transport. Subclasses fix the endpoint."""
import hashlib
import time
from .core import dec
from .executor import Halt,APIError,RECOVERABLE_READ_ERRORS


class WriteBlocked(Halt):
    """Local validation failed before a mutating HTTP request was sent."""


class EntrySkipped(WriteBlocked):
    """A late entry quote/freshness check rejected an unsubmitted opening."""

class PreSubmitReadError(WriteBlocked):
    """Authorization GET failed before transport; no write was attempted."""
    def __init__(self,error):
        self.read_error=error
        super().__init__(str(error))

class FuturesBroker:
    def __init__(self,client):
        self.client=client
        self.write_attempts=0
        self.assert_endpoint()

    def identity(self):return hashlib.sha256(self.client.key.encode()).hexdigest()

    def assert_endpoint(self):raise NotImplementedError('A fixed-endpoint broker is required')

    def authorize_write(self,method,path,params):raise Halt('This transport is read-only')

    def request(self,method,path,params=None):
        self.assert_endpoint()
        if method!='GET':
            try:self.authorize_write(method,path,params or {})
            except RECOVERABLE_READ_ERRORS as exc:raise PreSubmitReadError(exc) from None
            except WriteBlocked:raise
            except Exception as exc:
                detail=str(exc) if isinstance(exc,(Halt,APIError)) else type(exc).__name__
                raise WriteBlocked(detail) from None
            # Count before transport: even a failed response can hide a write.
            self.write_attempts+=1
        try:return self.client.request(method,path,params,signed=True)
        except APIError as exc:
            # Only retry a read, once, after correcting its rejected timestamp.
            # Order submissions/cancellations retain their durable reconciliation.
            if method!='GET' or exc.code!=-1021 or getattr(self.client,'handles_timestamp_retry',False) is True:raise
            self.sync();self.assert_endpoint()
            return self.client.request(method,path,params,signed=True)

    def sync(self):
        self.assert_endpoint();self.client.sync()

    def account(self):
        self.assert_endpoint()
        # TradeClient.account performs several signed GETs directly, outside
        # this adapter's request retry. Correct a rejected read snapshot once.
        try:snapshot=self.client.account()
        except APIError as exc:
            if exc.code!=-1021 or getattr(self.client,'handles_timestamp_retry',False) is True:raise
            self.sync();self.assert_endpoint()
            snapshot=self.client.account()
        raw=self.request('GET','/fapi/v3/account')
        asset=next((a for a in raw.get('assets',[]) if a.get('asset')=='USDT'),None)
        if not asset or 'availableBalance' not in asset:raise Halt('USDT available balance could not be verified')
        snapshot['available_usdt']=asset['availableBalance']
        return snapshot

    def symbol_config(self,symbol):
        rows=self.request('GET','/fapi/v1/symbolConfig',{'symbol':symbol})
        selected=next((row for row in rows if row.get('symbol')==symbol),None)
        if not selected:raise Halt('Symbol configuration unavailable')
        return selected

    def fee_rate(self,symbol):return self.request('GET','/fapi/v1/commissionRate',{'symbol':symbol})['takerCommissionRate']
    def rules(self,symbol):
        self.assert_endpoint();return self.client.rules(symbol)
    def quote(self,symbol):
        self.assert_endpoint();return self.client.quote(symbol)
    def mark_price(self,symbol):
        self.assert_endpoint()
        return self.client.request('GET','/fapi/v1/premiumIndex',{'symbol':symbol},signed=False)['markPrice']
    def open_orders(self,symbol):return self.request('GET','/fapi/v1/openOrders',{'symbol':symbol})
    def open_stops(self,symbol):return self.request('GET','/fapi/v1/openAlgoOrders',{'symbol':symbol})
    def place(self,params):return self.request('POST','/fapi/v1/order',params)
    def query(self,symbol,client):return self.request('GET','/fapi/v1/order',dict(symbol=symbol,origClientOrderId=client))
    def query_order_id(self,symbol,order):return self.request('GET','/fapi/v1/order',dict(symbol=symbol,orderId=order))
    def place_stop(self,params):return self.request('POST','/fapi/v1/algoOrder',params)
    def query_stop(self,client):return self.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=client))
    def query_stop_id(self,order):return self.request('GET','/fapi/v1/algoOrder',dict(algoId=order))
    def cancel_stop(self,client):return self.request('DELETE','/fapi/v1/algoOrder',dict(clientAlgoId=client))
    def cancel_stop_id(self,order):return self.request('DELETE','/fapi/v1/algoOrder',dict(algoId=order))
    def catalogue(self):
        self.assert_endpoint()
        if not hasattr(self,'_catalogue') or time.monotonic()-self._catalogue[0]>60:
            value=self.client.request('GET','/fapi/v1/exchangeInfo',signed=False)
            self._catalogue=(time.monotonic(),value)
        return self._catalogue[1]
    def symbol_class(self,symbol):
        from .demo_scope import classify_contract
        row=next((r for r in self.catalogue().get('symbols',[]) if r.get('symbol')==symbol),None)
        return classify_contract(row) if row else None
    def prepare_leverage(self,symbol,leverage):
        self.assert_endpoint()
        if type(leverage) is not int or not 1<=leverage<=10:raise Halt('Leverage is outside the approved range')
        response=self.request('POST','/fapi/v1/leverage',dict(symbol=symbol,leverage=leverage))
        if int(response.get('leverage',0))!=leverage:raise Halt('Leverage change was not confirmed')
    def all_open_orders(self):return self.request('GET','/fapi/v1/openOrders')
    def all_open_stops(self):return self.request('GET','/fapi/v1/openAlgoOrders')

    def fills(self,symbol,order):
        rows=self.request('GET','/fapi/v1/userTrades',dict(symbol=symbol,orderId=order,limit=1000))
        if len(rows)>=1000:raise Halt('Fill pagination requires review; accounting was not truncated')
        return rows

    def funding(self,symbol,start_ms,end_ms):
        rows=[]
        for page in range(1,101):
            batch=self.request('GET','/fapi/v1/income',dict(symbol=symbol,incomeType='FUNDING_FEE',
                startTime=start_ms,endTime=end_ms,page=page,limit=1000))
            rows.extend(batch)
            if len(batch)<1000:return rows
        raise Halt('Funding history pagination exceeded its bounded window')
