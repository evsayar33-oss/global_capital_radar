"""Runner-native source smoke test. Uses production parsers, no repository writes."""
import json
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from source_recovery import ISSUERS,parse_issuer,parse_creation,parse_shfe_cn,SHFE
from native_adapters import SHFE as SHFE_EN,parse_shfe
from runner_sources import verified_page
from urllib.parse import urlencode

def issuer_verified(symbol,today):
    r,mode=verified_page(ISSUERS[symbol],lambda html:parse_issuer(html,symbol,today),
                         '[data-key="so"]' if symbol in ("USO","CPER") else None)
    r["transport"]=mode
    if symbol in ("USO","CPER"):
        url="https://www.uscfinvestments.com/holdings/"+symbol.lower()
        try:
            c,transport=verified_page(url,lambda h:parse_creation(h,symbol,today))
            if c["source_date"]!=r["source_date"]:raise ValueError("creation/NAV date mismatch")
            r.update(c,creation_status="OBSERVED",creation_source_url=url,creation_transport=transport,
                     estimated_creation_usd=c["net_created_shares"]*r["nav_usd"],
                     creation_basis="issuer net created shares times same-date rounded NAV")
        except Exception as e:r.update(creation_status="UNAVAILABLE",creation_error=str(e))
    return r

def shfe_verified(now):
    day=now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    errors=[]
    for offset in range(4):
        d=day-timedelta(days=offset)
        if d.weekday()>=5:continue
        candidates=[(SHFE+"dailystock_"+d.strftime("%Y%m%d")+"/ZH/all.html",parse_shfe_cn),
                    (SHFE_EN+"?"+urlencode(dict(query_date=d.strftime("%Y%m%d"),query_params="dailystock")),parse_shfe)]
        for url,parse in candidates:
            try:
                r,mode=verified_page(url,lambda h:parse(h,d))
                return dict(r,source_url=url,transport=mode)
            except Exception as e:errors.append(type(e).__name__+": "+str(e)[:200])
    return dict(status="UNAVAILABLE",source="SHFE",error="; ".join(errors))

def main():
    now=datetime.now(timezone.utc);today=now.astimezone(ZoneInfo("America/New_York")).date()
    from concurrent.futures import ThreadPoolExecutor
    def safe(key,fn):
        try:r=fn()
        except Exception as e:r=dict(status="UNAVAILABLE",error=type(e).__name__+": "+str(e))
        print("RUNNER_RESULT "+json.dumps(dict(key=key,**r),ensure_ascii=False),flush=True)
        return r
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(safe,s,lambda s=s:issuer_verified(s,today)) for s in ISSUERS]
        jobs.append(pool.submit(safe,"SHFE",lambda:shfe_verified(now)))
        result=[f.result() for f in jobs]
    print("RUNNER_OBSERVED "+str(sum(r.get("status")=="OBSERVED" for r in result))+"/4",flush=True)
    return 0 if any(r.get("status")=="OBSERVED" for r in result) else 1

if __name__=="__main__":raise SystemExit(main())
