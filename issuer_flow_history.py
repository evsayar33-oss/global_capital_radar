"""Official issuer NAV/share history; derived creation estimates, not cash transfers."""
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode
from secondary_sources import number
from horizons import boundary

FUNDS={
 'SLV':('239855','iShares Silver Trust'),
 'IWM':('239710','iShares Russell 2000 ETF'),
 'SHY':('239452','iShares 1-3 Year Treasury Bond ETF'),
 'SGOV':('314116','iShares 0-3 Month Treasury Bond ETF'),
 'IBIT':('333011','iShares Bitcoin Trust ETF'),
 'ETHA':('337614','iShares Ethereum Trust ETF'),
}
NS='{urn:schemas-microsoft-com:office:spreadsheet}'

def url(symbol):
    return 'https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document?'+urlencode(dict(appType='PRODUCT_PAGE',appSubType='ISHARES',targetSite='us-ishares',locale='en_US',portfolioId=FUNDS[symbol][0],component='fundDownload',userType='individual'))

def cells(row):
    out=[]
    for c in row.findall(NS+'Cell'):
        index=int(c.get(NS+'Index',len(out)+1))
        if index<=len(out) or index>100:raise ValueError('invalid sparse worksheet index')
        out.extend(['']*(index-len(out)-1))
        d=c.find(NS+'Data');out.append(''.join(d.itertext()).strip() if d is not None else '')
    return out

def normalized(s):
    return ' '.join(s.replace('®','').replace('–','-').replace('−','-').split()).casefold()

def parse(text,symbol,today):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('unsupported workbook entities')
    # The official file contains bare ampersands in disclaimer hyperlink attributes.
    # Escape only those XML syntax errors; never repair numeric data or dates.
    xml=re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', text)
    root=ET.fromstring(xml)
    sheets={s.get(NS+'Name'):s for s in root.findall(NS+'Worksheet')}
    if 'Performance' not in sheets or 'Historical' not in sheets:raise ValueError('issuer workbook sheets missing')
    identity=[cells(r) for r in sheets['Performance'].findall('.//'+NS+'Row')]
    if not identity or not identity[0] or normalized(identity[0][0])!=normalized(FUNDS[symbol][1]):
        raise ValueError('issuer workbook identity mismatch')
    rows=[cells(r) for r in sheets['Historical'].findall('.//'+NS+'Row')]
    required=['As Of','NAV per Share','Shares Outstanding']
    if not rows or any(rows[0].count(k)!=1 for k in required):raise ValueError('issuer historical schema mismatch')
    indices=[rows[0].index(k) for k in required]; records={}
    for row in rows[1:]:
        if not any(row):continue
        if len(row)<=max(indices):raise ValueError('short issuer history row')
        ds,nav,shares=(row[i] for i in indices)
        day=datetime.strptime(ds,'%b %d, %Y').date()
        if day>today or day in records:raise ValueError('issuer duplicate/future date')
        if nav in ('--','-','') or shares in ('--','-',''):continue
        nav=float(nav.replace(',',''));shares=float(shares.replace(',',''))
        if not number(nav) or not number(shares) or nav<=0 or shares<=0 or not shares.is_integer():raise ValueError('issuer NAV/shares invalid')
        records[day]=(nav,int(shares))
    if not records:raise ValueError('issuer history empty')
    return records

def collect(symbol,today,calendar,reader):
    from flow_continuity import observed
    text=reader(url(symbol));records=parse(text,symbol,today)
    raw={};skipped=[];aum={}
    for previous,day in zip(calendar,calendar[1:]):
        if day not in records or previous not in records:continue
        nav,shares=records[day];prior_nav,prior_shares=records[previous]
        # Do not interpret large NAV discontinuities as creations (e.g. stock splits).
        if not 2/3<nav/prior_nav<1.5:
            skipped.append(str(day));continue
        raw[day]=(shares-prior_shares)*nav
        aum[previous]=prior_nav*prior_shares
    meta=dict(source='BlackRock / iShares official workbook',source_url=url(symbol),units='USD',
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),precision='ISSUER_DERIVED_ESTIMATE',
        estimate_basis='change in official shares outstanding times same-day NAV',
        aum_basis='official shares outstanding times NAV; estimated net assets',
        source_history_start=str(min(records)),source_history_end=str(max(records)),
        source_observations=len(records),skipped_discontinuities=skipped,
        historical_publication_time_verified=False,independent_corroboration=False)
    result=observed(symbol,'ISHARES_HISTORY',raw,today,calendar,meta)
    end=max(raw)
    for key,h in result['horizons'].items():
        prior=[d for d in calendar if d<=boundary(end,key,1)]
        start=prior[-1] if prior else None
        if start in aum and h.get('net_usd_m') is not None:
            h.update(flow_aum_pct=100*h['net_usd_m']*1e6/aum[start],aum_asof=str(start),aum_basis=meta['aum_basis'])
    result['action']='BEKLE · resmî pay/NAV kaynaklı akış tahmini'
    for h in result['horizons'].values():h['action']=result['action']
    return result

if __name__=='__main__':
    import json
    from datetime import timezone
    from zoneinfo import ZoneInfo
    from radar import read
    from flow_continuity import session_calendar
    now=datetime.now(timezone.utc);today=now.astimezone(ZoneInfo('America/New_York')).date()
    calendar=session_calendar(today,now)
    failed=[]
    for symbol in FUNDS:
        try:
            r=collect(symbol,today,calendar,read)
            print('ISSUER_RESULT '+json.dumps(dict(symbol=symbol,date=r['flow_asof'],days=r['daily_count'],source_start=r['provenance']['source_history_start'],horizons={k:{f:v.get(f) for f in ('net_usd_m','reference_count','flow_aum_pct')} for k,v in r['horizons'].items()})),flush=True)
            if symbol=='SLV' and (r['daily_count']<400 or any(r['horizons'][k].get('net_usd_m') is None for k in ('1H','1A','3A','1Y'))):failed.append(symbol)
        except Exception as e:failed.append(symbol);print('ISSUER_ERROR',symbol,type(e).__name__,str(e),flush=True)
    raise SystemExit(bool(failed))
