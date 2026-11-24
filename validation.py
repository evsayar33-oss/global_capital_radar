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
    payload={"checked_at":datetime.now(timezone.utc).isoformat(),"assets":checks,"open_integrations":gaps,
             "telegram":"Teslimat yalnız API yanıtı başarılıysa kaydedilir",
             "selection":"30 bağımsız örnek öncesi yöntem seçilmez"}
    (ROOT/"history/validation.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    report_old = report["seen_at"][:10] != datetime.now(timezone.utc).date().isoformat()
    return int(report_old or any(c["source_error"] or c["stale"] or c["cached"] for c in checks))


if __name__=="__main__":
    raise SystemExit(main())
