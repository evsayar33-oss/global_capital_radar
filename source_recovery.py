"""Source-specific evidence; never substitutes missing historical data or trading signals."""
import hashlib
import json
import re
from datetime import date,datetime,timedelta,timezone
from html.parser import HTMLParser
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from secondary_sources import number

SHFE="https://www.shfe.com.cn/data/tradedata/future/stockdata/"
ISSUERS={"USO":"https://www.uscfinvestments.com/uso",
         "CPER":"https://www.uscfinvestments.com/cper",
         "QQQ":"https://www.invesco.com/qqq-etf/en/about.html"}

class Page(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.hidden=0;self.tables=[];self.table=None;self.row=None;self.cell=None
        self.feed(html)
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):self.hidden+=1
        if tag=="table":self.table=[]
        if tag=="tr" and self.table is not None:self.row=[]
        if tag in ("th","td") and self.row is not None:self.cell=[]
    def handle_data(self,s):
        if self.hidden:return
        if s.strip():self.parts.append(s.strip())
        if self.cell is not None:self.cell.append(s)
    def handle_endtag(self,tag):
        if tag in ("script","style"):self.hidden=max(0,self.hidden-1)
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()));self.cell=None
        if tag=="tr" and self.row is not None:
            self.table.append(self.row);self.row=None
        if tag=="table" and self.table is not None:
            self.tables.append(self.table);self.table=None
    @property
    def text(self):return " ".join(" ".join(self.parts).split())

def parse_shfe_cn(html,day):
    p=Page(html)
    t=p.text
    date_regex=rf"{day.year}\s*年\s*0?{day.month}\s*月\s*0?{day.day}\s*日|{day.isoformat()}|{day.strftime('%Y%m%d')}"
    if "期货仓单日报" not in t or not re.search(date_regex,t):
        raise ValueError("SHFE Chinese report date/title missing")
    found=[]
    for rows in p.tables:
        if not any(row and row[0].strip()=="铜" for row in rows):continue
        if not any(re.search(r"单位\s*[:：]\s*吨",cell) for row in rows for cell in row):
            raise ValueError("SHFE copper tonne unit missing")
        if not any("期货" in row and "增减" in row for row in rows):
            raise ValueError("SHFE copper column mismatch")
        totals=[];subs=[];warehouses=[]
        for row in rows:
            if len(row)<3:continue
            vals=[v.replace(",","").strip() for v in row[-2:]]
            if not re.fullmatch(r"\d+",vals[0]) or not re.fullmatch(r"[+-]?\d+",vals[1]):continue
            x=tuple(map(int,vals))
            labels=row[:-2]
            if any(v.strip().endswith("总计") for v in labels):totals.append(x)
            elif any(v.strip()=="合计" for v in labels):subs.append(x)
            else:warehouses.append(x)
        if len(totals)!=1 or not subs or not warehouses:raise ValueError("SHFE totals missing")
        if tuple(map(sum,zip(*subs)))!=totals[0] or tuple(map(sum,zip(*warehouses)))!=totals[0]:
            raise ValueError("SHFE warehouse/subtotal mismatch")
        found.append(totals[0])
    if len(found)!=1:raise ValueError("SHFE CU identity ambiguous/missing")
    return dict(status="OBSERVED",source="SHFE",upstream_id="SHFE",source_date=str(day),
                units="metric tonnes",on_warrant_tonnes=found[0][0],change_tonnes=found[0][1],
                scope="SHFE CU warrants, not BC or COMEX",transport_id="official_zh_static")

def shfe_cn(now,reader):
    day=now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    errors=[]
    for offset in range(5):
        d=day-timedelta(days=offset)
        if d.weekday()>=5:continue
        url=SHFE+"dailystock_"+d.strftime("%Y%m%d")+"/ZH/all.html"
        try:
            raw=reader(url)
            r=parse_shfe_cn(raw,d)
            return dict(r,source_url=url,source_sha256=hashlib.sha256(raw.encode()).hexdigest())
        except Exception as exc:errors.append(str(d)+": "+type(exc).__name__+": "+str(exc))
    return dict(status="UNAVAILABLE",source="SHFE",upstream_id="SHFE",source_url=SHFE,error="; ".join(errors))

def amount(value):
    v=float(value.replace(",","").replace("$","").strip())
    if not number(v) or v<=0:raise ValueError("nonpositive issuer figure")
    return v

class USCFFields(HTMLParser):
    """Exact source field identities; do not extract values from JavaScript."""
    def __init__(self,html,symbol):
        super().__init__(convert_charrefs=True)
        self.symbol=symbol;self.stack=[];self.values={};self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("br","img","input","meta","link","hr","source","wbr","area","base","embed","param","track","col"):return
        inherited=self.stack[-1][1] if self.stack else None
        location=a.get("data-location",inherited)
        field=a.get("data-key")
        active=field if field in ("asofdate","nav","navps","so","navtotal") and location==self.symbol else None
        self.stack.append((tag,location,active,[]))
    def handle_data(self,data):
        for item in self.stack:
            if item[2]:item[3].append(data)
    def handle_endtag(self,tag):
        i=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if i is None:return
        for _,_,key,parts in self.stack[i:]:
            v=" ".join("".join(parts).split())
            if key and v:self.values.setdefault(key,set()).add(v)
        del self.stack[i:]

