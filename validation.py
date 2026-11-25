"""Veri kapsamı ve gerçekleşmiş doğrulama durumunu kaydeder."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    report=json.loads((ROOT/"history/rotation/latest.json").read_text())
    checks=[]
    for row in report["assets"]:
        checks.append({"asset":row["symbol"],"flow_date":row.get("flow_asof"),
                       "source_error":row.get("error"),"cached":row.get("cached_source",False),
                       "stale":row.get("stale",False),
                       "missing_horizons":[k for k in ("1H","1A","3A","1Y") if row.get("horizons",{}).get(k,{}).get("reference_count",0)<5],
                       "cot_date":row.get("cot_asof")})
    gaps=["SGOV TBF3 doğrulanmış fiyat ve pozisyon serisi","Bakır depo stokları","Petrol vade farkı","Kripto vadeli primi","Gerçek komisyon ve kayma kalibrasyonu"]
    # Separate observed context from still-unverified production integrations.
    # A cash auction is not a futures settlement; a quoted spread is not a fill.
    native_path=ROOT/"history/native_research/results.json"
    try:
        native=json.loads(native_path.read_text())
    except (OSError,ValueError):
        native={}
    native_status=native.get("native_status",{})
    native_context={
        "evaluated_at":native.get("evaluated_at"),
        "status":native_status,
        "errors":native.get("native_errors",{}),
        "scope":"RESEARCH_ONLY_NOT_PRODUCTION_CONFIRMATION",
    }
    continuity=report.get("continuity",{})
    payload={"continuity_status":continuity.get("status","UNAVAILABLE"),"alternative_count":continuity.get("alternative_count",0),"alternative_unavailable":continuity.get("unavailable_count"),"checked_at":datetime.now(timezone.utc).isoformat(),"assets":checks,"open_integrations":gaps,"native_context":native_context,
             "telegram":"Teslimat yalnız API yanıtı başarılıysa kaydedilir",
             "selection":"30 bağımsız örnek öncesi yöntem seçilmez"}
    (ROOT/"history/validation.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    report_old = report["seen_at"][:10] != datetime.now(timezone.utc).date().isoformat()
    return int(report_old or any(c["source_error"] or c["stale"] or c["cached"] for c in checks))


if __name__=="__main__":
    raise SystemExit(main())
