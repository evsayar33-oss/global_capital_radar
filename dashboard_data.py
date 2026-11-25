"""Read-only dashboard projections; never feed these into production decisions."""
import json
import re
from pathlib import Path


def display_frame(rows):
    """Keep numeric types and CSV nulls; render missing cells explicitly."""
    import pandas as pd
    return pd.DataFrame(rows).style.format(na_rep="—", precision=3)


def missing_reason(asset, horizon):
    reasons = []
    if any(asset.get(k) for k in ("error", "cached_source", "stale")):
        reasons.append("Akış güncel değil; varsa tutar önceki gözlemdir")
    if horizon.get("net_usd_m") is None:
        reasons.append("Seçili vade için kesintisiz akış yok")
    if horizon.get("flow_aum_pct") is None:
        reasons.append("Dönem başı fon büyüklüğü doğrulanmadı")
    if horizon.get("magnitude_percentile") is None:
        reasons.append("Güç hesabı için yeterli geçmiş dönem yok")
    if horizon.get("method_samples") is None:
        reasons.append("Doğrulanmış yöntem örnek sayısı yok")
    if asset.get("cot_code") is None and asset.get("symbol") == "SGOV":
        reasons.append("TBF3 pozisyon serisi yok")
    return "; ".join(reasons) or "—"


def continuity_rows(assets, continuity, key, expired=False):
    rows = []
    for asset in assets:
        r = continuity.get("assets", {}).get(asset["symbol"], {})
        c = r.get("selected") or r.get("stale_reference") or {}
        h = c.get("horizons", {}).get(key, {})
        reasons = []
        if c.get("stale"):
            reasons.append(f"Eski gözlem; {c.get('lag_sessions')} seans geride; sinyalde kullanılmaz")
        if h.get("net_usd_m") is None:
            reasons.append("Seçili vade için kesintisiz akış yok")
        if h.get("magnitude_percentile") is None:
            reasons.append("Yüzdelik için yeterli geçmiş dönem yok")
        errors = "; ".join(f"{provider}: {error}" for provider, error in r.get("errors", {}).items())
        if not c and not errors:
            errors = continuity.get("reason") or "Doğrulanmış alternatif gözlem yok"
        rows.append({
            "Fon": asset["symbol"], "Kaynak": c.get("provider"),
            "Veri hassasiyeti": (c.get("provenance") or {}).get("precision", "Kaynak doğrulamasına tabi"),
            "Durum": "ESKİ · yalnız referans" if c.get("stale") else r.get("status", "UNAVAILABLE"),
            "Akış tarihi": c.get("flow_asof"), "Günlük net USD": c.get("daily_flow_usd"),
            "Ardışık gün": c.get("daily_count"), "Vade net milyon USD": h.get("net_usd_m"),
            "Akış / başlangıç fon büyüklüğü %": h.get("flow_aum_pct"),
            "Geçmiş dönem": h.get("reference_count"), "Akış gücü": h.get("strength"),
            "Yüzdelik": h.get("magnitude_percentile"),
            "Karar": "BEKLE · rapor eski" if expired else "BEKLE · alternatif veri eski" if c.get("stale") else c.get("action", "BEKLE · veri yok"),
            "Eksik veri açıklaması": "; ".join(reasons), "Kaynak hataları": errors,
        })
    return rows


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
        "Hata": row.get("error"), "FRED hatası": row.get("primary_error"),
        "Alternatif hata": row.get("alternative_error"),
        "Kaynak": row.get("source"), "Kaynak serisi": row.get("source_series"),
        "Gözlem türü": row.get("observation_basis"),
        "Son doğrulanmış dönem (eski)": (row.get("last_verified") or {}).get("period"),
        "Son doğrulanmış değer (eski)": (row.get("last_verified") or {}).get("value"),
        "Önceki kayıt UTC": (row.get("last_verified") or {}).get("observed_at"),
    } for row in report.get("indicators", [])]



