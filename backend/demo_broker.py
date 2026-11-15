"""Strict demo-only transport for the v2 strategy. No production order endpoint."""
import hashlib
import time
from .core import dec
from .executor import Halt


class DemoBroker:
    environment='testnet'
    base='https://demo-fapi.binance.com'

    def __init__(self,client):
        if client.environment!='testnet' or client.base!=self.base:
            raise Halt('A separate Binance Futures demo key/session is required')
        self.client=client

    def identity(self):return hashlib.sha256(self.client.key.encode()).hexdigest()

    def assert_demo(self):
        if self.client.environment!='testnet' or self.client.base!=self.base:
            raise Halt('Demo endpoint identity changed; order transport blocked')

    def request(self,method,path,params=None):
        self.assert_demo()
        return self.client.request(method,path,params,signed=True)

    def sync(self):
        self.assert_demo();self.client.sync()

    def account(self):
        self.assert_demo()
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
        self.assert_demo();return self.client.rules(symbol)
    def quote(self,symbol):
        self.assert_demo();return self.client.quote(symbol)
    def open_orders(self,symbol):return self.request('GET','/fapi/v1/openOrders',{'symbol':symbol})
    def open_stops(self,symbol):return self.request('GET','/fapi/v1/openAlgoOrders',{'symbol':symbol})
    def place(self,params):return self.request('POST','/fapi/v1/order',params)
    def query(self,symbol,client):return self.request('GET','/fapi/v1/order',dict(symbol=symbol,origClientOrderId=client))
    def query_order_id(self,symbol,order):return self.request('GET','/fapi/v1/order',dict(symbol=symbol,orderId=order))
    def place_stop(self,params):return self.request('POST','/fapi/v1/algoOrder',params)
    def query_stop(self,client):return self.request('GET','/fapi/v1/algoOrder',dict(clientAlgoId=client))
    def cancel_stop(self,client):return self.request('DELETE','/fapi/v1/algoOrder',dict(clientAlgoId=client))

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
