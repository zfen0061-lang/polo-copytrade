"""Strict Demo endpoint. This class can never be switched to production."""
from .executor import Halt
from .futures_broker import FuturesBroker


class DemoBroker(FuturesBroker):
    environment='testnet'
    base='https://demo-fapi.binance.com'

    def assert_endpoint(self):
        if (self.environment!='testnet' or self.base!='https://demo-fapi.binance.com'
                or self.client.environment!='testnet' or self.client.base!='https://demo-fapi.binance.com'):
            raise Halt('A separate Binance Futures demo key/session is required; endpoint identity changed')

    def assert_demo(self):self.assert_endpoint()

    def authorize_write(self,method,path,params):self.assert_endpoint()