def rotation_rows(assets, key, expired=False):
    rows = []
    for asset in assets:
        h = asset.get("horizons",{}).get(key,{})
        rows.append({"Varlık":asset["asset"],"Fon":asset["symbol"],"Net milyon USD":h.get("net_usd_m"),
                     "Akış / başlangıç fon büyüklüğü %":h.get("flow_aum_pct"),"Toplam getiri %":h.get("total_return_pct"),"SGOV farkı (puan)":h.get("excess_sgov_pp"),"Göreli sıra":h.get("relative_rank"),"Fiyat gözlemi · kararı etkilemez":h.get("price_confirmation","TEYİTSİZ"),
                     "Akış":h.get("strength","Veri eksik"),"Geçmiş dönem":h.get("reference_count"),
                     "Yüzdelik":h.get("magnitude_percentile"),"Vadeli teyit":h.get("confirmation","TEYİTSİZ"),
                     "Etkin yöntem":"Devre dışı · kaynak kullanılamıyor" if any(asset.get(k) for k in ("error","stale","cached_source")) else h.get("selected_method") or "Varsayılan · doğrulama sürüyor","Yöntem örnek sayısı":h.get("method_samples"),
                     "Karar":"BEKLE · rapor eski" if expired else h.get("action","BEKLE"),"Akış tarihi":asset.get("flow_asof"),"Vadeli tarih":h.get("cot_end") or asset.get("cot_asof"),"CFTC pozisyon farkı (puan)":h.get("cot_change_pp"),"Birincil kaynak hatası":asset.get("error"),"Fiyat tarihi":asset.get("price_asof"),"Eksik veri açıklaması":missing_reason(asset,h)})
    return rows


def expectation_rows(expectations):
    """Project year-keyed forecasts without inventing a scalar or a date."""
    rows = []
    for name, item in expectations.items():
        status = "Kaynak hatası" if item.get("error") else "Eski" if item.get("stale") else "Gözlem"
        years = {k: v for k, v in item.items() if re.fullmatch(r"\d{4}", k)}
        archive = item.get("archived_forecast") or {}
        if years or archive:
            for year, value in sorted(years.items()):
                rows.append({"Gösterge": name, "Dönem": year, "Değer": value,
                             "Durum": status, "Hata": item.get("error"), "Kaynak": item.get("source")})
            for year, value in sorted(archive.items()):
                rows.append({"Gösterge": name, "Dönem": year, "Değer": value,
                             "Durum": "Arşiv · güncel kaynak doğrulanmadı", "Hata": item.get("error"),
                             "Kaynak": item.get("source"), "Arşiv": item.get("archive")})
        else:
            rows.append({"Gösterge": name, "Dönem": item.get("period"), "Değer": item.get("value"),
                         "Durum": status, "Hata": item.get("error"), "Kaynak": item.get("source")})
    return rows


def overview_rows(assets, continuity, key, expired=False):
    """The displayed horizon and notification use the same source-separated observation."""
    from flow_view import observation,HORIZONS
    rows=[]
    for asset in assets:
        o=observation(asset,continuity,key,expired); h=o["h"]
        rows.append({"Fon":asset["symbol"],"Varlık":asset["asset"],"Vade":HORIZONS[key],
                     "Akış kaynağı":o["source"],"Vade başlangıç sınırı":o["period_start"],
                     "Akış tarihi":o["asof"],"Vade net milyon USD":h.get("net_usd_m"),
                     "Akış yönü":o.get("direction","Veri eksik"),
                     "Akış / başlangıç fon büyüklüğü %":h.get("flow_aum_pct"),
                     "Akış gücü":h.get("strength","Veri eksik"),"Yüzdelik":h.get("magnitude_percentile"),
                     "Yönsel akış baskısı %":h.get("directional_pressure_pct"),"Pozitif akış seansı %":h.get("positive_sessions_pct"),"Ölçülen seans":h.get("directional_sessions"),
                     "Geçmiş dönem":h.get("reference_count"),"Veri durumu":o["status"],
                     "Veri hassasiyeti":o.get("precision"),"Karar":o["action"],
                     "Eksik veri açıklaması":o["explanation"]})
    return rows


def monthly_reference_rows(root,key,asof):
    from datetime import datetime
    from flow_metrics import monthly_reference
    try:
        clock=datetime.fromisoformat(asof)
    except (TypeError,ValueError):
        return []
    rows=[]
    for symbol in ("QQQ","CPER","USO"):
        records,error=read_report(root,"native_research/extended_history/monthly_"+symbol+".json")
        if error:continue
        for r in monthly_reference(records,symbol,key,clock):
            rows.append({"Fon":symbol,"Kaynak":r["source"],"Belge":r["form"],
                         "Dönem başlangıcı":r["start"],"Dönem sonu":r["end"],
                         "Yayımlanabilir tarih":r["available"],"İlk kayıt":r["first_seen"],
                         "Net milyon USD":r["net_usd_m"],"Akış / başlangıç AUM %":r["flow_aum_pct"],
                         "Beyan edilen brüt akış baskısı %":r["reported_gross_pressure_pct"],
                         "Geçmiş bağımsız dönem":r["reference_count"],"Tarihsel yüzdelik":r["magnitude_percentile"],
                         "Tarihsel akış gücü":r["strength"],"Durum":"ARŞİV · güncel hareketli vade değil"})
    return rows