def issuer_fields(html,symbol,today):
    p=Page(html);name={"USO":"United States Oil Fund","CPER":"United States Copper Index Fund"}[symbol]
    if name.lower() not in p.text.lower():raise ValueError("issuer identity mismatch")
    v=USCFFields(html,symbol).values
    def exact(keys,pattern):
        matches={x for key in keys for x in v.get(key,set()) if re.fullmatch(pattern,x)}
        if len(matches)!=1:raise ValueError("USCF missing or conflicting "+"/".join(keys))
        return matches.pop()
    ds=exact(("asofdate",),r"(?:As of\s+)?\d{1,2}/\d{1,2}/\d{4}")
    d=datetime.strptime(ds.removeprefix("As of "),"%m/%d/%Y").date()
    if not 0<=(today-d).days<=7:raise ValueError("issuer stale/future date")
    nav=amount(exact(("nav","navps"),r"\$[\d,.]+"))
    shares=amount(exact(("so",),r"[\d,]+"))
    aum=amount(exact(("navtotal",),r"\$[\d,.]+"))
    if not shares.is_integer() or abs(shares*nav/aum-1)>.005:raise ValueError("issuer shares NAV AUM reconcile")
    return dict(status="OBSERVED",symbol=symbol,source="USCF",upstream_id="USCF",source_date=str(d),
                nav_usd=nav,shares=shares,shares_unit="shares",shares_precision="exact_integer",
                reported_aum_usd=aum,calculated_aum_usd=nav*shares,source_url=ISSUERS[symbol],
                publication_intraday_verified=False,parser="USCF_DATA_KEY")

def parse_issuer(html,symbol,today):
    p=Page(html)
    t=p.text
    if symbol in ("USO","CPER"):
        try:return issuer_fields(html,symbol,today)
        except ValueError:pass
        name={"USO":"United States Oil Fund","CPER":"United States Copper Index Fund"}[symbol]
        if name.lower() not in t.lower():raise ValueError("issuer identity mismatch")
        # Bind all fields to the same Key Facts section and its date.
        m=re.search(r"\bKey Facts\s+As of\s+(\d{1,2}/\d{1,2}/\d{4})\s+(.*?)(?:Performance|Swipe to see additional data)",t,re.I)
        if not m:
            # Navigation can repeat Key Facts, but the data block is unique.
            m=re.search(r"\bAs of\s+(\d{1,2}/\d{1,2}/\d{4})\s+(NAV\s*\^?\s+\$[\d,.]+.{0,700}?Total Net Assets\s+\$[\d,.]+)",t,re.I)
        if not m:raise ValueError("issuer dated Key Facts absent")
        d=datetime.strptime(m.group(1),"%m/%d/%Y").date();block=m.group(2)
        nav=amount(re.search(r"\bNAV\s*\^?\s+(\$[\d,.]+)",block,re.I).group(1))
        shares=amount(re.search(r"Shares Outstanding\s+([\d,]+)",block,re.I).group(1))
        aum=amount(re.search(r"Total Net Assets\s+(\$[\d,.]+)",block,re.I).group(1))
        if not shares.is_integer() or abs(shares*nav/aum-1)>.005:raise ValueError("issuer shares NAV AUM reconcile")
        unit="shares";precision="exact_integer"
    elif symbol=="QQQ":
        # Invesco's dated overview pairs AUM and rounded share count, not NAV.
        # Require ticker and both figures inside one explicitly dated block.
        if not re.search(r"\bInvesco QQQ\b",t,re.I):raise ValueError("QQQ issuer identity")
        matches=[]
        for m in re.finditer(r"\bas of\s+(\d{1,2}/\d{1,2}/\d{4})\s+Fund ticker\s+QQQ\b",t,re.I):
            block=re.split(r"\bas of\s+\d{1,2}/\d{1,2}/\d{4}",t[m.end():m.end()+1000],maxsplit=1,flags=re.I)[0]
            a=re.findall(r"\bAssets Under Management\s+\$\s*([\d,.]+)\s*(B|M|billion|million)\b",block,re.I)
            sh=re.findall(r"\bShares Outstanding\s+([\d,.]+)\s*(M|million|B|billion)\b",block,re.I)
            if len(a)==len(sh)==1:
                matches.append((m.group(1),*a[0],*sh[0]))
        if len(set(matches))!=1:raise ValueError("QQQ dated AUM/shares snapshot missing or ambiguous")
        ds,av,au,sv,su=matches[0]
        d=datetime.strptime(ds,"%m/%d/%Y").date()
        if not 0<=(today-d).days<=7:raise ValueError("issuer stale/future date")
        def scaled(v,u):return amount(v)*(1e9 if u.lower() in ("b","billion") else 1e6)
        aum=scaled(av,au);shares=scaled(sv,su)
        return dict(status="OBSERVED",symbol="QQQ",source="Invesco",upstream_id="Invesco",
                    source_date=str(d),nav_usd=None,shares=shares,shares_unit="shares",
                    shares_precision="rounded",reported_aum_usd=aum,calculated_aum_usd=None,
                    aum_precision="rounded",snapshot_only=True,flow_eligible=False,
                    source_url=ISSUERS["QQQ"],publication_intraday_verified=False)
    else:raise ValueError("unsupported fund")
    if not 0<=(today-d).days<=7:raise ValueError("issuer stale/future date")
    return dict(status="OBSERVED",symbol=symbol,source="Invesco" if symbol=="QQQ" else "USCF",
                upstream_id="Invesco" if symbol=="QQQ" else "USCF",
                source_date=str(d),nav_usd=nav,shares=shares,shares_unit=unit,shares_precision=precision,
                reported_aum_usd=aum,calculated_aum_usd=nav*shares,source_url=ISSUERS[symbol],
                publication_intraday_verified=False)

