"""Paired, nonoverlapping evaluation of frozen V2 decisions. No orders."""
import json
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from pathlib import Path
from statistics import mean, stdev
from zoneinfo import ZoneInfo
from adaptive_flow import BASE, BUY, REDUCE, WAIT, METHODS, ELIGIBLE, VERSION
from horizons import PERIODS
from radar import month

ROOT = Path(__file__).resolve().parent
COSTS = (.10,.30,.50) # percentage points per round trip, assumptions
NY = ZoneInfo("America/New_York")


def atomic(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
    temp.replace(path)


def outcome(bars,cash,day,key,today):
    entries = sorted(d for d in cash if day<d<=day+timedelta(days=5))
    if not entries:
        return None
    entry=entries[0]
    target=entry+timedelta(days=7) if key=="1H" else month(entry,PERIODS[key])
    exits=sorted(d for d in cash if target<=d<today and (d-target).days<=5)
    if not exits:
        return None
    end=exits[0]
    if not all(s.get(d) for s in (bars,cash) for d in (entry,end)):
        return None
    return end,100*(bars[end][1]/bars[entry][0]-cash[end][1]/cash[entry][0])


def score(action,excess,cost):
    if action==BUY:
        return excess-cost
    if action==REDUCE:
        return -excess-cost
    if action==WAIT:
        return 0.
    return None


def summary(values):
    if not values:
        return {"n":0}
    return dict(n=len(values),mean_pp=mean(values),positive=sum(v>0 for v in values),
                lower95_pp=mean(values)-1.96*stdev(values)/sqrt(len(values)) if len(values)>1 else None)


def collect(reports,series,today,*,replay=False,existing=None):
    """First eligible signal per symbol/horizon/date; do not resample unchanged source."""
    observations=[]
    if replay:
        observations=[(date.fromisoformat(x["assumed_signal_day"]),x["symbol"],x["horizon"],
                       x["source_end"],x["methods"]) for x in reports]
    else:
        for day,report in reports:
            for r in report["assets"]:
                if any(r.get(k) for k in ("error","stale","cached_source")):
                    continue
                for key,h in r.get("horizons",{}).items():
                    if h.get("adaptive_version")==VERSION and h.get("adaptive_methods"):
                        # same flow release is not another independent forecast
                        observations.append((day,r["symbol"],key,r.get("flow_asof"),h["adaptive_methods"]))
    tracks={k:list(v) for k,v in (existing or {}).items()}
    occupied={k:date.fromisoformat(v[-1]["end"]) for k,v in tracks.items() if v}
    seen={(k,r["source"]) for k,v in tracks.items() for r in v}
    blocked=set()
    cash=series.get("SGOV",{})
    for day,sym,key,source,methods in sorted(observations,key=lambda x:x[0]):
        identity=sym+"/"+key
        if sym=="SGOV" or not source or (identity,source) in seen:
            continue
        seen.add((identity,source))
        if identity in blocked or day<=occupied.get(identity,date.min):
            continue
        if not any(m in (BUY,REDUCE,WAIT) for m in methods.values()):
            continue
        result=outcome(series.get(sym,{}),cash,day,key,today)
        if not result:
            # Do not let a missing earlier observation change a locked cohort.
            if not replay:
                blocked.add(identity)
            continue
        end,excess=result
        occupied[identity]=end
        tracks.setdefault(identity,[]).append(dict(day=str(day),end=str(end),source=source,
                                                  excess_pp=excess,methods=methods))
    return tracks


def paired(rows,m,cost):
    return [(score(r["methods"][m],r["excess_pp"],cost),
             score(r["methods"][BASE],r["excess_pp"],cost))
            for r in rows if r["methods"].get(m) in (BUY,REDUCE,WAIT)
            and r["methods"].get(BASE) in (BUY,REDUCE,WAIT)]


def evaluate_tracks(tracks, *, exploratory=False):
    output={}
    for identity,rows in tracks.items():
        models={}
        for m in METHODS:
            available=[r for r in rows if r["methods"].get(m) in (BUY,REDUCE,WAIT)]
            active=[r for r in available if r["methods"][m]!=WAIT]
            models[m]=dict(available=len(available),active=len(active),
                           hit_rate=(sum(score(r["methods"][m],r["excess_pp"],.10)>0 for r in active)/len(active) if active else None),
                           cost_stress={str(c):summary([score(r["methods"][m],r["excess_pp"],c) for r in available]) for c in COSTS})
        entry=dict(independent_periods=len(rows),models=models,status="EXPLORATORY_ONLY" if exploratory else "INSUFFICIENT")
        # Fixed chronological train/holdout/confirmation. No rolling reuse of
        # a failed holdout, no reselecting a winner after seeing it.
        # Common dates by construction for comparison with control, with
        # missing candidate evidence disqualifying it rather than becoming zero.
        if not exploratory and len(rows)>=30:
            train=rows[:30]
            contenders=[m for m in ELIGIBLE if len(paired(train,m,.30))==30
                        and sum(r["methods"][m]!=WAIT for r in train)>=10]
            if contenders:
                winner=max(contenders,key=lambda m:mean(a-b for a,b in paired(train,m,.30)))
                entry.update(candidate=winner,status="HOLDOUT_PENDING")
                for name,part in (("holdout",rows[30:50]),("confirmation",rows[50:70])):
                    if len(part)<20:
                        break
                    pairs=paired(part,winner,.30)
                    active=sum(r["methods"].get(winner) in (BUY,REDUCE) for r in part)
                    adv=summary([a-b for a,b in pairs])
                    absolute=summary([a for a,b in pairs])
                    stressed=paired(part,winner,.50)
                    passed=(len(pairs)==20 and active>=10 and
                            adv.get("lower95_pp") is not None and adv["lower95_pp"]>0 and
                            absolute["mean_pp"]>0 and mean(a for a,b in stressed)>0 and
                            mean(a-b for a,b in stressed)>0)
                    entry[name]=dict(paired_advantage=adv,absolute=absolute,active=active,passed=passed)
                    entry["status"]=("CONFIRMATION_PENDING" if name=="holdout" else "RESEARCH_ACCEPT") if passed else "REJECTED"
                    if not passed:
                        break
        if entry["status"]=="RESEARCH_ACCEPT" and len(rows)>=80:
            recent=rows[-10:]
            pairs=paired(recent,entry["candidate"],.30)
            entry["drift_check"]=dict(paired=len(pairs),advantage=summary([a-b for a,b in pairs]),
                                       absolute=summary([a for a,b in pairs]))
            if len(pairs)!=10 or mean(a-b for a,b in pairs)<=0 or mean(a for a,b in pairs)<=0:
                entry["status"]="RESEARCH_REVOKED"
        output[identity]=entry
    return output


def run(reports,series,today,replay_data,errors,*,root=ROOT):
    ledger=root/"history/adaptive_forward_ledger.json"
    frozen=json.loads(ledger.read_text()) if ledger.exists() else {}
    prospective=collect(reports,series,today,existing=frozen)
    atomic(ledger,prospective)
    historical=collect(replay_data,series,today,replay=True)
    report=dict(version=VERSION,evaluated_at=datetime.now(timezone.utc).isoformat(),
                cost_assumptions_pp=list(COSTS),price_errors=errors,
                prospective=evaluate_tracks(prospective),
                exploratory_current_vintage=evaluate_tracks(historical,exploratory=True),
                promotion="SHADOW_ONLY_NO_PRODUCTION_CHANGE",
                note="Directional relative SGOV score, not executable portfolio PnL. Replay uses current vintage and assumed seven-day lag; never qualifies a method.")
    atomic(root/"history/adaptive_results.json",report)
    lines=["# Adaptive Flow V2 – research", "",
           "Forward: frozen actual observations only. Replay: current vintage, assumed 7-day publication lag; no PIT proof, no promotion.",
           "Scores relative to SGOV, directional proxy, cost assumptions 10/30/50 bp; WAIT=0, unavailable excluded.", "",
           "|Type|Asset/horizon|Independent periods|Status|Candidate|", "|---|---|---:|---|---|"]
    for typ,group in (("Forward",report["prospective"]),("Replay",report["exploratory_current_vintage"])):
        for identity,item in sorted(group.items()):
            lines.append(f"|{typ}|{identity}|{item['independent_periods']}|{item['status']}|{item.get('candidate','—')}|")
    if not prospective:
        lines.append("\nNo matured V2 forward sample.")
    if not historical:
        lines.append("\nNo usable matured exploratory replay.")
    lines.append("\nFull model coverage, scores and cost sensitivity: history/adaptive_results.json.")
    (root/"ADAPTIVE.md").write_text("\n".join(lines)+"\n")
    return report
