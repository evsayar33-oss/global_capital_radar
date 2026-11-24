import unittest
from datetime import date,timedelta,datetime,timezone
import json
from native_research import parse_history,alfred_vintage,crypto,cost_context,issuer_aum_crosscheck

class NativeResearchTests(unittest.TestCase):
    def test_etfiq_history_contiguous_and_no_monthly_splice(self):
        end=date(2026,11,20)
        cal=[end-timedelta(days=i) for i in range(8,-1,-1)]
        p=dict(schemaVersion=3,ticker="SPY",cite={"publisher":"ETFIQ"},asOf=str(end),
            daily=[dict(d=str(d),navDate=str(cal[i-1]),flow=100) for i,d in enumerate(cal) if i],
            monthly=[dict(m="2020-01",flow=1e12)],windows={})
        raw,aum,meta=parse_history(p,"SPY",end,cal)
        self.assertEqual(len(raw),8)
        self.assertEqual(sum(raw.values()),800)
        self.assertEqual(meta["units"],"USD")
        self.assertEqual(aum,{})
        p["daily"]=[r for r in p["daily"] if r["d"]!=str(cal[5])]
        with self.assertRaises(ValueError):parse_history(p,"SPY",end,cal)

    def test_vintage_and_secret_absence(self):
        d=date(2026,11,20)
        # Key-free fallback must be tested with injected data, not the network.
        v=alfred_vintage("DFII10",d,None,lambda _:"observation_date,DFII10_20261120\n2026-11-19,2.88\n")
        self.assertEqual(v["status"],"OBSERVED_DATE_VINTAGE")
        self.assertEqual(v["observations"][0]["value"],2.88)
        self.assertEqual(alfred_vintage("DFII10",d,None,lambda _:"invalid")["status"],"UNAVAILABLE")
        p={"observations":[dict(date="2026-11-21",value="3",realtime_start=str(d),realtime_end=str(d))]}
        self.assertEqual(alfred_vintage("DFII10",d,"secret",lambda _:json.dumps(p))["status"],"UNAVAILABLE")

    def test_authenticated_vintage_and_safe_fallback(self):
        d=date(2026,11,24)
        payload={"observations":[dict(date="2026-11-23",value="2.79",realtime_start=str(d),realtime_end=str(d))]}
        result=alfred_vintage("DFII10",d,"private-key",lambda _:json.dumps(payload))
        self.assertEqual(result["source"],"FRED API / ALFRED")
        self.assertTrue(result["realtime_interval_verified"])
        self.assertNotIn("private-key",str(result))
        def fallback(url):
            if "api.stlouisfed.org" in url:
                raise ValueError("private-key")
            return "observation_date,DFII10_20261124\n2026-11-23,2.79\n"
        result=alfred_vintage("DFII10",d,"private-key",fallback)
        self.assertEqual(result["source"],"ALFRED graph CSV")
        self.assertEqual(result["api_error"],"ValueError")
        self.assertNotIn("private-key",str(result))
        payload["observations"].append(payload["observations"][0])
        self.assertEqual(alfred_vintage("DFII10",d,"private-key",lambda _:json.dumps(payload))["status"],"UNAVAILABLE")

    def test_funding_interval_and_basis(self):
        now=datetime(2026,11,20,12,tzinfo=timezone.utc)
        ts=int(now.timestamp()*1000)
        p=[dict(symbol="BTCUSDT",fundingTime=ts-3600000,fundingRate="0.0001"),
           dict(symbol="BTCUSDT",fundingTime=ts,fundingRate="0.0001")]
        m=dict(symbol="BTCUSDT",time=ts,markPrice="101",indexPrice="100")
        result=crypto("BTCUSDT",now,lambda u:json.dumps(p if "fundingRate?" in u else m))
        self.assertEqual(result["interval_hours"],1)
        self.assertAlmostEqual(result["annualized_pct"],87.6)
        self.assertAlmostEqual(result["basis_pct"],1.)

    def test_missing_cost_and_aum(self):
        self.assertIsNone(cost_context()["commission_bps"])
        self.assertIsNone(issuer_aum_crosscheck({},100,"2026-11-20")["relative_error_pct"])
        a=issuer_aum_crosscheck(dict(status="OBSERVED",start_aum_date="2026-11-20",start_aum_usd=100),101,"2026-11-20")
        self.assertAlmostEqual(a["relative_error_pct"],1.)
