import os
import unittest
from unittest.mock import patch
from datetime import date
import keyed_sources as k
import macro_sources as m


class KeyedSourcesTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{"EIA_API_KEY":"test-secret","BEA_API_KEY":"test-secret",
                                        "BLS_API_KEY":"test-secret","CENSUS_API_KEY":"test-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.today=date(2026,11,24)

    def test_eia_identity_and_units(self):
        p={"response":{"frequency":"daily","total":1,"data":[{"period":"2026-11-20","series":"RBRTE","units":"$/BBL","value":"80.5"}]}}
        rows,meta=k.eia_series("DCOILBRENTEU",self.today,lambda *a,**kw:(p,"hash"))
        self.assertEqual(rows[date(2026,11,20)],80.5)
        self.assertNotIn("test-secret",str(meta))
        p["response"]["data"][0]["series"]="RWTC"
        with self.assertRaises(ValueError):
            k.eia_series("DCOILBRENTEU",self.today,lambda *a,**kw:(p,"hash"))

    def test_bea_core_line_exact(self):
        p={"BEAAPI":{"Results":{"Data":[{"TableName":"T20804","LineNumber":"25","SeriesCode":"DPCCRG","LineDescription":"PCE excluding food and energy","TimePeriod":"2026M09","DataValue":"130.902"}]}}}
        rows,meta=k.bea_series("PCEPILFE",self.today,lambda *a,**kw:(p,"hash"))
        self.assertEqual(rows[date(2026,9,1)],130.902)
        self.assertNotIn("test-secret",str(meta))
        p["BEAAPI"]["Results"]["Data"][0]["LineDescription"]="Market-based PCE excluding food and energy"
        with self.assertRaises(ValueError):
            k.bea_series("PCEPILFE",self.today,lambda *a,**kw:(p,"hash"))

    def test_bls_registered_path(self):
        p={"status":"REQUEST_SUCCEEDED","Results":{"series":[{"seriesID":"CUSR0000SA0","data":[{"year":"2026","period":"M10","value":"337.476"}]}]}}
        with patch.object(m,"bls_authenticated",return_value=(p,"hash")):
            rows,meta=m.bls_series("CPIAUCSL",self.today,lambda _:self.fail("unexpected fallback"))
        self.assertTrue(meta["authenticated_request"])
        self.assertNotIn("test-secret",str(meta))

    def test_census_customs_not_bop_and_exact_scope(self):
        def reply(url,params):
            return [["GEN_VAL_MO","CTY_CODE","I_COMMODITY","time"],
                    ["12345","-","2709",params["time"]]],"hash"
        rows,meta=k.census_crude_imports(self.today,reply)
        self.assertEqual(len(rows),2)
        self.assertIn("NOT_BOP",meta["observation_basis"])
        self.assertNotIn("test-secret",str(meta))

    def test_secret_not_in_transport_error(self):
        with patch.object(k,"urlopen",side_effect=ValueError("test-secret")):
            with self.assertRaisesRegex(ValueError,"authenticated response failed") as c:
                k.request_json(k.BEA_URL,{"UserID":"test-secret"})
        self.assertNotIn("test-secret",str(c.exception))

    def test_safe_diagnostics_allowlist(self):
        self.assertEqual(k.safe_failure(ValueError("authenticated HTTP status 403")),"authenticated HTTP status 403")
        self.assertEqual(k.safe_failure(ValueError("BEA line identity mismatch")),"BEA line identity mismatch")
        self.assertEqual(k.safe_failure(ValueError("https://api.example?key=test-secret")),"ValueError")

    def test_eia_pages_and_hashes(self):
        calls=[]
        def reply(url,params):
            calls.append((url,params.copy()))
            i=params["offset"]
            row={"period":f"2026-11-{19+i}","series":"RBRTE","units":"$/bbl","value":"81"}
            return {"response":{"frequency":"daily","total":"2","data":[row]}},f"hash-{i}"
        rows,meta=k.eia_series("DCOILBRENTEU",self.today,reply)
        self.assertEqual(len(rows),2)
        self.assertEqual([c[1]["offset"] for c in calls],[0,1])
        self.assertEqual(calls[0][1]["facets[series][]"],"RBRTE")
        self.assertTrue(calls[0][0].endswith("/petroleum/pri/spt/data/"))
        self.assertEqual(meta["source_sha256"],["hash-0","hash-1"])

    def test_eia_duplicate_page_rejected(self):
        row={"period":"2026-11-20","series":"RBRTE","units":"$/BBL","value":"81"}
        with self.assertRaisesRegex(ValueError,"date or pagination mismatch"):
            k.eia_series("DCOILBRENTEU",self.today,lambda *a,**kw:({"response":{"total":2,"data":[row]}},"hash"))

    def test_bea_headline_and_wrong_series_rejected(self):
        row={"TableName":"T20804","LineNumber":"1","SeriesCode":"DPCERG",
             "LineDescription":"Personal consumption expenditures (PCE)","TimePeriod":"2026M09","DataValue":"130.902"}
        reply=lambda *a,**kw:({"BEAAPI":{"Results":{"Data":[row]}}},"hash")
        rows,_=k.bea_series("PCEPI",self.today,reply)
        self.assertEqual(len(rows),1)
        row["SeriesCode"]="DPCCRG"
        with self.assertRaisesRegex(ValueError,"BEA line identity mismatch"):
            k.bea_series("PCEPI",self.today,reply)
