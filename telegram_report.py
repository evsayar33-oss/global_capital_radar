"""Notify only new dated flow observations in a concise, combined report."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flow_view import observation, HORIZONS, number

ROOT = Path(__file__).resolve().parent


TITLE = "YENİ AKIŞ TARİHİ GÜNCELLEMESİ\n\nAKIŞ TARİHİ GÜNCELLENEN VARLIKLAR:"
MAX_MESSAGE_LENGTH = 3800


def message(data):
    return "\n\n".join(text for text, _ in batches(events(data, {})))


def events(data, state):
    # Keep the existing per-source receipts for auditing, but compare dates
    # across all sources for the same asset and investment horizon.
    latest = {}
    for key, receipt in state.items():
        identity = key.rsplit("/", 1)[0]
        asof = receipt.get("asof")
        if asof:
            latest[identity] = max(latest.get(identity, ""), asof)

    output = []
    continuity = data.get("continuity") or {}
    for asset in data["assets"]:
        symbol = asset["symbol"]
        name = asset.get("asset")
        display = f"{name} ({symbol})" if name and name != symbol else symbol
        for horizon, label in HORIZONS.items():
            o = observation(asset, continuity, horizon)
            h = o["h"]
            value = h.get("net_usd_m")
            if o["stale"] or not number(value) or not o["asof"]:
                continue
            identity = symbol + "/" + horizon
            key = identity + "/" + o["source"]
            current = dict(asof=o["asof"], start=o["period_start"], action=o["action"],
                           strength=h.get("strength", "Geçmiş yetersiz"), net_usd_m=value,
                           percentile=h.get("magnitude_percentile"), references=h.get("reference_count"),
                           confirmation=h.get("confirmation") if o["primary"] else None)
            previous = latest.get(identity, "")
            if current["asof"] < previous:
                continue
            # A same-date revision or source switch is not a new flow date.
            line = None
            if current["asof"] > previous:
                line = f"{display} = {current['asof']} - {o['direction']} - {label}"
            output.append((key, line, current))
    return output


def batches(changes):
    # Combine all changed horizons into one message where possible.
    # Keep delivery receipts per row; main persists them only after acknowledgement.
    body = TITLE
    pending = []
    for key, line, current in changes:
        if not line:
            continue
        if pending and len(body) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            yield body, pending
            body = TITLE
            pending = []
        body += "\n" + line
        pending.append((key, current))
    if pending:
        yield body, pending


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
