"""Notify new dated flow observations and material revisions, never trade orders."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flow_view import observation, HORIZONS, number

ROOT = Path(__file__).resolve().parent


def message(data):
    return "\n".join(line for _,line,_ in events(data,{}) if line)


def events(data, state):
    output=[]
    continuity=data.get("continuity") or {}
    for asset in data["assets"]:
        for horizon,label in HORIZONS.items():
            o=observation(asset,continuity,horizon)
            h=o["h"]; value=h.get("net_usd_m")
            if o["stale"] or not number(value) or not o["asof"]:
                continue
            key=asset["symbol"]+"/"+horizon+"/"+o["source"]
            current=dict(asof=o["asof"],start=o["period_start"],action=o["action"],
                         strength=h.get("strength","Geçmiş yetersiz"),net_usd_m=value,
                         percentile=h.get("magnitude_percentile"),references=h.get("reference_count"),
                         confirmation=h.get("confirmation") if o["primary"] else None)
            old=state.get(key)
            if old and old.get("asof","")>current["asof"]:
                continue
            reasons=[]
            if not old or old.get("asof")!=current["asof"]:
                reasons.append("Yeni kaynak tarihi")
            elif any(old.get(k)!=current.get(k) for k in ("action","strength","net_usd_m","percentile","confirmation")):
                reasons.append("Aynı tarih · veri/karar revizyonu")
            pct=current["percentile"]
            text=(f"{asset['symbol']} · {o['source']} · {o['asof']}\\n"
                  f"{o['direction']} {abs(value):,.3f} milyon USD · {current['strength']} · "
                  f"yüzdelik {pct if pct is not None else 'ölçülemedi'} · n={current['references'] if current['references'] is not None else '—'}\\n"
                  f"{current['action']}")
            if o.get("precision"):
                text+=f" · {o['precision']}"
            if current["confirmation"]:
                text+=" · "+current["confirmation"]
            if reasons:
                text+="\\n"+" / ".join(reasons)
            output.append((key,text if reasons else None,current))
    return output


def batches(changes):
    # One bounded message per horizon where possible; per-source receipt keys
    # are committed only after Telegram acknowledges that message.
    for horizon,label in HORIZONS.items():
        title=f"Sermaye radarı · {label} · yeni akış gözlemleri\\nAraştırma; işlem emri değildir."
        body=title; pending=[]
        for key,text,current in changes:
            if not text or key.split("/")[1]!=horizon:
                continue
            if pending and len(body)+len(text)+2>3800:
                yield body,pending
                body=title;pending=[]
            body+="\\n\\n"+text;pending.append((key,current))
        if pending:
            yield body,pending


def save(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    temporary.replace(path)


def main():
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token and not chat:
        print("Telegram secrets tanımlı değil, gönderim atlandı.")
        return
    if not token or not chat:
        raise SystemExit("Telegram için iki Actions secret gereklidir.")
    data = json.loads((ROOT/"history/rotation/latest.json").read_text())
    if data["seen_at"][:10] != datetime.now(timezone.utc).date().isoformat():
        raise SystemExit("Bugüne ait rapor bulunamadı.")
    folder = ROOT/"history"/"notifications"
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(hashlib.sha256(chat.encode()).hexdigest()[:16]+".json")
    state = json.loads(path.read_text()) if path.exists() else {}
    changes=events(data,state)
    for text,pending in batches(changes):
        request = Request("https://api.telegram.org/bot"+token+"/sendMessage",
                          data=urlencode({"chat_id":chat,"text":text}).encode())
        try:
            with urlopen(request,timeout=20) as response:
                receipt=json.load(response)
                if not receipt.get("ok") or not receipt.get("result",{}).get("message_id"):
                    raise ValueError()
        except Exception:
            raise SystemExit("Telegram teslimatı doğrulanamadı.") from None
        for key,current in pending:
            state[key]={**current,"telegram_message_id":receipt["result"]["message_id"]}
        save(path,state)
    print(f"FLOW_NOTIFICATION_SENT {sum(bool(text) for _,text,_ in changes)}",flush=True)


if __name__=="__main__":
    main()
