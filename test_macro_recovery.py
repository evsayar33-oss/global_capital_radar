import unittest,json
from datetime import date,datetime,timezone
from macro_recovery import alfred_csv,contract_pair,contract_closes,wti_pair,treasury_auction,issuer_revision,first_creation
class MacroRecoveryTests(unittest.TestCase):
    def test_actual_vintage_header(self):
        data="observation_date,DFII10_20261123\n2026-11-19,2.88\n2026-11-20,2.77\n2026-11-21,\n"
        r=alfred_csv("DFII10",date(2026,11,23),lambda _:data)
        self.assertEqual(r["observations"][-1]["value"],2.77)
        self.assertFalse(r["publication_intraday_verified"])
        for bad in (data.replace("20261123","20261124"),data+"2026-11-24,2.6\n"):
            with self.assertRaises(ValueError):alfred_csv("DFII10",date(2026,11,23),lambda _:bad)
    def test_vintage_bounded_retry(self):
        from urllib.parse import urlsplit,parse_qs
        from urllib.error import HTTPError
        calls=[]
        def reader(url):
            calls.append(parse_qs(urlsplit(url).query))
            if len(calls)==1:raise TimeoutError("transient")
            return "observation_date,DFII10_20261123\n2026-11-20,2.77\n"
        r=alfred_csv("DFII10",date(2026,11,23),reader)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]["cosd"],["2026-10-23"])
        self.assertEqual(calls[1]["cosd"],["2026-11-09"])
        self.assertEqual(r["requested_window_days"],14)
        denied=[]
        def blocked(url):
            denied.append(url)
            raise HTTPError(url,403,"Forbidden",None,None)
        with self.assertRaises(HTTPError):alfred_csv("DFII10",date(2026,11,23),blocked)
        self.assertEqual(len(denied),1)
    def test_contract_pair(self):
        self.assertEqual(contract_pair(date(2026,11,23)),[(2027,1),(2027,2)])
        self.assertEqual(contract_pair(date(2026,12,2)),[(2027,1),(2027,2)])
        with self.assertRaises(ValueError):contract_pair(date(2026,11,20))
        def reader(url):
            jan="CLF27.NYM" in url;sym="CLF27.NYM" if jan else "CLG27.NYM"
            # Observed Yahoo contract close values on Nov 23; current day excluded.
            return json.dumps({"chart":{"error":None,"result":[{
                "meta":{"symbol":sym,"instrumentType":"FUTURE","currency":"USD","exchangeName":"NYM",
                        "longName":"Crude Oil Jan 27" if jan else "Crude Oil Feb 27"},
                "timestamp":[1795410000,1795496400],
                "indicators":{"quote":[{"close":[80.17 if jan else 79.07,999]}]}}]}})
        r=wti_pair(datetime(2026,11,24,14,tzinfo=timezone.utc),reader)
        self.assertAlmostEqual(r["front_minus_next_usd_per_barrel"],1.10)
        self.assertFalse(r["official_settlement_verified"])
        self.assertFalse(r["production_proxy_allowed"])
    def test_auction_context(self):
        r={"securityType":"Bill","securityTerm":"13-Week","cashManagementBill":"No",
           "competitiveAuctionCloseDate":"2026-11-23T00:00:00","cusip":"912797WC7",
           "issueDate":"2026-11-27T00:00:00","maturityDate":"2027-02-25T00:00:00",
           "highRate":"4.180","bidToCoverRatio":"2.74"}
        v=treasury_auction(date(2026,11,24),lambda _:json.dumps([r]))
        self.assertAlmostEqual(v["implied_final_settlement_index"],95.82)
        self.assertFalse(v["actual_tbf3_settlement_verified"])
        self.assertFalse(v["cot_verified"])
        with self.assertRaises(ValueError):treasury_auction(date(2026,11,23),lambda _:json.dumps([r]))
    def test_late_creation_and_revisions(self):
        hist={};base=dict(status="OBSERVED",source_date="2026-11-23",
            source_sha256="same",creation_status="UNAVAILABLE",shares=100,nav_usd=10)
        a=datetime(2026,11,24,13,tzinfo=timezone.utc);b=datetime(2026,11,24,14,tzinfo=timezone.utc)
        issuer_revision(hist,base,a)
        self.assertIsNone(first_creation(hist["2026-11-23"]))
        obs=dict(base,creation_status="OBSERVED",net_created_shares=5,estimated_creation_usd=50,creation_source_sha256="a")
        issuer_revision(hist,obs,b)
        issuer_revision(hist,dict(obs,net_created_shares=6,estimated_creation_usd=60,creation_source_sha256="b"),b)
        self.assertEqual(first_creation(hist["2026-11-23"])["estimated_creation_usd"],50)
        self.assertEqual(first_creation(hist["2026-11-23"])["first_seen_at"],b.isoformat())
        self.assertEqual(len(hist["2026-11-23"]["revisions"]),2)
