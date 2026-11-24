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
        p={"BEAAPI":{"Results":{"Data":[{"TableName":"T20804","LineNumber":"6","LineDescription":"PCE excluding food and energy","TimePeriod":"2026M09","DataValue":"130.902"}]}}}
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
