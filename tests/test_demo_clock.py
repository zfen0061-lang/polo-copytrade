import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import io
import json
import urllib.error
import urllib.parse

from backend.demo_broker import DemoBroker
from backend.executor import APIError
from backend.executor import Halt
from backend.live import TradeClient


class TransportClockTests(unittest.TestCase):
    def client(self):return TradeClient(key='fixture-key',secret='fixture-secret',environment='testnet')

    def test_wall_clock_jump_does_not_change_signed_timestamp(self):
        client=self.client()
        with patch('backend.live.time.monotonic',return_value=10),patch('backend.live.time.time',return_value=100), \
                patch.object(client,'request',return_value={'serverTime':200000}):client.sync()
        with patch('backend.live.time.monotonic',return_value=11),patch('backend.live.time.time',return_value=900000):
            self.assertEqual(client.signing_timestamp(),200750)

    def test_asymmetric_sample_is_anchored_at_receipt_without_guessing_half_rtt(self):
        client=self.client()
        with patch('backend.live.time.monotonic',side_effect=[10,11.8]), \
                patch.object(client,'request',return_value={'serverTime':200000}):client.sync()
        with patch('backend.live.time.monotonic',return_value=11.8):
            self.assertEqual(client.signing_timestamp(),199750)
        self.assertEqual(client.clock_info['rtt_ms'],1800)

    def test_slow_clock_samples_are_bounded_and_block_signing(self):
        client=self.client()
        with patch('backend.live.time.monotonic',side_effect=[0,3,4,7,8,11]), \
                patch.object(client,'request',return_value={'serverTime':200000}) as request:
            with self.assertRaisesRegex(Halt,'too slow'):client.sync()
        self.assertEqual(request.call_count,3);self.assertIsNone(client.clock_anchor)

    def test_direct_snapshot_reads_retry_only_the_rejected_get(self):
        client=self.client();calls=[]
        def transport(request,timeout):
            path=urllib.parse.urlsplit(request.full_url).path;calls.append((request.method,path))
            if len(calls)==1:
                raise urllib.error.HTTPError('fixture',400,'rejected',{},io.BytesIO(b'{"code":-1021}'))
            payload=({'serverTime':200000} if path.endswith('/time') else
                {'canTrade':True} if path.endswith('/accountConfig') else
                [] if path.endswith('/positionRisk') else {})
            return io.BytesIO(json.dumps(payload).encode())
        with patch.object(client,'signing_timestamp',return_value=199750),patch.object(client.opener,'open',side_effect=transport):
            self.assertEqual(client.account()['positions'],[])
        self.assertEqual([p for _,p in calls].count('/fapi/v1/accountConfig'),2)
        self.assertEqual([p for _,p in calls].count('/fapi/v1/time'),1)

    def test_adapter_does_not_multiply_transport_retries_or_replay_writes(self):
        client=self.client();broker=DemoBroker(client)
        with patch.object(client,'_request_once',side_effect=APIError(-1021)) as request,patch.object(client,'sync') as sync:
            with self.assertRaises(APIError):broker.request('GET','/fapi/v3/account')
            self.assertEqual(request.call_count,2);sync.assert_called_once()
            request.reset_mock();sync.reset_mock()
            with self.assertRaises(APIError):broker.place({'symbol':'BTCUSDT'})
            request.assert_called_once();sync.assert_not_called()


class DemoClockTests(unittest.TestCase):
    def test_account_snapshot_resynchronizes_its_direct_signed_reads_once(self):
        client=self.client();client.account=Mock(side_effect=[APIError(-1021),{'positions':[]}])
        client.request.return_value={'assets':[{'asset':'USDT','availableBalance':'50'}]}
        self.assertEqual(DemoBroker(client).account()['available_usdt'],'50')
        self.assertEqual(client.account.call_count,2);client.sync.assert_called_once()
    def test_repeated_snapshot_timestamp_error_still_halts_after_one_retry(self):
        client=self.client();client.account=Mock(side_effect=APIError(-1021))
        with self.assertRaises(APIError):DemoBroker(client).account()
        self.assertEqual(client.account.call_count,2);client.sync.assert_called_once()
        client.request.assert_not_called()
    def test_snapshot_permission_error_does_not_retry(self):
        client=self.client();client.account=Mock(side_effect=APIError(-2015))
        with self.assertRaises(APIError):DemoBroker(client).account()
        self.assertEqual(client.account.call_count,1);client.sync.assert_not_called()

    def client(self):
        return SimpleNamespace(environment='testnet',base='https://demo-fapi.binance.com',
            request=Mock(),sync=Mock())
    def test_rejected_read_is_resynchronized_and_retried_once(self):
        client=self.client();client.request.side_effect=[APIError(-1021),{'ok':True}]
        self.assertEqual(DemoBroker(client).request('GET','/fapi/v3/account'),{'ok':True})
        client.sync.assert_called_once();self.assertEqual(client.request.call_count,2)
    def test_repeated_timestamp_rejection_is_not_an_infinite_retry(self):
        client=self.client();client.request.side_effect=APIError(-1021)
        with self.assertRaises(APIError):DemoBroker(client).request('GET','/fapi/v3/account')
        self.assertEqual(client.request.call_count,2);client.sync.assert_called_once()
    def test_order_writes_and_other_errors_are_never_retried(self):
        for method,code in [('POST',-1021),('DELETE',-1021),('GET',-2013)]:
            with self.subTest(method=method,code=code):
                client=self.client();client.request.side_effect=APIError(code)
                with self.assertRaises(APIError):DemoBroker(client).request(method,'/fapi/v1/order')
                self.assertEqual(client.request.call_count,1);client.sync.assert_not_called()
