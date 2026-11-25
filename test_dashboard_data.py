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
