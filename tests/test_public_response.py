import unittest
from backend.core import Invalid
from backend.feeds import PublicCollector,PublicResponseUnavailable
from unittest.mock import Mock


class Response:
    def __init__(self,status,payload):self.status,self.payload=status,payload
    def json(self):return self.payload


class PublicResponseTests(unittest.TestCase):
    def test_known_busy_code_uses_backoff_but_other_public_codes_still_stop(self):
        with self.assertRaises(ConnectionError):
            PublicCollector.verify_operation_response(Response(200,dict(success=False,code='11012005')))
        with self.assertRaises(Invalid):
            PublicCollector.verify_operation_response(Response(200,dict(success=False,code='11012006')))

    def test_expired_body_is_transient_but_malformed_json_still_blocks(self):
        response=Response(200,None)
        response.json=Mock(side_effect=RuntimeError('Response.json: Protocol error (Network.getResponseBody): No resource with given identifier found'))
        with self.assertRaises(PublicResponseUnavailable):PublicCollector.verify_operation_response(response)
        response.json=Mock(side_effect=ValueError('invalid JSON'))
        with self.assertRaises(Invalid):PublicCollector.verify_operation_response(response)

    def test_response_is_validated_when_finished_and_not_read_again_after_expiry(self):
        from types import SimpleNamespace
        collector=PublicCollector.__new__(PublicCollector)
        collector.url='https://www.binance.com/zh-CN/copy-trading/lead-details/123'
        listeners={}
        collector.page=SimpleNamespace(on=lambda name,callback:listeners.update({name:callback}),
            remove_listener=lambda name,callback:listeners.pop(name))
        response=Response(200,dict(success=True,code='000000'))
        response.url='https://www.binance.com/copy-trade/lead-portfolio/order-history?portfolioId=123'
        request=Mock(post_data_json=None);request.response.return_value=response;response.request=request
        def fetch(known,portfolio,captures):
            listeners['request'](request);listeners['requestfinished'](request)
            response.json=Mock(side_effect=AssertionError('body expired after navigation'))
            collector.wait_for_verified_response(captures,'order-history')
            return [],False
        collector._fetch_page=fetch
        self.assertEqual(collector.fetch(set()),([],False));self.assertEqual(listeners,{})

    def test_callback_defers_access_denial_to_fetch_and_removes_listeners(self):
        from types import SimpleNamespace
        collector=PublicCollector.__new__(PublicCollector);collector.url='https://www.binance.com/lead-details/123'
        listeners={}
        collector.page=SimpleNamespace(on=lambda name,callback:listeners.update({name:callback}),
            remove_listener=lambda name,callback:listeners.pop(name))
        response=Response(429,{})
        response.url='https://www.binance.com/copy-trade/lead-portfolio/order-history?portfolioId=123'
        request=Mock(post_data_json=None);request.response.return_value=response;response.request=request
        def fetch(known,portfolio,captures):
            listeners['request'](request);listeners['requestfinished'](request)
            collector.wait_for_verified_response(captures,'order-history')
        collector._fetch_page=fetch
        with self.assertRaises(Invalid):collector.fetch(set())
        self.assertEqual(listeners,{})

    def test_hydration_request_with_empty_or_wrong_portfolio_is_not_ready(self):
        from types import SimpleNamespace
        response=SimpleNamespace(url='https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/order-history',request=SimpleNamespace(post_data_json={'portfolioId':''}))
        matches=PublicCollector.matches_public_response
        self.assertFalse(matches(response,'order-history','5075281354358777856'))
        response.request.post_data_json={'portfolioId':'123'}
        self.assertFalse(matches(response,'order-history','5075281354358777856'))
        response.request.post_data_json={'portfolioId':'5075281354358777856'}
        self.assertTrue(matches(response,'order-history','5075281354358777856'))
        response.url='https://example.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/order-history'
        self.assertFalse(matches(response,'order-history','5075281354358777856'))

    def test_detail_ready_matches_the_actual_url_portfolio(self):
        from types import SimpleNamespace
        response=SimpleNamespace(url='https://www.binance.com/bapi/futures/v1/friendly/future/copy-trade/lead-portfolio/detail?portfolioId=5075281354358777856',request=SimpleNamespace(post_data_json=None))
        self.assertTrue(PublicCollector.matches_public_response(response,'detail','5075281354358777856'))

    def test_ui_request_must_be_confirmed_successful(self):
        PublicCollector.verify_operation_response(Response(200,dict(success=True,code='000000')))
        for payload in ({},dict(success=False,code='000000'),dict(success=True,code='100001')):
            with self.subTest(payload=payload),self.assertRaises(Invalid):
                PublicCollector.verify_operation_response(Response(200,payload))

    def test_denial_and_throttling_are_not_automatically_bypassed(self):
        for status in (401,403,418,429):
            with self.subTest(status=status),self.assertRaises(Invalid):
                PublicCollector.verify_operation_response(Response(status,{}))
        with self.assertRaises(ConnectionError):
            PublicCollector.verify_operation_response(Response(503,{}))
