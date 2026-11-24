"""Varlık bazında ETF talebi, vadeli pozisyon ve ileriye dönük araştırma kaydı."""
import csv
import io
import json
import math
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from radar import read, month
from horizons import analyze, interpret

ROOT = Path(__file__).resolve().parent
# Fon, ekonomik maruziyet, CFTC standart vadeli kontrat kodu.
ASSETS = [
    ("SPY", "S&P 500", "13874A"), ("QQQ", "Nasdaq-100", "209742"),
    ("DIA", "Dow Jones", "124603"), ("IWM", "Russell 2000", "239742"),
    ("SGOV", "ABD Hazine bonosu · 0–3 ay", None),
    ("SHY", "ABD Hazine tahvili · 1–3 yıl", "042601"),
    ("GLD", "Altın", "088691"), ("SLV", "Gümüş", "084691"),
    ("CPER", "Bakır vadeli", "085692"), ("USO", "WTI petrol vadeli", "067651"),
    ("IBIT", "Bitcoin", "133741"), ("ETHA", "Ether", "146021"),
]


class FlowChart(HTMLParser):
    points = None
    aum = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "fund-flow-chart-container":
            self.points = json.loads(attrs["data-series"])
        if attrs.get("id") == "aumcontainer":
            self.aum = json.loads(attrs["data-series"])[2]


def flows(html, today, *, detailed=False):
    chart = FlowChart()
    chart.feed(html)
    if not chart.points:
        raise ValueError("ETF akış grafiği eksik")
    dates = {}
    for ts, val in chart.points:
        day = datetime.fromtimestamp(ts / 1000, timezone.utc).date()
        if day in dates or day > today or val is None or not math.isfinite(val):
            raise ValueError("ETF tarih/değer dizisi geçersiz")
        dates[day] = val
    days = sorted(dates)
    end = days[-1]
    if len(days) < 5:
        raise ValueError("ETF geçmişi eksik")
    match = re.search(r'5 Day Net Flows:</b>\s*([+−\-\d.,]+)\s*([KMB]?)\s*<', html)
    if not match:
        raise ValueError("Dolar birimi doğrulanamadı")
    display = float(match[1].replace(",", "").replace("−", "-")) * {"":1, "K":1e3, "M":1e6, "B":1e9}[match[2]]
    five = sum(dates[d] for d in days[-5:])
    scales = [s for s in (1,1e3,1e6,1e9) if math.isclose(five*s, display, rel_tol=.011, abs_tol=.01)]
    if len(scales) != 1:
        raise ValueError("Akış birimi haftalık tutarla eşleşmedi")
    unit = scales[0] / 1e6
    result = {"1G": round(dates[end]*unit, 3)}
    for key, start in [("1H", end-timedelta(days=7)), ("1A", month(end,-1)), ("3A", month(end,-3)), ("1Y", month(end,-12))]:
        window = [d for d in days if start < d <= end]
        if days[0] <= start and not any((b-a).days > 7 for a,b in zip([start]+window,window)):
            result[key] = round(sum(dates[d] for d in window)*unit, 3)
    # Önceki 52 ayrı haftayla karşılaştır. Haftaların eksiksiz kapsanmasını iste.
    reference = []
    for i in range(1, 53):
        stop = end-timedelta(weeks=i)
        start = stop-timedelta(weeks=1)
        observations = [dates[d] for d in days if start < d <= stop]
        if days[0] <= start and len(observations) >= 3:
            reference.append(sum(observations)*unit)
    percentile = None
    if len(reference) == 52 and "1H" in result:
        percentile = round(100*sum(v <= result["1H"] for v in reference)/len(reference))
    if detailed:
        horizons = analyze(dates, days, unit)
        assets = {}
        if chart.aum:
            assets = {datetime.fromtimestamp(ts/1000,timezone.utc).date():v*unit for ts,v in chart.aum if v is not None and math.isfinite(v) and v>0}
            from horizons import boundary
            for key,h in horizons.items():
                target = boundary(end,key,1)
                prior = sorted(d for d in assets if d<=target)
                if prior and (target-prior[-1]).days<=4 and h["net_usd_m"] is not None:
                    h["flow_aum_pct"]=100*h["net_usd_m"]/assets[prior[-1]]
                    h["aum_asof"]=str(prior[-1])
        from adaptive_flow import build_features
        research = build_features(dates, days, unit, assets)
        for key,h in horizons.items():
            h['adaptive_features'],h['adaptive_replay'] = research[key]
        return end, result, percentile, horizons
    return end, result, percentile


