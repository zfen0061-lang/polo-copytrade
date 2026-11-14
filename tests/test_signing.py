import io
import unittest
from unittest.mock import patch

from backend.live import TradeClient


class SigningTests(unittest.TestCase):
    def test_signed_request_matches_binance_published_hmac_example(self):
        # Public documentation example, never user credentials. All I/O is mocked.
        # https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
        client=TradeClient(key='public-example',secret='2b5eb11e18796d12d88f13dc27dbbd02c2cc51ff7059765ed9821957d82bb4d9')
        params=dict(symbol='BTCUSDT',side='BUY',type='LIMIT',quantity=1,price=9000,
                    timeInForce='GTC',recvWindow=5000,timestamp=1591702613943)
        expected=('symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC'
                  '&recvWindow=5000&timestamp=1591702613943'
                  '&signature=3c661234138461fcc7a7d8746c6558c9842d4e10870d2ecbedf7777cad694af9')
        with patch('backend.live.time.time',return_value=1591702613.943), \
                patch.object(client.opener,'open',return_value=io.BytesIO(b'{}')) as request:
            client.request('GET','/fapi/v1/accountConfig',params,signed=True)
        actual=request.call_args.args[0]
        self.assertEqual(actual.full_url,client.base+'/fapi/v1/accountConfig?'+expected)
        self.assertEqual(actual.get_method(),'GET')


if __name__=='__main__':
    unittest.main()
