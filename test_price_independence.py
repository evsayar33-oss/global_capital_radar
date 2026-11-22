import unittest
from datetime import date, timedelta
from unittest.mock import patch
from price_context import enrich


class PriceIndependenceTests(unittest.TestCase):
    def test_price_cannot_veto_flow_candidate(self):
        today = date(2026,11,22)
        end = date(2026,11,20)
        for declining in (True,False,None):
            row = {"symbol":"GLD","horizons":{"1H":{"action":"ALIM ADAYI","net_usd_m":10,"flow_aum_pct":1}}}
            def prices(symbol,*args):
                if declining is None:
                    raise ValueError("unavailable")
                last = 90 if declining and symbol=="GLD" else 110
                return {end-timedelta(days=7):(100,100),end:(last,last)}
            with patch("price_context.prices",side_effect=prices):
                enrich([row],today)
            self.assertEqual(row["horizons"]["1H"]["action"],"ALIM ADAYI")
