import unittest
from telegram_report import TITLE, batches, events, message
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
