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


class StaleReferenceTests(unittest.TestCase):
    def test_stale_reference_is_never_selected(self):
        calendar=[date(2026,11,d) for d in (13,16,17,18,19,20,23,24)]
        raw={d:0 for d in calendar[:-2]}
        r=observed('SPY','ETFIQ_HISTORY',raw,date(2026,11,25),calendar,{},retain_stale=True)
        self.assertEqual(r['status'],'STALE_REFERENCE')
        self.assertEqual(r['lag_sessions'],2)
        self.assertEqual(r['daily_flow_usd'],0)
        self.assertIsNone(choose([r]))
        self.assertTrue(r['action'].startswith('BEKLE'))
        with self.assertRaises(ValueError):
            observed('SPY','ETFIQ_HISTORY',raw,date(2026,11,25),calendar,{})
        for bad in (date(2026,11,26),date(2026,11,22)):
            with self.assertRaises(ValueError):
                observed('SPY','ETFIQ_HISTORY',{**raw,bad:20},date(2026,11,25),calendar,{},retain_stale=True)

    def test_collect_reports_reference_without_counting_it_fresh(self):
        import flow_continuity
        stale=dict(status='STALE_REFERENCE',stale=True,flow_asof='2026-11-20',daily_count=10,
                   provider='ETFIQ_HISTORY',symbol='SPY')
        with patch.object(flow_continuity,'etfiq_history',return_value=stale):
            r=collect(Path('.'),[dict(symbol='SPY',error='403')],date(2026,11,25),
                      [date(2026,11,24)],lambda url:'{}',datetime(2026,11,25,tzinfo=timezone.utc))
        self.assertEqual(r['alternative_count'],0)
        self.assertEqual(r['unavailable_count'],1)
        self.assertIsNone(r['assets']['SPY']['selected'])
        self.assertEqual(r['assets']['SPY']['stale_reference'],stale)
        self.assertFalse(r['assets']['SPY']['production_eligible'])

    def test_history_aum_is_used_only_at_exact_period_start(self):
        import flow_continuity
        calendar=[date(2026,11,d) for d in (13,16,17,18,19,20,23,24)]
        raw={d:1000000 for d in calendar}
        with patch('native_research.parse_history',return_value=(raw,{date(2026,11,17):100000000},{})):
            r=flow_continuity.etfiq_history('SPY',date(2026,11,25),calendar,lambda url:'{}')
        self.assertEqual(r['horizons']['1H']['flow_aum_pct'],5)
        with patch('native_research.parse_history',return_value=(raw,{date(2026,11,16):100000000},{})):
            r=flow_continuity.etfiq_history('SPY',date(2026,11,25),calendar,lambda url:'{}')
        self.assertNotIn('flow_aum_pct',r['horizons']['1H'])


class SessionCalendarTests(unittest.TestCase):
    def test_no_price_dependency_and_early_close(self):
        from flow_continuity import session_calendar,live
        today=date(2026,11,27)
        before=datetime(2026,11,27,17,59,tzinfo=timezone.utc)
        after=datetime(2026,11,27,18,1,tzinfo=timezone.utc)
        self.assertEqual(session_calendar(today,before)[-1],date(2026,11,25))
        self.assertEqual(session_calendar(today,after)[-1],today)
        self.assertNotIn(date(2026,11,26),session_calendar(today,after))
        with patch("evaluate_rotation.prices",side_effect=RuntimeError("HTTP 429")), \
             patch("flow_continuity.collect",return_value={"assets":{}}) as collect_mock:
            result=live(Path("."),[],today,lambda url:"{}",after)
        self.assertEqual(result["calendar_source"],"exchange_calendars XNYS")
        self.assertEqual(collect_mock.call_args.args[3][-1],today)

    def test_non_session_bounds_and_weekend(self):
        from flow_continuity import session_calendar
        today=date(2026,11,29)
        now=datetime(2026,11,29,14,tzinfo=timezone.utc)
        sessions=session_calendar(today,now)
        self.assertEqual(sessions[-1],date(2026,11,27))
        self.assertTrue(all(d.weekday()<5 for d in sessions))
        self.assertGreaterEqual(sessions[0],today-timedelta(days=25*366))

    def test_regular_close_boundary(self):
        from flow_continuity import session_calendar
        today=date(2026,11,25)
        self.assertEqual(session_calendar(today,datetime(2026,11,25,20,59,tzinfo=timezone.utc))[-1],
                         date(2026,11,24))
        self.assertEqual(session_calendar(today,datetime(2026,11,25,21,1,tzinfo=timezone.utc))[-1],today)

