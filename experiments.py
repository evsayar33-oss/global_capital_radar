"""Fiyattan bağımsız üç öncü yöntemin ileri zamanlı karşılaştırması."""
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from horizon_evaluation import evaluate

ROOT = Path(__file__).resolve().parent
VERSION = "early-v1"
METHODS = ("flow", "flow_position", "flow_persistence")


def record(rows):
    path = ROOT/"history"/"method_selection.json"
    selection = json.loads(path.read_text()) if path.exists() else {}
    for row in rows:
        horizons = row.get("horizons",{})
        for key,h in horizons.items():
            base = "BEKLE"
            usable = not any(row.get(k) for k in ("error","stale","cached_source"))
            if not usable:
                # Outages are missing observations, not legitimate abstentions.
                for field in ("early_methods","experiment_version","selected_method","method_selected_at","method_samples"):
                    h.pop(field,None)
                h["action"]="BEKLE · kaynak kullanılamıyor"
                continue
            if h.get("strength","").startswith(("Güçlü","Olağanüstü")):
                base = "ALIM ADAYI" if h.get("net_usd_m",0)>0 else "AZALTMA ADAYI"
            methods = {"flow":base,"flow_position":"BEKLE","flow_persistence":"BEKLE"}
            if h.get("confirmation")=="YÖN UYUMLU":
                methods["flow_position"]=base
            adjacent = {"1H":"1A","1A":"1H","3A":"1A","1Y":"3A"}[key]
            if h.get("net_usd_m",0) is not None:
                other = horizons.get(adjacent,{}).get("net_usd_m")
                if other is not None and other*h.get("net_usd_m",0)>0:
                    methods["flow_persistence"]=base
            h["early_methods"] = methods
            h["experiment_version"]=VERSION
            chosen = selection.get(row["symbol"]+"/"+key,{})
            if chosen.get("version")==VERSION and chosen.get("status")=="validated" and chosen.get("method") in METHODS:
                h["action"]=methods[chosen["method"]]
                h["selected_method"]=chosen["method"]
                h["method_selected_at"]=chosen.get("selected_at")
                h["method_samples"]=chosen.get("samples")
            else:
                h["selected_method"]="flow_position · doğrulama sürüyor"


def compare(reports, series, today):
    """Aynı tarihte tüm yöntemler için kazanç puanı, BEKLE için sıfır."""
    tracks = {}
    occupied = {}
    for day,report in sorted(reports,key=lambda x:x[0]):
        for row in report["assets"]:
            symbol = row["symbol"]
            if symbol=="SGOV" or any(row.get(k) for k in ("error","stale","cached_source")):
                continue
            for key,h in row.get("horizons",{}).items():
                if h.get("experiment_version") != VERSION:
                    continue
                identity = symbol+"/"+key
                if day<=occupied.get(identity,date.min):
                    continue
                proxy={"assets":[{"symbol":symbol,"horizons":{key:{"action":"ALIM ADAYI","confirmation":"YÖN UYUMLU"}}}]}
                result=evaluate([(day,proxy)],series,today)
                if not result:
                    continue
                # Çıkışa kadar yeni örnek alınmaz.
                from horizons import boundary
                cash=series.get("SGOV",{})
                entry=min(d for d in cash if d>day)
                from radar import month
                from datetime import timedelta
                target=entry+timedelta(days=7) if key=="1H" else month(entry,{"1A":1,"3A":3,"1Y":12}[key])
                occupied[identity]=min(d for d in cash if d>=target)
                excess=result[0][2]
                scores={}
                for method in METHODS:
                    action=h["early_methods"][method]
                    # 10 baz puan toplam geçiş maliyeti araştırma varsayımı.
                    scores[method]=excess-.10 if action=="ALIM ADAYI" else -excess-.10 if action=="AZALTMA ADAYI" else 0.0
                tracks.setdefault(identity,[]).append(scores)
    selection={}
    for identity, samples in tracks.items():
        choice={"version":VERSION,"samples":len(samples),"status":"insufficient"}
        if len(samples)>=30:
            train,test=samples[:-10],samples[-10:]
            winner=max(METHODS,key=lambda m:statistics.mean(s[m] for s in train))
            # Son 10 bağımsız dönem doğrulama. Tüm yöntemlerle aynı tarihler.
            values=[s[winner] for s in test]
            lower=statistics.mean(values)-2*statistics.stdev(values)/(len(values)**.5)
            if lower>0 and sum(v>0 for v in values)>=7:
                choice.update(status="validated",method=winner,holdout_mean_pp=statistics.mean(values),lower_bound_pp=lower)
        selection[identity]=choice
    return persist_selection(selection, today)


def persist_selection(selection, today):
    """Eksik veri seçimi silmez. Yeni doğrulanmış seçim bir sonraki taramada kullanılır."""
    path = ROOT/"history"/"method_selection.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    audit_path = ROOT/"history"/"method_changes.json"
    audit = json.loads(audit_path.read_text()) if audit_path.exists() else []
    now = datetime.now(timezone.utc).isoformat()
    merged = dict(previous)
    for identity, choice in selection.items():
        old = previous.get(identity,{})
        if old.get("version")==VERSION and choice["samples"] < old.get("samples",0):
            continue
        old_method = old.get("method") if old.get("status")=="validated" else None
        new_method = choice.get("method") if choice.get("status")=="validated" else None
        if old_method != new_method:
            audit.append({"identity":identity,"previous_method":old_method,
                          "method":new_method,"changed_at":now,"evaluation_date":str(today),
                          "evidence":dict(choice),"effective":"next_scan"})
        choice["selected_at"] = now if old_method != new_method else old.get("selected_at")
        choice["evaluated_at"] = now
        merged[identity] = choice
    # Denetim günlüğü önce yazılır. Yarım kalan yazmada tekrar kayıt güvenlidir.
    for target, content in ((audit_path,audit),(path,merged)):
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(content,ensure_ascii=False,indent=2))
        temp.replace(target)
    return merged
