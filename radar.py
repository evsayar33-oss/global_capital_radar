"""Kamuya açık verilerden tarihli makro ve sermaye akışı raporu."""
from ici import parse as parse_ici
import calendar
import csv
import io
import json
import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
HORIZONS = {"1G": 1, "1H": 7, "1A": -1, "3A": -3, "1Y": -12}


def read(url):
    with urlopen(Request(url, headers={"User-Agent": "global-capital-radar/1.0"}), timeout=35) as response:
        return response.read().decode("utf-8-sig")


def month(d, offset):
    year, m = divmod(d.year * 12 + d.month - 1 + offset, 12)
    return date(year, m + 1, min(d.day, calendar.monthrange(year, m + 1)[1]))


def fred(key):
    data = csv.DictReader(io.StringIO(read("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + key)))
    rows = {}
    for row in data:
        if row[key] not in ("", "."):
            value = float(row[key])
            if not math.isfinite(value):
                raise ValueError("Geçersiz değer")
            rows[date.fromisoformat(row[data.fieldnames[0]])] = value
    if not rows:
        raise ValueError("Boş seri")
    return rows


def summarize(meta, data, today):
    series = {d: (1 / v if meta["change"] == "inverse" else v) for d, v in data.items() if d <= today}
    end = max(series)
    kind = meta["change"]
    freq = meta["freq"]
    changes = {}
    for label, step in HORIZONS.items():
        target = month(end, step) if step < 0 else end - timedelta(days=step)
        if (freq in ("M", "Q", "Y") and step > 0) or (freq == "Q" and step == -1) or (freq == "W" and step == 1) or (freq == "Y" and step != -12):
            continue
        prev = max((d for d in series if d <= target), default=None)
        tolerance = 5 if freq == "D" else 0 if freq in ("M", "Q", "Y") else 6
        if prev is None or (target - prev).days > tolerance:
            continue
        current, old = series[end], series[prev]
        if kind in ("inverse", "pct"):
            if old == 0:
                continue
            delta = 100 * (current / old - 1)
        else:
            delta = (current - old) * (100 if kind == "bp" else 1)
        changes[label] = round(delta, 4)
    return dict(meta, period=str(end), value=series[end], changes=changes,
                stale=(today-end).days > int(meta["max_age"]))


def retrieve(meta, today):
    try:
        data = fred(meta["id"])
        return summarize(meta, data, today), data
    except Exception as exc:
        return dict(meta, error=str(exc)), {}


def market_rate(today):
    target = month(today.replace(day=1), 1)
    code = "ZQ" + "FGHJKMNQUVXZ"[target.month-1] + target.strftime("%y") + ".CBT"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=2y"
    chart = json.loads(read(url))["chart"]["result"][0]
    if chart["meta"]["symbol"].upper() != code:
        raise ValueError("Sözleşme eşleşmedi")
    closes = chart["indicators"]["quote"][0]["close"]
    rates = {datetime.fromtimestamp(t, timezone.utc).date(): 100 - v
             for t, v in zip(chart["timestamp"], closes) if v is not None and math.isfinite(v) and v > 0}
    return summarize(dict(freq="D", change="bp", max_age=7, contract=code, target=str(target)), rates, today)


def extras(today):
    out = {}
    for key in ("IMF", "Fed SEP", "Vadeli Fed fonları (%)", "Dünya geniş para / GSYH (%)"):
        try:
            if key == "IMF":
                data = json.loads(read("https://www.imf.org/external/datamapper/api/v1/PCPIPCH/WEOWORLD"))
                curve = data["values"]["PCPIPCH"]["WEOWORLD"]
                out[key] = {str(y): float(curve[str(y)]) for y in (today.year, today.year + 1)}
            elif key.startswith("Vadeli"):
                out[key] = market_rate(today)
            elif key == "Fed SEP":
                out[key] = {str(d.year): v for d, v in sorted(fred("FEDTARMD").items()) if d.year >= today.year}
                if not out[key]:
                    raise ValueError("Projeksiyon bulunamadı")
            else:
                raw = json.loads(read("https://api.worldbank.org/v2/country/WLD/indicator/FM.LBL.BMNY.GD.ZS?format=json&mrnev=2"))
                rows = {date(int(r["date"]), 1, 1): float(r["value"]) for r in raw[1] if r["value"] is not None}
                out[key] = summarize(dict(freq="Y", change="pp", max_age=1100), rows, today)
        except Exception as exc:
            out[key] = {"error": str(exc)}
            if key == "IMF":
                out[key].update(archive="WEO 2026-10-13", archived_forecast={"2026": 4.7, "2027": 4.1},
                                source="https://www.imf.org/en/Publications/WEO/Issues/2026/10/13/world-economic-outlook-october-2026")
    return out


def forecast(flows, today):
    # Tahmin ayı tamamen gelecekte. Referans model son yayımlanan aydır.
    target = str(month(today.replace(day=1), 1))
    signals = []
    for item, data in flows:
        if item.get("error") or item["stale"]:
            continue
        end = date.fromisoformat(item["period"])
        window = [data.get(month(end, -i)) for i in range(3)]
        if None not in window:
            signals.append(dict(id=item["id"], target=target, observed=str(end),
                                estimate=statistics.median(window), baseline=window[0]))
    return signals


def conditions(rows):
    table = {r["id"]: r for r in rows if "error" not in r and not r["stale"]}
    groups = [
        ("Risk iştahı", "1A", {"BAMLH0A0HYM2": -1, "VIXCLS": -1, "NFCI": -1}, "güçleniyor", "zayıflıyor"),
        ("ABD kredi erişimi", "3A", {"TOTLL": 1, "DRTSCILM": -1}, "genişliyor", "daralıyor"),
        ("Dolar gücü", "1A", {"DTWEXBGS": 1, "DEXJPUS": -1, "DEXUSEU": -1}, "artıyor", "azalıyor"),
    ]
    results = []
    for name, h, signs, positive, negative in groups:
        evidence = {k: table[k]["changes"][h] for k in signs if k in table and h in table[k]["changes"]}
        votes = [change * signs[k] for k, change in evidence.items()]
        if len(votes) < len(signs):
            verdict = "veri eksik"
        elif all(v > 0 for v in votes):
            verdict = positive
        elif all(v < 0 for v in votes):
            verdict = negative
        else:
            verdict = "karışık veya yatay"
        results.append(f"- {name} ({h}) · {verdict} · {evidence}")
    return results


def main():
    now = datetime.now(timezone.utc)
    today = now.date()
    with (ROOT / "catalog.csv").open() as f:
        catalog = list(csv.DictReader(f))
    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = list(pool.map(lambda m: retrieve(m, today), catalog))
    rows = [r for r, data in pairs]
    try:
        weekly = parse_ici(read("https://www.ici.org/research/stats/combined_flows"))
        for name, data in weekly.items():
            meta = dict(id="ICI_" + name, label="ICI fon akışı · " + name, freq="W", change="flow", max_age=17)
            rows.append(summarize(meta, data, today))
    except Exception as exc:
        rows.append(dict(id="ICI", label="ICI haftalık fon akışı", error=str(exc)))
    extra = extras(today)
    flows = [(r, data) for r, data in pairs if r["change"] == "flow"]
    history = ROOT / "history"
    history.mkdir(exist_ok=True)
    path = history / (str(today) + ".json")
    signals = forecast(flows, today)
    # İlk başarılı aylık tahmini ve ilk açıklanan sonucu değiştirmeden sakla.
    ledger = history / "forecasts.json"
    records = json.loads(ledger.read_text()) if ledger.exists() else {}
    for signal in signals:
        key = signal["target"] + "/" + signal["id"]
        records.setdefault(key, dict(signal, issued=now.isoformat()))
    for record in records.values():
        if "actual" in record:
            continue
        for r, data in flows:
            actual = data.get(date.fromisoformat(record["target"]))
            if r["id"] == record["id"] and actual is not None and today >= month(date.fromisoformat(record["target"]), 1):
                record.update(actual=actual, first_seen=now.isoformat())
    payload = dict(as_of=now.isoformat(), indicators=rows, expectations=extra)
    for file, obj in [(path, payload), (ledger, records)]:
        temp = file.with_suffix(".tmp")
        temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))
        temp.replace(file)
    lines = [f"# Sermaye radarı · {today}", "", "## Gözlenen yabancı net alımları",
             "", "Milyon USD. Her satırın tarihi işlem ayını gösterir.", ""]
    for r, _ in flows:
        if not r.get("error"):
            lines.append(f"- {r['label']} · {r['period']} · {r['value']:+,.0f}" + (" · gecikmiş" if r["stale"] else ""))
    lines += ["", "## Gelecek ay için araştırma tahmini", "", "Üç aylık medyan, milyon USD. İlk tahmin sabittir.", ""]
    for s in signals:
        v = records[s["target"] + "/" + s["id"]]
        lines.append(f"- {v['target']} · {s['id']} · {v['estimate']:+,.0f}")
    scored = [v for v in records.values() if "actual" in v]
    for code in [r["id"] for r, _ in flows]:
        obs = [v for v in scored if v["id"] == code]
        if obs:
            mae = [statistics.mean(abs(v[k]-v["actual"]) for v in obs) for k in ("estimate", "baseline")]
            lines.append(f"- {code} · {len(obs)} ay · ortalama mutlak hata {mae[0]:,.0f} · son ay modeli {mae[1]:,.0f}")
    if not scored:
        lines.append("Henüz sonuçlanmış ileri test yok.")
    lines += ["", "## Makro koşullar", ""] + conditions(rows)
    lines += ["", "## Gösterge değişimleri", "", "|Gösterge|Dönem|Son değer|Fark birimi|1G|1H|1A|3A|1Y|", "|---|---|---:|---|---:|---:|---:|---:|---:|"]
    units = dict(flow="milyon USD", pct="%", inverse="%", pp="yüzde puan", bp="baz puan", points="puan")
    for r in rows:
        if "error" in r:
            lines.append(f"|{r['label']}|Kaynak hatası|—|—|—|—|—|—|—|")
        else:
            fields = [r["label"], r["period"] + (" (gecikmiş)" if r["stale"] else ""), f"{r['value']:.6g}", units[r["change"]]]
            fields.extend(str(r["changes"].get(h, "—")) for h in HORIZONS)
            lines.append("|" + "|".join(fields) + "|")
    lines += ["", "## Projeksiyonlar ve küresel para", ""]
    for k, v in extra.items():
        lines.append(f"- {k} · {json.dumps(v, ensure_ascii=False)}")
    (ROOT / "LATEST.md").write_text("\n".join(lines) + "\n")
    return int(any(r.get("error") or r.get("stale") for r in rows) or any("error" in v or v.get("stale") for v in extra.values()))


if __name__ == "__main__":
    raise SystemExit(main())