def cot_archive(today):
    histories = {}
    years = [today.year-1, today.year]
    for year in years:
        url = f"https://www.cftc.gov/files/dea/history/deacot{year}.zip"
        try:
            with urlopen(Request(url,headers={"User-Agent":"global-capital-radar/1.0"}), timeout=30) as r:
                archive = zipfile.ZipFile(io.BytesIO(r.read()))
        except Exception:
            if year < today.year or (histories and today.month == 1):
                continue
            raise
        with archive, archive.open("annual.txt") as data:
            for row in csv.DictReader(io.TextIOWrapper(data,encoding="latin1")):
                code = row["CFTC Contract Market Code"]
                if code not in CODES:
                    continue
                day = date.fromisoformat(row["As of Date in Form YYYY-MM-DD"])
                if day <= today:
                    oi = int(row["Open Interest (All)"])
                    if oi > 0:
                        net = int(row["Noncommercial Positions-Long (All)"]) - int(row["Noncommercial Positions-Short (All)"])
                        histories.setdefault(code,{})[day] = 100*net/oi
    return histories


CODES = {code for _,_,code in ASSETS if code}


def cot_with_source(today):
    from secondary_sources import cot_api, combine_cot
    primary,primary_error={},None
    try:
        primary=cot_archive(today)
    except Exception as exc:
        primary_error=str(exc)
    try:
        secondary=cot_api(today,CODES,read)
        if primary:
            joined,ok=combine_cot(primary,secondary)
            return joined, {"transport":"CFTC archive + matched API" if ok else "CFTC archive",
                            "api_overlap_verified":ok}
        return secondary,{"transport":"CFTC API fallback","archive_error":primary_error}
    except Exception as exc:
        if primary:
            return primary,{"transport":"CFTC archive","api_error":str(exc)}
        raise ValueError("Both CFTC transports unavailable: "+str(primary_error)+" / "+str(exc)) from exc


def cot(today):
    return cot_with_source(today)[0]


def classify(values, position):
    week, mo = values.get("1H"), values.get("1A")
    if week is None or mo is None:
        return "VERİ EKSİK"
    if week > 0 and mo > 0:
        return "ALIM ADAYI" if position is not None and position > 0 else "GİRİŞ İZLE"
    if week < 0 and mo < 0:
        return "AZALTMA ADAYI" if position is not None and position < 0 else "ÇIKIŞ İZLE"
    return "BEKLE"


def fund_history(symbol, url, today):
    # Yerel kaynak önbelleği sadece grafiği ve birimi doğrulanmış sayfalar içerir.
    cache = ROOT/".cache"/(symbol+".html")
    try:
        html = read(url)
        parsed = flows(html, today, detailed=True)
    except Exception:
        if not cache.is_file():
            raise
        return flows(cache.read_text(), today, detailed=True), True
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(html)
    return parsed, False


