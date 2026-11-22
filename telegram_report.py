"""Günlük araştırma özetini tanımlanmış Telegram sohbetine gönderir."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def message(data):
    lines = ["Sermaye radarı · "+data["seen_at"][:10], "Araştırma · tutarlar milyon USD"]
    for key, title in [("1H","1 hafta"),("1A","1 ay"),("3A","3 ay"),("1Y","1 yıl")]:
        lines.extend(["",title])
        for asset in data["assets"]:
            h = asset.get("horizons",{}).get(key,{})
            value = h.get("net_usd_m")
            net = "—" if value is None else f"{value:+,.0f}"
            lines.append(f"{asset['symbol']} {net} · {h.get('strength','Veri eksik')} · {h.get('confirmation','TEYİTSİZ')} · {h.get('action','BEKLE')}")
    return "\n".join(lines)


def main():
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token and not chat:
        return
    if not token or not chat:
        raise SystemExit("Telegram için iki Actions secret gereklidir.")
    data = json.loads((Path(__file__).parent/"history/rotation/latest.json").read_text())
    if data["seen_at"][:10] != datetime.now(timezone.utc).date().isoformat():
        raise SystemExit("Bugüne ait rapor bulunamadı.")
    body = message(data)
    chunks = [""]
    for line in body.splitlines():
        if len(chunks[-1])+len(line)>3900:
            chunks.append("")
        chunks[-1] += line+"\n"
    for chunk in chunks:
        request = Request("https://api.telegram.org/bot"+token+"/sendMessage",
                          data=urlencode({"chat_id":chat,"text":chunk}).encode())
        try:
            with urlopen(request,timeout=20) as response:
                if not json.load(response).get("ok"):
                    raise ValueError()
        except Exception:
            raise SystemExit("Telegram gönderimi doğrulanamadı. Bot erişimini ve chat ID değerini kontrol edin.") from None


if __name__=="__main__":
    main()
