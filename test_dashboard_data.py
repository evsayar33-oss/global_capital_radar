import json
import tempfile
import unittest
from pathlib import Path

from dashboard_data import read_report, latest_macro, coverage_rows, method_rows, native_rows, historical_rows, macro_rows


class DashboardDataTests(unittest.TestCase):
    def test_reports_and_missing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNotNone(read_report(root, "absent.json")[1])
            (root / "2026-11-23.json").write_text('{"as_of":"old"}')
            (root / "2026-11-24.json").write_text('{"as_of":"new"}')
            (root / "validation.json").write_text('{"as_of":"not macro"}')
            self.assertEqual(latest_macro(root), ({"as_of": "new"}, None))
            (root / "2026-11-24.json").write_text("invalid")
            self.assertIsNotNone(latest_macro(root)[1])

    def test_unavailable_not_zero_and_cost_labels(self):
        model = {"available": 0, "active": 0, "hit_rate": None, "cost_stress": {"0.3": {"n": 0}}}
        rows = method_rows({"SPY/1H": {"models": {"M01": model}, "independent_periods": 5},
                            "SPY/1A": {"models": {"M01": dict(model, available=5, hit_rate=0.4, cost_stress={"0.3":{"mean_pp": -0.2}})}}}, "1A")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["İsabet %"], 40)
        self.assertEqual(rows[0]["30 bp ort. SGOV farkı (puan)"], -0.2)
        self.assertIsNone(rows[0]["10 bp ort. SGOV farkı (puan)"])
        self.assertIsNone(method_rows({"SPY/1H":{"models":{"M00":model}}})[0]["İsabet %"])

    def test_research_only_and_source_errors_preserved(self):
        self.assertEqual(coverage_rows({"coverage":[{"symbol":"USO","status":"UNAVAILABLE","error":"403"}]})[0]["Hata"], "403")
        rows = native_rows({"WTI": {"status":"UNAVAILABLE_CURRENT_OFFICIAL"}, "WTI_CLOSE_PAIR":{"status":"OBSERVED_DELAYED_CLOSE_PAIR","front_minus_next_usd_per_barrel":1.1}})
        self.assertIsNone(rows[0]["WTI yakın vade farkı USD/varil"])
        self.assertEqual(rows[1]["WTI yakın vade farkı USD/varil"], 1.1)
        row = historical_rows({"symbols":{"QQQ":{"monthly_count":84,"daily_history_contiguous":False,"production_eligible":False}}})[0]
        self.assertEqual(row["Aylık kayıt"], 84)
        self.assertFalse(row["Üretime uygun"])
        self.assertEqual(macro_rows({"indicators":[{"id":"DFII10","error":"timeout"}]})[0]["Durum"], "Kaynak hatası")

    def test_committed_reports_are_readable_and_projectable(self):
        root = Path(__file__).parent / "history"
        for path, project in (
            ("native_research/results.json", coverage_rows),
            ("native_research/native_latest.json", native_rows),
            ("native_research/extended_history/results.json", historical_rows),
        ):
            data, error = read_report(root, path)
            self.assertIsNone(error)
            self.assertTrue(project(data))
        data, error = latest_macro(root)
        self.assertIsNone(error)
        self.assertTrue(macro_rows(data))

    def test_streamlit_renders_committed_report_if_installed(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("Streamlit unavailable in backend-only environment")
        app = AppTest.from_file(str(Path(__file__).parent / "streamlit_app.py")).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 5)
        self.assertTrue(any("Vadeli / native" in tab.label for tab in app.tabs))
        self.assertGreaterEqual(len(app.dataframe), 6)


class DashboardOutageTests(unittest.TestCase):
    def test_selected_horizon_and_disabled_method(self):
        from dashboard_data import rotation_rows
        asset=dict(asset='S&P 500',symbol='SPY',error='403',cot_change_pp=2.39,
                   horizons={'1A':dict(cot_change_pp=9.5,action='BEKLE')})
        row=rotation_rows([asset],'1A')[0]
        self.assertEqual(row['CFTC pozisyon farkı (puan)'],9.5)
        self.assertIn('Devre dışı',row['Etkin yöntem'])
        self.assertIn('Dönem başı',row['Eksik veri açıklaması'])
        self.assertIsNone(rotation_rows([asset],'1Y')[0]['CFTC pozisyon farkı (puan)'])

    def test_missing_and_stale_alternative_are_explained(self):
        from dashboard_data import continuity_rows
        assets=[{'symbol':'SPY'}]
        report={'assets':{'SPY':{'errors':{'ETFIQ_HISTORY':'stale'},'selected':None}}}
        row=continuity_rows(assets,report,'1H')[0]
        self.assertIn('stale',row['Kaynak hataları'])
        report['assets']['SPY']['stale_reference']={'stale':True,'lag_sessions':2,'daily_flow_usd':0}
        row=continuity_rows(assets,report,'1H')[0]
        self.assertEqual(row['Günlük net USD'],0)
        self.assertIn('ESKİ',row['Durum'])
        self.assertEqual(row['Karar'],'BEKLE · alternatif veri eski')


