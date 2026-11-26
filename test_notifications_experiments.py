import unittest
from telegram_report import (TITLE, DIRECTION_TITLE, batches, events, message,
                             direction_events, migrate_direction_state)
from experiments import record
from unittest.mock import patch

class Notifications(unittest.TestCase):
    def data(self,action="ALIM ADAYI",strength="Güçlü giriş"):
        return {"assets":[{"asset":"Altın","symbol":"GLD","flow_asof":"2026-11-24","horizons":{"1H":{"action":action,"strength":strength,"net_usd_m":100}}}]}
    def test_once_then_change(self):
        event=events(self.data(),{})[0]
        self.assertIsNotNone(event[1])
        state={event[0]:event[2]}
        self.assertIsNone(events(self.data(),state)[0][1])
        self.assertIsNone(events(self.data("BEKLE","Zayıf giriş"),state)[0][1])
    def test_new_wait_is_observation_but_outage_is_not(self):
        self.assertIsNotNone(events(self.data("BEKLE","Zayıf giriş"),{})[0][1])
        d=self.data();d["assets"][0]["error"]="unavailable"
        self.assertEqual(events(d,{}),[])
    def test_early_methods_ignore_price(self):
        h={"action":"ALIM ADAYI","strength":"Güçlü giriş","confirmation":"YÖN UYUMLU","net_usd_m":1,"total_return_pct":-20}
        row={"symbol":"GLD","horizons":{"1H":h,"1A":dict(h)}}
        with patch("experiments.Path.exists",return_value=False):
            record([row])
        self.assertTrue(all(v=="ALIM ADAYI" for v in h["early_methods"].values()))


class NewFlowNotifications(unittest.TestCase):
    def test_new_date_same_strength_and_no_duplicate_or_rollback(self):
        d=Notifications().data()
        e=events(d,{})[0]; state={e[0]:e[2]}
        self.assertIsNone(events(d,state)[0][1])
        d["assets"][0]["flow_asof"]="2026-11-25"
        next_event=events(d,state)[0]
        self.assertEqual(next_event[1], "Altın (GLD) = 2026-11-25 - Giriş - 1 hafta")
        state[next_event[0]]=next_event[2]
        d["assets"][0]["flow_asof"]="2026-11-24"
        self.assertEqual(events(d,state),[])

    def test_alternative_outage_is_observed_not_trade_and_grouped(self):
        d=Notifications().data()
        d["assets"][0]["error"]="403"
        d["continuity"]={"assets":{"GLD":{"selected":{"provider":"ETFIQ_HISTORY","status":"OBSERVED",
            "flow_asof":"2026-11-24","daily_flow_usd":-1000000,
            "horizons":{"1H":{"net_usd_m":-20,"strength":"Güçlü çıkış"},
                        "1A":{"net_usd_m":50,"strength":"Güçlü giriş"}}}}}}
        out=events(d,{})
        self.assertEqual(len(out),3)
        self.assertTrue(all("üretim onayı yok" in e[2]["action"] for e in out))
        batch = list(batches(out))
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0][0], TITLE + "\n" + "\n".join([
            "Altın (GLD) = 2026-11-24 - Çıkış - 1 gün",
            "Altın (GLD) = 2026-11-24 - Çıkış - 1 hafta",
            "Altın (GLD) = 2026-11-24 - Giriş - 1 ay",
        ]))
        self.assertEqual(len(batch[0][1]), 3)
        self.assertEqual(message(d), batch[0][0])
        d["continuity"]["assets"]["GLD"]["selected"]["stale"]=True
        self.assertEqual(events(d,{}),[])


    def test_legacy_receipts_block_repeated_dates_from_other_sources(self):
        d = Notifications().data()
        state = {
            "GLD/1H/ETFIQ_HISTORY": {"asof": "2026-11-24", "telegram_message_id": 7},
            "GLD/1H/ISSUER_HISTORY": {"asof": "2026-11-23", "telegram_message_id": 2},
        }
        self.assertEqual(list(batches(events(d, state))), [])
        d["assets"][0]["flow_asof"] = "2026-11-23"
        self.assertEqual(events(d, state), [])
        d["assets"][0]["flow_asof"] = "2026-11-25"
        self.assertEqual(len(list(batches(events(d, state)))), 1)

    def test_direction_and_date_are_independent_per_asset_and_horizon(self):
        d = Notifications().data()
        d["assets"] += [{"asset": "Bitcoin", "symbol": "IBIT", "flow_asof": "2026-11-25",
                         "horizons": {"1A": {"net_usd_m": 0}, "3A": {"net_usd_m": -20},
                                      "1Y": {"net_usd_m": None}}}]
        state = {"GLD/1H/ETFdb": {"asof": "2026-11-24"}}
        expected = TITLE + "\nBitcoin (IBIT) = 2026-11-25 - Net sıfır - 1 ay" \
                         + "\nBitcoin (IBIT) = 2026-11-25 - Çıkış - 3 ay"
        out = list(batches(events(d, state)))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], expected)
        self.assertEqual(len(out[0][1]), 2)

    def test_large_batch_splits_without_losing_rows(self):
        changes = [(f"ASSET{i}/1G/ETFdb", f"ASSET{i} = 2026-11-25 - Giriş - 1 gün",
                    {"asof": "2026-11-25"}) for i in range(200)]
        reports = list(batches(changes))
        self.assertGreater(len(reports), 1)
        self.assertTrue(all(text.startswith(TITLE) and len(text) <= 3800 for text, _ in reports))
        self.assertEqual([key for _, pending in reports for key, _ in pending],
                         [key for key, _, _ in changes])


