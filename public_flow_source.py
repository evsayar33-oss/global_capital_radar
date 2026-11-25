"""Rounded published daily flows: separate observational fallback, never signals."""
import hashlib
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

URL='https://www.privatewealthdaily.com/etf/'

class DailyTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.body=False; self.cell=None; self.cells=[]; self.rows=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='figure' and a.get('data-chart')=='daily-net-flows-1m':self.active=True
        if not self.active:return
        if tag=='tbody':self.body=True
        if self.body and tag=='tr':self.cells=[]
        if self.body and tag in ('th','td'):self.cell=''
    def handle_data(self,data):
        if self.cell is not None:self.cell+=data
    def handle_endtag(self,tag):
        if tag in ('th','td') and self.cell is not None:self.cells.append(self.cell.strip());self.cell=None
        if tag=='tr' and self.body:self.rows.append(self.cells)
        if tag=='tbody':self.body=False
        if tag=='figure':self.active=False

def parse(html,symbol,today,calendar):
    text=unescape(re.sub('<[^>]+>',' ',html))
    if not re.search(r'<title>\s*'+re.escape(symbol)+r'\s+[—–-]',html):
        raise ValueError('flow page symbol mismatch')
    m=re.search(r'Flows through\s+([A-Z][a-z]{2} \d{1,2}, \d{4})',text)
    if not m:raise ValueError('flow publication date missing')
    end=datetime.strptime(m[1],'%b %d, %Y').date()
    if not 0<=(today-end).days<=7:raise ValueError('flow source stale/future')
    parser=DailyTable();parser.feed(html)
    raw={}
    for cells in parser.rows:
        if len(cells)!=2:raise ValueError('invalid daily table')
        label,value=cells
        d=datetime.strptime(label+' '+str(end.year),'%b %d %Y').date()
        if d>end:
            d=d.replace(year=d.year-1)
        if d not in calendar or not 0<=(end-d).days<=35 or d in raw:
            raise ValueError('daily flow calendar/date mismatch')
        m=re.fullmatch(r'([+−-]?)\$([\d,]+(?:\.\d+)?)([KMBT]?)',value)
        if not m:raise ValueError('daily flow USD unit missing')
        raw[d]=(-1 if m[1] in ('−','-') else 1)*float(m[2].replace(',',''))*{'':1,'K':1e3,'M':1e6,'B':1e9,'T':1e12}[m[3]]
    if len(raw)<5 or max(raw)!=end:raise ValueError('daily flow coverage incomplete')
    return raw,dict(source='Private Wealth Daily',source_url=URL+symbol+'?r=1m',
        source_date=str(end),units='USD',precision='PUBLISHER_ROUNDED',
        source_sha256=hashlib.sha256(html.encode()).hexdigest(),
        historical_publication_time_verified=False,independent_corroboration=False,
        caveat='Published rounded daily amounts; observation only, not exact cash flows or strategy evidence')

def collect(symbol,today,calendar,reader):
    from flow_continuity import observed
    raw,meta=parse(reader(URL+symbol+'?r=1m'),symbol,today,calendar)
    result=observed(symbol,'PWD_DAILY_ROUNDED',raw,today,calendar,meta)
    result['action']='BEKLE · yuvarlanmış alternatif gözlem'
    for h in result['horizons'].values():
        h.update(action=result['action'],strength='Yuvarlanmış gözlem · güç ölçülmedi',magnitude_percentile=None)
    return result
