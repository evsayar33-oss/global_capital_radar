import unittest
from datetime import date
from filing_history import parse_uscf,parse_nport,exhibit,sparse
class FilingTests(unittest.TestCase):
    def test_cper_exact_fund(self):
        # Reduced numerical fields from SEC filing 0001104659-26-120528.
        html="""United States Commodity Index Fund Monthly Account Statement For the Month Ended September 30, 2026
        Statement of Changes in Net Asset Value Net Asset Value Beginning of Month 9/1/26 $ 393,754,849
        Additions (100,000 Shares) 10,843,770 Net Income (Loss) 11,351,901 Net Asset Value End of Month $ 415,950,520
        To the Shareholders of United States Commodity Index Fund
        United States Copper Index Fund Monthly Account Statement For the Month Ended September 30, 2026
        Statement of Changes in Net Asset Value Net Asset Value Beginning of Month 9/1/26 $ 750,295,665
        Additions (50,000 Shares) 1,959,385 Withdrawals (850,000 Shares) (34,184,975 )
        Net Income (Loss) (4,684,516 ) Net Asset Value End of Month $ 713,385,559
        Net Asset Value Per Share (17,950,000 Shares) $ 39.74 To the Shareholders of United States Copper Index Fund"""
        r=parse_uscf(html,"CPER",date(2026,10,30),"0001104659-26-120528","https://www.sec.gov/",date(2026,11,24))
        self.assertEqual(r["net_flow_usd"],-32225590)
        self.assertEqual(r["available_from_date"],"2026-10-31")
        with self.assertRaises(ValueError):parse_uscf(html.replace("713,385,559","713,385,000"),"CPER",date(2026,10,30),"x","",date(2026,11,24))
    def test_uso(self):
        html="""United States Oil Fund, LP Monthly Account Statement For the Month Ended September 30, 2026
        Statement of Changes in Net Asset Value Net Asset Value Beginning of Month 9/1/26 $ 1,790,469,813
        Additions (6,400,000 Shares) 940,698,279 Withdrawals (8,500,000 Shares) (1,264,202,703 )
        Net Income (Loss) 179,970,315 Net Asset Value End of Month $ 1,646,935,704
        To the Limited Partners of United States Oil Fund, LP"""
        r=parse_uscf(html,"USO",date(2026,10,30),"0001104659-26-120516","https://www.sec.gov/",date(2026,11,24))
        self.assertEqual(r["net_flow_usd"],-323504424)
        self.assertEqual(exhibit("<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>"+html+"</TEXT></DOCUMENT>"),html)
    def test_qqq(self):
        p={"schemaVersion":3,"ticker":"QQQ","cite":{"publisher":"ETFIQ"},"monthly":[
          {"m":"2019-07","flow":986655345,"src":"nport","accession":"0001752724-19-184787","filed":"2019-11-29","form":"NPORT-P","in":6469524994,"out":-5482869649,"scope":"fund"},
          {"m":"2026-10","src":"daily","flow":1}]}
        r=parse_nport(p,date(2026,11,24))
        self.assertEqual(len(r),1);self.assertEqual(r["2019-07"]["available_from_date"],"2019-11-30")
        p["monthly"][0]["flow"]+=10
        with self.assertRaises(ValueError):parse_nport(p,date(2026,11,24))
    def test_sparse(self):
        p={"schemaVersion":3,"ticker":"CPER","cite":{"publisher":"ETFIQ"},"asOf":"2026-11-10","daily":[
          {"d":"2026-11-02","navDate":"2026-10-30","flow":0},
          {"d":"2026-11-10","navDate":"2026-11-09","flow":-2}]}
        r=sparse(p,"CPER",date(2026,11,24))
        self.assertEqual(len(r),2);self.assertNotIn("2026-11-03",r)
        self.assertEqual(r["2026-11-02"]["flow_usd"],0)
