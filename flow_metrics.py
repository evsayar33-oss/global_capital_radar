"""Observed directional pressure and dated monthly references; research only."""
from calendar import monthrange
from datetime import date, datetime
from math import fsum, isfinite
from horizons import boundary, describe

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v)

def pressure(values):
    if not values or not all(finite(x) for x in values):
        return None
    gross=fsum(abs(x) for x in values)
    return round(100*fsum(values)/gross,4) if gross else None

def daily_window(raw,sessions,end,key):
    start=boundary(end,key,1)
    if not sessions or min(sessions)>start or end not in sessions:
        return {}
    window=sorted({x for x in sessions if start<x<=end})
    if len(window)<3 or any(x not in raw or not finite(raw[x]) for x in window):
        return {}
    values=[raw[x] for x in window]
    return dict(net_usd_m=round(fsum(values)/1e6,3),directional_pressure_pct=pressure(values),
                directional_sessions=len(window),positive_sessions_pct=round(100*sum(x>0 for x in values)/len(values),4),
                pressure_basis="DAILY_NET_OVER_ABSOLUTE_DAILY_NET",pressure_start=str(start),pressure_end=str(end))

def monthly_reference(records,symbol,key,asof):
    count={"1A":1,"3A":3,"1Y":12}.get(key)
    if not count or asof.tzinfo is None:
        return []
    groups={}
    for name,r in records.items():
        if r.get("symbol")!=symbol or r.get("month")!=name or r.get("role")!="MONTHLY_RESEARCH_ONLY_NO_DAILY_INTERPOLATION":
            continue
        try:
            d=date.fromisoformat(r["period_end"])
            available=date.fromisoformat(r["available_from_date"])
            seen=datetime.fromisoformat(r["first_seen_at"])
            if (d.strftime("%Y-%m")!=name or d.day!=monthrange(d.year,d.month)[1]
                or seen.tzinfo is None or seen>asof or not d<available<=asof.date()):
                continue
            v,inc,out=(r.get(k) for k in ("net_flow_usd","inflow_usd","outflow_usd"))
            if not all(finite(x) for x in (v,inc,out)) or inc<0 or out>0 or abs(v-inc-out)>0.01:
                continue
            if not r.get("source") or not r.get("form"):
                continue
            groups.setdefault((r["source"],r["form"]),{})[d.year*12+d.month-1]=r
        except (KeyError,ValueError,TypeError):
            continue
    result=[]
    for (source,form),items in sorted(groups.items()):
        end=max(items)
        def period(stop):
            indexes=range(stop-count+1,stop+1)
            return [items[i] for i in indexes] if all(i in items for i in indexes) else []
        current=period(end)
        if not current:
            continue
        net=fsum(r["net_flow_usd"] for r in current)
        gross=fsum(r["inflow_usd"]-r["outflow_usd"] for r in current)
        past=[]
        for stop in range(end-count,min(items)+count-2,-count):
            block=period(stop)
            if block:past.append(fsum(r["net_flow_usd"] for r in block))
        strength,pct=describe(net,past)
        aum=current[0].get("start_aum_usd")
        result.append(dict(symbol=symbol,source=source,form=form,start=current[0]["month"]+"-01",
            end=current[-1]["period_end"],available=max(r["available_from_date"] for r in current),
            first_seen=max(r["first_seen_at"] for r in current),net_usd_m=round(net/1e6,3),
            flow_aum_pct=100*net/aum if finite(aum) and aum>0 else None,
            reported_gross_pressure_pct=round(100*net/gross,4) if gross else None,
            reference_count=len(past),magnitude_percentile=pct,strength=strength))
    return result