def snapshot(asset, today, positions):
    symbol, name, code = asset
    row = dict(symbol=symbol, asset=name, cash_source=f"https://etfdb.com/etf/{symbol}/", cot_code=code)
    history = positions.get(code,{})
    delta = None
    if history:
        latest = max(history)
        previous = latest-timedelta(days=7)
        if (today-latest).days <= 13 and previous in history:
            delta = round(history[latest]-history[previous],3)
        row.update(cot_asof=str(latest), cot_change_pp=delta)
    try:
        (end, values, percentile, horizons), cached = fund_history(symbol, row["cash_source"], today)
        row["cached_source"] = cached
        stale = (today-end).days > 7
        for key, horizon in horizons.items():
            interpret(horizon, key, end, history, stale, today)
            from adaptive_flow import cot_feature
            if horizon.get('adaptive_features'):
                horizon['adaptive_features']['cot_z'] = cot_feature(horizon,history,key)
            if symbol == "SGOV" and not history:
                horizon["confirmation"] = "TEYİTSİZ · CME TBF3 pozisyon serisi yok"
            if cached:
                horizon.update(confirmation="TEYİTSİZ · kaynak yeniden okunamadı",action="BEKLE · önbellek")
        row["horizons"] = horizons
        row.update(flow_asof=str(end), net_usd_m=values, weekly_percentile=percentile, stale=stale,
                   status="VERİ ESKİ" if stale else classify(values, delta))
    except Exception as exc:
        row.update(error=str(exc), status="VERİ EKSİK")
    return row


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    try:
        positions, cot_source = cot_with_source(today)
        error = None
    except Exception as exc:
        positions, error, cot_source = {}, str(exc), {"transport":"unavailable"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda a: snapshot(a, today, positions), ASSETS))
    archive_folder = ROOT/"history"/"rotation"
    missing = {r["symbol"]:r for r in rows if r.get("error")}
    for path in sorted(archive_folder.glob("2*.json"), reverse=True):
        if not missing:
            break
        try:
            prior_report = json.loads(path.read_text())
        except (ValueError, OSError) as exc:
            print(f"Invalid historical observation excluded: {path.name}: {exc}")
            continue
        for old in prior_report["assets"]:
            symbol = old["symbol"]
            if symbol not in missing or not old.get("net_usd_m") or old.get("error"):
                continue
            row = missing.pop(symbol)
            for field in ("flow_asof","net_usd_m","weekly_percentile"):
                row[field] = old.get(field)
            row["horizons"] = {}
            for key in ("1H","1A","3A","1Y"):
                h = dict(old.get("horizons",{}).get(key,{}))
                h.update(net_usd_m=row["net_usd_m"].get(key), confirmation="TEYİTSİZ · kaynak okunamadı",action="BEKLE · önceki gözlem")
                h.setdefault("strength","Güç ölçülemedi")
                row["horizons"][key]=h
    from secondary_sources import capture_etfiq
    secondary_flow = capture_etfiq(ROOT,today,rows,read)
    from price_context import enrich
    price_errors = enrich(rows,today)
    from experiments import record
    record(rows)
    from adaptive_flow import record as record_adaptive
    from adaptive_evaluation import atomic
    replay = record_adaptive(rows)
    # Keep last valid replay if source is temporarily unavailable. Merge by
    # symbol only when a newly observed source is usable; never pretend stale
    # replay is a fresh forward observation.
    replay_path = ROOT/"history/adaptive_replay.json"
    if replay:
        old_replay = json.loads(replay_path.read_text()) if replay_path.exists() else []
        updated = {r["symbol"] for r in replay}
        atomic(replay_path,[r for r in old_replay if r["symbol"] not in updated]+replay)
    payload = dict(price_errors=price_errors, schema_version=4, seen_at=now.isoformat(), cot_error=error, cot_source=cot_source, secondary_flow=secondary_flow, assets=rows)
    folder = ROOT/"history"/"rotation"
    folder.mkdir(exist_ok=True,parents=True)
    # Her çalıştırmanın bilgi kümesi korunur. Tüketiciler latest.json okur.
    data = json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False)
    archive = folder/(now.strftime("%Y%m%dT%H%M%S%fZ")+".json")
    temp_archive = archive.with_suffix(".tmp")
    temp_archive.write_text(data)
    temp_archive.replace(archive)
    temp = folder/"latest.tmp"
    temp.write_text(data)
    temp.replace(folder/"latest.json")
    lines = ["# Varlıklar arası sermaye takibi", "", str(today)+" · Araştırma",
             "", "Akışlar seçili ABD fonunda milyon USD. COT farkı haftalık yüzde puan.",
             "", "|Varlık · fon|Akış son tarihi|1G|1H|1A|3A|1Y|Haftalık yüzdelik|COT tarihi|COT farkı|",
             "|---|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for row in rows:
        fields = [row["asset"]+" · "+row["symbol"],row.get("flow_asof","—")]
        fields.extend(str(row.get("net_usd_m",{}).get(k,"—")) for k in ("1G","1H","1A","3A","1Y"))
        fields.extend([str(row.get("weekly_percentile","—")),row.get("cot_asof","—"),str(row.get("cot_change_pp","—"))])
        lines.append("|"+"|".join(fields)+"|")
    lines += ["", "## Vadeye göre sonuç", "", "Yüzdelik, bu fonun mutlak net akışını aynı uzunluktaki geçmiş dönemlerle karşılaştırır. Vadeli pozisyonların yön uyumu fiyat tahmini değildir.", ""]
    for key,title in [("1H","1 hafta"),("1A","1 ay"),("3A","3 ay"),("1Y","1 yıl")]:
        lines += [f"### {title}", "", "|Varlık|Net milyon USD|Geçmiş dönem|Yüzdelik|Akış gücü|Vadeli teyit|Araştırma kararı|", "|---|---:|---:|---:|---|---|---|"]
        for row in rows:
            h = row.get("horizons", {}).get(key, {})
            fields = [row["asset"], h.get("net_usd_m"), h.get("reference_count"), h.get("magnitude_percentile"),
                      h.get("strength","Veri eksik"),h.get("confirmation","TEYİTSİZ"),h.get("action","BEKLE")]
            lines.append("|"+"|".join(str(v) if v is not None else "—" for v in fields)+"|")
        lines.append("")
    (ROOT/"ROTATION.md").write_text("\n".join(lines)+"\n")
    return int(any(r.get("error") or r.get("stale") or r.get("cached_source") or (r["cot_code"] and r.get("cot_change_pp") is None) for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
