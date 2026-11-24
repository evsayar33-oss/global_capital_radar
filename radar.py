"""Kamuya açık verilerden tarihli makro ve sermaye akışı raporu."""
from ici import parse as parse_ici
import calendar
import csv
import io
import json
import math
import os
from urllib.parse import urlencode
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from time import sleep

ROOT = Path(__file__).resolve().parent
HORIZONS = {"1G": 1, "1H": 7, "1A": -1, "3A": -3, "1Y": -12}


def read(url):
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers={"User-Agent": "global-capital-radar/1.0"}), timeout=20) as response:
                return response.read().decode("utf-8-sig")
        except HTTPError as exc:
            if attempt or exc.code not in (408,429,500,502,503,504):
                raise
        except (URLError,TimeoutError):
            if attempt:
                raise
        sleep(1)


def month(d, offset):
    year, m = divmod(d.year * 12 + d.month - 1 + offset, 12)
    return date(year, m + 1, min(d.day, calendar.monthrange(year, m + 1)[1]))


def fred_with_source(key):
    today = datetime.now(timezone.utc).date()
    start = str(today - timedelta(days=800))
    secret = os.getenv("FRED_API_KEY")
    api_error = None
    if secret:
        try:
            query = urlencode(dict(series_id=key, api_key=secret, file_type="json", observation_start=start))
            payload = json.loads(read("https://api.stlouisfed.org/fred/series/observations?" + query))
            rows = {}
            for row in payload["observations"]:
                d = date.fromisoformat(row["date"])
                if d in rows:
                    raise ValueError("duplicate FRED API observation")
                if row["value"] in ("", "."):
                    continue
                v = float(row["value"])
                if not math.isfinite(v):
                    raise ValueError("nonfinite FRED API observation")
                rows[d] = v
            if not rows:
                raise ValueError("empty FRED API series")
            return rows, dict(source="FRED API", source_series=key,
                              observation_basis="CURRENT_VINTAGE", historical_vintage_verified=False)
        except Exception as exc:
            # Never include an authenticated URL in a persisted error.
            api_error = type(exc).__name__
    data = csv.DictReader(io.StringIO(read("https://fred.stlouisfed.org/graph/fredgraph.csv?" +
                                           urlencode(dict(id=key, cosd=start)))))
    if not data.fieldnames or key not in data.fieldnames:
        raise ValueError("FRED CSV identity mismatch")
    rows = {}
    for row in data:
        if row[key] not in ("", "."):
            value = float(row[key])
            if not math.isfinite(value):
                raise ValueError("Geçersiz değer")
            rows[date.fromisoformat(row[data.fieldnames[0]])] = value
    if not rows:
        raise ValueError("Boş seri")
    return rows, dict(source="FRED graph CSV", source_series=key, observation_basis="CURRENT_VINTAGE",
                      historical_vintage_verified=False, api_error=api_error)


def fred(key):
    return fred_with_source(key)[0]


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
    from macro_sources import SUPPORTED, fresh_series
    try:
        data, source = fred_with_source(meta["id"])
        row = summarize(dict(meta, **source), data, today)
        if not row["stale"] or meta["id"] not in SUPPORTED:
            return row, data
        primary_error = "FRED series stale"
    except Exception as exc:
        primary_error = type(exc).__name__ + ": " + str(exc)
    if meta["id"] in SUPPORTED:
        try:
            data, source = fresh_series(meta["id"], today, read, meta["max_age"])
            row = summarize(dict(meta, **source), data, today)
            row.update(primary_error=primary_error, source_status="DIRECT_SOURCE_OBSERVED")
            return row, data
        except Exception as exc:
            return dict(meta, error=primary_error, alternative_error=type(exc).__name__ + ": " + str(exc)), {}
    return dict(meta, error=primary_error), {}


def attach_last_verified(rows, history):
    # Display evidence only. Never put old values in current row, forecast or conditions.
    wanted = {r["id"]: r for r in rows if r.get("error")}
    for path in sorted(history.glob("????-??-??.json"), reverse=True):
        if not wanted:
            break
        try:
            payload = json.loads(path.read_text())
            seen = payload["as_of"]
            if not isinstance(seen, str):
                continue
            for old in payload.get("indicators", []):
                key = old.get("id")
                if key not in wanted:
                    continue
                if not old.get("error") and not old.get("stale") and old.get("period") and old.get("value") is not None:
                    previous = {k: old.get(k) for k in ("period", "value", "changes", "source", "source_series", "observation_basis")}
                    previous["observed_at"] = seen
                else:
                    previous = old.get("last_verified")
                    if not previous:
                        continue
                wanted.pop(key)["last_verified"] = previous
        except (OSError, ValueError, KeyError, TypeError):
            continue


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
    # Customs-basis commodity imports are separately named, never substitute BOP.
    if os.getenv("CENSUS_API_KEY"):
        try:
            from keyed_sources import census_crude_imports
            trade, evidence = census_crude_imports(today)
            extra["Census · ABD ham petrol ithalatı (USD)"] = summarize(dict(freq="M",change="pct",max_age=120,**evidence),trade,today)
        except Exception as exc:
            extra["Census · ABD ham petrol ithalatı (USD)"] = {"error":type(exc).__name__,"scope":"CUSTOMS_BASIS_NOT_BOP"}
    flows = [(r, data) for r, data in pairs if r["change"] == "flow"]
    history = ROOT / "history"
    history.mkdir(exist_ok=True)
    path = history / (str(today) + ".json")
    attach_last_verified(rows, history)
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
            previous = r.get("last_verified") or {}
            last = f" · son kayıt {previous['period']}: {previous['value']}" if previous else ""
            lines.append(f"|{r['label']}|Kaynak hatası{last}|—|—|—|—|—|—|—|")
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
