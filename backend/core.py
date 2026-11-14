from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid

D = Decimal
ACTIONS = {'OPEN_LONG', 'OPEN_SHORT', 'CLOSE_LONG', 'CLOSE_SHORT'}
DEFAULTS = dict(budget='1000', order_margin='25', leverage=2, max_deviation='0.03',
                stop_loss_pct='0.02', close_fraction='0.5', max_signal_age=60,
                max_loss='100', fee_rate='0.0004', symbols=['BTCUSDT', 'ETHUSDT'],
                poll_seconds=15, utc_offset_minutes=None)


class Invalid(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def dec(value):
    try:
        n = D(str(value))
    except Exception:
        raise Invalid('Expected a number / 请输入数字') from None
    if not n.is_finite():
        raise Invalid('Number must be finite / 数值无效')
    return n


def validate_config(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise Invalid('Unknown configuration fields / 配置字段无效')
    c = dict(DEFAULTS, **raw)
    for key in ('budget', 'order_margin', 'max_loss'):
        if dec(c[key]) <= 0:
            raise Invalid(key + ' must be positive / 必须大于零')
        c[key] = str(dec(c[key]))
    for key in ('max_deviation', 'stop_loss_pct', 'close_fraction'):
        x = dec(c[key])
        if x <= 0 or x > 1 or (key != 'close_fraction' and x >= 1):
            raise Invalid(key + ' must be a fraction / 请填写有效比例')
        c[key] = str(x)
    leverage = dec(c['leverage'])
    if leverage != leverage.to_integral_value() or not 1 <= leverage <= 125:
        raise Invalid('Leverage must be an integer from 1 to 125 / 杠杆需为1–125的整数')
    c['leverage'] = int(leverage)
    if dec(c['order_margin']) > dec(c['budget']) or dec(c['max_loss']) > dec(c['budget']):
        raise Invalid('Order margin/loss budget exceeds trader budget / 单笔保证金或亏损预算超过交易员预算')
    fee = dec(c['fee_rate'])
    if fee < 0 or fee >= D('0.1'):
        raise Invalid('Invalid fee rate / 手续费率无效')
    c['fee_rate'] = str(fee)
    for key, low, high in [('max_signal_age', 1, 86400), ('poll_seconds', 10, 3600)]:
        value = dec(c[key])
        if value != value.to_integral_value() or not low <= value <= high:
            raise Invalid('Invalid ' + key)
        c[key] = int(value)
    if c['utc_offset_minutes'] is not None:
        offset = dec(c['utc_offset_minutes'])
        if offset != offset.to_integral_value() or abs(offset) > 840:
            raise Invalid('Invalid source timezone / 时区偏移无效')
        c['utc_offset_minutes'] = int(offset)
    symbols = c['symbols']
    if not isinstance(symbols, list) or not symbols or len(symbols) > 20:
        raise Invalid('Choose 1–20 symbols / 请选择1–20个合约')
    if not all(isinstance(s, str) and re.fullmatch(r'[A-Z0-9_]{1,24}USDT', s) for s in symbols):
        raise Invalid('Invalid USDT symbol / USDT交易对无效')
    c['symbols'] = list(dict.fromkeys(symbols))
    return c


def validate_url(url):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    match = re.fullmatch(r'/(?:zh-CN/)?copy-trading/lead-details/(\d{10,24})/?', parts.path)
    if parts.scheme != 'https' or parts.netloc != 'www.binance.com' or not match:
        raise Invalid('Use a Binance lead portfolio URL / 请使用币安带单项目链接')
    return 'https://www.binance.com/zh-CN/copy-trading/lead-details/' + match.group(1)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS traders(id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,
              source TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 0,authorized INTEGER NOT NULL DEFAULT 0,
              config TEXT NOT NULL,created TEXT NOT NULL,baseline INTEGER NOT NULL DEFAULT 0,counter INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,trader_id TEXT NOT NULL,
              source_id TEXT NOT NULL,action TEXT,symbol TEXT,source_time TEXT,first_seen TEXT NOT NULL,
              source_price TEXT,quote_price TEXT,delay_ms INTEGER,deviation TEXT,status TEXT NOT NULL,reason TEXT,
              UNIQUE(trader_id,source_id));
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,event_id INTEGER,trader_id TEXT NOT NULL,
              symbol TEXT NOT NULL,side TEXT NOT NULL,kind TEXT NOT NULL,qty TEXT NOT NULL,price TEXT NOT NULL,
              fee TEXT NOT NULL,pnl TEXT NOT NULL,created TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'paper');
            CREATE TABLE IF NOT EXISTS positions(trader_id TEXT,symbol TEXT,side TEXT,qty TEXT,entry TEXT,
              mark TEXT,stop TEXT,leverage INTEGER,PRIMARY KEY(trader_id,symbol,side));
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,trader_id TEXT,level TEXT,
              message TEXT,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS equity(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT,created TEXT);
            ''')
            # Additive migrations remain readable by an already-running dashboard.
            for table,column,declaration in (
                ('traders','signal_monitor',"TEXT NOT NULL DEFAULT '{}'"),
                ('events','source_quantity','TEXT'),
            ):
                if column not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
                    db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+declaration)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('paused','false')")
            db.execute("INSERT OR IGNORE INTO settings VALUES ('starting_balance','10000')")
            if not db.execute('SELECT 1 FROM traders LIMIT 1').fetchone():
                c = json.dumps(DEFAULTS)
                db.execute('INSERT INTO traders(id,name,url,source,config,created) VALUES (?,?,?,?,?,?)',
                           ('aoying', '熬鹰资本', 'https://www.binance.com/zh-CN/copy-trading/lead-details/5075281354358777856',
                            'demo', c, now()))
                self.log(db, 'aoying', 'info', '演示账户已建立。演示价格和操作不代表交易员真实交易。')

    @contextmanager
    def db(self):
        with self.lock:
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    @staticmethod
    def log(db, trader_id, level, message):
        db.execute('INSERT INTO logs(trader_id,level,message,created) VALUES (?,?,?,?)',
                   (trader_id, level, message[:1000], now()))

    @staticmethod
    def trader(row):
        r = dict(row)
        r['config'] = json.loads(r['config'])
        r['enabled'], r['authorized'] = bool(r['enabled']), bool(r['authorized'])
        return r

    def get_trader(self, trader_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM traders WHERE id=?', (trader_id,)).fetchone()
            if not row:
                raise Invalid('Trader not found / 未找到交易员')
            return self.trader(row)

    def save_trader(self, payload, trader_id=None):
        name = str(payload.get('name', '')).strip()
        if not name or len(name) > 80:
            raise Invalid('Name is required / 请填写交易员名称')
        url = validate_url(str(payload.get('url', '')))
        source = payload.get('source', 'demo')
        if source not in ('demo', 'binance_public'):
            raise Invalid('Unsupported data source / 数据源无效')
        config = validate_config(payload.get('config', {}))
        authorized = payload.get('authorized') is True
        if source == 'binance_public' and not authorized:
            raise Invalid('Confirm authorized automated access before using a public feed / 请先确认数据自动访问权限')
        with self.db() as db:
            if trader_id:
                old = db.execute('SELECT * FROM traders WHERE id=?', (trader_id,)).fetchone()
                if not old:
                    raise Invalid('Trader not found')
                if old['enabled']:
                    raise Invalid('Pause this trader before editing / 请先暂停该交易员再编辑')
                positions = db.execute('SELECT * FROM positions WHERE trader_id=?', (trader_id,)).fetchall()
                if any(dec(p['qty']) > 0 for p in positions):
                    raise Invalid('Close its paper positions before changing configuration / 修改配置前请先平掉该交易员模拟仓位')
                changed = old['url'] != url or old['source'] != source
                db.execute('UPDATE traders SET name=?,url=?,source=?,authorized=?,config=?,baseline=? WHERE id=?',
                           (name, url, source, int(authorized), json.dumps(config), 0 if changed else old['baseline'], trader_id))
            else:
                trader_id = uuid.uuid4().hex[:12]
                db.execute('INSERT INTO traders(id,name,url,source,authorized,config,created) VALUES (?,?,?,?,?,?,?)',
                           (trader_id, name, url, source, int(authorized), json.dumps(config), now()))
            self.log(db, trader_id, 'info', '交易员配置已保存；实际交易未启用。')
        return self.get_trader(trader_id)

    def toggle(self, trader_id, enabled):
        t = self.get_trader(trader_id)
        if enabled and t['source'] == 'binance_public':
            if not t['authorized'] or t['config']['utc_offset_minutes'] is None:
                raise Invalid('Public feed requires authorized access and a verified timezone / 公开数据源需要访问权限和已核实的时区')
            import importlib.util
            if importlib.util.find_spec('playwright') is None:
                raise Invalid('Install optional Playwright collector first / 请先安装可选的Playwright采集依赖')
        with self.db() as db:
            db.execute('UPDATE traders SET enabled=? WHERE id=?', (int(enabled), trader_id))
            self.log(db, trader_id, 'info', '模拟跟随已启动。' if enabled else '已暂停新信号；模拟仓位止损继续检查。')

    def pause_all(self, paused):
        with self.db() as db:
            db.execute("UPDATE settings SET value=? WHERE key='paused'", (json.dumps(paused),))
            self.log(db, None, 'warning' if paused else 'info', '全局暂停新增仓位。' if paused else '全局新增仓位已恢复。')

    @staticmethod
    def pnl(db, trader_id=None):
        rows = db.execute('SELECT pnl,fee FROM orders' + (' WHERE trader_id=?' if trader_id else ''),
                          (trader_id,) if trader_id else ()).fetchall()
        return sum((dec(r['pnl']) - dec(r['fee']) for r in rows), D('0'))

    @staticmethod
    def unrealized(p):
        return (dec(p['mark']) - dec(p['entry'])) * dec(p['qty']) * (1 if p['side'] == 'LONG' else -1)

    def _close(self, db, p, qty, price, config, kind='CLOSE', event_id=None):
        qty = min(dec(qty), dec(p['qty']))
        if qty <= 0:
            return
        price = dec(price)
        pnl = (price - dec(p['entry'])) * qty * (1 if p['side'] == 'LONG' else -1)
        fee = qty * price * dec(config['fee_rate'])
        db.execute('INSERT INTO orders(id,event_id,trader_id,symbol,side,kind,qty,price,fee,pnl,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex[:16], event_id, p['trader_id'], p['symbol'], p['side'], kind, str(qty), str(price), str(fee), str(pnl), now()))
        left = dec(p['qty']) - qty
        if left == 0:
            db.execute('DELETE FROM positions WHERE trader_id=? AND symbol=? AND side=?',
                       (p['trader_id'], p['symbol'], p['side']))
        else:
            db.execute('UPDATE positions SET qty=?,mark=? WHERE trader_id=? AND symbol=? AND side=?',
                       (str(left), str(price), p['trader_id'], p['symbol'], p['side']))

    def mark(self, trader_id, symbol, bid, ask):
        bid, ask = dec(bid), dec(ask)
        if not 0 < bid <= ask:
            raise Invalid('Invalid bid/ask')
        t = self.get_trader(trader_id)
        with self.db() as db:
            positions = db.execute('SELECT * FROM positions WHERE trader_id=? AND symbol=?', (trader_id, symbol)).fetchall()
            for position in positions:
                p = dict(position)
                price = bid if p['side'] == 'LONG' else ask
                db.execute('UPDATE positions SET mark=? WHERE trader_id=? AND symbol=? AND side=?',
                           (str(price), trader_id, symbol, p['side']))
                triggered = price <= dec(p['stop']) if p['side'] == 'LONG' else price >= dec(p['stop'])
                if triggered:
                    self._close(db, p, p['qty'], price, t['config'], 'STOP_LOSS')
                    self.log(db, trader_id, 'warning', symbol + ' 模拟止损触发。仅在本机运行且报价更新时生效。')
            positions = list(db.execute('SELECT * FROM positions WHERE trader_id=?', (trader_id,)))
            total_pnl = self.pnl(db, trader_id) + sum((self.unrealized(p) for p in positions), D('0'))
            if total_pnl <= -dec(t['config']['max_loss']):
                for p in positions:
                    self._close(db, p, p['qty'], p['mark'], t['config'], 'LOSS_LIMIT')
                db.execute('UPDATE traders SET enabled=0 WHERE id=?', (trader_id,))
                self.log(db, trader_id, 'error', '模拟亏损预算已触发；已平模拟仓位并暂停。')

    def process(self, trader_id, event, bid, ask, baseline=False):
        t = self.get_trader(trader_id)
        if json.loads(t.get('signal_monitor') or '{}').get('mode')=='observe':
            raise Invalid('This trader is configured for signal observation only; paper execution is disabled')
        c = t['config']
        if event.get('action') not in ACTIONS:
            raise Invalid('Unknown action / 操作类型未知')
        symbol = str(event.get('symbol', ''))
        source_id = str(event.get('source_id', ''))
        if not source_id or len(source_id) > 200:
            raise Invalid('Invalid source operation ID')
        price, bid, ask = dec(event.get('price')), dec(bid), dec(ask)
        if not (price > 0 and 0 < bid <= ask):
            raise Invalid('Invalid prices')
        try:
            stamp = datetime.fromisoformat(event['source_time'])
            if stamp.tzinfo is None:
                raise ValueError()
        except Exception:
            raise Invalid('Source timestamp needs a verified timezone / 源时间必须具有已核实的时区') from None
        delay_ms = int((datetime.now(timezone.utc) - stamp).total_seconds() * 1000)
        opening = event['action'].startswith('OPEN')
        side = 'LONG' if event['action'].endswith('LONG') else 'SHORT'
        buy = event['action'] in ('OPEN_LONG', 'CLOSE_SHORT')
        quote = ask if buy else bid
        deviation = (quote / price - 1) * (1 if buy else -1)
        with self.db() as db:
            # Unique trader/source operation keys make repeated reads idempotent.
            cur = db.execute('INSERT OR IGNORE INTO events(trader_id,source_id,action,symbol,source_time,first_seen,source_price,quote_price,delay_ms,deviation,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                             (trader_id, source_id, event['action'], symbol, event['source_time'], now(), str(price), str(quote), delay_ms, str(deviation), 'pending'))
            if not cur.rowcount:
                return dict(status='duplicate')
            event_id = cur.lastrowid
            def finish(status, reason=''):
                db.execute('UPDATE events SET status=?,reason=? WHERE id=?', (status, reason, event_id))
                return dict(status=status, reason=reason, event_id=event_id)
            if baseline:
                return finish('baseline', '首次历史基线，不执行旧操作 / Historical baseline')
            if symbol not in c['symbols']:
                return finish('skipped', '不在合约白名单 / Symbol not allowed')
            if not t['enabled']:
                return finish('skipped', '交易员已暂停 / Trader paused')
            if delay_ms < -5000:
                return finish('skipped', '源时区或时钟异常 / Future timestamp')
            positions = list(db.execute('SELECT * FROM positions WHERE trader_id=?', (trader_id,)))
            p = next((dict(p) for p in positions if p['symbol'] == symbol and p['side'] == side), None)
            if not opening:
                # Late closes cannot open a position. Do not discard them solely because they are old.
                if not p:
                    return finish('skipped', '没有对应模拟仓位 / No owned paper position')
                if delay_ms > c['max_signal_age'] * 1000:
                    self.log(db, trader_id, 'warning', '迟到的减仓信号仅按已配置比例减少现有模拟仓位。')
                self._close(db, p, dec(p['qty']) * dec(c['close_fraction']), quote, c, 'CLOSE', event_id)
                return finish('filled', '模拟减仓；不是源账户真实减仓百分比 / Paper reduction')
            if json.loads(db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]):
                return finish('skipped', '全局暂停开仓 / Global entry pause')
            if delay_ms > c['max_signal_age'] * 1000:
                return finish('skipped', '开仓信号已过期 / Entry signal expired')
            if deviation > dec(c['max_deviation']):
                return finish('skipped', '不利跟随价差超过上限 / Entry deviation exceeded')
            if any(p['symbol'] == symbol and p['side'] != side for p in positions):
                return finish('skipped', '同一交易员存在反向仓位 / Opposite position exists')
            net_pnl = self.pnl(db, trader_id)
            margin_used = sum((dec(p['qty']) * dec(p['entry']) / p['leverage'] for p in positions), D('0'))
            margin = dec(c['order_margin'])
            if margin + margin_used > dec(c['budget']) + net_pnl:
                return finish('skipped', '交易员可用模拟预算不足 / Trader budget exceeded')
            total_positions = list(db.execute('SELECT * FROM positions'))
            total_margin = sum((dec(p['qty']) * dec(p['entry']) / p['leverage'] for p in total_positions), D('0'))
            balance = dec(db.execute("SELECT value FROM settings WHERE key='starting_balance'").fetchone()[0]) + self.pnl(db)
            if total_margin + margin > balance:
                return finish('skipped', '模拟账户可用资金不足 / Account budget exceeded')
            if net_pnl <= -dec(c['max_loss']):
                return finish('skipped', '已触发亏损预算 / Loss budget reached')
            qty = (margin * c['leverage'] / quote).quantize(D('0.00000001'), rounding=ROUND_DOWN)
            if qty <= 0:
                return finish('skipped', '模拟数量过小 / Quantity too small')
            fee = qty * quote * dec(c['fee_rate'])
            if total_margin + margin + fee > balance:
                return finish('skipped', '计入手续费后模拟账户资金不足 / Account budget exceeded after fees')
            if margin + fee > dec(c['budget']) + net_pnl - margin_used:
                return finish('skipped', '计入手续费后预算不足 / Insufficient margin after fees')
            previous_qty = dec(p['qty']) if p else D('0')
            entry = (previous_qty * dec(p['entry']) + qty * quote) / (previous_qty + qty) if p else quote
            candidate_stop = entry * (1 - dec(c['stop_loss_pct']) if side == 'LONG' else 1 + dec(c['stop_loss_pct']))
            stop = candidate_stop
            if p:
                stop = max(dec(p['stop']), stop) if side == 'LONG' else min(dec(p['stop']), stop)
            db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?)',
                       (trader_id, symbol, side, str(previous_qty + qty), str(entry), str(quote), str(stop), c['leverage']))
            db.execute('INSERT INTO orders(id,event_id,trader_id,symbol,side,kind,qty,price,fee,pnl,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex[:16], event_id, trader_id, symbol, side, 'OPEN', str(qty), str(quote), str(fee), '0', now()))
            self.log(db, trader_id, 'info', symbol + ' ' + side + ' 模拟成交。')
            return finish('filled', '本地买卖一报价模拟，不保证真实成交 / Paper fill')

    def close_paper(self, trader_id, symbol=None, side=None):
        t = self.get_trader(trader_id)
        with self.db() as db:
            rows = list(db.execute('SELECT * FROM positions WHERE trader_id=?', (trader_id,)))
            for p in rows:
                if (symbol is None or p['symbol'] == symbol) and (side is None or p['side'] == side):
                    self._close(db, p, p['qty'], p['mark'], t['config'], 'MANUAL_CLOSE')
            self.log(db, trader_id, 'info', '已按最后已知模拟报价平仓。')

    def snapshot(self):
        with self.db() as db:
            traders = [self.trader(r) for r in db.execute('SELECT * FROM traders ORDER BY created')]
            positions = [dict(r) for r in db.execute('SELECT * FROM positions')]
            orders = [dict(r) for r in db.execute('SELECT * FROM orders ORDER BY rowid DESC LIMIT 200')]
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 300')]
            logs = [dict(r) for r in db.execute('SELECT * FROM logs ORDER BY id DESC LIMIT 100')]
            pnl = self.pnl(db)
            balance = dec(db.execute("SELECT value FROM settings WHERE key='starting_balance'").fetchone()[0])
            unrealized = sum((self.unrealized(p) for p in positions), D('0'))
            for p in positions:
                p['unrealized'] = str(self.unrealized(p))
            delays = sorted(e['delay_ms'] for e in events if e['status'] != 'baseline' and e['delay_ms'] is not None and e['delay_ms'] >= 0)
            fees = sum((dec(o[0]) for o in db.execute('SELECT fee FROM orders')), D('0'))
            for t in traders:
                t['realized_net'] = str(self.pnl(db, t['id']))
                latest = next((e for e in events if e['trader_id'] == t['id']), None)
                t['last_seen'] = latest['first_seen'] if latest else None
            points = [dict(r) for r in db.execute('SELECT value,created FROM equity ORDER BY id DESC LIMIT 60')][::-1]
            return dict(mode='paper', live_available=False, live_reason='此接口只返回模拟实验室数据；账户工作台使用独立的 /api/live 接口。',
                        paused=json.loads(db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]),
                        metrics=dict(balance=str(balance), equity=str(balance + pnl + unrealized), realized_net=str(pnl),
                                     unrealized=str(unrealized), fees=str(fees), positions=len(positions),
                                     delay_median_ms=delays[len(delays)//2] if delays else None,
                                     delay_p95_ms=delays[min(len(delays)-1,int(len(delays)*0.95))] if delays else None),
                        traders=traders, positions=positions, orders=orders, events=events, logs=logs, equity=points)

    def record_equity(self):
        state = self.snapshot()
        with self.db() as db:
            db.execute('INSERT INTO equity(value,created) VALUES (?,?)', (state['metrics']['equity'], now()))

    def export_config(self):
        state = self.snapshot()
        return dict(schema=1, mode='paper', traders=[{k:t[k] for k in ('name','url','source','authorized','config')} for t in state['traders']])
