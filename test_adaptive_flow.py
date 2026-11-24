import unittest
from datetime import date,timedelta
from adaptive_flow import features, candidates, zscore, percentile, BUY, WAIT, BASE, PROXY
from adaptive_evaluation import collect, evaluate_tracks, score


class AdaptiveFlowTests(unittest.TestCase):
    def test_robust_and_degenerate(self):
        self.assertIsNone(zscore(10,[1]*20,"robust"))
        self.assertGreater(zscore(100,list(range(20)),"robust"), 5)
        self.assertIsNone(percentile(10,[1]*5))

    def test_asof_and_aum_normalization(self):
        end=date(2026,10,31)
        days=[end-timedelta(days=i) for i in range(500,-1,-1)]
        flow={d:float(1+(i%11)) for i,d in enumerate(days)}
        aum={d:1000.+i for i,d in enumerate(days)}
        f=features(flow,days,aum,days,end,"1H")
        future=end+timedelta(days=1)
        flow[future]=1e9
        aum[future]=1e9
        self.assertEqual(f,features(flow,days+[future],aum,days+[future],end,"1H"))
        self.assertAlmostEqual(f["normalized"],100*sum(flow[d] for d in days[-7:])/aum[end-timedelta(days=7)])

    def test_price_is_not_eligible(self):
        f=dict(raw=10,normalized=2,raw_rank=99,normalized_rank=99,z=3,robust_z=3,ewma_z=3,persistence=.8)
        a=candidates(f,base=BUY,proxy=-1)
        b=candidates(f,base=BUY,proxy=1)
        self.assertEqual(a.pop(PROXY),BUY)
        self.assertEqual(b.pop(PROXY),WAIT)
        self.assertEqual(a,b)
        self.assertIsNone(candidates({"raw":1})["M03_zscore"])

    def test_missing_is_not_wait_and_no_promotion_from_replay(self):
        self.assertIsNone(score(None,10,.1))
        self.assertEqual(score(WAIT,10,.1),0)
        rows=[dict(methods={BASE:WAIT,"M01_raw_percentile":BUY},excess_pp=2.) for _ in range(70)]
        self.assertEqual(evaluate_tracks({"GLD/1H":rows},exploratory=True)["GLD/1H"]["status"],"EXPLORATORY_ONLY")
        self.assertEqual(evaluate_tracks({"GLD/1H":rows[:29]})["GLD/1H"]["status"],"INSUFFICIENT")
        self.assertEqual(evaluate_tracks({"GLD/1H":rows})["GLD/1H"]["status"],"RESEARCH_ACCEPT")

    def test_duplicate_source_and_overlap(self):
        from adaptive_flow import VERSION
        start=date(2026,1,1)
        bars={start+timedelta(days=i):(100.,101.) for i in range(40)}
        report=lambda src: {"assets":[{"symbol":"GLD","flow_asof":src,"horizons":{"1H":{"adaptive_version":VERSION,"adaptive_methods":{BASE:BUY}}}}]}
        records=[(start,report("2026-01-01")),(start+timedelta(days=12),report("2026-01-01")),
                 (start+timedelta(days=13),report("2026-01-14"))]
        result=collect(records,{"GLD":bars,"SGOV":bars},start+timedelta(days=40))
        self.assertEqual(len(result["GLD/1H"]),2)

    def test_frozen_outcomes_survive_source_outage(self):
        from adaptive_flow import VERSION
        start=date(2026,1,1)
        bars={start+timedelta(days=i):(100.,101.) for i in range(40)}
        report={"assets":[{"symbol":"GLD","flow_asof":str(start),"horizons":{"1H":{"adaptive_version":VERSION,"adaptive_methods":{BASE:BUY}}}}]}
        first=collect([(start,report)],{"GLD":bars,"SGOV":bars},start+timedelta(days=40))
        self.assertEqual(len(first["GLD/1H"]),1)
        self.assertEqual(collect([(start,report)],{},start+timedelta(days=41),existing=first),first)

    def test_shadow_selection_does_not_change_production(self):
        from adaptive_flow import record
        method="M01_raw_percentile"
        h=dict(action=WAIT,cot_change_pp=1,early_methods={"flow_position":WAIT},
               adaptive_features=dict(raw=10,raw_rank=95,source_end="2026-11-20"))
        r=dict(symbol="GLD",horizons={"1H":h})
        record([r],{"GLD/1H":{"status":"RESEARCH_ACCEPT","candidate":method}})
        self.assertEqual(h["adaptive_shadow_action"],BUY)
        self.assertEqual(h["action"],WAIT)
        record([r],{"GLD/1H":{"status":"RESEARCH_REVOKED","candidate":method}})
        self.assertEqual(h["adaptive_shadow_method"],BASE)
