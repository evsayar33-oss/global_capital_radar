"""Independent, source-native research lane. Does not change production decisions."""
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from adaptive_flow import build_features, record, VERSION, BUY, REDUCE, WAIT
from adaptive_evaluation import atomic, collect, evaluate_tracks
from evaluate_rotation import prices
from horizons import analyze, interpret, PERIODS
from radar import read
from rotation import ASSETS, CODES, cot_with_source
from secondary_sources import cot_api, parse_etfiq, ETFIQ_URL, number
from native_adapters import okx_crypto, shfe_copper, tbf3
from source_recovery import shfe_cn, capture_issuer, estimate_adjacent, tff_tbf3
from runner_recovery import issuer_verified, shfe_verified
from macro_recovery import alfred_csv, wti_pair, treasury_auction, issuer_revision

ROOT=Path(__file__).resolve().parent
NY=ZoneInfo("America/New_York")
FLOW_URL="https://etfiq.com/data/flows/funds/"
ALFRED_URL="https://api.stlouisfed.org/fred/series/observations"
CFTC_TBF3="041741"


def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()


def parse_history(p,symbol,today,calendar):
    """ETFIQ schema 3, USD, daily-only; no monthly-to-daily interpolation."""
    if (p.get("schemaVersion")!=3 or p.get("ticker")!=symbol or
        p.get("cite",{}).get("publisher")!="ETFIQ"):
        raise ValueError("ETFIQ schema/symbol/publisher mismatch")
    end=date.fromisoformat(p["asOf"])
    if end>today or (today-end).days>7:
        raise ValueError("ETFIQ fund history stale/future")
    raw={}
    seen=set()
    skipped=[]
    for r in p["daily"]:
        d=date.fromisoformat(r["d"])
        prior=date.fromisoformat(r["navDate"])
        if d in seen:
            raise ValueError("duplicate flow date")
        seen.add(d)
        if d>end or not number(r.get("flow")):
            raise ValueError("invalid flow value/date")
        # If cash calendar is missing a session, do not infer a zero.
        earlier=[x for x in calendar if x<d]
        if (d not in calendar or not earlier or prior!=max(earlier)
            or r.get("held") or r.get("roundTrip") or r.get("status") not in (None,"ok")):
            skipped.append(str(d))
            continue
        raw[d]=r["flow"]
    if len(raw)<5 or max(raw)!=end:
        raise ValueError("insufficient/stale validated daily observations")
    # Use only the contiguous suffix of the verified US session calendar.
    suffix=[]
    for d in reversed([d for d in calendar if d<=end]):
        if d not in raw:
            break
        suffix.append(d)
    if len(suffix)<5:
        raise ValueError("insufficient contiguous daily observations")
    raw={d:raw[d] for d in sorted(suffix)}
    aum={}
    for w in p.get("windows",{}).values():
        if not isinstance(w,dict) or not number(w.get("startAssets")) or w["startAssets"]<=0:
            continue
        if w.get("startAsOf") and w.get("startBasis") in ("daily","aum.json"):
            d=date.fromisoformat(w["startAsOf"])
            if d<=end:
                if d in aum and aum[d]!=w["startAssets"]:
                    raise ValueError("conflicting AUM within source")
                aum[d]=w["startAssets"]
    return raw,aum,dict(source="ETFIQ",source_url=FLOW_URL+symbol.lower()+".json",
        source_date=str(end),coverage_start=str(min(raw)),coverage_end=str(max(raw)),
        daily_count=len(raw),skipped_count=len(skipped),units="USD",
        aum_basis="ETFIQ-derived; not independently verified",source_digest=digest(p),
        historical_publication_time_verified=False,license="ETFIQ computed, attribution required",
        role="INDEPENDENT_SHADOW_NOT_PRODUCTION")


def archive(root,kind,now,obj):
    folder=root/kind
    folder.mkdir(parents=True,exist_ok=True)
    path=folder/(now.strftime("%Y%m%dT%H%M%S%fZ")+"-"+digest(obj)[:12]+".json")
    atomic(path,obj)
    return path


