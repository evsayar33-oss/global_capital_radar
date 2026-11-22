import json
import unittest
from datetime import datetime, timezone

from datetime import date, timedelta
from evaluate_rotation import measure
from rotation import classify, flows


class RotationTests(unittest.TestCase):
    def test_confirmation_and_conflict(self):
        self.assertEqual(classify({"1H":1,"1A":2}, .5), "ALIM ADAYI")
        self.assertEqual(classify({"1H":-2,"1A":-1}, -.5), "AZALTMA ADAYI")
        self.assertEqual(classify({"1H":1,"1A":2}, -.5), "GİRİŞ İZLE")
        self.assertEqual(classify({"1H":-1,"1A":2}, None), "BEKLE")
        self.assertEqual(classify({}, None), "VERİ EKSİK")

    def test_units_and_windows(self):
        rows = [[datetime(2026,11,d,tzinfo=timezone.utc).timestamp()*1000, 0.1] for d in [6,9,10,11,12,13]]
        page = "<div id='fund-flow-chart-container' data-series='"+json.dumps(rows)+"'></div><b>5 Day Net Flows:</b>500 M<"
        end = datetime(2026,11,13).date()
        self.assertEqual(flows(page,end), (end,{"1G":100,"1H":500},None))
        with self.assertRaises(ValueError):
            flows(page.replace("500 M", "32 M"),end)

    def test_forward_window(self):
        friday = date(2026,11,13)
        bars = {friday+timedelta(days=i): (100,100+i) for i in (0,3,4,5,6,7)}
        cash = {d:(1,1) for d in bars}
        outcome = measure(bars,cash,friday)
        self.assertEqual(outcome["excess_pp"],7)
        self.assertEqual(outcome["entry"],"2026-11-16")
        self.assertIsNone(measure({},cash,friday))
