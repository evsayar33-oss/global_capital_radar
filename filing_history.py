"""Monthly filing evidence and sparse daily archive; never production inputs."""
import calendar
import hashlib
import json
import os
import re
import time
import subprocess
import html as html_lib
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from source_recovery import Page
from secondary_sources import number
from adaptive_evaluation import atomic

ROOT=Path(__file__).resolve().parent
CIKS={"USO":"1327068","CPER":"1479247"}
NAMES={"USO":"United States Oil Fund, LP","CPER":"United States Copper Index Fund"}
ETFIQ="https://etfiq.com/data/flows/funds/"
SEC="https://www.sec.gov/Archives/edgar/data/"
ROLE="MONTHLY_RESEARCH_ONLY_NO_DAILY_INTERPOLATION"

def month_end(m):
    d=date.fromisoformat(m+"-01")
    return date(d.year,d.month,calendar.monthrange(d.year,d.month)[1])

def parse_nport(p,today):
    if p.get("schemaVersion")!=3 or p.get("ticker")!="QQQ" or p.get("cite",{}).get("publisher")!="ETFIQ":
        raise ValueError("ETFIQ identity")
    out={}
    for r in p.get("monthly",[]):
        if r.get("src")!="nport" or r.get("scope")!="fund" or r.get("form") not in ("NPORT-P","NPORT-P/A"):continue
        m=r["m"];end=month_end(m);filed=date.fromisoformat(r["filed"])
        if not end<=filed<=today or not re.fullmatch(r"\d{10}-\d{2}-\d{6}",r["accession"]):
            raise ValueError("NPORT period/filing identity")
        a,b,v=r.get("in"),r.get("out"),r.get("flow")
        if not all(number(x) for x in (a,b,v)) or a<0 or b>0 or abs(a+b-v)>1:
            raise ValueError("NPORT flow identity")
        if m in out:raise ValueError("duplicate month")
        out[m]=dict(symbol="QQQ",month=m,period_end=str(end),filed_date=str(filed),
            available_from_date=str(filed+timedelta(days=1)),accession=r["accession"],form=r["form"],
            inflow_usd=a,outflow_usd=b,net_flow_usd=v,source="ETFIQ / SEC N-PORT",
            source_url=ETFIQ+"qqq.json",attribution="ETFIQ (etfiq.com)",role=ROLE,
            historical_vintage_complete=False,publication_intraday_verified=False)
    return out

def usd(s):
    s=re.sub(r"[\s,$]","",s).replace("−","-")
    if s in ("—","–","-"):return 0
    if s.startswith("(") and s.endswith(")"):s="-"+s[1:-1]
    if not re.fullmatch(r"-?\d+",s):raise ValueError("invalid USD")
    return int(s)

