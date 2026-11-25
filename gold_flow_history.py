"""GLD issuer archive: NAV-adjusted changes in published total net assets."""
import hashlib
import io
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.request import Request,urlopen
from secondary_sources import number
from horizons import boundary

URL='https://api.spdrgoldshares.com/api/v1/historical-archive?exchange=NYSE&lang=en&product=gld'
N='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def parse(blob,today):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        if sum(i.file_size for i in z.infolist())>50_000_000:raise ValueError('oversized issuer archive')
        def xml(name):
            b=z.read(name)
            if b'<!DOCTYPE' in b.upper() or b'<!ENTITY' in b.upper():raise ValueError('unsupported XLSX entity')
            return ET.fromstring(b)
        wb=xml('xl/workbook.xml')
        sheets=[s for s in wb.findall('.//'+N+'sheet') if s.get('name')=='US GLD Historical Archive']
        if len(sheets)!=1:raise ValueError('GLD archive identity missing')
        rels={r.get('Id'):r.get('Target') for r in xml('xl/_rels/workbook.xml.rels')}
        path=rels[sheets[0].get(R+'id')]
        path=path.lstrip('/') if path.startswith('/') else posixpath.normpath('xl/'+path)
        if not path.startswith('xl/worksheets/'):raise ValueError('invalid issuer worksheet path')
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(t.itertext()) for t in xml('xl/sharedStrings.xml').findall(N+'si')]
        rows=[]
        for row in xml(path).findall('.//'+N+'row'):
            values={}
            for c in row.findall(N+'c'):
                column=''.join(x for x in c.get('r','') if x.isalpha())
                v=c.find(N+'v');value=v.text if v is not None else ''
                if c.get('t')=='s':value=shared[int(value)]
                elif c.get('t')=='inlineStr':value=''.join(c.find(N+'is').itertext())
                values[column]=value
            rows.append(values)
    return parse_rows(rows,today)

def parse_rows(rows,today):
    if not rows:raise ValueError('empty gold archive')
    names=['Date','NAV/Share at 10:30am NYT','Total Net Asset Value in the Trust']
    indices=[]
    for name in names:
        found=[k for k,v in rows[0].items() if v==name]
        if len(found)!=1:raise ValueError('gold archive column mismatch')
        indices.append(found[0])
    records={};seen=set()
    for row in rows[1:]:
        ds,nav,assets=(row.get(i,'') for i in indices)
        if not ds:continue
        day=datetime.strptime(ds,'%d-%b-%Y').date()
        if day in seen or day>today:raise ValueError('gold duplicate/future date')
        seen.add(day)
        if nav=='US Holiday' and assets=='US Holiday':continue
        if nav in ('','N/A','--') or assets in ('','N/A','--'):continue
        nav=float(nav);assets=float(assets)
        if not number(nav) or not number(assets) or min(nav,assets)<=0:raise ValueError('gold archive invalid NAV/assets')
        records[day]=(nav,assets)
    return records

def download():
    with urlopen(Request(URL,headers={'User-Agent':'global-capital-radar/1.0'}),timeout=30) as r:return r.read()

def collect(today,calendar,reader=download):
    from flow_continuity import observed
    blob=reader();records=parse(blob,today);raw={};skipped=[]
    for prev,day in zip(calendar,calendar[1:]):
        if prev not in records or day not in records:continue
        nav,assets=records[day];pnav,passets=records[prev]
        if not 2/3<nav/pnav<1.5:skipped.append(str(day));continue
        raw[day]=assets-passets*nav/pnav
    meta=dict(source='SPDR Gold Shares official archive',source_url=URL,units='USD',
        source_sha256=hashlib.sha256(blob).hexdigest(),precision='ISSUER_DERIVED_ESTIMATE',
        estimate_basis='total net assets minus prior total net assets times NAV ratio',
        source_history_start=str(min(records)),source_history_end=str(max(records)),source_observations=len(records),
        skipped_discontinuities=skipped,historical_publication_time_verified=False,independent_corroboration=False)
    result=observed('GLD','SPDR_GOLD_HISTORY',raw,today,calendar,meta)
    prior=[d for d in calendar if d<max(raw)]
    if prior and prior[-1] in records:
        result['daily_observation'].update(flow_aum_pct=100*raw[max(raw)]/records[prior[-1]][1],aum_asof=str(prior[-1]))
    for key,h in result['horizons'].items():
        prior=[d for d in calendar if d<=boundary(max(raw),key,1)]
        if prior and prior[-1] in records and h.get('net_usd_m') is not None:
            h.update(flow_aum_pct=100*h['net_usd_m']*1e6/records[prior[-1]][1],aum_asof=str(prior[-1]),aum_basis='issuer published total net assets')
        h['action']='BEKLE · resmî NAV/varlık kaynaklı akış tahmini'
    result['action']='BEKLE · resmî NAV/varlık kaynaklı akış tahmini'
    return result
