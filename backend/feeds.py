"""Optional visible-page collector and explicitly synthetic demo feed."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

from .core import D, Invalid, dec, now

STAMP = re.compile(r'(?<!\d)(\d{2}-\d{2}),?\s+(\d{2}:\d{2}:\d{2})')
NUM = r'[+-]?[\d,]+(?:\.\d+)?'
MAP = {'买入开多':'OPEN_LONG','卖出开空':'OPEN_SHORT','卖出平多':'CLOSE_LONG','买入平空':'CLOSE_SHORT'}


def parse_public(text, year, offset):
    text = re.sub(r'\s+', ' ', text).strip()
    stamps = list(STAMP.finditer(text))
    if not stamps:
        raise Invalid('No complete public operations found; this is not proof of a flat position')
    output, duplicates = [], Counter()
    for i, stamp in enumerate(stamps):
        body = text[stamp.end():stamps[i+1].start() if i+1 < len(stamps) else None]
        action = re.search('|'.join(MAP), body)
        symbol = re.search(r'([A-Z0-9_]+USDT)\s*永续合约', body)
        price = re.search(r'以均价为\s*(' + NUM + r')\s*USDT', body)
        qty = re.search(r'成交数量为\s*(' + NUM + r')', body)
        if not all((action,symbol,price,qty)):
            raise Invalid('Public operation format changed; stopped without placing orders')
        when = datetime.strptime(f'{year}-{stamp.group(1)} {stamp.group(2)}', '%Y-%m-%d %H:%M:%S')
        when = when.replace(tzinfo=timezone(timedelta(minutes=offset)))
        if when > datetime.now(when.tzinfo) + timedelta(days=1):
            when = when.replace(year=year-1)
        row = dict(action=MAP[action.group()],symbol=symbol.group(1),price=price.group(1).replace(',',''),
                   source_time=when.isoformat(),source_quantity=qty.group(1).replace(',',''))
        key = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        duplicates[key] += 1
        row['source_id'] = key + ':' + str(duplicates[key])
        output.append(row)
    return output


class PublicResponseUnavailable(ConnectionError):
    """A transient browser response-body lifetime failure, not an access denial."""


class PublicCollector:
    def __init__(self, url, offset, *, timezone_id=None, expected_name=None):
        from playwright.sync_api import sync_playwright
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=True)
            options=dict(locale='zh-CN')
            if timezone_id:
                options['timezone_id']=timezone_id
            self.page = self.browser.new_page(**options)
        except Exception:
            self.runtime.stop()
            raise
        self.url, self.offset = url, offset
        self.expected_name=expected_name

    def close(self):
        try:
            self.browser.close()
        finally:
            self.runtime.stop()

    def fetch(self, known):
        portfolio=urllib.parse.urlsplit(self.url).path.rstrip('/').rsplit('/',1)[-1]
        started=set();captures=[]
        def remember_request(request):started.add(request)
        def remember_finished(request):
            if request not in started:return
            response=request.response()
            if response is None:return
            for kind in ('detail','order-history'):
                if self.matches_public_response(response,kind,portfolio):
                    # Read the completed body now. Keeping a Response object until
                    # after page hydration/load may lose its CDP resource body.
                    try:self.verify_operation_response(response);error=None
                    except Exception as exc:error=exc
                    captures.append((kind,error))
                    break
        # The site may restore the active tab and fetch before our click. Keep
        # responses from requests started during this navigation, not old pages.
        self.page.on('request',remember_request)
        self.page.on('requestfinished',remember_finished)
        try:return self._fetch_page(known,portfolio,captures)
        finally:
            self.page.remove_listener('request',remember_request)
            self.page.remove_listener('requestfinished',remember_finished)

    def wait_for_verified_response(self,captures,kind,timeout=15):
        from playwright.sync_api import TimeoutError as BrowserTimeout
        deadline=time.monotonic()+timeout
        while True:
            match=next((item for item in captures if item[0]==kind),None)
            if match:
                if match[1] is not None:raise match[1]
                return
            if time.monotonic()>=deadline:
                raise BrowserTimeout('No verified '+kind+' response for this navigation')
            self.page.wait_for_timeout(100)

    def _fetch_page(self,known,portfolio,captures):
        # The SSR heading exists before React knows the portfolio ID. Waiting
        # only for the heading can submit portfolioId="" and display no records.
        response=self.page.goto(self.url, wait_until='domcontentloaded', timeout=35000)
        if response and response.status in (401,403,418,429):
            raise Invalid('Public page access restricted or rate limited; observation paused')
        self.wait_for_verified_response(captures,'detail',20)
        if self.expected_name:
            self.page.get_by_role('heading',name=self.expected_name,exact=True).wait_for(timeout=15000)
        self.page.wait_for_load_state('load',timeout=20000)
        # Binance renders clickable SSR tabs before client handlers are attached.
        # Give client hydration a bounded settling period before selecting a tab.
        self.page.wait_for_timeout(2000)
        tab=self.page.get_by_role('tab', name='最新操作记录', exact=True)
        from playwright.sync_api import TimeoutError as BrowserTimeout
        for attempt in range(2):
            tab.click(timeout=15000)
            try:self.wait_for_verified_response(captures,'order-history')
            except BrowserTimeout:
                if attempt:raise
            else:break
            self.page.wait_for_timeout(2000)
        panel = self.page.get_by_role('tabpanel', name='最新操作记录', exact=True)
        panel.wait_for(timeout=15000)
        # The date and clock may be separate spans; match the complete panel text.
        self.page.wait_for_function(r'(el)=>/\d{2}-\d{2},?\s+\d{2}:\d{2}:\d{2}/.test(el.innerText)',
                                    arg=panel.element_handle(),timeout=15000)
        dates = panel.get_by_role('textbox').all()
        year = datetime.strptime(dates[-1].input_value(), '%Y-%m-%d').year if dates else datetime.now().year
        rows = parse_public(panel.inner_text(), year, self.offset)
        for _ in range(20):
            if not known or any(r['source_id'] in known for r in rows):
                return rows, False
            more = panel.get_by_role('button', name='更多', exact=True)
            if not more.count() or not more.is_visible():
                break
            before = panel.inner_text()
            more.click()
            until = time.monotonic()+10
            while time.monotonic() < until:
                current = panel.inner_text()
                if len(STAMP.findall(current)) > len(STAMP.findall(before)):
                    break
                self.page.wait_for_timeout(250)
            else:
                break
            rows = parse_public(current, year, self.offset)
        return rows, bool(known)

    @staticmethod
    def matches_public_response(response,kind,portfolio):
        parsed=urllib.parse.urlsplit(response.url)
        if parsed.hostname!='www.binance.com' or not parsed.path.endswith('/copy-trade/lead-portfolio/'+kind):return False
        params={k:v[0] for k,v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            body=response.request.post_data_json
            if isinstance(body,dict):params.update(body)
        except (ValueError,TypeError):pass
        return str(params.get('portfolioId',''))==portfolio

    @staticmethod
    def verify_operation_response(response):
        if response.status in (401,403,418,429):
            raise Invalid('Public operation access restricted or rate limited; observation paused')
        if response.status>=500:
            raise ConnectionError('Public operation service is temporarily unavailable')
        if response.status!=200:
            raise Invalid('Unexpected public operation response; observation paused')
        try:payload=response.json()
        except Exception as exc:
            if ('Network.getResponseBody' in str(exc) and any(message in str(exc) for message in
                    ('No resource with given identifier found','No data found for resource with given identifier'))):
                raise PublicResponseUnavailable('Public response body expired; browser connection will be rebuilt') from None
            if isinstance(exc,ValueError):
                raise Invalid('Public operation response was not valid JSON; observation paused') from None
            raise
        if not isinstance(payload,dict) or payload.get('success') is not True or payload.get('code')!='000000':
            code=str(payload.get('code','unknown')) if isinstance(payload,dict) else 'invalid_json'
            code=re.sub(r'[^A-Za-z0-9_-]','',code)[:40]
            if code=='11012005':
                raise ConnectionError('Public operation service is busy (public code 11012005); retrying with backoff')
            message=re.sub(r'\s+',' ',str(payload.get('message') or ''))[:160] if isinstance(payload,dict) else ''
            raise Invalid('Public operation request was not successful (public code '+code+'): '+message+'; observation paused')


def public_quote(symbol):
    query = urllib.parse.urlencode({'symbol': symbol})
    with urllib.request.urlopen('https://fapi.binance.com/fapi/v1/ticker/bookTicker?'+query,timeout=5) as response:
        row = json.load(response)
    return dec(row['bidPrice']),dec(row['askPrice'])


class Runner:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run,daemon=True,name='paper-scheduler')
        self.workers = {}

    def start(self):
        self.thread.start()

    def shutdown(self):
        self.stop.set()
        self.thread.join(timeout=5)
        for stop, _ in self.workers.values():
            stop.set()

    def demo_quote(self, symbol, step):
        base = 100 if symbol == 'BTCUSDT' else 50
        middle = D(str(round(base*(1+math.sin(step*0.6)*0.008),5)))
        return middle-D('0.01'),middle+D('0.01')

    def demo_once(self, trader_id, forced=None):
        t = self.store.get_trader(trader_id)
        if t['source'] != 'demo' or not t['enabled']:
            raise Invalid('Start a demo trader before generating synthetic signals / 请先启动演示交易员')
        with self.store.db() as db:
            db.execute('UPDATE traders SET counter=counter+1 WHERE id=?',(trader_id,))
            step = db.execute('SELECT counter FROM traders WHERE id=?',(trader_id,)).fetchone()[0]
        sequence=[('OPEN_LONG','BTCUSDT'),('OPEN_LONG','BTCUSDT'),('CLOSE_LONG','BTCUSDT'),
                  ('OPEN_SHORT','ETHUSDT'),('CLOSE_SHORT','ETHUSDT'),('CLOSE_LONG','BTCUSDT')]
        action,symbol=sequence[(step-1)%len(sequence)]
        bid,ask=self.demo_quote(symbol,step)
        self.store.mark(trader_id,symbol,bid,ask)
        price = (bid+ask)/2
        if forced == 'over_deviation':
            action='OPEN_LONG'
            price=ask/(D('1')+dec(t['config']['max_deviation'])+D('0.02'))
        event=dict(source_id=f'demo-{step}',action=action,symbol=symbol,price=str(price),source_time=now())
        result=self.store.process(trader_id,event,bid,ask)
        self.store.record_equity()
        return result

    def run(self):
        due={}
        while not self.stop.wait(1):
            state=self.store.snapshot()
            for t in state['traders']:
                monitor=json.loads(t.get('signal_monitor') or '{}')
                if monitor.get('mode')=='observe':
                    # A signal observer never enters the paper execution scheduler.
                    continue
                if t['source']=='binance_public':
                    active=t['enabled'] or any(p['trader_id']==t['id'] for p in state['positions'])
                    if active and t['id'] not in self.workers:
                        signal=threading.Event()
                        worker=threading.Thread(target=self.public_worker,args=(t['id'],signal),daemon=True)
                        self.workers[t['id']]=(signal,worker)
                        worker.start()
                    if not active and t['id'] in self.workers:
                        self.workers[t['id']][0].set()
                    continue
                if not t['enabled'] and not any(p['trader_id']==t['id'] for p in state['positions']):
                    continue
                # Paper protective stops keep updating while new signals are paused.
                for symbol in t['config']['symbols']:
                    bid,ask=self.demo_quote(symbol,t['counter']+(time.time()%20)/10)
                    self.store.mark(t['id'],symbol,bid,ask)
                if t['enabled'] and time.monotonic()>=due.get(t['id'],0):
                    try:
                        self.demo_once(t['id'])
                    except Exception as error:
                        with self.store.db() as db:
                            self.store.log(db,t['id'],'error',str(error))
                    due[t['id']]=time.monotonic()+max(5,t['config']['poll_seconds'])

    def public_worker(self,trader_id,stop):
        collector=None
        try:
            t=self.store.get_trader(trader_id)
            while not stop.is_set() and not self.stop.is_set():
                t=self.store.get_trader(trader_id)
                if not t['enabled']:
                    state=self.store.snapshot()
                    for p in state['positions']:
                        if p['trader_id']==trader_id:
                            self.store.mark(trader_id,p['symbol'],*public_quote(p['symbol']))
                else:
                    if collector is None:
                        collector=PublicCollector(t['url'],t['config']['utc_offset_minutes'])
                    with self.store.db() as db:
                        known={r[0] for r in db.execute('SELECT source_id FROM events WHERE trader_id=?',(trader_id,))}
                    rows,gap=collector.fetch(known)
                    fresh=self.store.get_trader(trader_id)
                    if not fresh['enabled'] or fresh['url']!=t['url'] or fresh['config']!=t['config']:
                        break
                    if gap:
                        raise Invalid('Public history gap: paused / 源记录无法衔接，已暂停')
                    quotes={}
                    for event in reversed(rows):
                        if event['source_id'] in known:
                            continue
                        symbol=event['symbol']
                        if symbol not in quotes:
                            quotes[symbol]=public_quote(symbol)
                        self.store.mark(trader_id,symbol,*quotes[symbol])
                        self.store.process(trader_id,event,*quotes[symbol],baseline=not t['baseline'])
                    with self.store.db() as db:
                        db.execute('UPDATE traders SET baseline=1 WHERE id=?',(trader_id,))
                    state=self.store.snapshot()
                    for p in state['positions']:
                        if p['trader_id']==trader_id:
                            quote=quotes.get(p['symbol']) or public_quote(p['symbol'])
                            self.store.mark(trader_id,p['symbol'],*quote)
                    self.store.record_equity()
                stop.wait(t['config']['poll_seconds'])
        except Exception as error:
            with self.store.db() as db:
                db.execute('UPDATE traders SET enabled=0 WHERE id=?',(trader_id,))
                self.store.log(db,trader_id,'error','采集暂停 / Collector paused: '+type(error).__name__+': '+str(error).split('\n')[0][:300])
            stop.wait(30)
        finally:
            if collector:
                collector.close()
            self.workers.pop(trader_id,None)