def parse_uscf(html,symbol,filed,accession,url,today):
    t=Page(html).text
    pat=re.escape(NAMES[symbol])+r"\s+Monthly Account Statement\s+For the Month Ended\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+(.*?)\s+To the (?:Limited Partners|Shareholders) of"
    matches=list(re.finditer(pat,t,re.I))
    if len(matches)!=1:raise ValueError("exact fund section missing/ambiguous")
    end=datetime.strptime(matches[0][1],"%B %d, %Y").date()
    if end!=month_end(end.strftime("%Y-%m")) or not end<=filed<=today:raise ValueError("statement date")
    block=matches[0][2]
    label="Statement of Changes in Net Asset Value"
    if block.count(label)!=1:raise ValueError("NAV statement missing/ambiguous")
    block=block.split(label,1)[1]
    amount=r"(\(?\s*[-−]?\s*\d[\d,]*\s*\)?|[—–-])"
    def field(label,optional=False):
        m=re.findall(label+r"\s*\$?\s*"+amount,block,re.I)
        if not m and optional and not re.search(label,block,re.I):return None
        if len(m)!=1:raise ValueError("missing/ambiguous field "+label)
        return usd(m[0])
    start=field(r"Net Asset Value Beginning of Month\s+\d{1,2}/\d{1,2}/\d{2,4}")
    ending=field(r"Net Asset Value End of Month")
    income=field(r"Net Income\s*\(Loss\)")
    add=field(r"Additions(?:\s*\([\d,]+\s+Shares\))?",True)
    withdraw=field(r"Withdrawals(?:\s*\(\s*\(?[\d,]+\)?\s+Shares\))?",True)
    a=add if add is not None else 0;b=withdraw if withdraw is not None else 0
    if start<=0 or ending<=0 or a<0 or b>0 or abs(start+income+a+b-ending)>1:
        raise ValueError("NAV accounting reconciliation")
    return dict(symbol=symbol,month=end.strftime("%Y-%m"),period_end=str(end),filed_date=str(filed),
        available_from_date=str(filed+timedelta(days=1)),accession=accession,form="8-K Exhibit 99.1",
        inflow_usd=a,outflow_usd=b,net_flow_usd=a+b,start_aum_usd=start,end_aum_usd=ending,
        net_income_usd=income,flow_aum_pct=100*(a+b)/start,omitted_additions=add is None,
        omitted_withdrawals=withdraw is None,source="SEC / USCF monthly account statement",
        source_url=url,source_sha256=hashlib.sha256(html.encode()).hexdigest(),role=ROLE,
        historical_vintage_complete=False,publication_intraday_verified=False)

def sec_read(url):
    time.sleep(.3)
    with urlopen(Request(url,headers={"User-Agent":os.getenv("SEC_USER_AGENT") or
        "Global Capital Radar research https://github.com/evsayar33-oss/global_capital_radar",
        "Accept-Encoding":"identity"}),timeout=12) as r:data=r.read(3_000_001)
    if len(data)>3_000_000:raise ValueError("SEC body too large")
    return data.decode("utf-8",errors="replace")

ISSUER_PDF_ROOT="https://secure.alpsinc.com/MarketingAPI/api/v1/Content/uscfinvestments/"
ISSUER_PDF_STEM={"USO":"united-states-oil-fund","CPER":"united-states-commodity-index-fund"}

def pdf_download(url):
    # Public issuer document endpoint, not a proxy for EDGAR.
    time.sleep(.25)
    with urlopen(Request(url,headers={"User-Agent":"Global Capital Radar research",
        "Accept":"application/pdf"}),timeout=12) as r:
        if not r.geturl().startswith(ISSUER_PDF_ROOT):raise ValueError("unexpected issuer redirect")
        raw=r.read(5_000_001)
    if len(raw)>5_000_000 or not raw.startswith(b"%PDF-"):raise ValueError("invalid issuer PDF")
    return raw

def parse_issuer_pdf_text(text,symbol,expected_end,url,today,now,raw_sha256):
    # PDF cover contains the original issuer issue date, not necessarily the
    # SEC filed date. Do not invent accession or a filing timestamp.
    t=" ".join(text.split())
    dates=set(re.findall(r"\bOn\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s*,?\s+.{0,400}?\bissued\s+(?:its|their)\s+monthly account statements?\b",t,re.I))
    issued=None
    if len(dates)==1:
        issued=datetime.strptime(next(iter(dates)),"%B %d, %Y").date()
        if not expected_end<=issued<=today:raise ValueError("issuer issue date invalid")
    elif len(dates)>1:raise ValueError("conflicting issuer issue dates")
    # Use today's first-observed date solely to validate the statement when
    # the cover has no unambiguous issue date; never backdate availability.
    r=parse_uscf(html_lib.escape(t),symbol,issued or today,None,url,today)
    if r["period_end"]!=str(expected_end):raise ValueError("issuer document month mismatch")
    r.update(source="USCF / ALPS public issuer report",source_sha256=raw_sha256,
        accession=None,filed_date=None,issued_date=str(issued) if issued else None,
        available_from_date=str((issued or today)+timedelta(days=1)),
        availability_basis="issuer cover issue date, not SEC timestamp" if issued else "first observed; historical issue date unknown",
        first_observed_timestamp=now.isoformat(),form="issuer monthly account statement")
    return r

