"""Bounded, source-native public macro series. No synthetic or spliced observations."""
import csv
import hashlib
import io
import json
import math
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

BLS = {
    "CPIAUCSL": "CUSR0000SA0",
    "CPILFESL": "CUSR0000SA0L1E",
    "CES0500000003": "CES0500000003",
}
TREASURY = {"DGS2": ("daily_treasury_yield_curve", "2 YR"),
            "DFII10": ("daily_treasury_real_yield_curve", "10 YR")}
NYFED = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
SUPPORTED = tuple(BLS) + tuple(TREASURY) + ("DFF",)


def finite(value):
    v = float(value)
    if not math.isfinite(v):
        raise ValueError("nonfinite macro observation")
    return v


def add(rows, d, value, today):
    if d > today or d in rows:
        raise ValueError("future or duplicate macro observation")
    rows[d] = finite(value)


def meta(source, identity, urls, bodies, basis):
    return dict(source=source, source_series=identity, source_urls=urls,
                source_sha256=[hashlib.sha256(b.encode()).hexdigest() for b in bodies],
                observation_basis=basis, historical_vintage_verified=False,
                publication_intraday_verified=False)


def bls_series(key, today, reader):
    identity = BLS[key]
    url = BLS_URL + identity
    raw = reader(url)
    data = json.loads(raw)
    series = data.get("Results", {}).get("series", [])
    if data.get("status") != "REQUEST_SUCCEEDED" or len(series) != 1 or series[0].get("seriesID") != identity:
        raise ValueError("BLS status or series identity mismatch")
    rows = {}
    for row in series[0]["data"]:
        p = row["period"]
        if p == "M13":
            continue
        if not re.fullmatch(r"M(0[1-9]|1[0-2])", p):
            raise ValueError("BLS nonmonthly period")
        d = date(int(row["year"]), int(p[1:]), 1)
        if row["value"] in ("", ".", "-"):
            continue
        add(rows, d, row["value"], today)
    return rows, meta("US Bureau of Labor Statistics", identity, [url], [raw],
                      "SOURCE_NATIVE_CURRENT_MONTHLY")


def treasury_series(key, today, reader):
    kind, field = TREASURY[key]
    rows, urls, bodies = {}, [], []
    # Two year partitions cover the 12-month comparison even in January.
    for year in (today.year - 1, today.year):
        url = TREASURY_URL + f"{year}/all?" + urlencode({"type": kind})
        raw = reader(url)
        reader_csv = csv.DictReader(io.StringIO(raw.lstrip("\ufeff")))
        fields = {f.strip().upper(): f for f in (reader_csv.fieldnames or [])}
        if not {"DATE", field} <= fields.keys():
            raise ValueError("Treasury CSV field identity mismatch")
        for row in reader_csv:
            d = datetime.strptime(row[fields["DATE"]], "%m/%d/%Y").date()
            if d.year != year or d > today:
                raise ValueError("Treasury date outside requested year")
            # Do not use potentially unfinished current-day curve.
            if d == today or row[fields[field]].strip() in ("", ".", "N/A"):
                continue
            add(rows, d, row[fields[field]], today)
        urls.append(url); bodies.append(raw)
    return rows, meta("US Treasury", kind + "/" + field, urls, bodies,
                      "SOURCE_NATIVE_CURRENT_PAR_YIELD")


def effr_series(today, reader):
    url = NYFED + "?" + urlencode({"startDate": str(today - timedelta(days=450)), "endDate": str(today)})
    raw = reader(url)
    rows = {}
    for row in json.loads(raw)["refRates"]:
        if row.get("type") != "EFFR":
            raise ValueError("NY Fed rate type mismatch")
        add(rows, date.fromisoformat(row["effectiveDate"]), row["percentRate"], today)
    return rows, meta("Federal Reserve Bank of New York", "EFFR", [url], [raw],
                      "SOURCE_NATIVE_BUSINESS_DAYS_NO_WEEKEND_FILL")


def direct_series(key, today, reader):
    if key in BLS:
        return bls_series(key, today, reader)
    if key in TREASURY:
        return treasury_series(key, today, reader)
    if key == "DFF":
        return effr_series(today, reader)
    raise ValueError("no verified source mapping")


def fresh_series(key, today, reader, max_age):
    data, provenance = direct_series(key, today, reader)
    if not data or (today-max(data)).days > int(max_age):
        raise ValueError("direct source stale or empty")
    if (max(data)-min(data)).days < 365:
        raise ValueError("direct source lacks one-year coverage")
    return data, provenance


def main():
    from concurrent.futures import ThreadPoolExecutor
    from radar import read
    from datetime import timezone
    today = datetime.now(timezone.utc).date()
    ages = {**{k: 75 for k in BLS}, **{k: 10 for k in TREASURY}, "DFF": 10}
    def probe(key):
        try:
            rows, evidence = fresh_series(key, today, read, ages[key])
            return dict(series=key,status="OBSERVED",last=str(max(rows)),observations=len(rows),
                        latest=rows[max(rows)],source=evidence["source"],basis=evidence["observation_basis"])
        except Exception as exc:
            return dict(series=key,status="UNAVAILABLE",error=type(exc).__name__+": "+str(exc))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, SUPPORTED))
    for result in results:
        print("DIRECT_MACRO_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    # Require two genuinely recovered series from at least one official source.
    # Individual missing sources remain visible and never count as successful.
    return 0 if sum(r["status"]=="OBSERVED" for r in results)>=2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
