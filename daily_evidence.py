"""First-observed daily ETFIQ snapshots, isolated from history endpoint and signals."""
import json
import hashlib
from datetime import date,datetime
from zoneinfo import ZoneInfo
from secondary_sources import ETFIQ_URL,number
from adaptive_evaluation import atomic

NY=ZoneInfo("America/New_York")
ROLE="FIRST_OBSERVED_DAILY_SOURCE_ONLY"

def verify_snapshot(payload):
    data={k:v for k,v in payload.items() if k not in ("captured_at_utc","content_sha256")}
    raw=json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False)
    if hashlib.sha256(raw.encode()).hexdigest()!=payload.get("content_sha256"):
        raise ValueError("daily snapshot digest mismatch")
    return data,datetime.fromisoformat(payload["captured_at_utc"])

def add_snapshot(ledger,data,seen,clock,calendar):
    if seen.tzinfo is None or clock.tzinfo is None or seen>clock:
        raise ValueError("invalid first-observed timestamp")
    if data.get("source")!="ETFIQ (etfiq.com)" or data.get("source_url")!=ETFIQ_URL:
        raise ValueError("daily source identity")
    day=date.fromisoformat(data["source_date"])
    if day>seen.astimezone(NY).date():raise ValueError("future source date")
    earlier=[d for d in calendar if d<day]
    if day not in calendar or not earlier:return 0
    prior=max(earlier);added=0
    for sym,r in data["funds"].items():
        if r.get("status")!="OBSERVED":continue
        flow,aum=r.get("flow_usd"),r.get("start_aum_usd")
        if r.get("start_aum_date")!=str(prior) or not all(number(x) for x in (flow,aum)) or aum<=0:
            continue
        entry=dict(source_date=str(day),prior_nav_date=str(prior),flow_usd=flow,
                   start_aum_usd=aum,first_seen_at=seen.isoformat(),source_url=ETFIQ_URL,role=ROLE)
        hist=ledger.setdefault(sym,{})
        first=hist.setdefault(str(day),entry)
        if first is entry:added+=1;continue
        keys=("flow_usd","start_aum_usd","prior_nav_date")
        if not any(all(v.get(k)==entry[k] for k in keys) for v in [first]+first.get("revisions",[])):
            first.setdefault("revisions",[]).append(entry)
    return added

def coverage(ledger,calendar,symbols):
    result={}
    for sym in sorted(symbols):
        dates={date.fromisoformat(d) for d in ledger.get(sym,{})}
        matched=sorted(dates & set(calendar))
        suffix=[]
        if matched:
            for d in reversed([x for x in calendar if x<=matched[-1]]):
                if d not in dates:break
                suffix.append(d)
        result[sym]=dict(observed_days=len(matched),contiguous_days=len(suffix),
                         first_date=str(matched[0]) if matched else None,
                         last_date=str(matched[-1]) if matched else None,
                         role=ROLE,production_eligible=False)
    return result

def capture(root,folder,daily,seen,calendar,symbols,clock=None):
    clock=clock or datetime.now(seen.tzinfo)
    path=folder/"daily_snapshot_ledger.json"
    ledger=json.loads(path.read_text()) if path.exists() else {}
    errors=[];snapshots=[]
    for p in (root/"history/secondary_flow").glob("*.json"):
        try:
            data,stamp=verify_snapshot(json.loads(p.read_text()))
            snapshots.append((stamp,data,p.name))
        except Exception as exc:errors.append(p.name+": "+type(exc).__name__)
    if daily.get("funds"):snapshots.append((seen,daily,"live"))
    for stamp,data,label in sorted(snapshots,key=lambda x:x[0].isoformat()):
        try:add_snapshot(ledger,data,stamp,clock,calendar)
        except Exception as exc:errors.append(label+": "+type(exc).__name__)
    atomic(path,ledger)
    return dict(status="OBSERVED" if any(ledger.values()) else "UNAVAILABLE",
                coverage=coverage(ledger,calendar,symbols),errors=errors,
                policy="SEPARATE_DAILY_ENDPOINT_NO_HISTORICAL_SPLICING")

def preserve_vintage(folder,record,seen):
    if record.get("status")!="OBSERVED_DATE_VINTAGE":return False
    import re
    series=record["series"];vintage=date.fromisoformat(record["vintage"])
    if not re.fullmatch(r"[A-Z0-9_]+",series):raise ValueError("series identity")
    if vintage>seen.astimezone(NY).date():raise ValueError("future vintage")
    obs=record["observations"]
    if not obs:raise ValueError("empty vintage")
    dates=set()
    for r in obs:
        d=date.fromisoformat(r["observation_date"])
        if d>vintage or d in dates or not number(r.get("value")):
            raise ValueError("invalid vintage observation")
        dates.add(d)
    data=dict(series=series,vintage=str(vintage),observations=obs,
              source=record.get("source","ALFRED API"),publication_intraday_verified=False)
    digest=hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()
    path=folder/"vintages"/series/(str(vintage)+"-"+digest[:20]+".json")
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        atomic(path,dict(data,first_seen_at=seen.isoformat(),content_sha256=digest))
    return True
