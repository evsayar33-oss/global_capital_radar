"""Observed alternative capital flows; isolated from primary strategy evidence.

A provider is never used to fill another provider's missing date. A daily
observation does not imply a valid weekly/monthly/yearly signal.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from horizons import analyze
from secondary_sources import number,parse_etfiq,ETFIQ_URL

WAIT="BEKLE · alternatif kaynak araştırma aşamasında"
NY=ZoneInfo("America/New_York")

def recent(day,today,calendar):
    return (0<=(today-day).days<=7 and day in calendar
            and sum(d>day for d in calendar)<=1)

def suffix(raw,calendar):
    if not raw:return {}
    days=[]
    for d in reversed([x for x in calendar if x<=max(raw)]):
        if d not in raw:break
        days.append(d)
    return {d:raw[d] for d in sorted(days)}

def observed(symbol,provider,raw,today,calendar,meta,aum=None,*,retain_stale=False):
    if not raw:raise ValueError("no source-native observations")
    if max(raw)>today or max(raw) not in calendar:
        raise ValueError("source data future or off calendar")
    raw=suffix(raw,calendar)
    if not raw or not 0<=(today-max(raw)).days<=7 or max(raw) not in calendar:
        raise ValueError("source data stale, future or off calendar")
    stale=not recent(max(raw),today,calendar)
    if stale and not retain_stale:
        raise ValueError("source data stale, future or off calendar")
    if not all(number(v) for v in raw.values()):raise ValueError("nonfinite source flow")
    days=sorted(raw);end=days[-1]
    h=analyze(raw,days,1e-6) if len(days)>=5 else {}
    # No normalized flow feature when the source lacks an exact beginning AUM.
    for v in h.values():
        v["action"]=WAIT
    return dict(status="STALE_REFERENCE" if stale else "OBSERVED",symbol=symbol,provider=provider,
                stale=stale,lag_sessions=sum(d>end for d in calendar),
                flow_asof=str(end),daily_flow_usd=raw[end],daily_count=len(raw),
                coverage_start=str(days[0]),coverage_end=str(end),
                horizons=h,provenance=meta,start_aum_usd=aum,
                role="SOURCE_SEPARATE_RESEARCH_ONLY",action="BEKLE · alternatif veri eski" if stale else WAIT)

def etfiq_history(symbol,today,calendar,reader):
    # Local import avoids a rotation/native_research import cycle.
    from native_research import parse_history,FLOW_URL
    p=json.loads(reader(FLOW_URL+symbol.lower()+".json"))
    raw,aum,meta=parse_history(p,symbol,today,calendar)
    result=observed(symbol,"ETFIQ_HISTORY",raw,today,calendar,meta,retain_stale=True)
    from horizons import boundary
    for key,h in result["horizons"].items():
        target=boundary(max(raw),key,1)
        previous=[d for d in calendar if d<=target]
        start=max(previous) if previous else None
        if start in aum and h.get("net_usd_m") is not None:
            h["flow_aum_pct"]=100*h["net_usd_m"]*1e6/aum[start]
            h["aum_asof"]=str(start)
        if result["stale"]:
            h["action"]="BEKLE · alternatif veri eski"
    return result

def etfiq_daily(symbol,today,calendar,daily):
    r=daily["funds"][symbol];d=date.fromisoformat(daily["source_date"])
    if r.get("status")!="OBSERVED":raise ValueError("daily fund unavailable")
    prior=[x for x in calendar if x<d]
    if not prior or str(max(prior))!=r.get("start_aum_date"):
        raise ValueError("daily beginning AUM date not previous session")
    return observed(symbol,"ETFIQ_DAILY",{d:r["flow_usd"]},today,calendar,
                    dict(source="ETFIQ (etfiq.com)",source_url=ETFIQ_URL,units="USD",
                         historical_publication_time_verified=False),r["start_aum_usd"],retain_stale=True)

def issuer_history(root,symbol,today,calendar,now):
    # Use only first-observed dated issuer evidence, not retrospective revised values.
    path=root/"history/native_research/issuer_snapshots"/(symbol+".json")
    hist=json.loads(path.read_text())
    raw={}; provenance={}
    from macro_recovery import first_creation
    for ds,entry in hist.items():
        r=first_creation(entry)
        if r is None:continue
        d=date.fromisoformat(ds)
        if d>today or d not in calendar:continue
        if (r.get("status")!="OBSERVED" or r.get("creation_status")!="OBSERVED"
            or r.get("symbol")!=symbol or r.get("upstream_id")!="USCF"
            or r.get("source_date")!=ds or r.get("shares_precision")!="exact_integer"):
            continue
        seen=datetime.fromisoformat(r["first_seen_at"])
        if seen.tzinfo is None or seen>now or seen.astimezone(NY).date()<d:
            raise ValueError("issuer first-seen timestamp invalid")
        shares=r.get("net_created_shares");nav=r.get("nav_usd")
        if type(shares) is not int or not number(nav) or nav<=0:
            continue
        estimate=shares*nav
        if not number(r.get("estimated_creation_usd")) or abs(estimate-r["estimated_creation_usd"])>.01:
            continue
        raw[d]=estimate
        provenance[d]=dict(first_seen_at=r["first_seen_at"],source_url=r.get("source_url"),
                           creation_source_url=r.get("creation_source_url"),source_sha256=r.get("source_sha256"),
                           creation_source_sha256=r.get("creation_source_sha256"))
    if not raw:raise ValueError("no verified issuer creation history")
    return observed(symbol,"USCF_CREATION",raw,today,calendar,
                    dict(provenance[max(raw)],source="USCF",units="USD",
                         estimate_basis="published net created shares times same-date rounded NAV",
                         publication_intraday_verified=False))

def choose(candidates):
    # Prefer the most recent observed source; at the same date prefer a
    # complete source-native history, then exact published issuer creation.
    # The non-selected observations are retained for comparison, not merged.
    order={"ETFIQ_HISTORY":1,"ETFIQ_DAILY":0,"USCF_CREATION":2,"PWD_DAILY_ROUNDED":-1,"FARSIDE_DAILY":0}
    candidates=[c for c in candidates if c.get("status")=="OBSERVED" and not c.get("stale")]
    return max(candidates,key=lambda x:(x["flow_asof"],x["daily_count"]>=5,
                                       order[x["provider"]])) if candidates else None

def collect(root,assets,today,calendar,reader,now):
    symbols={a["symbol"] for a in assets}
    if not calendar or not 0<=(today-max(calendar)).days<=5:
        return dict(status="UNAVAILABLE",reason="US session calendar missing/stale",assets={})
    try:daily=parse_etfiq(json.loads(reader(ETFIQ_URL)),today,symbols)
    except Exception as exc:daily=None;daily_error=type(exc).__name__+": "+str(exc)
    def one(row):
        sym=row["symbol"]; candidates=[];errors={}
        def attempt(name,fn):
            try:candidates.append(fn())
            except Exception as exc:errors[name]=type(exc).__name__+": "+str(exc)
        attempt("ETFIQ_HISTORY",lambda:etfiq_history(sym,today,calendar,reader))
        if daily is None:errors["ETFIQ_DAILY"]=daily_error
        else:attempt("ETFIQ_DAILY",lambda:etfiq_daily(sym,today,calendar,daily))
        if sym in ("USO","CPER"):attempt("USCF_CREATION",lambda:issuer_history(root,sym,today,calendar,now))
        if not choose(candidates):
            from public_flow_source import collect as public_collect
            attempt("PWD_DAILY_ROUNDED",lambda:public_collect(sym,today,calendar,reader))
        if sym in ("IBIT","ETHA") and not choose(candidates):
            from public_flow_source import farside
            attempt("FARSIDE_DAILY",lambda:farside(sym,today,calendar,reader))
        selected=choose(candidates)
        primary_ok=not any(row.get(k) for k in ("error","stale","cached_source")) and bool(row.get("flow_asof"))
        return sym,dict(status="PRIMARY_OBSERVED" if primary_ok else "ALTERNATIVE_OBSERVED" if selected else "UNAVAILABLE",
                        selected=selected,candidates=candidates,errors=errors,
                        stale_reference=max((c for c in candidates if c.get("stale")),key=lambda c:(c["flow_asof"],c["daily_count"]),default=None),
                        primary_usable=primary_ok,production_eligible=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=dict(pool.map(one,assets))
    count=sum(x["status"]=="ALTERNATIVE_OBSERVED" for x in result.values())
    unavailable=sum(x["status"]=="UNAVAILABLE" for x in result.values())
    stale_count=sum(x["stale_reference"] is not None for x in result.values())
    return dict(status="DEGRADED_RESEARCH_AVAILABLE" if count else "UNAVAILABLE" if unavailable else "PRIMARY_OBSERVED",
                alternative_count=count,unavailable_count=unavailable,stale_reference_count=stale_count,assets=result,
                policy="NO_MIXING_NO_PRODUCTION_PROMOTION")

def live(root,assets,today,reader,now):
    from evaluate_rotation import prices
    try:
        # Calendar only: no return/price confirmation enters flow signals.
        bars=prices("SGOV",today-timedelta(days=850),today)
        calendar=sorted(d for d,v in bars.items() if v)
        return collect(root,assets,today,calendar,reader,now)
    except Exception as exc:
        return dict(status="UNAVAILABLE",reason=type(exc).__name__+": "+str(exc),assets={})

def main():
    from rotation import ASSETS
    from radar import read
    from pathlib import Path
    now=datetime.now(timezone.utc);today=now.astimezone(NY).date()
    # PR smoke simulates ETFdb outage, calls actual alternative endpoints.
    rows=[dict(symbol=s,error="simulated primary unavailable") for s,_,_ in ASSETS]
    report=live(Path(__file__).resolve().parent,rows,today,read,now)
    for sym,r in report.get("assets",{}).items():
        s=r["selected"]
        print("CONTINUITY_RESULT "+json.dumps(dict(symbol=sym,status=r["status"],
               provider=s["provider"] if s else None,date=s["flow_asof"] if s else None,
               daily_count=s["daily_count"] if s else 0,precision=s["provenance"].get("precision") if s else None,errors=r["errors"]),ensure_ascii=False),flush=True)
    full=sum(any(c["status"]=="OBSERVED" and c["daily_count"]>=5 for c in x["candidates"])
             for x in report.get("assets",{}).values())
    count=report.get("alternative_count",0)
    print("CONTINUITY_SUMMARY "+json.dumps(dict(alternatives=count,source_native_histories=full,
              policy=report.get("policy"),reason=report.get("reason"))),flush=True)
    # Regression floor, not proof of strategy validation.
    return 0 if count>=8 and full>=8 else 1

if __name__=="__main__":raise SystemExit(main())

