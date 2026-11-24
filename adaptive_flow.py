"""Adaptive Flow V2. Frozen research signals; price never gates eligible methods."""
from bisect import bisect_right
from datetime import date, timedelta
from math import isfinite, sqrt
from statistics import mean, median, stdev
from horizons import PERIODS, boundary, describe

VERSION = "adaptive-flow-v2.0"
BASE = "M00_flow_position"
ELIGIBLE = ("M01_raw_percentile", "M02_aum_percentile", "M03_zscore",
            "M04_robust_zscore", "M05_ewma_zscore", "M06_acceleration",
            "M07_persistence", "M08_cot_anomaly", "M09_cross_asset",
            "M10_regime", "M12_ensemble")
PROXY = "M11_cost_proxy"
METHODS = (BASE,) + ELIGIBLE + (PROXY,)
BUY, REDUCE, WAIT = "ALIM ADAYI", "AZALTMA ADAYI", "BEKLE"
MIN_REF = 12
REPLAY_LIMIT = {"1H": 104, "1A": 36, "3A": 12, "1Y": 3}


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)


def sign(v):
    return 1 if v > 0 else -1 if v < 0 else 0


def action(v):
    return BUY if v > 0 else REDUCE if v < 0 else WAIT


def percentile(v, past):
    if not number(v) or len(past) < MIN_REF:
        return None
    return 100 * (sum(abs(x) < abs(v) for x in past) +
                  .5 * sum(abs(x) == abs(v) for x in past)) / len(past)


def zscore(v, past, kind="standard"):
    if not number(v) or len(past) < MIN_REF:
        return None
    if kind == "robust":
        center = median(past)
        scale = 1.4826 * median(abs(x-center) for x in past)
    elif kind == "ewma":
        # newest observation first; no current observation in fit
        weights = [.94**i for i in range(len(past))]
        total = sum(weights)
        center = sum(x*w for x,w in zip(past,weights))/total
        scale = sqrt(sum(w*(x-center)**2 for x,w in zip(past,weights))/total)
    else:
        center, scale = mean(past), stdev(past)
    return (v-center)/scale if scale > 1e-12 else None


def windows(flows, days, aum, aum_days, end, key):
    """Nonoverlapping, calendar-aligned windows; preserve missing slots."""
    result = []
    for i in range(53):
        stop, start = boundary(end,key,i), boundary(end,key,i+1)
        if start < days[0]:
            break
        obs = days[bisect_right(days,start):bisect_right(days,stop)]
        if len(obs)<3 or any((b-a).days>6 for a,b in zip([start]+obs,obs+[stop])):
            result.append(None)
            continue
        values = [flows[d] for d in obs]
        total = sum(values)
        j = bisect_right(aum_days,start)-1
        norm = None
        if j >= 0 and (start-aum_days[j]).days <= 4:
            norm = 100*total/aum[aum_days[j]]
        persistence = sum(sign(v)==sign(total) for v in values)/len(values) if total else 0
        result.append((total,norm,persistence,obs))
    return result


def features(flows, days, aum, aum_days, end, key, *, weights=False):
    w = windows(flows,days,aum,aum_days,end,key)
    if not w or w[0] is None:
        return {}
    raw, norm, persistence, obs = w[0]
    rawpast = [x[0] for x in w[1:] if x is not None]
    past = [x[1] for x in w[1:] if x is not None and number(x[1])]
    accel = None
    # No bridging missing consecutive periods.
    if len(w)>1 and w[1] is not None and number(norm) and number(w[1][1]):
        accel = norm-w[1][1]
    apast = [a[1]-b[1] for a,b in zip(w[1:],w[2:])
             if a is not None and b is not None and number(a[1]) and number(b[1])]
    # Compare recent flow dispersion with its older own-history dispersion.
    # Threshold is a preregistered hypothesis, not an optimized parameter.
    regime = None
    if len(past)>=24 and len(w)>=25 and all(x is not None and number(x[1]) for x in w[1:25]):
        recent = stdev([x[1] for x in w[1:9]])
        older = stdev([x[1] for x in w[9:25]])
        if older > 1e-12:
            regime = "high" if recent > older else "normal"
    f = dict(raw=raw, normalized=norm, raw_rank=describe(raw,rawpast)[1],
             normalized_rank=percentile(norm,past), normalized_n=len(past),
             z=zscore(norm,past), robust_z=zscore(norm,past,"robust"),
             ewma_z=zscore(norm,past,"ewma"), acceleration=accel,
             acceleration_z=zscore(accel,apast,"robust"), persistence=persistence,
             flow_regime=regime, source_end=str(end))
    if weights:
        f["positive_weights"] = [[str(d),flows[d]] for d in obs if flows[d]>0]
    return f