class ObservedProjectionTests(unittest.TestCase):
    def test_year_keyed_expectations_and_archived_values(self):
        from dashboard_data import expectation_rows
        rows=expectation_rows({"Fed SEP":{"2026":4.1,"2027":4.0},
            "IMF":{"error":"403","archive":"WEO","archived_forecast":{"2026":4.7}},
            "Future":{"period":"2026-11-25","value":0}})
        self.assertEqual([(r["Dönem"],r["Değer"]) for r in rows[:2]],[("2026",4.1),("2027",4.0)])
        self.assertIn("Arşiv",rows[2]["Durum"])
        self.assertEqual(rows[2]["Hata"],"403")
        self.assertEqual(rows[3]["Değer"],0)

    def test_overview_never_mixes_failed_primary_with_alternative(self):
        from dashboard_data import overview_rows
        asset={"asset":"S&P","symbol":"SPY","error":"403","horizons":{"1H":{"net_usd_m":999}}}
        obs={"provider":"ETFIQ_HISTORY","flow_asof":"2026-11-23","daily_flow_usd":100,
             "status":"OBSERVED","horizons":{"1H":{"net_usd_m":2,"flow_aum_pct":0}}}
        continuity={"assets":{"SPY":{"selected":obs,"status":"ALTERNATIVE_OBSERVED"}}}
        row=overview_rows([asset],continuity,"1H")[0]
        self.assertEqual(row["Vade net milyon USD"],2)
        self.assertEqual(row["Akış / başlangıç fon büyüklüğü %"],0)
        self.assertIn("üretim onayı yok",row["Karar"])
        self.assertIsNone(overview_rows([asset],{},"1H")[0]["Vade net milyon USD"])
        self.assertIsNone(overview_rows([asset],continuity,"1Y")[0]["Vade net milyon USD"])


class HorizonObservationTests(unittest.TestCase):
    def test_source_selection_uses_requested_horizon_not_daily_winner(self):
        from dashboard_data import overview_rows
        asset={"asset":"Oil","symbol":"USO","error":"403"}
        short={"provider":"USCF_CREATION","status":"OBSERVED","flow_asof":"2026-11-24","daily_flow_usd":1000000}
        long={"provider":"ETFIQ_HISTORY","status":"OBSERVED","flow_asof":"2026-11-23",
              "daily_flow_usd":2000000,"horizons":{"1H":{"net_usd_m":11},"1A":{"net_usd_m":22},
                                                  "3A":{"net_usd_m":33},"1Y":{"net_usd_m":44}}}
        c={"assets":{"USO":{"selected":short,"candidates":[short,long]}}}
        for key,value in (("1G",1),("1H",11),("1A",22),("3A",33),("1Y",44)):
            r=overview_rows([asset],c,key)[0]
            self.assertEqual(r["Vade net milyon USD"],value)
            self.assertEqual(r["Akış kaynağı"],"USCF_CREATION" if key=="1G" else "ETFIQ_HISTORY")
        self.assertEqual(overview_rows([asset],c,"1A")[0]["Vade başlangıç sınırı"],"2026-10-23")

    def test_live_snapshot_all_horizons_streamlit(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("Streamlit unavailable")
        from dashboard_data import overview_rows
        root=Path(__file__).parent
        report=json.loads((root/"history/rotation/latest.json").read_text())
        app=AppTest.from_file(str(root/"streamlit_app.py")).run(timeout=30)
        for key in ("1G","1H","1A","3A","1Y"):
            app.radio[0].set_value(key).run(timeout=30)
            self.assertFalse(app.exception)
            actual=app.dataframe[0].value.set_index("Fon")
            expected=overview_rows(report["assets"],report.get("continuity",{}),key)
            for row in expected:
                value=row["Vade net milyon USD"]
                got=actual.loc[row["Fon"],"Vade net milyon USD"]
                if value is None:
                    import pandas as pd
                    self.assertTrue(pd.isna(got))
                else:
                    self.assertAlmostEqual(got,value)


    def test_daily_prefers_verified_same_date_aum(self):
        from flow_view import observation
        a={"asset":"SPY","symbol":"SPY","error":"403"}
        h={"provider":"ETFIQ_HISTORY","status":"OBSERVED","flow_asof":"2026-11-23",
           "daily_flow_usd":100,"daily_count":400,"daily_observation":{"reference_count":52}}
        d={"provider":"ETFIQ_DAILY","status":"OBSERVED","flow_asof":"2026-11-23",
           "daily_flow_usd":100,"daily_count":1,"daily_observation":{"flow_aum_pct":0.1}}
        o=observation(a,{"assets":{"SPY":{"selected":h,"candidates":[h,d]}}},"1G")
        self.assertEqual(o["h"]["flow_aum_pct"],0.1)
        self.assertEqual(o["source"],"ETFIQ_DAILY")