def issuer_pdf(symbol,end,today,now,reader=pdf_download):
    url=ISSUER_PDF_ROOT+ISSUER_PDF_STEM[symbol]+"-8-kms-"+end.strftime("%Y%m%d")+".pdf"
    raw=reader(url)
    p=subprocess.run(["pdftotext","-layout","-","-"],input=raw,capture_output=True,timeout=20,check=True)
    return parse_issuer_pdf_text(p.stdout.decode("utf-8"),symbol,end,url,today,now,hashlib.sha256(raw).hexdigest())

def issuer_months(today,smoke):
    end=today.replace(day=1)-timedelta(days=1)
    ends=[]
    for _ in range(4 if smoke else 24):
        ends.append(end)
        end=end.replace(day=1)-timedelta(days=1)
    # An independently verified public document, not fixture data, is also
    # checked in smoke if the most recent month is not yet posted.
    if smoke and date(2025,9,30) not in ends:ends.append(date(2025,9,30))
    return ends

def discover(symbol,today,reader,limit):
    cik=CIKS[symbol]
    p=json.loads(reader("https://data.sec.gov/submissions/CIK"+cik.zfill(10)+".json"))
    if str(p["cik"]).lstrip("0")!=cik:raise ValueError("CIK mismatch")
    r=p["filings"]["recent"];out=[]
    for form,items,acc,ds in zip(r["form"],r["items"],r["accessionNumber"],r["filingDate"],strict=True):
        if form!="8-K" or "7.01" not in items or "9.01" not in items:continue
        filed=date.fromisoformat(ds)
        if not today-timedelta(days=730)<=filed<=today:continue
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}",acc):raise ValueError("accession")
        out.append((acc,filed))
        if len(out)>=limit:break
    return out

def exhibit(s):
    matches=[]
    for doc in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>",s,re.I|re.S):
        typ=re.search(r"<TYPE>\s*([^\r\n<]+)",doc,re.I)
        if not typ or typ[1].strip().upper()!="EX-99.1":continue
        m=re.search(r"<TEXT>(.*?)</TEXT>",doc,re.I|re.S)
        if m:matches.append(m[1])
    if len(matches)!=1:raise ValueError("unique EX-99.1 missing")
    return matches[0]

def sparse(p,symbol,today):
    if p.get("schemaVersion")!=3 or p.get("ticker")!=symbol or p.get("cite",{}).get("publisher")!="ETFIQ":raise ValueError("identity")
    end=date.fromisoformat(p["asOf"])
    if end>today:raise ValueError("future archive")
    out={};seen=set()
    for r in p["daily"]:
        d=date.fromisoformat(r["d"]);prior=date.fromisoformat(r["navDate"])
        if d in seen or d>end or not number(r.get("flow")):raise ValueError("invalid daily")
        seen.add(d)
        if not 0<(d-prior).days<=5 or d.weekday()>=5 or prior.weekday()>=5 or r.get("held") or r.get("roundTrip") or r.get("status") not in (None,"ok"):continue
        out[str(d)]=dict(symbol=symbol,source_date=str(d),prior_nav_date=str(prior),flow_usd=r["flow"],
            source="ETFIQ (etfiq.com)",source_url=ETFIQ+symbol.lower()+".json",
            role="SPARSE_ARCHIVE_NOT_CONTIGUOUS_OR_PIT_VERIFIED")
    return out

def merge(old,new,now,fields):
    for k,r in new.items():
        first=old.setdefault(k,dict(r,first_seen_at=now.isoformat()))
        if any(first.get(f)!=r.get(f) for f in fields):
            revisions=first.setdefault("revisions",[])
            if not any(all(x.get(f)==r.get(f) for f in fields) for x in revisions):
                revisions.append(dict(r,first_seen_at=now.isoformat()))
    return old