def build_features(dates, days, unit, assets):
    flows = {d:dates[d]*unit for d in days}
    aum = {d:v for d,v in assets.items() if d<=days[-1] and number(v) and v>0}
    aum_days = sorted(aum)
    end = days[-1]
    out = {}
    for key in PERIODS:
        f = features(flows,days,aum,aum_days,end,key,weights=True)
        replay = []
        # Current-vintage replay is exploratory only; no historical release
        # time or revision vintage is asserted. Assumed 7 calendar day delay.
        for i in range(1,REPLAY_LIMIT[key]+1):
            target = boundary(end,key,i)
            j = bisect_right(days,target)-1
            if j<0 or (target-days[j]).days>4:
                continue
            historical_end = days[j]
            x = features(flows,days,aum,aum_days,historical_end,key)
            if x:
                replay.append(x)
        out[key] = (f,replay)
    return out


def cot_feature(h, history, key):
    if not h.get("cot_end") or not number(h.get("cot_change_pp")):
        return None
    end = date.fromisoformat(h["cot_end"])
    days = sorted(d for d in history if d<=end)
    past = []
    for i in range(1,53):
        stop,start = boundary(end,key,i),boundary(end,key,i+1)
        a = min(days,key=lambda d:abs((d-stop).days),default=None)
        b = min(days,key=lambda d:abs((d-start).days),default=None)
        if a is not None and b is not None and a>b and abs((a-stop).days)<=3 and abs((b-start).days)<=3:
            past.append(history[a]-history[b])
    return zscore(h["cot_change_pp"],past,"robust")


def candidates(f, *, base=None, cot=None, cross=None, proxy=None):
    """None is unavailable, WAIT is a genuine evaluated decision."""
    raw, norm = f.get("raw"),f.get("normalized")
    d = action(raw) if number(raw) else None
    def gate(metric, condition):
        return None if not number(metric) or d is None else d if condition and raw!=0 else WAIT
    def zg(v, threshold=1.5):
        return gate(v, number(v) and abs(v)>=threshold and v*raw>0 if number(raw) else False)
    rr, nr = f.get("raw_rank"),f.get("normalized_rank")
    p = f.get("persistence")
    regime = f.get("flow_regime")
    out = {
        BASE:base,
        "M01_raw_percentile":gate(rr,number(rr) and rr>=75),
        "M02_aum_percentile":gate(nr,number(nr) and nr>=75),
        "M03_zscore":zg(f.get("z")),
        "M04_robust_zscore":zg(f.get("robust_z")),
        "M05_ewma_zscore":zg(f.get("ewma_z")),
        "M06_acceleration":zg(f.get("acceleration_z")),
        "M07_persistence":gate(p,number(p) and p>=.65 and number(nr) and nr>=60) if number(nr) else None,
        "M08_cot_anomaly":zg(cot) if number(nr) and nr>=60 else WAIT if number(cot) and number(nr) else None,
        "M09_cross_asset":gate(cross,number(cross) and abs(cross)>=.6 and number(norm) and cross*norm>0),
        "M10_regime":gate(nr,number(nr) and nr >= (85 if regime=="high" else 70)) if regime else None,
        PROXY:gate(proxy,number(proxy) and proxy<=0 and raw>0 and number(nr) and nr>=75) if number(raw) and number(nr) else None,
    }
    votes = [out[m] for m in ("M02_aum_percentile","M03_zscore","M04_robust_zscore","M05_ewma_zscore","M06_acceleration","M07_persistence") if out[m] is not None]
    out["M12_ensemble"] = (d if d and d!=WAIT and votes.count(d)>=max(3,(len(votes)+1)//2) else WAIT) if len(votes)>=4 else None
    return out


def cross_scores(rows):
    """Signed relative rank, same observed date, at least six valid peers."""
    result = {}
    for key in PERIODS:
        groups = {}
        for r in rows:
            if not usable(r):
                continue
            f = r.get("horizons",{}).get(key,{}).get("adaptive_features",{})
            if number(f.get("normalized")):
                groups.setdefault(f["source_end"],[]).append((r["symbol"],f["normalized"]))
        for pairs in groups.values():
            if len(pairs)<6:
                continue
            for sym,v in pairs:
                # Ties receive midrank; signed rank -1 to +1.
                rank = (sum(x<v for _,x in pairs)+.5*(sum(x==v for _,x in pairs)-1))/(len(pairs)-1)
                result[sym,key]=2*rank-1
    return result


def usable(row):
    return not any(row.get(k) for k in ("error","stale","cached_source"))


def record(rows):
    """Freeze all prospective features and actions. No production promotion."""
    cross = cross_scores(rows)
    replay = []
    for r in rows:
        for key,h in r.get("horizons",{}).items():
            f = h.get("adaptive_features",{})
            f.pop("positive_weights",None)
            history = h.pop("adaptive_replay",[])
            if not usable(r) or not f:
                h.pop("adaptive_features",None)
                continue
            base = h.get("early_methods",{}).get("flow_position")
            methods = candidates(f,base=base,cot=f.get("cot_z"),
                                 cross=cross.get((r["symbol"],key)),proxy=f.get("cost_proxy_gap_pct"))
            f["cross_rank"] = cross.get((r["symbol"],key))
            h["adaptive_version"] = VERSION
            h["adaptive_methods"] = methods
            for x in history:
                replay.append(dict(symbol=r["symbol"],horizon=key,
                                   assumed_signal_day=str(date.fromisoformat(x["source_end"])+timedelta(days=7)),
                                   source_end=x["source_end"],methods=candidates(x)))
    return replay
