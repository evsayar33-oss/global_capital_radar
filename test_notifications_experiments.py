import unittest
from telegram_report import events
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
        self.assertIsNotNone(events(self.data("BEKLE","Zayıf giriş"),state)[0][1])
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
        self.assertIn("Yeni kaynak tarihi",next_event[1])
        state[next_event[0]]=next_event[2]
        d["assets"][0]["flow_asof"]="2026-11-24"
        self.assertEqual(events(d,state),[])

    def test_alternative_outage_is_observed_not_trade_and_grouped(self):
        from telegram_report import batches
        d=Notifications().data()
        d["assets"][0]["error"]="403"
        d["continuity"]={"assets":{"GLD":{"selected":{"provider":"ETFIQ_HISTORY","status":"OBSERVED",
            "flow_asof":"2026-11-24","daily_flow_usd":-1000000,
            "horizons":{"1H":{"net_usd_m":-20,"strength":"Güçlü çıkış"},
                        "1A":{"net_usd_m":50,"strength":"Güçlü giriş"}}}}}}
        out=events(d,{})
        self.assertEqual(len(out),3)
        self.assertTrue(all("üretim onayı yok" in e[1] for e in out))
        self.assertEqual(len(list(batches(out))),3)
        d["continuity"]["assets"]["GLD"]["selected"]["stale"]=True
        self.assertEqual(events(d,{}),[])
