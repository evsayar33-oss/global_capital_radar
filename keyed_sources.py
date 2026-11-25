"""Authenticated official-source adapters. Keys are never returned or logged."""
import hashlib
import json
import os
import re
from datetime import date,timedelta
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError

EIA = {"DCOILBRENTEU":("PET.RBRTE.D","RBRTE","$/BBL","petroleum/pri/spt"),
       "DHHNGSP":("NG.RNGWHHD.D","RNGWHHD","$/MMBTU","natural-gas/pri/fut")}
BEA = {"PCEPI":("1","DPCERG",("personal consumption expenditures","personal consumption expenditures (pce)","pce")),
       "PCEPILFE":("25","DPCCRG",("pce excluding food and energy","personal consumption expenditures excluding food and energy"))}
BLS_URL="https://api.bls.gov/publicAPI/v2/timeseries/data/"
BEA_URL="https://apps.bea.gov/api/data/"
EIA_URL="https://api.eia.gov/v2/"
CENSUS_URL="https://api.census.gov/data/timeseries/intltrade/imports/hs"


def request_json(url,params=None,body=None):
    """Only fixed public provider endpoints; redact authenticated URLs/errors."""
    target=url+("?" + urlencode(params,doseq=True) if params else "")
    try:
        payload=None if body is None else json.dumps(body).encode()
        req=Request(target,data=payload,headers={"User-Agent":"global-capital-radar/1.0",
                    "Accept":"application/json","Content-Type":"application/json"})
        with urlopen(req,timeout=20) as res:
            raw=res.read(8_000_001)
        if len(raw)>8_000_000:
            raise ValueError("response too large")
        return json.loads(raw),hashlib.sha256(raw).hexdigest()
    except HTTPError as exc:
        raise ValueError("authenticated HTTP status "+str(exc.code)) from None
    except Exception as exc:
        raise ValueError("authenticated response failed: "+type(exc).__name__) from None


def credential(name):
    value=os.getenv(name)
    if not value:
        raise ValueError(name+" absent")
    return value


def provenance(source,series,url,digest,basis):
    return dict(source=source,source_series=series,source_urls=[url],source_sha256=[digest],
                observation_basis=basis,authenticated_request=True,
                historical_vintage_verified=False,publication_intraday_verified=False)


def bls_authenticated(identity,today,request=request_json):
    p,h=request(BLS_URL,body={"seriesid":[identity],"startyear":str(today.year-2),
                             "endyear":str(today.year),"registrationkey":credential("BLS_API_KEY")})
    return p,h


def eia_series(key,today,request=request_json):
    from macro_sources import add
    identity,code,unit,route=EIA[key]
    url=EIA_URL+route+"/data/"
    first=today-timedelta(days=800)
    params={"api_key":credential("EIA_API_KEY"),"frequency":"daily",
            "data[]":"value","facets[series][]":code,
            "start":str(first),"end":str(today),"length":5000,
            "sort[0][column]":"period","sort[0][direction]":"asc"}
    rows={}; hashes=[]; seen=set(); offset=0; total=None
    for _ in range(16):
        p,h=request(url,params={**params,"offset":offset})
        response=p["response"]
        if response.get("frequency") not in (None,"daily"):
            raise ValueError("EIA frequency mismatch")
        data=response["data"]
        page_total=int(response["total"])
        if total is None:
            total=page_total
        if page_total!=total or total<0 or offset+len(data)>total:
            raise ValueError("EIA inconsistent pagination")
        if not data and offset<total:
            raise ValueError("EIA truncated history")
        hashes.append(h)
        for row in data:
            if row.get("series")!=code or str(row.get("units","")).upper()!=unit:
                raise ValueError("EIA series or units mismatch")
            day=date.fromisoformat(row["period"])
            if not first<=day<=today or day in seen:
                raise ValueError("EIA date or pagination mismatch")
            seen.add(day)
            if row.get("value") not in (None,"","."):
                add(rows,day,row["value"],today)
        offset+=len(data)
        if offset==total:
            meta=provenance("EIA API",identity,url,hashes[0],"SOURCE_NATIVE_CURRENT_DAILY_SPOT")
            meta["source_sha256"]=hashes
            return rows,meta
    raise ValueError("EIA truncated history")


