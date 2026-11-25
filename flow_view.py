"""Shared, read-only, horizon-specific observation projection. No strategy promotion."""
from datetime import date
from math import isfinite
from horizons import boundary

HORIZONS = {"1G":"1 gün", "1H":"1 hafta", "1A":"1 ay", "3A":"3 ay", "1Y":"1 yıl"}
WAIT = "BEKLE · araştırma gözlemi; üretim onayı yok"

def number(value):
    return isinstance(value, (int, float)) and not isinstance(value,bool) and isfinite(value)

def as_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None

def direction(value):
    return "Giriş" if value > 0 else "Çıkış" if value < 0 else "Net sıfır"

def horizon_data(item, key, primary=False):
    if key != "1G":
        return dict((item.get("horizons") or {}).get(key) or {})
    if primary:
        value = (item.get("net_usd_m") or {}).get("1G")
    else:
        daily = item.get("daily_flow_usd")
        value = daily / 1e6 if number(daily) else None
    h = dict(item.get("daily_observation") or {})
    h["net_usd_m"] = value
    h.setdefault("strength", "Geçmiş yetersiz" if number(value) else "Veri eksik")
    return h

def observation(asset, continuity, key, expired=False):
    if key not in HORIZONS:
        raise ValueError("unknown horizon")
    broken = any(asset.get(k) for k in ("error","cached_source","stale"))
    record = (continuity.get("assets") or {}).get(asset["symbol"]) or {}
    candidates = []
    if not broken and as_date(asset.get("flow_asof")):
        candidates.append(("ETFdb",asset,horizon_data(asset,key,True),False,True))
    for item in [record.get("selected"), *(record.get("candidates") or []), record.get("stale_reference")]:
        if not item or not as_date(item.get("flow_asof")) or not item.get("provider"):
            continue
        if item.get("status") not in ("OBSERVED","STALE_REFERENCE"):
            continue
        stale = bool(item.get("stale") or item.get("status")=="STALE_REFERENCE")
        candidates.append((item["provider"],item,horizon_data(item,key),stale,False))
    def score(entry):
        source,item,h,stale,primary=entry
        valid=number(h.get("net_usd_m"))
        return (valid, not stale, primary, item["flow_asof"],
                number(h.get("flow_aum_pct")), h.get("reference_count") or 0, item.get("daily_count") or 0)
    if not candidates:
        return dict(source=None,asof=None,period_start=None,h={},stale=True,
                    primary=False,status="UNAVAILABLE",action="BEKLE · veri yok",
                    explanation="Doğrulanmış kaynak gözlemi yok")
    source,item,h,stale,primary=max(candidates,key=score)
    day=as_date(item.get("flow_asof"))
    start=day if key=="1G" else boundary(day,key,1)
    reasons=[]
    if expired or stale: reasons.append("Eski gözlem; sinyalde kullanılmaz")
    if not number(h.get("net_usd_m")): reasons.append("Seçili vade için kesintisiz akış yok")
    if h.get("flow_aum_pct") is None: reasons.append("Dönem başı AUM doğrulanmadı")
    if h.get("magnitude_percentile") is None: reasons.append("Akış gücü için geçmiş yetersiz")
    value=h.get("net_usd_m")
    return dict(source=source,asof=str(day),period_start=str(start),h=h,
                stale=expired or stale,primary=primary,
                status="ESKİ · yalnız referans" if expired or stale else "Birincil gözlem" if primary else "ALTERNATIVE_OBSERVED",
                action="BEKLE · rapor eski" if expired or stale else h.get("action","BEKLE") if primary and key!="1G" else WAIT,
                explanation="; ".join(reasons),direction=direction(value) if number(value) else "Veri eksik",
                daily_flow_usd=item.get("daily_flow_usd") if not primary else (item.get("net_usd_m") or {}).get("1G",0)*1e6 if number((item.get("net_usd_m") or {}).get("1G")) else None,
                precision=(item.get("provenance") or {}).get("precision"),daily_count=item.get("daily_count"))
