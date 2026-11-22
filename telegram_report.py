"""Güçlü giriş ve karar değişimlerini kalıcı gönderim kaydıyla bildirir."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def message(data):
    return "\n".join(line for _,line,_ in events(data,{}) if line)


def events(data, state):
    output = []
    for asset in data["assets"]:
        if asset.get("error") or asset.get("stale") or asset.get("cached_source"):
            continue
        for horizon,h in asset.get("horizons",{}).items():
            key = asset["symbol"]+"/"+horizon
            action = h.get("action","BEKLE")
            # Veri arızası ekonomik karar değişimi sayılmaz.
            if any(word in action for word in ("veri","önbellek","önceki gözlem")):
                continue
            strong = h.get("strength") in ("Güçlü giriş","Olağanüstü giriş")
            current = {"action":action,"strong":strong,"strength":h.get("strength")}
            old = state.get(key)
            reasons = []
            if strong and (not old or not old.get("strong") or old.get("strength")!=current["strength"]):
                reasons.append(h["strength"])
            if old and old["action"] != action:
                reasons.append(old["action"]+" → "+action)
            text = f"{asset['asset']} · {horizon}\n"+ " · ".join(reasons)
            value = h.get("net_usd_m")
            text += f"\nNet akış {value} milyon USD · {asset.get('flow_asof','—')}\n{h.get('confirmation','TEYİTSİZ')}\nKarar {action}"
            output.append((key,text if reasons else None,current))
    return output


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
    for key,text,current in events(data,state):
        if text:
            request = Request("https://api.telegram.org/bot"+token+"/sendMessage",
                              data=urlencode({"chat_id":chat,"text":"Sermaye radarı · araştırma\n"+text}).encode())
            try:
                with urlopen(request,timeout=20) as response:
                    if not json.load(response).get("ok"):
                        raise ValueError()
            except Exception:
                raise SystemExit("Telegram teslimatı doğrulanamadı.") from None
        state[key] = current
        save(path,state)


if __name__=="__main__":
    main()