def run(root,today,now,reader,sec_reader=sec_read,smoke=False):
    folder=root/"history/native_research/extended_history"
    result=dict(evaluated_at=now.isoformat(),policy=ROLE,symbols={})
    for sym in ("QQQ","CPER","USO"):
        dp=folder/("daily_"+sym+".json");mp=folder/("monthly_"+sym+".json")
        daily=json.loads(dp.read_text()) if dp.exists() else {}
        monthly=json.loads(mp.read_text()) if mp.exists() else {}
        new_daily={};new_month={};errors=[]
        try:
            p=json.loads(reader(ETFIQ+sym.lower()+".json"))
            new_daily=sparse(p,sym,today)
            if sym=="QQQ":new_month=parse_nport(p,today)
        except Exception as exc:errors.append("ETFIQ: "+str(exc))
        if sym in CIKS:
            try:
                records=discover(sym,today,sec_reader,6 if smoke else 30)
                existing={r.get("accession") for r in monthly.values() if r.get("accession")}
                for acc,filed in records:
                    if not smoke and acc in existing:continue
                    url=SEC+CIKS[sym]+"/"+acc.replace("-","")+"/"+acc+".txt"
                    try:
                        r=parse_uscf(exhibit(sec_reader(url)),sym,filed,acc,url,today)
                        # Preserve earlier filings instead of treating newer revision as first.
                        if r["month"] not in new_month or r["filed_date"]<new_month[r["month"]]["filed_date"]:
                            new_month[r["month"]]=r
                    except HTTPError as exc:
                        errors.append("SEC HTTP "+str(exc.code))
                        if exc.code in (403,429):break
                    except Exception as exc:errors.append(acc+": "+str(exc))
            except Exception as exc:errors.append("SEC discovery: "+str(exc))
            # Issuer and SEC are two delivery channels for the same underlying
            # filing, not independent corroboration. Prefer exact SEC dates.
            for end in issuer_months(today,smoke):
                m=end.strftime("%Y-%m")
                if m in new_month or (m in monthly and not smoke):continue
                try:
                    r=issuer_pdf(sym,end,today,now)
                    new_month[m]=r
                    if smoke:break
                except HTTPError as exc:
                    errors.append("issuer PDF "+m+" HTTP "+str(exc.code))
                    if exc.code in (403,429):break
                except Exception as exc:errors.append("issuer PDF "+m+": "+str(exc))
        merge(daily,new_daily,now,("flow_usd","prior_nav_date"))
        merge(monthly,new_month,now,("net_flow_usd","inflow_usd","outflow_usd","accession","filed_date","issued_date"))
        if not smoke:
            folder.mkdir(parents=True,exist_ok=True);atomic(dp,daily);atomic(mp,monthly)
        result["symbols"][sym]=dict(sparse_daily_count=len(daily),live_daily_count=len(new_daily),
            daily_start=min(daily) if daily else None,daily_end=max(daily) if daily else None,
            monthly_count=len(monthly),live_monthly_count=len(new_month),
            monthly_start=min(monthly) if monthly else None,monthly_end=max(monthly) if monthly else None,
            errors=errors[:20],daily_history_contiguous=False,production_eligible=False)
    if not smoke:atomic(folder/"results.json",result)
    return result

def main():
    import sys
    from radar import read
    from zoneinfo import ZoneInfo
    now=datetime.now(timezone.utc);today=now.astimezone(ZoneInfo("America/New_York")).date()
    smoke="--smoke" in sys.argv
    r=run(ROOT,today,now,read,smoke=smoke)
    print("EXTENDED_HISTORY "+json.dumps(r,ensure_ascii=False),flush=True)
    q=r["symbols"]["QQQ"]
    return 0 if q["live_monthly_count"]>=12 and all(r["symbols"][s]["live_daily_count"]>0 for s in ("QQQ","CPER","USO")) and all(r["symbols"][s]["live_monthly_count" if smoke else "monthly_count"]>0 for s in CIKS) else 1

if __name__=="__main__":raise SystemExit(main())