def alfred_vintage(series,asof,key,reader=read):
    if not key:
        return alfred_csv(series,asof,reader)
    query=urlencode(dict(series_id=series,api_key=key,file_type="json",
                         realtime_start=str(asof),realtime_end=str(asof),
                         observation_start=str(asof-timedelta(days=400)),observation_end=str(asof)))
    try:
        p=json.loads(reader(ALFRED_URL+"?"+query))
        observations=[]
        for r in p["observations"]:
            d=date.fromisoformat(r["date"])
            start=date.fromisoformat(r["realtime_start"])
            end=date.fromisoformat(r["realtime_end"])
            if d>asof or not start<=asof<=end:
                raise ValueError("ALFRED vintage violation")
            if r["value"]!=".":
                v=float(r["value"])
                if not number(v):
                    raise ValueError("ALFRED nonfinite")
                observations.append(dict(observation_date=str(d),value=v,realtime_start=str(start),realtime_end=str(end)))
        return dict(status="OBSERVED_DATE_VINTAGE" if observations else "UNAVAILABLE",
                    series=series,vintage=str(asof),observations=observations,
                    publication_intraday_verified=False)
    except Exception as exc:
        # Do not log the URL: it contains the API key.
        return dict(status="UNAVAILABLE",series=series,vintage=str(asof),error=type(exc).__name__,observations=[])


def crypto(symbol,now,reader=read):
    # Binance USD-M. The funding interval is inferred only from adjacent
    # actual settlement timestamps, not a fixed 8-hour assumption.
    root="https://fapi.binance.com/fapi/v1/"
    p=json.loads(reader(root+"fundingRate?"+urlencode(dict(symbol=symbol,limit=1000))))
    rows=[]
    seen=set()
    for r in sorted(p,key=lambda r:r["fundingTime"]):
        t=datetime.fromtimestamp(r["fundingTime"]/1000,timezone.utc)
        v=float(r["fundingRate"])
        if r["symbol"]!=symbol or t>now or t in seen or not number(v):
            raise ValueError("funding identity/time/value")
        seen.add(t)
        hours=(t-rows[-1][0]).total_seconds()/3600 if rows else None
        rows.append((t,v,hours))
    if not rows or (now-rows[-1][0]).total_seconds()>86400:
        raise ValueError("stale funding")
    mark=json.loads(reader(root+"premiumIndex?"+urlencode(dict(symbol=symbol))))
    checked_at=max(now,datetime.now(timezone.utc)) if reader is read else now
    t=datetime.fromtimestamp(mark["time"]/1000,timezone.utc)
    mp,ip=float(mark["markPrice"]),float(mark["indexPrice"])
    if mark["symbol"]!=symbol or not 0<mp or not 0<ip or not number(mp) or not number(ip) or not 0<=(checked_at-t).total_seconds()<=900:
        raise ValueError("invalid/stale premium")
    last=rows[-1]
    annual=last[1]*365*24/last[2]*100 if last[2] in (1,2,4,8) else None
    return dict(status="OBSERVED",symbol=symbol,source="Binance USD-M",source_url=root,
                funding_asof=last[0].isoformat(),funding_rate=last[1],
                interval_hours=last[2],annualized_pct=annual,
                basis_pct=100*(mp/ip-1),basis_asof=t.isoformat(),
                history=[dict(time=t.isoformat(),rate=v,interval_hours=h) for t,v,h in rows],
                caveat="annualized latest settlement, not a forecast")


