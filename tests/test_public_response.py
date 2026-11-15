import unittest
from backend.core import Invalid
from backend.feeds import PublicCollector


class Response:
    def __init__(self,status,payload):self.status,self.payload=status,payload
    def json(self):return self.payload


class PublicResponseTests(unittest.TestCase):
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
