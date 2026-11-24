import unittest,json,tempfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from flow_continuity import observed,choose,issuer_history,etfiq_daily,collect
from experiments import record,compare

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,11,24)
        self.calendar=[date(2026,11,d) for d in (13,16,17,18,19,20,23)]
        self.now=datetime(2026,11,24,14,tzinfo=timezone.utc)
    def test_gap_never_bridged_and_no_daily_signal(self):
        raw={self.calendar[0]:100,self.calendar[-1]:200}
        r=observed("SPY","ETFIQ_HISTORY",raw,self.today,self.calendar,{})
        self.assertEqual(r["daily_count"],1)
        self.assertEqual(r["horizons"],{})
        self.assertEqual(r["daily_flow_usd"],200)
        self.assertEqual(r["role"],"SOURCE_SEPARATE_RESEARCH_ONLY")
        with self.assertRaises(ValueError):
            observed("SPY","ETFIQ_HISTORY",{self.calendar[0]:100},self.today,self.calendar,{})
    def test_independent_selection(self):
        raw={d:100 for d in self.calendar}
        a=observed("USO","ETFIQ_HISTORY",raw,self.today,self.calendar,{})
        b=observed("USO","USCF_CREATION",{self.calendar[-1]:-500},self.today,self.calendar,{})
        self.assertEqual(choose([a,b])["provider"],"ETFIQ_HISTORY")
        self.assertEqual(a["daily_flow_usd"],100)
        self.assertEqual(b["daily_flow_usd"],-500)
        self.assertTrue(all(h["action"].startswith("BEKLE") for h in a["horizons"].values()))
    def test_issuer_exact_first_seen(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"history/native_research/issuer_snapshots"
            p.mkdir(parents=True)
            entry=dict(status="OBSERVED",creation_status="OBSERVED",symbol="USO",
                upstream_id="USCF",shares_precision="exact_integer",source_date="2026-11-23",
                first_seen_at="2026-11-24T13:00:00+00:00",net_created_shares=600000,
                nav_usd=133.31,estimated_creation_usd=79986000)
            (p/"USO.json").write_text(json.dumps({"2026-11-23":entry}))
            r=issuer_history(Path(td),"USO",self.today,self.calendar,self.now)
            self.assertEqual(r["daily_flow_usd"],79986000)
            self.assertEqual(r["daily_count"],1)
            self.assertEqual(r["horizons"],{})
            entry["first_seen_at"]="2026-11-25T13:00:00+00:00"
            (p/"USO.json").write_text(json.dumps({"2026-11-23":entry}))
            with self.assertRaises(ValueError):issuer_history(Path(td),"USO",self.today,self.calendar,self.now)
    def test_outage_does_not_create_wait_sample(self):
        h=dict(action="ALIM ADAYI",early_methods={"flow":"ALIM ADAYI"},experiment_version="early-v1")
        row=dict(symbol="GLD",error="403",horizons={"1H":h})
        with patch("experiments.Path.exists",return_value=False):
            record([row])
        self.assertNotIn("experiment_version",h)
        self.assertNotIn("early_methods",h)
        self.assertTrue(h["action"].startswith("BEKLE"))
        h["experiment_version"]="early-v1"
        with patch("experiments.persist_selection",side_effect=lambda x,y:x):
            self.assertEqual(compare([(self.today,{"assets":[row]})],{},self.today),{})
    def test_daily_requires_previous_session(self):
        daily={"source_date":"2026-11-23","funds":{"SPY":{"status":"OBSERVED","flow_usd":0,
                     "start_aum_usd":1000,"start_aum_date":"2026-11-20"}}}
        self.assertEqual(etfiq_daily("SPY",self.today,self.calendar,daily)["daily_flow_usd"],0)
        daily["funds"]["SPY"]["start_aum_date"]="2026-11-19"
        with self.assertRaises(ValueError):etfiq_daily("SPY",self.today,self.calendar,daily)