def issuer_snapshot(symbol,today,reader):
    raw=reader(ISSUERS[symbol])
    return dict(parse_issuer(raw,symbol,today),source_sha256=hashlib.sha256(raw.encode()).hexdigest())

def parse_creation(html,symbol,today):
    p=Page(html)
    name={"USO":"United States Oil Fund","CPER":"United States Copper Index Fund"}[symbol]
    if name.lower() not in p.text.lower():raise ValueError("creation fund identity")
    m=re.search(r"Creation\s*/\s*Redemption\s+As of\s+(\d{1,2}/\d{1,2}/\d{4})\s+Shares Created\s*/\s*Redeemed\s+([+-]?[\d,]+)",p.text,re.I)
    if not m:raise ValueError("creation dated observation missing")
    d=datetime.strptime(m.group(1),"%m/%d/%Y").date()
    if not 0<=(today-d).days<=7:raise ValueError("creation stale/future")
    return dict(source_date=str(d),net_created_shares=int(m.group(2).replace(",","")))

def capture_issuer(symbol,today,reader):
    result=issuer_snapshot(symbol,today,reader)
    if symbol in ("USO","CPER"):
        url="https://www.uscfinvestments.com/holdings/"+symbol.lower()
        try:
            c=parse_creation(reader(url),symbol,today)
            if c["source_date"]!=result["source_date"]:raise ValueError("creation and NAV dates differ")
            result.update(c,creation_status="OBSERVED",creation_source_url=url,
                estimated_creation_usd=c["net_created_shares"]*result["nav_usd"],
                creation_basis="issuer published net created shares times same-date rounded NAV")
        except Exception as exc:
            result.update(creation_status="UNAVAILABLE",creation_error=str(exc))
    return result

def estimate_adjacent(previous,current,calendar):
    # No rounded QQQ share deltas, no gap or split extrapolation.
    if any(r.get("status")!="OBSERVED" or r.get("shares_precision")!="exact_integer" for r in (previous,current)):
        return None
    if previous["symbol"]!=current["symbol"] or previous["upstream_id"]!=current["upstream_id"]:return None
    d=date.fromisoformat(current["source_date"]);p=date.fromisoformat(previous["source_date"])
    earlier=[x for x in calendar if x<d]
    if not earlier or max(earlier)!=p or d not in calendar:return None
    # An extreme reciprocal shares/NAV move is a corporate-action warning;
    # do not assume it is a creation or redemption.
    if abs(current["shares"]/previous["shares"]-1)>.20 or abs(current["nav_usd"]/previous["nav_usd"]-1)>.20:return None
    return (current["shares"]-previous["shares"])*current["nav_usd"]

TFF={"futures_only":"gpe5-46if","combined":"yw9f-hn96"}
def tff_tbf3(today,reader):
    result={}
    for kind,code in TFF.items():
        url="https://publicreporting.cftc.gov/resource/"+code+".json?"+urlencode(
            {"cftc_contract_market_code":"041741","$limit":5000,"$order":"report_date_as_yyyy_mm_dd DESC"})
        try:
            p=json.loads(reader(url))
            if not isinstance(p,list) or len(p)>=5000:raise ValueError("TFF response invalid/truncated")
            days=[]
            for r in p:
                d=date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
                if r["cftc_contract_market_code"]!="041741" or d>today:raise ValueError("TFF identity/date")
                days.append(d)
            result[kind]=dict(status="OBSERVED" if days and (today-max(days)).days<=13 else "NO_CURRENT_COT_SERIES",
                latest_report_date=str(max(days)) if days else None,count=len(days),source_url=url,upstream_id="CFTC")
        except Exception as exc:result[kind]=dict(status="UNAVAILABLE",source_url=url,error=str(exc),upstream_id="CFTC")
    return dict(status="OBSERVED" if any(v["status"]=="OBSERVED" for v in result.values()) else
        "NO_CURRENT_COT_SERIES" if all(v["status"]=="NO_CURRENT_COT_SERIES" for v in result.values()) else "UNAVAILABLE",
        source="CFTC TFF",upstream_id="CFTC",reports=result,proxy_used=False,
        caveat="report availability only; TFF categories are not Legacy net noncommercial positions")
