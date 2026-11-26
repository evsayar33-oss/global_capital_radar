"""Send concise, independently tracked flow-date and flow-direction updates."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flow_view import observation, HORIZONS, number, direction

ROOT = Path(__file__).resolve().parent


TITLE = "YENİ AKIŞ TARİHİ GÜNCELLEMESİ\n\nAKIŞ TARİHİ GÜNCELLENEN VARLIKLAR:"
DIRECTION_TITLE = "YENİ AKIŞ YÖNÜ GÜNCELLEMESİ\n\nAKIŞ YÖNÜ GÜNCELLENEN VARLIKLAR:"
MAX_MESSAGE_LENGTH = 3800


def message(data):
    return "\n\n".join(text for text, _ in batches(events(data, {})))


def observations(data):
    """Use the same selected, valid observation as the dashboard for each horizon."""
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
            yield identity, key, display, label, current


def latest_receipt_dates(state):
    # Keep the existing per-source receipts for auditing, but compare dates
    # across all sources for the same asset and investment horizon.
    latest = {}
    for key, receipt in state.items():
        identity = key.rsplit("/", 1)[0]
        asof = receipt.get("asof")
        if asof:
            latest[identity] = max(latest.get(identity, ""), asof)
    return latest


def events(data, state):
    latest = latest_receipt_dates(state)
    output = []
    for identity, key, display, label, current in observations(data):
        previous = latest.get(identity, "")
        if current["asof"] < previous:
            continue
        # A same-date revision or source switch is not a new flow date.
        line = None
        if current["asof"] > previous:
            line = f"{display} = {current['asof']} - {direction(current['net_usd_m'])} - {label}"
        output.append((key, line, current))
    return output


def migrate_direction_state(date_receipts):
    """Seed each horizon from its newest previously delivered dated observation."""
    latest = {}
    ranks = {}
    for key, receipt in date_receipts.items():
        identity, source = key.rsplit("/", 1)
        asof, value = receipt.get("asof"), receipt.get("net_usd_m")
        if not asof or not number(value):
            continue
        msgid = receipt.get("telegram_message_id")
        rank = (asof, msgid if isinstance(msgid, int) else 0)
        if rank > ranks.get(identity, ("", 0)):
            ranks[identity] = rank
            latest[identity] = dict(asof=asof, direction=direction(value), source=source)
    return latest


def direction_events(data, state, date_receipts=None):
    """Compare the net direction independently of date notifications.

    An initial valid observation establishes the baseline without an alert.
    A changed sign is eligible even on the same date; older or unavailable
    observations cannot replace the baseline.
    """
    date_watermarks = latest_receipt_dates(date_receipts or {})
    output = []
    for identity, key, display, label, observation_data in observations(data):
        current = dict(asof=observation_data["asof"],
                       direction=direction(observation_data["net_usd_m"]),
                       source=key.rsplit("/", 1)[1])
        previous = state.get(identity, {})
        if current["asof"] < max(previous.get("asof", ""), date_watermarks.get(identity, "")):
            continue
        old_direction = previous.get("direction")
        line = None
        if old_direction is not None and old_direction != current["direction"]:
            line = f"{display} = {label} - {current['direction']}"
        output.append((identity, line, current))
    return output


def batches(changes, title=TITLE):
    # Combine all changed horizons into one message where possible.
    # Keep delivery receipts per row; main persists them only after acknowledgement.
    body = title
    pending = []
    for key, line, current in changes:
        if not line:
            continue
        if pending and len(body) + len(line) + 1 > MAX_MESSAGE_LENGTH:
            yield body, pending
            body = title
            pending = []
        body += "\n" + line
        pending.append((key, current))
    if pending:
        yield body, pending


def save(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    temporary.replace(path)


def deliver(changes, title, token, chat, path, state):
    """Persist each batch only after Telegram acknowledges delivery."""
    sent = 0
    for text, pending in batches(changes, title):
        request = Request("https://api.telegram.org/bot"+token+"/sendMessage",
                          data=urlencode({"chat_id":chat,"text":text}).encode())
        try:
            with urlopen(request, timeout=20) as response:
                receipt = json.load(response)
                if not receipt.get("ok") or not receipt.get("result", {}).get("message_id"):
                    raise ValueError()
        except Exception:
            raise RuntimeError("Telegram teslimatı doğrulanamadı.") from None
        for key, current in pending:
            state[key] = {**current, "telegram_message_id":receipt["result"]["message_id"]}
        save(path, state)
        sent += len(pending)
    return sent


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
    folder.mkdir(parents=True, exist_ok=True)
    chat_id = hashlib.sha256(chat.encode()).hexdigest()[:16]
    path = folder/(chat_id + ".json")
    direction_path = folder/(chat_id + ".directions.json")
    state = json.loads(path.read_text()) if path.exists() else {}

    # Bootstrap once from the older date receipts, before any new date message
    # is delivered. The separate file prevents either delivery overwriting
    # the other type's baseline.
    exists = direction_path.exists()
    direction_state = (json.loads(direction_path.read_text()) if exists
                       else migrate_direction_state(state))
    changes = events(data, state)
    direction_changes = direction_events(data, direction_state, state)
    baseline_changed = not exists
    for identity, line, current in direction_changes:
        if line is None:
            updated = {**direction_state.get(identity, {}), **current}
            if updated != direction_state.get(identity):
                direction_state[identity] = updated
                baseline_changed = True
    if baseline_changed:
        save(direction_path, direction_state)

    failures = []
    for label, title, updates, target, receipts in (
        ("FLOW_NOTIFICATION_SENT", TITLE, changes, path, state),
        ("DIRECTION_NOTIFICATION_SENT", DIRECTION_TITLE, direction_changes,
         direction_path, direction_state),
    ):
        try:
            sent = deliver(updates, title, token, chat, target, receipts)
            print(f"{label} {sent}", flush=True)
        except RuntimeError:
            failures.append(label)
    if failures:
        raise SystemExit("Telegram teslimatı doğrulanamadı: " + ", ".join(failures))


if __name__=="__main__":
    main()
