import unittest
from telegram_report import events
from experiments import record
from unittest.mock import patch

class Notifications(unittest.TestCase):
    def data(self,action="ALIM ADAYI",strength="Güçlü giriş"):
        return {"assets":[{"asset":"Altın","symbol":"GLD","horizons":{"1H":{"action":action,"strength":strength}}}]}
    def test_once_then_change(self):
        event=events(self.data(),{})[0]
        self.assertIsNotNone(event[1])
        state={event[0]:event[2]}
        self.assertIsNone(events(self.data(),state)[0][1])
        self.assertIsNotNone(events(self.data("BEKLE","Zayıf giriş"),state)[0][1])
    def test_no_first_wait_no_outage(self):
        self.assertIsNone(events(self.data("BEKLE","Zayıf giriş"),{})[0][1])
        d=self.data();d["assets"][0]["error"]="unavailable"
        self.assertEqual(events(d,{}),[])
    def test_early_methods_ignore_price(self):
        h={"action":"ALIM ADAYI","strength":"Güçlü giriş","confirmation":"YÖN UYUMLU","net_usd_m":1,"total_return_pct":-20}
        row={"symbol":"GLD","horizons":{"1H":h,"1A":dict(h)}}
        with patch("experiments.Path.exists",return_value=False):
            record([row])
        self.assertTrue(all(v=="ALIM ADAYI" for v in h["early_methods"].values()))