class TelegramDelivery(unittest.TestCase):
    def test_receipts_persist_only_after_success_and_prevent_repeat(self):
        import hashlib
        import io
        import json
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from telegram_report import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rotation = root / "history" / "rotation"
            rotation.mkdir(parents=True)
            d = Notifications().data()
            d["seen_at"] = datetime.now(timezone.utc).isoformat()
            (rotation / "latest.json").write_text(json.dumps(d))
            path = root / "history" / "notifications" / (hashlib.sha256(b"test-chat").hexdigest()[:16] + ".json")
            with patch("telegram_report.ROOT", root), \
                 patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat"}), \
                 patch("telegram_report.urlopen") as send:
                send.side_effect = OSError("network unavailable")
                with self.assertRaises(SystemExit):
                    main()
                self.assertFalse(path.exists())
                send.side_effect = lambda *a, **kw: io.StringIO('{"ok":false}')
                with self.assertRaises(SystemExit):
                    main()
                self.assertFalse(path.exists())
                send.side_effect = lambda *a, **kw: io.StringIO('{"ok":true,"result":{"message_id":42}}')
                main()
                self.assertEqual(json.loads(path.read_text())["GLD/1H/ETFdb"]["telegram_message_id"], 42)
                count = send.call_count
                main()
                self.assertEqual(send.call_count, count)

