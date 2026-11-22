"""Aynı uzunlukta, örtüşmeyen geçmiş dönemlerle akış büyüklüğü karşılaştırması."""
from bisect import bisect_right
from datetime import timedelta
from radar import month

PERIODS = {"1H": 0, "1A": 1, "3A": 3, "1Y": 12}


def boundary(end, key, index):
    months = PERIODS[key]
    return month(end, -months*index) if months else end-timedelta(weeks=index)


def describe(value, past):
    count = len(past)
    if count < 5:
        return "Geçmiş yetersiz", None
    magnitude = abs(value)
    rank = 100*(sum(abs(v)<magnitude for v in past)+0.5*sum(abs(v)==magnitude for v in past))/count
    if value == 0 or rank <= 15:
        return "Yatay", round(rank,1)
    direction = "giriş" if value > 0 else "çıkış"
    level = "Olağanüstü" if rank >= 90 else "Güçlü" if rank >= 75 else "Zayıf" if rank <= 40 else "Olağan"
    return f"{level} {direction}", round(rank,1)


def analyze(dates, days, unit):
    end = days[-1]
    result = {}
    for key in PERIODS:
        past = []
        current = None
        for i in range(53):
            stop, start = boundary(end,key,i), boundary(end,key,i+1)
            if start < days[0]:
                break
            window = days[bisect_right(days,start):bisect_right(days,stop)]
            gaps = zip([start]+window,window+[stop])
            if len(window) < 3 or any((b-a).days>6 for a,b in gaps):
                continue
            value = sum(dates[d]*unit for d in window)
            if i == 0:
                current = value
            else:
                past.append(value)
        strength, pct = describe(current,past) if current is not None else ("Veri eksik",None)
        result[key] = dict(net_usd_m=None if current is None else round(current,3), strength=strength,
                           magnitude_percentile=pct, reference_count=len(past))
    return result


def interpret(horizon, key, end, history, stale, today):
    value = horizon["net_usd_m"]
    available = sorted(d for d in history if d <= end)
    confirm = "TEYİTSİZ · karşılaştırılabilir vadeli veri yok"
    if stale:
        confirm = "TEYİTSİZ · akış verisi eski"
    elif available and value is not None:
        last = available[-1]
        target = boundary(last,key,1)
        prior = sorted((d for d in available if d < last), key=lambda d: (-abs((target-d).days), -d.toordinal()))
        if prior and abs((target-prior[-1]).days)<=3 and (end-last).days<=6 and (today-last).days<=13:
            delta = round(history[last]-history[prior[-1]],3)
            horizon.update(cot_change_pp=delta, cot_start=str(prior[-1]), cot_end=str(last))
            confirm = "YÖN UYUMLU" if value*delta>0 else "TEYİTSİZ · yönler çelişiyor" if value*delta<0 else "TEYİTSİZ · yön yok"
    horizon["confirmation"] = confirm
    strength = horizon["strength"]
    if strength.startswith(("Veri","Geçmiş")) or stale:
        action = "BEKLE · veri yetersiz"
    elif strength == "Yatay" or strength.startswith("Zayıf"):
        action = "BEKLE · akış zayıf veya yatay"
    elif confirm != "YÖN UYUMLU":
        action = "BEKLE · yön teyitsiz"
    elif strength.startswith(("Güçlü","Olağanüstü")):
        action = "ALIM ADAYI" if value > 0 else "AZALTMA ADAYI"
    else:
        action = "Girişi izle" if value > 0 else "Çıkışı izle"
    horizon["action"] = action
