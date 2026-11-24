"""Read-only native data; independent market provenance and explicit failures."""
import json
import re
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from secondary_sources import number,cot_api

OKX="https://www.okx.com/api/v5/"
SHFE="https://www.shfe.com.cn/eng/reports/StatisticalData/DailyData/"
def ts(value):
    return datetime.fromtimestamp(int(value)/1000,timezone.utc)

def okx_rows(path,params,reader):
    p=json.loads(reader(OKX+path+"?"+urlencode(params)))
    if p.get("code")!="0" or not isinstance(p.get("data"),list) or not p["data"]:
        raise ValueError("OKX invalid or empty response")
    return p["data"]

def okx_quote(path,params,identity,fields,reader,clock):
    rows=okx_rows(path,params,reader)
    if len(rows)!=1 or rows[0].get("instId")!=identity:
        raise ValueError("OKX quote identity")
    r=rows[0]
    t=ts(r["ts"])
    if not 0<=(clock()-t).total_seconds()<=900:
        raise ValueError("OKX quote stale/future")
    values=[float(r[k]) for k in fields]
    if not all(number(v) and v>0 for v in values):
        raise ValueError("OKX quote nonpositive")
    return t,values

def okx_crypto(inst,now,reader,clock=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    rows=okx_rows("public/funding-rate-history",{"instId":inst,"limit":100},reader)
    settled={}
    checked=clock()
    for r in rows:
        if r.get("instId")!=inst or r.get("instType")!="SWAP":
            raise ValueError("OKX funding identity")
        t=ts(r["fundingTime"])
        v=float(r["realizedRate"])
        if t>checked or t in settled or not number(v):
            raise ValueError("OKX settlement timestamp/value")
        settled[t]=v
    ordered=sorted(settled)
    if len(ordered)<2 or not 0<=(checked-ordered[-1]).total_seconds()<=86400:
        raise ValueError("OKX stale/short settled funding")
    history=[]
    for i,t in enumerate(ordered):
        hours=(t-ordered[i-1]).total_seconds()/3600 if i else None
        history.append(dict(time=t.isoformat(),rate=settled[t],interval_hours=hours))
    last=history[-1]
    h=last["interval_hours"]
    # Missing intervals may be gaps; avoid annualizing nonstandard spacing.
    annual=last["rate"]*365*24/h*100 if h in (1,2,4,8) else None
    result=dict(status="OBSERVED",source="OKX",source_url=OKX,symbol=inst,
                funding_asof=last["time"],funding_rate=last["rate"],interval_hours=h,
                annualized_pct=annual,history=history,basis_pct=None,quoted_spread_bps=None,
                caveat="settled funding only; quoted spread is not execution cost")
    try:
        idx=inst.removesuffix("-SWAP")
        mt,(mark,)=okx_quote("public/mark-price",{"instType":"SWAP","instId":inst},inst,("markPx",),reader,clock)
        it,(index,)=okx_quote("market/index-tickers",{"instId":idx},idx,("idxPx",),reader,clock)
        if abs((mt-it).total_seconds())>120:
            raise ValueError("OKX mark/index time mismatch")
        result.update(basis_pct=100*(mark/index-1),basis_asof=min(mt,it).isoformat(),basis_status="OBSERVED")
    except Exception as exc:
        result.update(basis_status="UNAVAILABLE",basis_error=str(exc))
    try:
        qt,(bid,ask)=okx_quote("market/ticker",{"instId":inst},inst,("bidPx","askPx"),reader,clock)
        if ask<bid:raise ValueError("crossed quote")
        result.update(quoted_spread_bps=10000*(ask-bid)/((ask+bid)/2),quote_asof=qt.isoformat(),spread_status="OBSERVED")
    except Exception as exc:
        result.update(spread_status="UNAVAILABLE",spread_error=str(exc))
    return result

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=None;self.cell=None;self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=="tr":self.row=[]
        if tag in ("td","th") and self.row is not None:self.cell=[]
    def handle_data(self,s):
        self.text.append(s)
        if self.cell is not None:self.cell.append(s)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()));self.cell=None
        if tag=="tr" and self.row is not None:
            self.rows.append(self.row);self.row=None