class DirectionNotifications(unittest.TestCase):
    def test_first_baseline_then_same_date_direction_change_only(self):
        d = Notifications().data()
        first = direction_events(d, {})
        self.assertEqual(len(first), 1)
        identity, line, baseline = first[0]
        self.assertIsNone(line)
        self.assertEqual(baseline["direction"], "Giriş")
        state = {identity: baseline}
        h = d["assets"][0]["horizons"]["1H"]
        h["net_usd_m"] = 10
        h["strength"] = "Zayıf giriş"
        self.assertEqual(list(batches(direction_events(d, state), DIRECTION_TITLE)), [])
        h["net_usd_m"] = -10
        flipped = direction_events(d, state)
        self.assertEqual(list(batches(flipped, DIRECTION_TITLE))[0][0],
                         DIRECTION_TITLE + "\nAltın (GLD) = 1 hafta - Çıkış")
        date_state = {"GLD/1H/ETFdb": {"asof": "2026-11-24"}}
        self.assertEqual(list(batches(events(d, date_state))), [])
        state[identity] = flipped[0][2]
        self.assertEqual(list(batches(direction_events(d, state), DIRECTION_TITLE)), [])

    def test_new_date_same_direction_then_zero_then_opposite(self):
        d = Notifications().data()
        state = {"GLD/1H": {"asof": "2026-11-24", "direction": "Giriş"}}
        d["assets"][0]["flow_asof"] = "2026-11-25"
        current = direction_events(d, state)[0]
        self.assertIsNone(current[1])
        self.assertEqual(current[2]["asof"], "2026-11-25")
        state[current[0]] = current[2]
        h = d["assets"][0]["horizons"]["1H"]
        h["net_usd_m"] = 0
        zero = direction_events(d, state)[0]
        self.assertEqual(zero[1], "Altın (GLD) = 1 hafta - Net sıfır")
        state[zero[0]] = zero[2]
        h["net_usd_m"] = -10
        self.assertEqual(direction_events(d, state)[0][1], "Altın (GLD) = 1 hafta - Çıkış")

    def test_valid_horizons_independent_stale_and_missing_never_flip(self):
        d = Notifications().data()
        a = d["assets"][0]
        a["flow_asof"] = "2026-11-25"
        a["horizons"].update({"1A": {"net_usd_m": -20}, "3A": {"net_usd_m": None}})
        state = {"GLD/1H": {"asof": "2026-11-24", "direction": "Giriş"},
                 "GLD/1A": {"asof": "2026-11-24", "direction": "Giriş"},
                 "GLD/3A": {"asof": "2026-11-24", "direction": "Çıkış"}}
        changes = direction_events(d, state)
        self.assertEqual([c[1] for c in changes if c[1]],
                         ["Altın (GLD) = 1 ay - Çıkış"])
        a["stale"] = True
        self.assertEqual(direction_events(d, state), [])
        a["stale"] = False
        a["flow_asof"] = "2026-11-23"
        self.assertEqual(direction_events(d, state), [])
        a["flow_asof"] = "2026-11-25"
        self.assertEqual(direction_events(d, state, {
            "GLD/1H/ETFdb": {"asof":"2026-11-26"},
            "GLD/1A/ETFdb": {"asof":"2026-11-26"}}), [])

    def test_source_switch_without_sign_change_does_not_alert(self):
        d = Notifications().data()
        state = {"GLD/1H": {"asof": "2026-11-24", "direction": "Giriş", "source": "ETFdb"}}
        d["assets"][0]["error"] = "403"
        d["continuity"] = {"assets": {"GLD": {"selected": {
            "provider": "ETFIQ_HISTORY", "status": "OBSERVED", "flow_asof": "2026-11-24",
            "horizons": {"1H": {"net_usd_m": 20}}}}}}
        self.assertEqual(list(batches(direction_events(d, state), DIRECTION_TITLE)), [])
        d["continuity"]["assets"]["GLD"]["selected"]["horizons"]["1H"]["net_usd_m"] = -20
        self.assertEqual(direction_events(d, state)[0][1], "Altın (GLD) = 1 hafta - Çıkış")

    def test_migration_uses_most_recent_receipt_and_message_id(self):
        legacy = {
            "GLD/1H/ETFdb": {"asof":"2026-11-24","net_usd_m":100,"telegram_message_id":20},
            "GLD/1H/ETFIQ": {"asof":"2026-11-24","net_usd_m":-30,"telegram_message_id":21},
            "GLD/1H/OLDER": {"asof":"2026-11-23","net_usd_m":20,"telegram_message_id":22},
            "GLD/1A/ETFdb": {"asof":"2026-11-24","net_usd_m":0},
            "GLD/1Y/ETFdb": {"asof":"2026-11-24","net_usd_m":None}}
        self.assertEqual(migrate_direction_state(legacy), {
            "GLD/1H":{"asof":"2026-11-24","direction":"Çıkış","source":"ETFIQ"},
            "GLD/1A":{"asof":"2026-11-24","direction":"Net sıfır","source":"ETFdb"}})

    def test_two_message_types_and_independent_delivery_retry(self):
        import hashlib
        import io
        import json
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path
        from urllib.parse import parse_qs
        from telegram_report import main

        for failed_title in (TITLE, DIRECTION_TITLE):
            with self.subTest(failed_title=failed_title), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rotation = root / "history" / "rotation"
                rotation.mkdir(parents=True)
                receipts = root / "history" / "notifications"
                receipts.mkdir()
                prefix = hashlib.sha256(b"test-chat").hexdigest()[:16]
                date_path = receipts / (prefix + ".json")
                direction_path = receipts / (prefix + ".directions.json")
                date_path.write_text(json.dumps({"GLD/1H/ETFdb":{
                    "asof":"2026-11-24","net_usd_m":100,"telegram_message_id":1}}))
                d = Notifications().data()
                d["seen_at"] = datetime.now(timezone.utc).isoformat()
                a = d["assets"][0]
                a["flow_asof"] = "2026-11-25"
                a["horizons"]["1H"]["net_usd_m"] = -100
                (rotation / "latest.json").write_text(json.dumps(d))
                sent = []
                def mock_send(req, **kw):
                    text = parse_qs(req.data.decode())["text"][0]
                    sent.append(text)
                    if text.startswith(failed_title):
                        raise OSError("network unavailable")
                    return io.StringIO('{"ok":true,"result":{"message_id":2}}')

                with patch("telegram_report.ROOT", root), \
                     patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN":"test-token", "TELEGRAM_CHAT_ID":"test-chat"}), \
                     patch("telegram_report.urlopen", side_effect=mock_send) as send:
                    with self.assertRaises(SystemExit):
                        main()
                    self.assertEqual(len(sent), 2)
                    self.assertEqual(sent[0], TITLE + "\nAltın (GLD) = 2026-11-25 - Çıkış - 1 hafta")
                    self.assertEqual(sent[1], DIRECTION_TITLE + "\nAltın (GLD) = 1 hafta - Çıkış")
                    date_state = json.loads(date_path.read_text())
                    direction_state = json.loads(direction_path.read_text())
                    self.assertEqual(date_state["GLD/1H/ETFdb"]["asof"],
                                     "2026-11-24" if failed_title == TITLE else "2026-11-25")
                    self.assertEqual(direction_state["GLD/1H"]["direction"],
                                     "Giriş" if failed_title == DIRECTION_TITLE else "Çıkış")
                    def retry(req, **kw):
                        sent.append(parse_qs(req.data.decode())["text"][0])
                        return io.StringIO('{"ok":true,"result":{"message_id":3}}')
                    send.side_effect = retry
                    main()
                    self.assertEqual(len(sent), 3)
                    self.assertTrue(sent[2].startswith(failed_title))
                    main()
                    self.assertEqual(len(sent), 3)
                    self.assertEqual(json.loads(date_path.read_text())["GLD/1H/ETFdb"]["asof"], "2026-11-25")
                    self.assertEqual(json.loads(direction_path.read_text())["GLD/1H"]["direction"], "Çıkış")
