"""Shared processing of verified public events; no account environment selection."""
import time
from .core import now
from .executor import Halt


def sync_funding(engine):
    end=int(time.time()*1000)
    rows=engine.book.db.execute('SELECT symbol,MIN(start_ms) FROM intervals GROUP BY symbol').fetchall()
    for symbol,start in rows:
        watermark=engine.book.get('funding_cursor:'+symbol)
        begin=max(int(start),int(watermark)-1000 if watermark else int(start))
        finish=min(end,begin+7*86400000)
        if begin>finish:continue
        engine.book.funding(engine.broker.funding(symbol,begin,finish))
        with engine.book.db:engine.book.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('funding_cursor:'+symbol,str(finish)))
        if finish<end:raise Halt('Funding catch-up is incomplete; review before proceeding')


def process_public(session,engine,source,prefix='aoying:',label='demo'):
    rows=session.source.events(session.cursor)
    def event(row):
        return dict(id=prefix+row['source_id'],action=row['action'],symbol=row['symbol'],
                    source_time=row['source_time'],detected_time=row['first_seen'],price=row['source_price'])
    def record(row,result):
        if result['state']!='duplicate':
            session.log('Public operation processed on '+label,origin='public',symbol=row['symbol'],
                action=row['action'],result=result['state'],reason=result.get('reason'),
                event_id=row['id'],price_check=result.get('price_check'))
    latest_close={}
    for index,row in enumerate(rows):
        if row['status']=='observed' and row['action'].startswith('CLOSE_'):
            latest_close[(row['symbol'],row['action'].split('_',1)[1])]=index
            item=event(row)
            if not engine.book.db.execute('SELECT 1 FROM intents WHERE id=?',(item['id'],)).fetchone():
                record(row,engine.handle(item))
    if not source['fresh']:
        if not session.source_waiting:
            session.log('Public source stale: holding entries while exchange protection maintenance continues','warning')
        with session.lock:session.source_waiting=True;session.last_tick=now()
    else:
        if session.source_waiting:session.log('Public source fresh again: resuming with original cursor and detection-age limit')
        with session.lock:session.source_waiting=False
    for index,row in enumerate(rows):
        if session.stop_event.is_set():return
        if row['status']=='observed' and row['action'].startswith('OPEN_'):
            item=event(row);side=row['action'].split('_',1)[1]
            if latest_close.get((row['symbol'],side),-1)>index:
                engine.price_check=None;record(row,engine.skip(item,'superseded_by_close'))
            elif not session.entries_enabled:
                engine.price_check=None;record(row,engine.skip(item,'entries_paused'))
            elif not source['fresh']:break
            else:record(row,engine.handle(item))
        session.cursor=row['id']
        with engine.book.db:engine.book.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('source_cursor',str(session.cursor)))
    with session.lock:session.last_tick=now()