def copper(now):
    """Read the official COMEX report; strict date/units/total checks."""
    import io
    import re
    import xlrd
    from urllib.request import Request,urlopen
    url="https://www.cmegroup.com/delivery_reports/Copper_Stocks.xls"
    with urlopen(Request(url,headers={"User-Agent":"global-capital-radar/2.1"}),timeout=25) as r:
        raw=r.read(4_000_001)
    if len(raw)>4_000_000:
        raise ValueError("oversized copper report")
    book=xlrd.open_workbook(file_contents=raw)
    sh=book.sheet_by_index(0)
    text=" ".join(str(c.value) for row in sh.get_rows() for c in row if c.ctype==xlrd.XL_CELL_TEXT)
    if "COPPER" not in text.upper():
        raise ValueError("wrong metal report")
    unit="short tons" if re.search(r"short\s+tons",text,re.I) else "pounds" if re.search(r"pounds|\blbs\b",text,re.I) else "metric tons" if re.search(r"metric\s+tons",text,re.I) else None
    if unit is None:
        raise ValueError("copper unit unknown")
    dates=[]
    totals=[]
    header=None
    for i in range(sh.nrows):
        row=sh.row(i)
        strings=[str(c.value).strip().upper() for c in row]
        for j,label in enumerate(strings):
            if ("ACTIVITY DATE" in label or "REPORT DATE" in label) and j+1<len(row):
                candidates=row[j+1:]
                for cell in candidates:
                    if cell.ctype==xlrd.XL_CELL_DATE:
                        dates.append(xlrd.xldate_as_datetime(cell.value,book.datemode).date())
                    elif cell.ctype==xlrd.XL_CELL_TEXT:
                        for fmt in ("%m/%d/%Y","%m/%d/%y","%Y-%m-%d"):
                            try: dates.append(datetime.strptime(str(cell.value).strip(),fmt).date()); break
                            except ValueError: pass
            if label in ("TOTAL TODAY","TODAY'S TOTAL","TOTAL STOCKS TODAY"):
                header=j
        if any(x in ("COMBINED TOTAL","GRAND TOTAL","TOTAL COMBINED") for x in strings):
            totals.append(row)
    if not dates or header is None or len(totals)!=1:
        raise ValueError("unrecognized copper worksheet layout")
    day=min(dates)
    cell=totals[0][header]
    if cell.ctype!=xlrd.XL_CELL_NUMBER or not number(cell.value) or cell.value<=0 or not 0<=(now.date()-day).days<=7:
        raise ValueError("copper total/date invalid")
    return dict(status="OBSERVED",source_url=url,source_date=str(day),units=unit,
                combined_stock=cell.value,source_sha256=hashlib.sha256(raw).hexdigest())


def issuer_aum_crosscheck(fund,primary,day):
    """Separate exact-date USD comparison; no inference on unmatched dates."""
    if (fund.get("status")!="OBSERVED" or fund.get("start_aum_date")!=day or
        not number(fund.get("start_aum_usd")) or fund["start_aum_usd"]<=0 or
        not number(primary) or primary<=0):
        return dict(status="UNAVAILABLE",relative_error_pct=None)
    return dict(status="MATCHED_DATE_UNQUALIFIED",relative_error_pct=100*(primary/fund["start_aum_usd"]-1))


def cost_context(spread_pct=None,commission_bps=None,slippage_bps=None):
    # A quoted rolling median spread is not a realized spread or slippage.
    valid=lambda x:number(x) and x>=0
    return dict(observed_median_spread_bps=spread_pct*100 if valid(spread_pct) else None,
                commission_bps=commission_bps if valid(commission_bps) else None,
                slippage_bps=slippage_bps if valid(slippage_bps) else None,
                scenario_roundtrip_bps=[10,30,50],realized_cost_verified=False)


def safe(fn):
    try:return fn()
    except Exception as exc:return dict(status="UNAVAILABLE",error=type(exc).__name__+": "+str(exc))