def bea_series(key,today,request=request_json):
    from macro_sources import add
    line,series,labels=BEA[key]
    p,h=request(BEA_URL,params={"UserID":credential("BEA_API_KEY"),"method":"GetData",
        "datasetname":"NIPA","TableName":"T20804","Frequency":"M",
        "Year":",".join(str(y) for y in range(today.year-2,today.year+1)),"ResultFormat":"JSON"})
    result=p["BEAAPI"]["Results"]
    rows={}
    for row in result["Data"]:
        if str(row.get("LineNumber"))!=line and row.get("SeriesCode")!=series:
            continue
        desc=str(row.get("LineDescription","")).strip().lower()
        if (desc not in labels or row.get("TableName")!="T20804"
                or str(row.get("LineNumber"))!=line or row.get("SeriesCode")!=series):
            raise ValueError("BEA line identity mismatch")
        period=row["TimePeriod"]
        if not re.fullmatch(r"\d{4}M(0[1-9]|1[0-2])",period):
            raise ValueError("BEA period mismatch")
        if row["DataValue"] in ("","(NA)","(D)","--"):
            continue
        add(rows,date(int(period[:4]),int(period[-2:]),1),row["DataValue"].replace(",",""),today)
    return rows,provenance("BEA API","NIPA T20804 line "+line+" / "+series,BEA_URL,h,"SOURCE_NATIVE_CURRENT_MONTHLY_PRICE_INDEX")


def census_crude_imports(today,request=request_json):
    """Customs-basis, all-country crude oil imports; not BOP goods imports."""
    from macro_sources import add
    from radar import month
    start=month(today.replace(day=1),-3)
    rows={};hashes=[]
    for day in (month(start,-12),start):
        period=day.strftime("%Y-%m")
        p,h=request(CENSUS_URL,params={"get":"GEN_VAL_MO,CTY_CODE,I_COMMODITY",
                    "time":period,"CTY_CODE":"-","I_COMMODITY":"2709","key":credential("CENSUS_API_KEY")})
        if len(p)!=2:
            raise ValueError("Census nonunique response")
        row=dict(zip(p[0],p[1],strict=True))
        if row.get("CTY_CODE")!="-" or row.get("I_COMMODITY")!="2709" or row.get("time")!=period:
            raise ValueError("Census country, product or period mismatch")
        value=int(row["GEN_VAL_MO"])
        if value<0:
            raise ValueError("negative Census import value")
        add(rows,day,value,today);hashes.append(h)
    evidence=provenance("US Census API","HS 2709 / GEN_VAL_MO / all countries",CENSUS_URL,
                        hashes[-1],"CUSTOMS_BASIS_CURRENT_MONTHLY_USD_NOT_BOP")
    evidence["source_sha256"]=hashes
    return rows,evidence


def safe_failure(exc):
    # Never log upstream response bodies or credentials; only our own known messages.
    message=str(exc)
    allowed={"EIA frequency mismatch","EIA truncated history","EIA series or units mismatch",
             "EIA inconsistent pagination","EIA date or pagination mismatch",
             "BEA line identity mismatch","BEA period mismatch","Census nonunique response",
             "Census country, product or period mismatch","negative Census import value",
             "missing, stale, short, or unauthenticated series",
             "future or duplicate macro observation","nonfinite macro observation",
             "EIA_API_KEY absent","BEA_API_KEY absent","BLS_API_KEY absent","CENSUS_API_KEY absent"}
    if message in allowed or re.fullmatch(r"authenticated HTTP status [0-9]{3}|authenticated response failed: [A-Za-z]+",message):
        return message
    return type(exc).__name__


def health():
    from datetime import datetime,timezone
    from macro_sources import fresh_series
    from radar import read
    today=datetime.now(timezone.utc).date()
    jobs=[("BLS_API_KEY","CPIAUCSL",lambda:fresh_series("CPIAUCSL",today,read,75)),
          ("EIA_API_KEY","DCOILBRENTEU",lambda:eia_series("DCOILBRENTEU",today)),
          ("EIA_API_KEY","DHHNGSP",lambda:eia_series("DHHNGSP",today)),
          ("BEA_API_KEY","PCEPI",lambda:bea_series("PCEPI",today)),
          ("BEA_API_KEY","PCEPILFE",lambda:bea_series("PCEPILFE",today)),
          ("CENSUS_API_KEY","HS2709",lambda:census_crude_imports(today))]
    result=[]
    for secret,name,fn in jobs:
        try:
            credential(secret)
            rows,meta=fn()
            age=120 if name=="HS2709" else 90 if name in BEA or name=="CPIAUCSL" else 15
            if not rows or (today-max(rows)).days>age or (max(rows)-min(rows)).days<365 or not meta.get("authenticated_request"):
                raise ValueError("missing, stale, short, or unauthenticated series")
            item=dict(secret=secret,series=name,status="AUTHENTICATED_OBSERVED",observations=len(rows),
                      last=str(max(rows)),source=meta["source"])
        except Exception as exc:
            item=dict(secret=secret,series=name,status="UNAVAILABLE",error=safe_failure(exc))
        result.append(item)
        print("KEYED_SOURCE_HEALTH "+json.dumps(item),flush=True)
    return 0 if all(x["status"]=="AUTHENTICATED_OBSERVED" for x in result) else 1


if __name__=="__main__":
    raise SystemExit(health())
