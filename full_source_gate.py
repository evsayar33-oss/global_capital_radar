"""Branch-only strict acceptance: fresh real observations, not cached smoke success."""
import json
from datetime import datetime,timezone
from pathlib import Path

SYMBOLS=("SPY","QQQ","DIA","IWM","SGOV","SHY","GLD","SLV","CPER","USO","IBIT","ETHA")
MIN_DAILY=400
def load_fresh(path,key,start):
    r=json.loads(path.read_text())
    seen=datetime.fromisoformat(r[key])
    if seen.tzinfo is None or seen<start:raise ValueError("stale report "+str(path))
    return r

def evaluate(native,details,filing,rotation):
    checks={}
    def add(key,ok,detail):checks[key]=dict(pass_=bool(ok),detail=detail)
    coverage={r["symbol"]:r for r in native.get("coverage",[])}
    for sym in SYMBOLS:
        r=coverage.get(sym,{})
        count=(r.get("provenance") or {}).get("daily_count",0)
        add("daily_history_"+sym,r.get("status")=="OBSERVED" and count>=MIN_DAILY,count)
    statuses=native.get("native_status",{})
    for k in ("BTC","ETH","SHFE_copper_warrant","COMEX_copper","issuer_USO","issuer_CPER","issuer_QQQ"):
        add(k,statuses.get(k)=="OBSERVED",statuses.get(k))
    for sym in ("USO","CPER"):
        r=details.get("issuer_"+sym,{})
        add("issuer_creation_"+sym,r.get("creation_status")=="OBSERVED",r.get("creation_status"))
    add("ALFRED_true_vintage",statuses.get("ALFRED")=="OBSERVED_DATE_VINTAGE" and bool(details.get("ALFRED",{}).get("observations")),statuses.get("ALFRED"))
    add("ALFRED_archive",native.get("alfred_vintage_archive",{}).get("status")=="ARCHIVED",native.get("alfred_vintage_archive"))
    add("WTI_official_settlement",details.get("WTI",{}).get("official_settlement_verified") is True and statuses.get("WTI")=="OBSERVED_OFFICIAL_SETTLEMENT_PAIR",statuses.get("WTI"))
    tbf=details.get("TBF3",{})
    add("TBF3_actual_COT",tbf.get("status")=="OBSERVED" and bool(tbf.get("observations")),tbf.get("status"))
    add("TBF3_actual_settlement",tbf.get("actual_settlement_verified") is True,tbf.get("price_status"))
    for k,status in (("WTI_CLOSE_PAIR","OBSERVED_DELAYED_CLOSE_PAIR"),("WTI_USL_PAIR","OBSERVED_ISSUER_VALUATION_PAIR"),("TBILL_AUCTION","OBSERVED_AUCTION_CONTEXT"),("TREASURY_REAL_YIELD","OBSERVED_CURRENT_PUBLICATION")):
        add(k,statuses.get(k)==status,statuses.get(k))
    for sym,minimum in (("QQQ",84),("CPER",23),("USO",23)):
        r=filing.get("symbols",{}).get(sym,{})
        add("monthly_"+sym,r.get("monthly_count",0)>=minimum and r.get("live_monthly_count",0)>0,r.get("monthly_count",0))
    c=rotation.get("continuity",{}).get("assets",{})
    add("alternative_all12",all(c.get(s,{}).get("selected") for s in SYMBOLS),sum(bool(c.get(s,{}).get("selected")) for s in SYMBOLS))
    p={r["symbol"]:r for r in rotation.get("assets",[])}
    missing=[s for s in SYMBOLS if s not in p or any(p[s].get(k) for k in ("error","stale","cached_source"))]
    add("primary_source_continuity",not missing,missing)
    add("price_series",not native.get("price_errors",{"missing":True}),native.get("price_errors"))
    return checks

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--started",required=True);p.add_argument("--out",required=True)
    a=p.parse_args();start=datetime.fromisoformat(a.started)
    folder=Path("history/native_research")
    try:
        n=load_fresh(folder/"results.json","evaluated_at",start)
        f=load_fresh(folder/"extended_history/results.json","evaluated_at",start)
        r=load_fresh(Path("history/rotation/latest.json"),"seen_at",start)
        d=json.loads((folder/"native_latest.json").read_text())
        checks=evaluate(n,d,f,r)
    except Exception as exc:
        checks={"fresh_reports":dict(pass_=False,detail=type(exc).__name__+": "+str(exc))}
    failures=[k for k,v in checks.items() if not v["pass_"]]
    result=dict(evaluated_at=datetime.now(timezone.utc).isoformat(),checks=checks,
                failed=failures,merge_ready=not failures)
    Path(a.out).write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print("FULL_SOURCE_GATE "+json.dumps(result,ensure_ascii=False),flush=True)
    return int(bool(failures))

if __name__=="__main__":raise SystemExit(main())
