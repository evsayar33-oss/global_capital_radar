import unittest,tempfile
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from daily_evidence import add_snapshot,coverage,preserve_vintage
from secondary_sources import ETFIQ_URL
from runner_recovery import shfe_read_once_retry
from full_source_gate import evaluate

class DailyEvidenceTests(unittest.TestCase):
    def test_immutable_daily_and_gap(self):
        d=date(2026,11,23);p=date(2026,11,20);g=date(2026,11,19);prev=date(2026,11,18)
        now=datetime(2026,11,24,14,tzinfo=timezone.utc)
        def row(day,prior,flow):return dict(source="ETFIQ (etfiq.com)",source_url=ETFIQ_URL,
            source_date=str(day),funds={"QQQ":dict(status="OBSERVED",start_aum_date=str(prior),flow_usd=flow,start_aum_usd=100)})
        h={};cal=[prev,g,p,d]
        add_snapshot(h,row(d,p,10),now,now,cal)
        add_snapshot(h,row(d,p,11),now,now,cal)
        add_snapshot(h,row(g,prev,0),now,now,cal)
        self.assertEqual(h["QQQ"][str(d)]["flow_usd"],10)
        self.assertEqual(h["QQQ"][str(d)]["revisions"][0]["flow_usd"],11)
        self.assertEqual(coverage(h,cal,["QQQ"])["QQQ"]["contiguous_days"],1)
        self.assertEqual(coverage(h,cal,["QQQ"])["QQQ"]["observed_days"],2)
        add_snapshot(h,row(p,prev,99),now,now,cal)
        self.assertNotIn(str(p),h["QQQ"])
    def test_vintage_not_context(self):
        now=datetime(2026,11,24,14,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.assertFalse(preserve_vintage(root,{"status":"OBSERVED_CURRENT_PUBLICATION"},now))
            v=dict(status="OBSERVED_DATE_VINTAGE",series="DFII10",vintage="2026-11-23",
                   observations=[dict(observation_date="2026-11-20",value=2.77)])
            self.assertTrue(preserve_vintage(root,v,now))
            self.assertTrue(preserve_vintage(root,v,now))
            self.assertEqual(len(list(root.rglob("*.json"))),1)
            v["observations"][0]["observation_date"]="2026-11-24"
            with self.assertRaises(ValueError):preserve_vintage(root,v,now)
    def test_shfe_retry_not_denial(self):
        calls=[]
        def reader(url,parser):
            calls.append(url)
            if len(calls)==1:raise URLError(ConnectionResetError())
            return {"status":"OBSERVED"},"RAW_HTTP_200"
        self.assertEqual(shfe_read_once_retry("url",lambda x:x,reader,lambda _:None)[0]["status"],"OBSERVED")
        self.assertEqual(len(calls),2)
        calls.clear()
        def denied(url,parser):
            calls.append(url);raise HTTPError(url,403,"Forbidden",None,None)
        with self.assertRaises(HTTPError):shfe_read_once_retry("url",lambda x:x,denied,lambda _:None)
        self.assertEqual(len(calls),1)
    def test_gate_no_substitution(self):
        checks=evaluate({"native_status":{"TREASURY_REAL_YIELD":"OBSERVED_CURRENT_PUBLICATION",
            "WTI_USL_PAIR":"OBSERVED_ISSUER_VALUATION_PAIR"}},{},{},{})
        self.assertTrue(checks["TREASURY_REAL_YIELD"]["pass_"])
        self.assertFalse(checks["ALFRED_true_vintage"]["pass_"])
        self.assertFalse(checks["WTI_official_settlement"]["pass_"])
        self.assertFalse(checks["daily_history_QQQ"]["pass_"])
