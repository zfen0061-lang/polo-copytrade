"""Rule-based execution core, used only by an explicitly started account session."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from decimal import Decimal, ROUND_DOWN, ROUND_UP

import hashlib

import hmac

import json

import os

from pathlib import Path

import sqlite3

import time

import urllib.error

import urllib.parse

import urllib.request

D = Decimal

TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'EXPIRED_IN_MATCH', 'REJECTED'}

class Halt(RuntimeError):
    """Stop execution for review; do not silently retry an uncertain trade."""

class APIError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Binance API code ' + str(code))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None

def number(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError('金额必须是有限数字。')
    return result

def quantize(value, step, up=False):
    step = number(step)
    if step <= 0:
        raise Halt('交易规则的步长无效。')
    return (number(value) / step).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN) * step

def validate_settings(c):
    if c.get('mode') not in ('paper', 'live'):
        raise ValueError('mode 必须为 paper 或 live。')
    for key in ('order_notional_usdt', 'max_total_notional_usdt', 'max_signal_age_seconds',
                'max_open_deviation', 'close_fraction', 'leverage'):
        if c.get(key) is None or number(c[key]) <= 0:
            raise ValueError('请明确填写参数：' + key)
    if number(c['max_total_notional_usdt']) < number(c['order_notional_usdt']):
        raise ValueError('总仓位名义金额上限不能小于每笔名义金额。')
    if number(c['max_open_deviation']) >= 1 or number(c['close_fraction']) > 1:
        raise ValueError('价差比例应小于 1，平仓比例应不大于 1。')
    leverage = number(c['leverage'])
    if leverage != leverage.to_integral_value():
        raise ValueError('杠杆应为整数。')
    if not c.get('symbols') or not all(isinstance(s, str) and s.endswith('USDT') for s in c['symbols']):
        raise ValueError('需要明确允许跟随的 USDT 交易对。')
    if c.get('source_utc_offset_minutes') is None:
        raise ValueError('需要先核实币安操作记录的时区，不能猜测信号是否过期。')
    offset = number(c['source_utc_offset_minutes'])
    if abs(offset) > 840 or offset != offset.to_integral_value():
        raise ValueError('时区偏移无效。')
    if c.get('close_rule') != 'fixed_fraction_on_each_close':
        raise ValueError('请明确选择平仓规则 fixed_fraction_on_each_close。')
    if c['mode'] == 'live' and c.get('live_enabled') is not True:
        raise ValueError('实盘尚未启用。')

class Binance:
    def __init__(self, live=False):
        self.live = live
        self.key = os.environ.get('AOYING_BINANCE_API_KEY', '') if live else ''
        self.secret = os.environ.get('AOYING_BINANCE_API_SECRET', '') if live else ''
        if live and not (self.key and self.secret):
            raise Halt('本机环境变量中尚未配置专用交易 API 凭据。')
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, params=None, signed=False):
        params = dict(params or {})
        headers = {}
        if signed:
            params.update(timestamp=int(time.time() * 1000), recvWindow=5000)
            headers['X-MBX-APIKEY'] = self.key
        query = urllib.parse.urlencode(params)
        if signed:
            query += '&signature=' + hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        address = 'https://fapi.binance.com' + path
        data = None
        if method == 'GET':
            address += '?' + query if query else ''
        else:
            data = query.encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(address, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                code = json.loads(error.read()).get('code', error.code)
            except Exception:
                code = error.code
            raise APIError(code) from None

    def rules(self, symbol):
        info = self.request('GET', '/fapi/v1/exchangeInfo')
        for item in info['symbols']:
            if item['symbol'] == symbol:
                if item['status'] != 'TRADING' or item['contractType'] != 'PERPETUAL' or item['marginAsset'] != 'USDT':
                    raise Halt('所选合约当前不可交易或不是 USDT 永续合约。')
                return {f['filterType']: f for f in item['filters']}
        raise Halt('交易对不存在。')

    def quote(self, symbol):
        data = self.request('GET', '/fapi/v1/ticker/bookTicker', {'symbol': symbol})
        return number(data['bidPrice']), number(data['askPrice'])

    def preflight(self, symbols, ledger, leverage):
        mode = self.request('GET', '/fapi/v1/positionSide/dual', signed=True)
        if mode['dualSidePosition'] is not False:
            raise Halt('第一版仅支持单向持仓；不会自动更改账户模式。')
        positions = self.request('GET', '/fapi/v3/positionRisk', signed=True)
        actual = {s: D('0') for s in symbols}
        for position in positions:
            if position['symbol'] in actual:
                if position['positionSide'] != 'BOTH':
                    raise Halt('持仓模式不匹配。')
                actual[position['symbol']] += number(position['positionAmt'])
        for symbol in symbols:
            if actual[symbol] != ledger.get(symbol, D('0')):
                raise Halt('账户持仓与本程序账本不一致，停止以免影响手动仓位。')
            if self.request('GET', '/fapi/v1/openOrders', {'symbol': symbol}, signed=True):
                raise Halt('所选交易对存在其他挂单，停止自动交易。')
            configs = self.request('GET', '/fapi/v1/symbolConfig', {'symbol': symbol}, signed=True)
            config = next((r for r in configs if r['symbol'] == symbol), None)
            if not config or config['marginType'].upper() != 'ISOLATED' or int(config['leverage']) != int(leverage):
                raise Halt('请在币安手动将选定合约设为逐仓及指定杠杆；程序不会代改。')

    def place(self, params):
        if not self.live:
            raise Halt('公共行情客户端不能下单。')
        return self.request('POST', '/fapi/v1/order', params, signed=True)

    def query(self, symbol, client_id):
        return self.request('GET', '/fapi/v1/order',
                            dict(symbol=symbol, origClientOrderId=client_id), signed=True)

class Engine:
    def __init__(self, config, path, broker):
        validate_settings(config)
        self.config, self.broker = config, broker
        if bool(broker.live) != (config['mode'] == 'live'):
            raise Halt('交易模式与客户端不匹配。')
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,qty TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,state TEXT NOT NULL,payload TEXT NOT NULL);
        ''')
        fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if broker.live:
            fingerprint += hashlib.sha256(broker.key.encode()).hexdigest()
        old = self.get('fingerprint')
        if old and old != fingerprint:
            pending=self.db.execute("SELECT 1 FROM jobs WHERE state='submitting' LIMIT 1").fetchone()
            has_stops=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stops'").fetchone()
            stops=self.db.execute('SELECT 1 FROM stops LIMIT 1').fetchone() if has_stops else None
            if any(self.ledger().values()) or pending or stops:
                self.db.close()
                raise Halt('仍有旧仓位、待查订单或保护单，不能直接更改实盘参数。')
            with self.db:self.db.execute("UPDATE settings SET value=? WHERE key='fingerprint'",(fingerprint,))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', ('fingerprint', fingerprint))

    def get(self, key):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def ledger(self):
        return {r['symbol']: number(r['qty']) for r in self.db.execute('SELECT * FROM positions')}

    def known(self):
        return {r[0] for r in self.db.execute('SELECT id FROM seen')}

    def finish(self, event, state, payload=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?)',
                            (event['id'], state, json.dumps(payload or {}, ensure_ascii=False)))
            self.db.execute('INSERT OR IGNORE INTO seen VALUES (?)', (event['id'],))
        return dict(id=event['id'], state=state, **(payload or {}))

    def settle(self, event, params, response):
        if response.get('status') not in TERMINAL:
            raise Halt('订单未达到终态，保留查单状态并暂停。')
        filled = number(response['executedQty'])
        if filled < 0 or filled > number(params['quantity']):
            raise Halt('成交数量异常。')
        position = self.ledger().get(event['symbol'], D('0'))
        signed_qty = filled if params['side'] == 'BUY' else -filled
        updated = position + signed_qty
        if params.get('reduceOnly') == 'true' and abs(updated) > abs(position):
            raise Halt('平仓结果与本地仓位不一致。')
        payload = dict(order=params, result=response, mode=self.config['mode'])
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO positions VALUES (?,?)', (event['symbol'], str(updated)))
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?)',
                            (event['id'], 'settled', json.dumps(payload, ensure_ascii=False)))
            self.db.execute('INSERT OR IGNORE INTO seen VALUES (?)', (event['id'],))
        return dict(id=event['id'], state='settled', **payload)

    def recover(self):
        rows = list(self.db.execute("SELECT * FROM jobs WHERE state='submitting'"))
        for row in rows:
            payload = json.loads(row['payload'])
            try:
                result = self.broker.query(payload['event']['symbol'], payload['order']['newClientOrderId'])
            except Exception as error:
                raise Halt('上次下单结果尚不确定，只查单、不重发；需要人工核对。') from error
            self.settle(payload['event'], payload['order'], result)

    def plan(self, event):
        c = self.config
        symbol, action = event['symbol'], event['action']
        if symbol not in c['symbols']:
            return None, '交易对不在允许名单'
        now = datetime.now(timezone.utc)
        source = datetime.fromisoformat(event['source_time']).replace(
            tzinfo=timezone(timedelta(minutes=int(c['source_utc_offset_minutes']))))
        age = (now - source).total_seconds()
        if age < -5 or age > float(c['max_signal_age_seconds']):
            return None, '操作时间异常或信号已过期'
        mapping = {'买入开多': ('BUY', 1, True), '卖出开空': ('SELL', -1, True),
                   '卖出平多': ('SELL', 1, False), '买入平空': ('BUY', -1, False)}
        if action not in mapping:
            raise Halt('未知的操作类型。')
        side, direction, opening = mapping[action]
        ledger = self.ledger()
        current = ledger.get(symbol, D('0'))
        if opening and current * direction < 0:
            return None, '已有反向仓位；不自动对冲或反手'
        if not opening and current * direction <= 0:
            return None, '没有本程序管理的对应方向仓位'
        rules = self.broker.rules(symbol)
        bid, ask = self.broker.quote(symbol)
        if not (0 < bid <= ask):
            raise Halt('行情报价无效。')
        reference = number(event['price'])
        if reference <= 0:
            raise Halt('源成交价格无效。')
        params = dict(symbol=symbol, side=side, positionSide='BOTH',
                      newClientOrderId='ay_' + hashlib.sha256(event['id'].encode()).hexdigest()[:28],
                      newOrderRespType='RESULT')
        lot = rules.get('LOT_SIZE')
        price_filter = rules.get('PRICE_FILTER')
        if not lot or not price_filter:
            raise Halt('缺少合约步长规则。')
        if opening:
            deviation = number(c['max_open_deviation'])
            limit = reference * (1 + deviation if side == 'BUY' else 1 - deviation)
            limit = quantize(limit, price_filter['tickSize'], up=side == 'SELL')
            market = ask if side == 'BUY' else bid
            if (side == 'BUY' and market > limit) or (side == 'SELL' and market < limit):
                return None, '当前价格超过允许追价范围'
            quantity = quantize(number(c['order_notional_usdt']) / max(limit, ask), lot['stepSize'])
            minimum = number(rules.get('MIN_NOTIONAL', {}).get('notional', '0'))
            if quantity * limit < minimum:
                return None, '每笔金额低于交易所最小名义金额'
            total = D('0')
            for s, qty in ledger.items():
                if qty:
                    b, a = self.broker.quote(s)
                    total += abs(qty) * max(b, a)
            if total + quantity * max(limit, ask) > number(c['max_total_notional_usdt']):
                return None, '将超过总仓位名义金额上限'
            params.update(type='LIMIT', timeInForce='IOC', price=format(limit, 'f'))
        else:
            lot = rules.get('MARKET_LOT_SIZE', lot)
            quantity = quantize(abs(current) * number(c['close_fraction']), lot['stepSize'])
            params.update(type='MARKET', reduceOnly='true')
        if quantity <= 0 or quantity < number(lot['minQty']) or quantity > number(lot['maxQty']):
            return None, '数量不满足交易所最小值、最大值或步长'
        params['quantity'] = format(quantity, 'f')
        return params, None

    def on_poll(self, events, gap=False):
        self.recover()
        if gap:
            raise Halt('源操作记录存在缺口，停止自动交易。')
        if not events:
            raise Halt('没有完整源操作记录。')
        if not self.get('baseline'):
            with self.db:
                self.db.executemany('INSERT OR IGNORE INTO seen VALUES (?)', ((e['id'],) for e in events))
                self.db.execute('INSERT INTO settings VALUES (?,?)', ('baseline', min(e['source_time'] for e in events)))
            return [dict(state='baseline', detail='启动前的历史操作仅作基线，不下单')]
        results = []
        known = self.known()
        for event in reversed(events):
            if event['id'] in known or event['source_time'] < self.get('baseline'):
                continue
            if (Path(self.config.get('stop_file', 'STOP_TRADING'))).exists():
                raise Halt('已检测到停止文件。')
            self.broker.preflight(self.config['symbols'], self.ledger(), self.config['leverage'])
            params, reason = self.plan(event)
            if params is None:
                results.append(self.finish(event, 'skipped', dict(reason=reason)))
                continue
            payload = dict(event=event, order=params)
            # Commit the intent before sending. A crash/timeout only permits a query, never a blind retry.
            with self.db:
                self.db.execute('INSERT INTO jobs VALUES (?,?,?)',
                                (event['id'], 'submitting', json.dumps(payload, ensure_ascii=False)))
            try:
                response = self.broker.place(params)
            except Exception as error:
                raise Halt('下单返回不确定，已记录待查订单并暂停；不会直接重发。') from error
            results.append(self.settle(event, params, response))
        return results
