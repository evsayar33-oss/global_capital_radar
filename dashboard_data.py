"""Read-only dashboard projections; never feed these into production decisions."""
import json
import re
from pathlib import Path


def read_report(root, relative):
    try:
        data = json.loads((Path(root) / relative).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}, f"{relative}: beklenen JSON nesnesi bulunamadı"
        return data, None
    except (OSError, ValueError) as exc:
        return {}, f"{relative}: {type(exc).__name__}"


def latest_macro(root):
    paths = sorted(p.name for p in Path(root).glob("*.json")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", p.name))
    return read_report(root, paths[-1]) if paths else ({}, "Günlük makro raporu bulunamadı")


def coverage_rows(report):
    return [{
        "Fon": row.get("symbol"), "Durum": row.get("status"),
        "Kaynak": (row.get("provenance") or {}).get("source"),
        "Başlangıç": (row.get("provenance") or {}).get("coverage_start"),
        "Bitiş": (row.get("provenance") or {}).get("coverage_end"),
        "Günlük gözlem": (row.get("provenance") or {}).get("daily_count"),
        **{f"{h} yöntem kapsamı": (row.get("model_coverage") or {}).get(h) for h in ("1H", "1A", "3A", "1Y")},
        "Hata": row.get("error"),
    } for row in report.get("coverage", [])]


def method_rows(cohorts, horizon=None):
    rows = []
    for cohort, result in cohorts.items():
        if horizon and not cohort.endswith("/" + horizon):
            continue
        for method, data in result.get("models", {}).items():
            cost = data.get("cost_stress") or {}
            rows.append({
                "Fon/vade": cohort, "Yöntem": method,
                "Bağımsız dönem": result.get("independent_periods"),
                "Ölçülebilen": data.get("available"), "Aktif sinyal": data.get("active"),
                "İsabet %": None if data.get("hit_rate") is None else 100 * data["hit_rate"],
                **{f"{bps} bp ort. SGOV farkı (puan)": cost.get(key, {}).get("mean_pp")
                   for bps, key in ((10, "0.1"), (30, "0.3"), (50, "0.5"))},
                "30 bp alt %95 sınırı": cost.get("0.3", {}).get("lower95_pp"),
                "Durum": result.get("status"),
            })
    return rows


def native_rows(report):
    rows = []
    for key, item in report.items():
        rows.append({
            "Veri": key, "Kaynak": item.get("source"), "Durum": item.get("status"),
            "Veri tarihi": item.get("source_date") or item.get("funding_asof") or item.get("latest_report_date"),
            "Funding % (yıllık)": item.get("annualized_pct"), "Basis %": item.get("basis_pct"),
            "Spread bp (kotasyon)": item.get("quoted_spread_bps"),
            "AUM USD": item.get("reported_aum_usd"), "Tahmini yaratım USD": item.get("estimated_creation_usd"),
            "WTI yakın vade farkı USD/varil": item.get("front_minus_next_usd_per_barrel"),
            "İhale iskonto %": item.get("high_discount_rate_pct"), "10Y reel faiz %": item.get("real_yield_10y_pct"),
            "Hata / açıklama": item.get("error") or item.get("reason") or item.get("caveat"),
            "Rol": item.get("role"), "Kaynak bağlantısı": item.get("source_url"),
        })
    return rows


def historical_rows(report):
    return [{
        "Fon": symbol, "Kesintili günlük kayıt": v.get("sparse_daily_count"),
        "Günlük başlangıç": v.get("daily_start"), "Günlük bitiş": v.get("daily_end"),
        "Aylık kayıt": v.get("monthly_count"), "Aylık başlangıç": v.get("monthly_start"),
        "Aylık bitiş": v.get("monthly_end"), "Günlük kesintisiz": v.get("daily_history_contiguous"),
        "Üretime uygun": v.get("production_eligible"), "Hata": " | ".join(v.get("errors", [])),
    } for symbol, v in report.get("symbols", {}).items()]


def macro_rows(report):
    return [{
        "Gösterge": row.get("label"), "Seri": row.get("id"), "Dönem": row.get("period"),
        "Değer": row.get("value"), "Frekans": row.get("freq"), "Fark birimi": row.get("change"),
        **{h: (row.get("changes") or {}).get(h) for h in ("1G", "1H", "1A", "3A", "1Y")},
        "Durum": "Kaynak hatası" if row.get("error") else ("Eski" if row.get("stale") else "Gözlem"),
        "Hata": row.get("error"),
    } for row in report.get("indicators", [])]
