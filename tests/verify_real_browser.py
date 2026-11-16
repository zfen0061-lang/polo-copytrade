"""Optional actual-browser fixture; all account transport is an offline fake.

Run separately with python -m tests.verify_real_browser. No real exchange I/O.
"""
import json
from pathlib import Path
import tempfile
import threading
import time
from decimal import Decimal
from playwright.sync_api import sync_playwright,expect
from backend.core import Store,now
from backend.feeds import Runner
from backend.real_session import RealSession
from backend.production import ProductionBroker
from backend.server import LocalHTTPServer,make_handler
from backend.strategy_v2 import StrategyPolicy
from tests.test_production import ProductionClientFixture


def main():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);source=Store(root/'source'/'state.db');t=source.get_trader('aoying')
        source.save_trader(dict(t,source='binance_public',authorized=True,config=dict(t['config'],utc_offset_minutes=0)),'aoying')
        monitor=dict(mode='observe',owner='offline-browser',heartbeat=time.time(),last_poll=now(),status='running',portfolio_id='5075281354358777856')
        with source.db() as db:db.execute('UPDATE traders SET enabled=1,signal_monitor=? WHERE id=?',(json.dumps(monitor),'aoying'))
        client=ProductionClientFixture();holder={}
        broker=ProductionBroker(client,entry_guard=lambda:holder['session'].entry_guard())
        session=RealSession(root/'real'/'state.db',source.path,factory=lambda:broker);holder['session']=session
        session.configure(StrategyPolicy('60','0.40',10,3,'0.03','60','initial_net_loss',60,{'BTCUSDT':'crypto','ETHUSDT':'crypto'}).public())
        store=Store(session.data);runner=Runner(store)
        server=LocalHTTPServer(('127.0.0.1',0),lambda *args:None);port=server.server_port
        server.RequestHandlerClass=make_handler(store,runner,port,real=session)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def event(key,action):
            with source.db() as db:
                db.execute('INSERT INTO events (trader_id,source_id,action,symbol,source_time,first_seen,source_price,source_quantity,delay_ms,status,reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    ('aoying','public:'+key,action,'BTCUSDT',now(),now(),'100','1',0,'observed','offline fixture'))
        errors=[]
        try:
            with sync_playwright() as runtime:
                browser=runtime.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(f'http://127.0.0.1:{port}/') else route.abort())
                page.goto(f'http://127.0.0.1:{port}/')
                expect(page.locator('#connection')).to_have_text('本机后台已连接')
                expect(page.locator('#start')).to_be_enabled()
                expect(page.locator('#phrase')).to_have_count(0)
                expect(page.locator('#confirm')).to_have_count(0)
                # Blockers are checked automatically before offering a start.
                client.exchange.hedge=True
                page.locator('#start').click()
                expect(page.locator('#review')).to_contain_text('暂不能启动')
                assert not session.running and client.exchange.submit_count==0
                client.exchange.hedge=False
                # A cancellation must never enable execution or place an order.
                dialogs=[]
                def decline(dialog):
                    dialogs.append(dialog.message);dialog.dismiss()
                page.once('dialog',decline)
                page.locator('#start').click()
                expect(page.locator('#start')).to_be_enabled()
                assert len(dialogs)==1 and '真实资金' in dialogs[0]
                assert not session.running and client.exchange.submit_count==0
                # Start saves edits and checks the account without extra steps.
                page.locator('[name=initial_capital]').fill('59')
                page.locator('[name=max_loss]').fill('59')
                def approve(dialog):
                    dialogs.append(dialog.message);dialog.accept()
                page.once('dialog',approve)
                page.locator('#start').click()
                expect(page.locator('#phase')).to_have_text('实盘自动跟随中',timeout=10000)
                assert session.policy.initial_capital=='59'
                assert len(dialogs)==2 and '59 USDT' in dialogs[1]
                event('browser-open','OPEN_LONG')
                expect(page.locator('#positions')).to_contain_text('BTCUSDT',timeout=10000)
                client.exchange.price*=Decimal('1.10')
                event('browser-close','CLOSE_LONG')
                expect(page.locator('#positions')).to_contain_text('没有本程序持仓',timeout=10000)
                page.locator('#pause').click();expect(page.locator('#phase')).to_have_text('新开仓已暂停')
                page.locator('#stop').click();expect(page.locator('#phase')).to_have_text('已停止')
                assert page.locator('img').evaluate('(el)=>el.complete&&el.naturalWidth>0')
                assert not errors,errors
                assert client.exchange.submit_count==2
                browser.close()
            print(json.dumps(dict(fixture_only=True,actual_binance_orders=False,fixture_orders=client.exchange.submit_count,
                browser_errors=errors,opening_requires_confirmation=True,full_close_outside_band=True,
                no_typed_phrase=True,automatic_preflight=True,cancel_places_no_orders=True)))
        finally:
            session.shutdown();server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':main()