def main():
    now=datetime.now(timezone.utc)
    today=now.astimezone(NY).date()
    folder=ROOT/"history/native_research"
    folder.mkdir(parents=True,exist_ok=True)
    # Retain immutable first-observed daily AUM evidence; no backdated AUM.
    aum_root=folder/"aum"
    aum_root.mkdir(parents=True,exist_ok=True)
    aum_ledger=aum_root/"etfiq.json"
    legacy=folder/"aum_observations.json"
    prior=aum_ledger if aum_ledger.exists() else legacy
    aum_history=json.loads(prior.read_text()) if prior.exists() else {}
    syms={s for s,_,_ in ASSETS}
    daily=safe(lambda:parse_etfiq(json.loads(read(ETFIQ_URL)),today,syms))
    for sym,r in daily.get("funds",{}).items():
        if r["status"]=="OBSERVED":
            day=r["start_aum_date"]
            entry=dict(value=r["start_aum_usd"],source_date=daily["source_date"],source="ETFIQ",source_url=ETFIQ_URL)
            history=aum_history.setdefault(sym,{})
            first=history.setdefault(day,dict(entry,first_seen=now.isoformat()))
            if first["value"]!=entry["value"]:
                revisions=first.setdefault("revisions",[])
                if not revisions or revisions[-1]["value"]!=entry["value"]:
                    revisions.append(dict(entry,first_seen=now.isoformat(),revision_of=digest({k:v for k,v in first.items() if k!="revisions"})))
    atomic(aum_ledger,aum_history)
    try:
        positions,cot_source=cot_with_source(today)
    except Exception as exc:
        positions,cot_source={},dict(status="UNAVAILABLE",error=str(exc))
    try:
        tbfseries,tbf_data=tbf3(today,read)
    except Exception as exc:
        tbfseries={}
        tbf_data=dict(status="UNAVAILABLE",code=CFTC_TBF3,error=type(exc).__name__+": "+str(exc))
    start=today-timedelta(days=850)
    with ThreadPoolExecutor(max_workers=4) as pool:
        def get_price(sym):
            return sym,safe(lambda:prices(sym,start,today))
        series=dict(pool.map(get_price,sorted(syms)))
    errors={s:b.get("error") for s,b in series.items() if b.get("status")=="UNAVAILABLE"}
    series={s:b for s,b in series.items() if s not in errors}
    calendar=sorted(d for d,v in series.get("SGOV",{}).items() if v)
    previous_path=folder/"results.json"
    previous=json.loads(previous_path.read_text()) if previous_path.exists() else {}
    rows=[]
    def fund(asset):
        sym,name,code=asset
        try:
            p=json.loads(read(FLOW_URL+sym.lower()+".json"))
            raw,aum,meta=parse_history(p,sym,today,calendar)
            for d,r in aum_history.get(sym,{}).items():
                aum.setdefault(date.fromisoformat(d),r["value"])
            days=sorted(raw); end=days[-1]
            h=analyze(raw,days,1e-6)
            research=build_features(raw,days,1e-6,{d:v/1e6 for d,v in aum.items()})
            history=tbfseries if sym=="SGOV" else positions.get(code,{})
            from adaptive_flow import cot_feature
            for k,v in h.items():
                interpret(v,k,end,history,False,today)
                f,replay=research[k]
                f["cot_z"]=cot_feature(v,history,k) if f else None
                v["adaptive_features"],v["adaptive_replay"]=f,replay
                # Control method exactly mirrors flow + position, without
                # calling the production selection code.
                b=v["action"] if v["action"] in (BUY,REDUCE) else WAIT
                v["early_methods"]={"flow_position":b}
            # Primary report and native report are physically isolated.
            return dict(symbol=sym,asset=name,flow_asof=str(end),horizons=h,provenance=meta,
                        costs=cost_context(),source_status="OBSERVED")
        except Exception as exc:
            return dict(symbol=sym,asset=name,error=type(exc).__name__+": "+str(exc),source_status="UNAVAILABLE")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(fund,ASSETS))
    replay=record(rows,previous.get("prospective",{}))
    # Separate source, immutable observations; never import primary ledger.
    report=dict(seen_at=now.isoformat(),source="ETFIQ",assets=rows,source_status="SHADOW_ONLY",
                cot_source=cot_source)
    archive(folder,"observations",now,report)
    history=[]
    for p in sorted((folder/"observations").glob("*.json")):
        x=json.loads(p.read_text())
        history.append((datetime.fromisoformat(x["seen_at"]).astimezone(NY).date(),x))
    ledger=folder/"forward_ledger.json"
    frozen=json.loads(ledger.read_text()) if ledger.exists() else {}
    prospective=collect(history,series,today,existing=frozen)
    atomic(ledger,prospective)
    historical=collect(replay,series,today,replay=True)
    # Independent optional sources. They are evidence only, not input to
    # production, and never represented by zero on failure.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={name:pool.submit(safe,fn) for name,fn in (
            ("BTC",lambda:okx_crypto("BTC-USDT-SWAP",datetime.now(timezone.utc),read)),
            ("ETH",lambda:okx_crypto("ETH-USDT-SWAP",datetime.now(timezone.utc),read)),
            ("SHFE_copper_warrant",lambda:shfe_verified(datetime.now(timezone.utc))),
            ("TBF3_TFF",lambda:tff_tbf3(today,read)),
            ("issuer_USO",lambda:issuer_verified("USO",today)),
            ("issuer_CPER",lambda:issuer_verified("CPER",today)),
            ("issuer_QQQ",lambda:issuer_verified("QQQ",today)),
            ("COMEX_copper",lambda:copper(datetime.now(timezone.utc))),
            ("ALFRED",lambda:alfred_vintage("DFII10",today-timedelta(days=1),os.getenv("FRED_API_KEY"))),
            ("WTI_CLOSE_PAIR",lambda:wti_pair(datetime.now(timezone.utc),read)),
            ("TBILL_AUCTION",lambda:treasury_auction(today,read)))}
        native={k:f.result() for k,f in futures.items()}
    for symbol in ("USO","CPER","QQQ"):
        key="issuer_"+symbol
        r=native[key]
        if r.get("status")!="OBSERVED":continue
        path=folder/"issuer_snapshots"/(symbol+".json")
        path.parent.mkdir(parents=True,exist_ok=True)
        hist=json.loads(path.read_text()) if path.exists() else {}
        d=r["source_date"]
        before=sorted(k for k in hist if k<d)
        if before:
            r["adjacent_creation_estimate_usd"]=estimate_adjacent(hist[before[-1]],r,calendar)
        issuer_revision(hist,r,datetime.now(timezone.utc))
        atomic(path,hist)
    native["TBF3"]=tbf_data
    native["WTI"]=dict(status="UNAVAILABLE_CURRENT_OFFICIAL",source_url="https://www.eia.gov/opendata/browser/petroleum/pri/fut",
                       historical_end="2024-04-05",reason="no verified current licensed settlement curve")
    # Store bounded summaries; funding history and vintage observations are
    # captured once per unique source content, not duplicated every scan.
    # Retain current detailed input, and bounded immutable daily summaries.
    atomic(folder/"native_latest.json",native)
    for key,value in native.items():
        provider={"BTC":"okx","ETH":"okx","SHFE_copper_warrant":"shfe","COMEX_copper":"comex","TBF3":"cftc","ALFRED":"alfred","WTI":"wti","TBF3_TFF":"cftc","issuer_USO":"uscf","issuer_CPER":"uscf","issuer_QQQ":"invesco","WTI_CLOSE_PAIR":"yahoo","TBILL_AUCTION":"treasurydirect"}[key]
        data={k:v for k,v in value.items() if k not in ("history","observations")}
        archive(folder,"native/"+provider+"/"+key,now,dict(data,first_seen_at=now.isoformat(),source_digest=digest(data)))
    compact={k:{a:b for a,b in v.items() if a not in ("history","observations")} for k,v in native.items()}
    archive(folder,"native_inputs",now,compact)
    result=dict(version=VERSION,evaluated_at=now.isoformat(),source="ETFIQ (etfiq.com)",
                price_errors=errors,coverage=[dict(symbol=r["symbol"],status=r["source_status"],
                provenance=r.get("provenance"),error=r.get("error"),
                model_coverage={k:sum(v is not None for v in h.get("adaptive_methods",{}).values())
                                for k,h in r.get("horizons",{}).items()}) for r in rows],
                prospective=evaluate_tracks(prospective),exploratory=evaluate_tracks(historical,exploratory=True),
                native_status={k:v.get("status") for k,v in native.items()},
                native_errors={k:v.get("error") for k,v in native.items() if v.get("error")},
                native_substatus={k:{a:b for a,b in v.items() if a.endswith("_status") or a.endswith("_error")} for k,v in native.items()},
                decision_policy="SHADOW_ONLY_NO_PRODUCTION_PROMOTION",
                costs=cost_context(),historical_publication_time_verified=False)
    atomic(folder/"results.json",result)
    lines=["# ETFIQ independent research / native evidence","",now.isoformat(),"",
           "Separate ETFIQ source history; no production override, no mixing with ETFdb. Current vintage replay is exploratory.","",
           "|Fund|Status|Daily samples|From|To|","|---|---|---:|---|---|"]
    for r in result["coverage"]:
        p=r.get("provenance") or {}
        lines.append(f"|{r['symbol']}|{r['status']}|{p.get('daily_count','—')}|{p.get('coverage_start','—')}|{p.get('coverage_end','—')}|")
    lines+=["","|Native input|Status|","|---|---|"]+[f"|{k}|{v}|" for k,v in result["native_status"].items()]
    lines+=["","|Research cohort|Independent replay periods|Forward periods|","|---|---:|---:|"]
    for k in sorted(set(result["prospective"])|set(result["exploratory"])):
        lines.append(f"|{k}|{result['exploratory'].get(k,{}).get('independent_periods',0)}|{result['prospective'].get(k,{}).get('independent_periods',0)}|")
    (ROOT/"NATIVE_RESEARCH.md").write_text("\n".join(lines)+"\n")
    return 0 if any(r["source_status"]=="OBSERVED" for r in rows) else 1


if __name__=="__main__":
    raise SystemExit(main())
