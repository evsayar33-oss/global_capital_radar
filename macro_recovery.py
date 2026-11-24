"""Date-vintage and contract-specific context. Never production confirmation."""
import csv
import hashlib
import io
import json
import math
import re
from datetime import date,datetime,timedelta,timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from secondary_sources import number

NY=ZoneInfo("America/New_York")
ALFRED_CSV="https://alfred.stlouisfed.org/graph/alfredgraph.csv"
YAHOO="https://query1.finance.yahoo.com/v8/finance/chart/"
TREASURY="https://www.treasurydirect.gov/TA_WS/securities/auctioned"
MONTH_CODES="FGHJKMNQUVXZ"
MONTH_NAMES=("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()

def alfred_csv(series,asof,reader):
    if not re.fullmatch(r"[A-Z0-9_]+",series):raise ValueError("invalid series")
    # Request only a recent date window; graph CSV is a context snapshot,
    # not the full 400-day API backfill. Retry a shorter window on transient
    # transport failures, never on access denial or invalid vintage content.
    from urllib.error import HTTPError, URLError
    for days in (31,14):
        url=ALFRED_CSV+"?"+urlencode(dict(id=series,vintage_date=str(asof),
                           cosd=str(asof-timedelta(days=days)),coed=str(asof)))
        try:
            raw=reader(url)
            break
        except HTTPError as exc:
            if days==14 or exc.code not in (408,429,500,502,503,504):raise
        except (TimeoutError,URLError):
            if days==14:raise
    rows=csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
    field=series+"_"+asof.strftime("%Y%m%d")
    if rows.fieldnames!=["observation_date",field]:
        raise ValueError("ALFRED CSV vintage header mismatch")
    observations=[];seen=set()
    for r in rows:
        if None in r or r[field] is None:raise ValueError("ALFRED CSV row width")
        d=date.fromisoformat(r["observation_date"])
        if d>asof or d in seen:raise ValueError("ALFRED future/duplicate date")
        seen.add(d)
        if r[field].strip() in ("","."):continue
        v=float(r[field])
        if not number(v):raise ValueError("ALFRED nonfinite")
        observations.append(dict(observation_date=str(d),value=v,vintage_date=str(asof)))
    if not observations or (asof-date.fromisoformat(max(x["observation_date"] for x in observations))).days>7:
        raise ValueError("ALFRED no recent observation")
    return dict(status="OBSERVED_DATE_VINTAGE",series=series,vintage=str(asof),
                observations=observations,source="ALFRED graph CSV",source_url=url,
                source_sha256=sha(raw),requested_window_days=days,publication_intraday_verified=False,
                realtime_interval_verified=False,role="DATE_VINTAGE_RESEARCH_ONLY")

def delivery_month(d,offset):
    i=d.year*12+d.month-1+offset
    return i//12,i%12+1

def contract_pair(day):
    # NYMEX CL normally expires three exchange business days before 25th
    # of preceding month. Avoid uncertain holiday/roll interval entirely.
    # On day 23 or later the next delivery month has already expired.
    if 15<=day.day<=22:
        raise ValueError("roll interval requires official expiration calendar")
    offset=1 if day.day<15 else 2
    return [delivery_month(day,offset+i) for i in range(2)]

def contract_symbol(ym):
    y,m=ym
    return "CL"+MONTH_CODES[m-1]+f"{y%100:02d}.NYM"

def contract_closes(ym,today,reader):
    sym=contract_symbol(ym)
    url=YAHOO+sym+"?range=10d&interval=1d"
    raw=reader(url);p=json.loads(raw)["chart"]
    if p.get("error") or len(p.get("result") or [])!=1:raise ValueError("contract chart unavailable")
    r=p["result"][0];m=r["meta"]
    if (m.get("symbol")!=sym or m.get("instrumentType")!="FUTURE" or
        m.get("currency")!="USD" or m.get("exchangeName")!="NYM" or
        not re.search(r"\bCrude Oil "+MONTH_NAMES[ym[1]-1]+r"\s+"+f"{ym[0]%100:02d}"+r"\b",m.get("longName",""),re.I)):
        raise ValueError("contract identity/currency mismatch")
    out={}
    for ts,v in zip(r["timestamp"],r["indicators"]["quote"][0]["close"],strict=True):
        d=datetime.fromtimestamp(ts,NY).date()
        if d>today or d in out:raise ValueError("future/duplicate contract day")
        if d==today:continue
        if v is not None and number(v):out[d]=float(v)
    return out,dict(contract=sym,delivery_month=f"{ym[0]:04d}-{ym[1]:02d}",
                    source_url=url,source_sha256=sha(raw))

def wti_pair(now,reader):
    today=now.astimezone(NY).date()
    # Select by the last possible completed session; then verify that the
    # actual matched observation date has the identical unambiguous pair.
    pair=contract_pair(today-timedelta(days=1))
    a,am=contract_closes(pair[0],today,reader);b,bm=contract_closes(pair[1],today,reader)
    common=sorted(a.keys()&b.keys())
    if not common:raise ValueError("no matched contract close")
    d=common[-1]
    if (today-d).days>4 or contract_pair(d)!=pair or max(a)!=d or max(b)!=d:
        raise ValueError("stale/unsynchronized/roll contract closes")
    return dict(status="OBSERVED_DELAYED_CLOSE_PAIR",source="Yahoo Finance NYMEX contract charts",
                source_date=str(d),front_contract=am,next_contract=bm,front_close_usd_per_barrel=a[d],
                next_close_usd_per_barrel=b[d],front_minus_next_usd_per_barrel=a[d]-b[d],
                official_settlement_verified=False,roll_calendar_verified=False,
                role="PRICE_DERIVED_CONTEXT_ONLY",production_proxy_allowed=False)

USL_HOLDINGS="https://www.uscfinvestments.com/holdings/usl"
TREASURY_REAL="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/all/"

def treasury_real_yield(today,reader):
    """Treasury's current publication, never an ALFRED historical vintage."""
    cutoff=today-timedelta(days=1)
    ym=cutoff.strftime("%Y%m")
    url=TREASURY_REAL+ym+"?"+urlencode({"_format":"csv","field_tdr_date_value_month":ym,"page":"","type":"daily_treasury_real_yield_curve"})
    raw=reader(url);rows=csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
    if not rows.fieldnames or not {"Date","10 YR"}<=set(rows.fieldnames):
        raise ValueError("Treasury real yield CSV identity")
    values={}
    for r in rows:
        d=datetime.strptime(r["Date"],"%m/%d/%Y").date()
        if d>today or d.strftime("%Y%m")!=ym or d in values:
            raise ValueError("Treasury curve date mismatch")
        if d>cutoff or r["10 YR"].strip() in ("","N/A","."):continue
        v=float(r["10 YR"])
        if not number(v):raise ValueError("invalid Treasury real yield")
        values[d]=v
    if not values or (today-max(values)).days>7:raise ValueError("Treasury real yield stale")
    d=max(values)
    return dict(status="OBSERVED_CURRENT_PUBLICATION",source="US Treasury daily par real yield curve",
                source_url=url,source_sha256=sha(raw),source_date=str(d),real_yield_10y_pct=values[d],
                historical_vintage_verified=False,publication_intraday_verified=False,
                role="CURRENT_MACRO_CONTEXT_ONLY",production_proxy_allowed=False)

def parse_usl_pair(html,today):
    from source_recovery import Page
    p=Page(html);t=p.text
    if not re.search(r"\bUnited States 12 Month Oil Fund\b",t,re.I):raise ValueError("USL identity")
    matches=set(re.findall(r"\bHoldings\s+As of\s+(\d{1,2}/\d{1,2}/\d{4})",t,re.I))
    if len(matches)!=1:raise ValueError("USL holdings date ambiguous")
    day=datetime.strptime(next(iter(matches)),"%m/%d/%Y").date()
    if not 0<(today-day).days<=4:raise ValueError("USL stale or unfinished session")
    pair=contract_pair(day)
    found={}
    for table in p.tables:
        if not any([x.strip().lower() for x in row]==["security","quantity","price","market value","ticker"] for row in table):
            continue
        for row in table:
            if len(row)!=5:continue
            a=re.fullmatch(r"WTI CRUDE FUTURE\s+([A-Za-z]{3})(\d{2})",row[0],re.I)
            if not a:continue
            mon=next((i+1 for i,v in enumerate(MONTH_NAMES) if v.lower()==a[1].lower()),None)
            if mon is None:raise ValueError("USL contract month")
            ym=(2000+int(a[2]),mon)
            if ym not in pair:continue
            sym=contract_symbol(ym)
            # USCF publishes a one-digit expiry code; the full year comes
            # from the security label. Both must agree.
            if row[4].strip()!=sym[:3]+str(ym[0]%10):raise ValueError("USL ticker mismatch")
            qty=int(row[1].replace(",",""))
            px=float(row[2].replace(",",""))
            mv=float(row[3].replace(",","").replace("$",""))
            if qty<=0 or not all(number(x) for x in (px,mv)) or abs(qty*1000*px-mv)>.05:
                raise ValueError("USL contract notional reconciliation")
            if ym in found:raise ValueError("duplicate USL contract")
            found[ym]=dict(contract=sym,delivery_month=f"{ym[0]:04d}-{ym[1]:02d}",
                           contracts=qty,valuation_usd_per_barrel=px,market_value_usd=mv)
    if any(ym not in found for ym in pair):raise ValueError("USL dated pair unavailable")
    a,b=[found[ym] for ym in pair]
    return dict(status="OBSERVED_ISSUER_VALUATION_PAIR",source="USCF USL published holdings",
                source_url=USL_HOLDINGS,source_date=str(day),front_contract=a,next_contract=b,
                front_valuation_usd_per_barrel=a["valuation_usd_per_barrel"],
                next_valuation_usd_per_barrel=b["valuation_usd_per_barrel"],
                front_minus_next_usd_per_barrel=a["valuation_usd_per_barrel"]-b["valuation_usd_per_barrel"],
                official_settlement_verified=False,roll_calendar_verified=False,
                role="ISSUER_VALUATION_CONTEXT_ONLY",production_proxy_allowed=False)

def usl_pair(now):
    from runner_sources import verified_page
    r,mode=verified_page(USL_HOLDINGS,lambda html:parse_usl_pair(html,now.astimezone(NY).date()),
                         'table')
    return dict(r,transport=mode)

def treasury_auction(today,reader):
    url=TREASURY+"?"+urlencode(dict(type="Bill",term="13-Week",format="json"))
    raw=reader(url);p=json.loads(raw)
    if not isinstance(p,list):raise ValueError("Treasury auction response")
    rows={}
    for r in p:
        if r.get("securityType")!="Bill" or r.get("securityTerm")!="13-Week":continue
        if r.get("cashManagementBill")!="No":continue
        ds=r.get("competitiveAuctionCloseDate","")
        if not ds:continue
        d=date.fromisoformat(ds[:10])
        if d>=today:continue # require a completed prior date; no intraday inference
        if not r.get("highRate") or not r.get("bidToCoverRatio"):continue
        v=float(r["highRate"]);bt=float(r["bidToCoverRatio"])
        if not number(v) or not number(bt) or bt<=0:raise ValueError("invalid auction results")
        issue=date.fromisoformat(r["issueDate"][:10]);maturity=date.fromisoformat(r["maturityDate"][:10])
        if not d<=issue<maturity or not 85<=(maturity-issue).days<=96:
            raise ValueError("13-week auction maturity")
        cusip=r.get("cusip","")
        if not re.fullmatch(r"[A-Z0-9]{9}",cusip):raise ValueError("auction CUSIP")
        item=dict(auction_date=str(d),cusip=cusip,issue_date=str(issue),maturity_date=str(maturity),
                  high_discount_rate_pct=v,bid_to_cover_ratio=bt)
        if d in rows and rows[d]!=item:raise ValueError("ambiguous auction date")
        rows[d]=item
    if not rows or (today-max(rows)).days>14:raise ValueError("no recent completed 13-week auction")
    last=rows[max(rows)]
    return dict(status="OBSERVED_AUCTION_CONTEXT",source="US TreasuryDirect",
                source_url=url,source_sha256=sha(raw),source_date=last["auction_date"],**last,
                implied_final_settlement_index=100-last["high_discount_rate_pct"],
                actual_tbf3_settlement_verified=False,cot_verified=False,
                role="CASH_AUCTION_CONTEXT_NOT_FUTURES_POSITION_OR_QUOTE",
                production_proxy_allowed=False)

def issuer_revision(history,record,seen):
    """Record late creation availability even if NAV page hash is unchanged."""
    fields=("shares","nav_usd","reported_aum_usd","creation_status","net_created_shares",
            "estimated_creation_usd","creation_source_sha256")
    first=history.setdefault(record["source_date"],dict(record,first_seen_at=seen.isoformat()))
    versions=[first]+first.get("revisions",[])
    if any(first.get(k)!=record.get(k) for k in fields):
        if not any(all(v.get(k)==record.get(k) for k in fields) for v in versions):
            first.setdefault("revisions",[]).append(dict(record,first_seen_at=seen.isoformat()))
    return history

def first_creation(record):
    # First usable published creation observation, not the latest revision.
    for r in [record]+record.get("revisions",[]):
        if r.get("status")=="OBSERVED" and r.get("creation_status")=="OBSERVED":
            return r
    return None

def main():
    from radar import read
    now=datetime.now(timezone.utc);today=now.astimezone(NY).date()
    jobs={"ALFRED":lambda:alfred_csv("DFII10",today-timedelta(days=1),read),
          "WTI_CLOSE_PAIR":lambda:wti_pair(now,read),
          "TBILL_AUCTION":lambda:treasury_auction(today,read),
          "TREASURY_REAL_YIELD":lambda:treasury_real_yield(today,read),
          "WTI_USL_PAIR":lambda:usl_pair(now)}
    results={}
    for k,fn in jobs.items():
        try:results[k]=fn()
        except Exception as exc:results[k]=dict(status="UNAVAILABLE",error=type(exc).__name__+": "+str(exc))
        print("MACRO_RESULT "+json.dumps(dict(key=k,**{a:b for a,b in results[k].items() if a!="observations"}),ensure_ascii=False),flush=True)
    # WTI has a deliberate no-observation roll window. Require ALFRED and
    # auction always; require contract close pair when outside that window.
    try:contract_pair(today-timedelta(days=1));need_wti=True
    except ValueError:need_wti=False
    vintage=results["ALFRED"]["status"]=="OBSERVED_DATE_VINTAGE"
    current=results["TREASURY_REAL_YIELD"]["status"]=="OBSERVED_CURRENT_PUBLICATION"
    close=results["WTI_CLOSE_PAIR"]["status"]=="OBSERVED_DELAYED_CLOSE_PAIR"
    valuation=results["WTI_USL_PAIR"]["status"]=="OBSERVED_ISSUER_VALUATION_PAIR"
    auction=results["TBILL_AUCTION"]["status"]=="OBSERVED_AUCTION_CONTEXT"
    # Two capabilities are intentionally different: contextual continuity
    # versus true point-in-time history and official settlement.
    # Require real alternative observations; never label fallback as vintage.
    context=(vintage or current) and auction and (not need_wti or close or valuation)
    print("MACRO_CAPABILITIES "+json.dumps(dict(context_continuity=context,
          true_alfred_vintage=vintage,dated_wti_close=close,issuer_wti_valuation=valuation,
          treasury_current=current,official_wti_settlement=False)),flush=True)
    return 0 if context else 1

if __name__=="__main__":raise SystemExit(main())
