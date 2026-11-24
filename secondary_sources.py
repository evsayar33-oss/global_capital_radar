"""Public secondary source capture; never fabricates primary ETF history."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from math import isfinite

CFTC_URL="https://publicreporting.cftc.gov/resource/6dca-aqww.json"
ETFIQ_URL="https://etfiq.com/data/flows/daily/latest.json"


def number(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v)


def cot_api(today,codes,read):
    fields=("cftc_contract_market_code","report_date_as_yyyy_mm_dd","open_interest_all",
            "noncomm_positions_long_all","noncomm_positions_short_all")
    codes_sql=",".join("'"+code+"'" for code in sorted(codes))
    query=urlencode({"$select":",".join(fields),"$where":
                     "cftc_contract_market_code in ("+codes_sql+") AND report_date_as_yyyy_mm_dd >= '"+str(today-timedelta(days=15*366))+"T00:00:00'",
                     "$limit":50000,"$order":"report_date_as_yyyy_mm_dd ASC,cftc_contract_market_code ASC"})
    data=json.loads(read(CFTC_URL+"?"+query))
    if not isinstance(data,list) or not data or len(data)>=50000:
        raise ValueError("CFTC API empty or truncated")
    result={}
    for row in data:
        code=row[fields[0]]
        day=date.fromisoformat(row[fields[1]][:10])
        if code not in codes or day>today:
            raise ValueError("CFTC API code/date mismatch")
        oi,long,short=(int(row[f]) for f in fields[2:])
        if min(oi,long,short)<0 or max(long,short)>oi:
            raise ValueError("CFTC impossible positions")
        if oi==0:
            continue
        value=100*(long-short)/oi
        out=result.setdefault(code,{})
        if day in out and out[day]!=value:
            raise ValueError("CFTC conflicting duplicate")
        out[day]=value
    if not result:
        raise ValueError("CFTC no valid positions")
    return result


def combine_cot(primary,secondary):
    # The API and annual archive are two transports of the same CFTC series.
    # Never splice if an overlapping observation disagrees.
    overlap=0
    for code,history in primary.items():
        for day,v in history.items():
            if day in secondary.get(code,{}):
                overlap+=1
                if abs(v-secondary[code][day])>1e-6:
                    return primary,False
    if not overlap:
        return primary,False
    result={c:dict(h) for c,h in secondary.items()}
    for code,history in primary.items():
        result.setdefault(code,{}).update(history)
    return result,True


def parse_etfiq(payload,today,symbols):
    if payload.get("schemaVersion")!=1 or payload.get("basis")!="daily":
        raise ValueError("ETFIQ schema/basis mismatch")
    day=date.fromisoformat(payload["asOf"])
    if day>today or (today-day).days>7:
        raise ValueError("ETFIQ source stale or future")
    found={}
    for row in payload["funds"]:
        sym=row.get("ticker")
        if sym not in symbols:
            continue
        if sym in found:
            raise ValueError("ETFIQ duplicate symbol")
        flow,aum=row.get("flowUsd"),row.get("startNetAssetsUsd")
        start=row.get("startNetAssetsDate")
        valid=(row.get("basis")=="daily" and row.get("status")=="ok" and row.get("held") is False
               and number(flow) and number(aum) and aum>0 and isinstance(start,str)
               and 0<(day-date.fromisoformat(start)).days<=5 and row.get("navDate")==start)
        found[sym]=dict(status="OBSERVED" if valid else "UNAVAILABLE",
                        flow_usd=flow if valid else None,start_aum_usd=aum if valid else None,
                        start_aum_date=start if valid else None)
    for sym in symbols-found.keys():
        found[sym]=dict(status="UNAVAILABLE",flow_usd=None,start_aum_usd=None,start_aum_date=None)
    return dict(source="ETFIQ (etfiq.com)",source_url=ETFIQ_URL,source_date=str(day),funds=found)


def capture_etfiq(root,today,rows,read):
    try:
        observed=parse_etfiq(json.loads(read(ETFIQ_URL)),today,{r["symbol"] for r in rows})
        folder=root/"history/secondary_flow"
        folder.mkdir(parents=True,exist_ok=True)
        data=json.dumps(observed,sort_keys=True,ensure_ascii=False,allow_nan=False)
        digest=hashlib.sha256(data.encode()).hexdigest()
        path=folder/(observed["source_date"]+"-"+digest[:16]+".json")
        if not path.exists():
            temp=path.with_suffix(".tmp")
            temp.write_text(data)
            temp.replace(path)
        matches=0
        for r in rows:
            secondary=observed["funds"][r["symbol"]]
            primary=r.get("net_usd_m",{}).get("1G")
            secondary=dict(secondary,source_date=observed["source_date"])
            if (secondary["status"]=="OBSERVED" and number(primary) and
                r.get("flow_asof")==observed["source_date"] and not any(r.get(k) for k in ("error","stale","cached_source"))):
                secondary["same_date_difference_usd"]=secondary["flow_usd"]-primary*1e6
                matches+=1
            r["secondary_flow"]=secondary
        return dict(source=observed["source"],date=observed["source_date"],
                    observed=sum(v["status"]=="OBSERVED" for v in observed["funds"].values()),
                    same_date_comparisons=matches,role="SHADOW_CORROBORATION_ONLY")
    except Exception as exc:
        return dict(source="ETFIQ (etfiq.com)",error=type(exc).__name__+": "+str(exc),
                    role="UNAVAILABLE_NOT_ZERO")