def parse_shfe(html,day):
    p=Tables();p.feed(html)
    text=" ".join(" ".join(p.text).split())
    if not re.search(r"Shanghai Futures Exchange Warehouse Stocks Daily",text,re.I) or not re.search(r"DATE\s*[:：]\s*"+str(day),text,re.I):
        raise ValueError("SHFE report title/date mismatch")
    # Read only copper (not Copper BC), require explicit unit and total.
    active=False;unit=False;header=False;pre_header=False;subs=[];total=None
    for row in p.rows:
        upper=[s.upper().strip() for s in row]
        if "COPPER" in upper:
            if active:raise ValueError("duplicate copper section")
            active=True;header=pre_header;unit=any(re.search(r"UNIT\s*[:：]\s*TONNE\b",s) for s in upper);continue
        if not active:
            if any(upper):pre_header="REGION" in upper and "WAREHOUSE" in upper and "ON WARRANT" in upper and "CHANGE" in upper
            continue
        # A new commodity/unit row before CU total is an incomplete CU section.
        if any(re.search(r"UNIT\s*[:：]",s) for s in upper) and not any(re.search(r"UNIT\s*[:：]\s*TONNE\b",s) for s in upper):
            raise ValueError("SHFE unexpected unit in copper section")
        if any(re.search(r"UNIT\s*[:：]",s) for s in upper) and len(upper)>1 and upper[0] and not re.search(r"UNIT\s*[:：]",upper[0]):
            raise ValueError("SHFE next product before copper total")
        if any(re.search(r"UNIT\s*[:：]\s*TONNE\b",s) for s in upper):unit=True
        if "ON WARRANT" in upper and "CHANGE" in upper:header=True
        label=next((s for s in upper if s in ("SUBTOTAL","TOTAL")),None)
        if label:
            i=upper.index(label)
            values=[s.replace(",","").strip() for s in row[i+1:] if s.strip()]
            if len(values)!=2 or not re.fullmatch(r"\d+",values[0]) or not re.fullmatch(r"[+-]?\d+",values[1]):
                raise ValueError("SHFE subtotal/total layout")
            value=int(values[0]);change=int(values[1])
            if label=="SUBTOTAL":subs.append((value,change))
            else:total=(value,change);break
    if not active or not unit or not header or not subs or total is None or tuple(map(sum,zip(*subs)))!=total:
        raise ValueError("SHFE copper unit/header/total reconciliation")
    return dict(status="OBSERVED",source="SHFE",source_date=str(day),units="metric tonnes",
                on_warrant_tonnes=total[0],change_tonnes=total[1],regions=len(subs),
                scope="SHFE copper warrants only; not COMEX inventories")

def shfe_copper(now,reader):
    day=now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    errors=[]
    for i in range(7):
        d=day-timedelta(days=i)
        if d.weekday()>=5:continue
        url=SHFE+"?"+urlencode(dict(query_date=d.strftime("%Y%m%d"),query_params="dailystock"))
        try:
            r=parse_shfe(reader(url),d);r["source_url"]=url;return r
        except Exception as exc:errors.append(str(d)+": "+type(exc).__name__+": "+str(exc))
    return dict(status="UNAVAILABLE",source="SHFE",error="; ".join(errors),source_url=SHFE)

def tbf3(today,reader):
    code="041741"
    hist=cot_api(today,{code},reader,allow_empty=True).get(code,{})
    latest=max(hist) if hist else None
    current=latest is not None and (today-latest).days<=13
    return hist,dict(status="OBSERVED" if current else "NO_CURRENT_COT_SERIES",
        code=code,contract_name="13-week U.S. Treasury bills",source="CFTC Legacy futures only",
        latest_report_date=str(latest) if latest else None,
        observations=[dict(date=str(d),noncommercial_net_oi_pct=v) for d,v in sorted(hist.items())],
        price_status="UNAVAILABLE_VERIFIED_TBF3_SETTLEMENT_HISTORY",
        production_proxy_allowed=False)
