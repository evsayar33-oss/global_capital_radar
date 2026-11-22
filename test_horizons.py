import unittest
from datetime import date, timedelta
from horizons import analyze, describe, interpret
from telegram_report import message


class HorizonTests(unittest.TestCase):
    def test_tail_both_signs(self):
        self.assertEqual(describe(-30,list(range(10))), ("Olağanüstü çıkış",100))
        self.assertEqual(describe(20,list(range(10))), ("Olağanüstü giriş",100))
        self.assertEqual(describe(20,[1,2]), ("Geçmiş yetersiz",None))

    def test_conflict_and_absence(self):
        end=date(2026,11,17)
        h=dict(net_usd_m=30,strength="Güçlü giriş")
        for past, expected in [(0,"ALIM ADAYI"),(10,"BEKLE · yön teyitsiz")]:
            interpret(h,"1H",end,{end:5,end-timedelta(days=7):past},False,end)
            self.assertEqual(h["action"],expected)
        interpret(h,"1Y",end,{},False,end)
        self.assertIn("TEYİTSİZ",h["confirmation"])

    def test_no_lookahead_or_partial_end(self):
        end=date(2026,11,19)
        data={end-timedelta(days=i):1 for i in range(600)}
        for i in range(7):data[end-timedelta(days=i)] = 100
        h=analyze(data,sorted(data),1)["1H"]
        self.assertEqual((h["net_usd_m"],h["reference_count"],h["strength"]),(700,52,"Olağanüstü giriş"))
        self.assertEqual(message({"seen_at":"2026-11-22","assets":[{"symbol":"GLD"}]}),"")
