import unittest
from datetime import date
from radar import summarize, forecast, conditions, month

class RadarTests(unittest.TestCase):
    def test_month_end(self):
        self.assertEqual(month(date(2024, 3, 31), -1), date(2024, 2, 29))

    def test_monthly_flow_sign(self):
        end = date(2025, 3, 1)
        row = summarize(dict(change="flow", freq="M", max_age=100),
                        {end: -5, month(end,-1): 10}, end)
        self.assertEqual(row["changes"], {"1A": -15})

    def test_inverse_quote_holiday(self):
        end = date(2025, 1, 6)
        r = summarize(dict(change="inverse", freq="D", max_age=10),
                      {date(2025, 1, 3): 150, end: 151}, end)
        self.assertLess(r["changes"]["1G"], 0)

    def test_target_and_gaps(self):
        today = date(2025, 12, 17)
        end = date(2025, 10, 1)
        row = dict(id="x", period=str(end), stale=False)
        data = {end: 50, month(end,-1): 5, month(end,-2): 7}
        signal, = forecast([(row, data)], today)
        self.assertEqual((signal["estimate"], signal["baseline"], signal["target"]), (7,50,"2026-01-01"))
        del data[month(end,-1)]
        self.assertFalse(forecast([(row, data)], today))

    def test_no_macro_data(self):
        self.assertTrue(all("veri eksik" in r for r in conditions([])))
