import unittest,json
from datetime import date,datetime,timedelta,timezone
from native_adapters import okx_crypto,parse_shfe,tbf3

class NativeAdaptersTests(unittest.TestCase):
    def test_settlement_basis_spread(self):
        now=datetime(2026,11,24,12,tzinfo=timezone.utc)
        ms=int(now.timestamp()*1000);inst="BTC-USDT-SWAP"
        def read(url):
            if "funding-rate-history" in url:
                rows=[dict(instId=inst,instType="SWAP",fundingTime=str(ms-i*3600000),realizedRate="0.0001") for i in (0,1)]
            elif "mark-price" in url:
                rows=[dict(instId=inst,ts=str(ms),markPx="101")]
            elif "index-tickers" in url:
                rows=[dict(instId="BTC-USDT",ts=str(ms),idxPx="100")]
            else:rows=[dict(instId=inst,ts=str(ms),bidPx="100",askPx="100.1")]
            return json.dumps(dict(code="0",data=rows))
        r=okx_crypto(inst,now,read,lambda:now)
        self.assertAlmostEqual(r["annualized_pct"],87.6)
        self.assertAlmostEqual(r["basis_pct"],1)
        self.assertGreater(r["quoted_spread_bps"],0)
        def failed(url):
            if "index-tickers" in url:raise OSError("blocked")
            return read(url)
        self.assertIsNone(okx_crypto(inst,now,failed,lambda:now)["basis_pct"])
        with self.assertRaises(ValueError):
            okx_crypto("ETH-USDT-SWAP",now,read,lambda:now)

    def test_shfe_reconciliation(self):
        html="""<p>Shanghai Futures Exchange Warehouse Stocks Daily DATE:2026-11-17</p>
        <table><tr><td>Region</td><td>Warehouse</td><td>On Warrant</td><td>Change</td></tr>
        <tr><td>COPPER</td><td>Unit：Tonne</td></tr>
        <tr><td>Region</td><td>Warehouse</td><td>On Warrant</td><td>Change</td></tr>
        <tr><td>Shanghai</td><td>Subtotal</td><td>1,000</td><td>-20</td></tr>
        <tr><td>Subtotal</td><td>500</td><td>10</td></tr>
        <tr><td>Total</td><td>1500</td><td>-10</td></tr></table>"""
        day=date(2026,11,17)
        self.assertEqual(parse_shfe(html,day)["on_warrant_tonnes"],1500)
        for bad in (html.replace("1500","1501"),html.replace("Tonne","Pound"),html.replace("2026-11-17","2026-11-16")):
            with self.assertRaises(ValueError):parse_shfe(bad,day)

    def test_tbf_empty_distinct_from_network_error(self):
        d=date(2026,11,24)
        h,r=tbf3(d,lambda _: "[]")
        self.assertEqual(h,{})
        self.assertEqual(r["status"],"NO_CURRENT_COT_SERIES")
        with self.assertRaises(ValueError):tbf3(d,lambda _: "{}")
