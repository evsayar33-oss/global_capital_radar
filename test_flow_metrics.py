import unittest
from datetime import date,timedelta
from pathlib import Path
from flow_metrics import pressure,daily_window
from dashboard_data import monthly_reference_rows

class FlowMetricsTests(unittest.TestCase):
    def test_pressure_and_zero(self):
        self.assertEqual(pressure([100,-25,25]),66.6667)
        self.assertEqual(pressure([-100,-1]),-100)
        self.assertEqual(pressure([1,-1]),0)
        self.assertIsNone(pressure([0,0]))
        self.assertIsNone(pressure([1,float("nan")]))

    def test_complete_window_no_gap(self):
        end=date(2026,11,23)
        sessions=[end-timedelta(days=i) for i in range(10,-1,-1) if (end-timedelta(days=i)).weekday()<5]
        raw={x:1e6 for x in sessions if x>date(2026,11,16)}
        result=daily_window(raw,sessions,end,"1H")
        self.assertEqual(result["net_usd_m"],5)
        self.assertEqual(result["directional_pressure_pct"],100)
        self.assertEqual(result["directional_sessions"],5)
        del raw[date(2026,11,19)]
        self.assertEqual(daily_window(raw,sessions,end,"1H"),{})

    def test_real_archives_dated_separate(self):
        root=Path(__file__).parent/"history"
        clock="2026-11-25T19:17:25+00:00"
        for key in ("1A","3A","1Y"):
            rows=monthly_reference_rows(root,key,clock)
            self.assertEqual({r["Fon"] for r in rows},{"QQQ","CPER","USO"})
            for r in rows:
                self.assertLess(r["Dönem sonu"],clock[:10])
                self.assertEqual(r["Durum"],"ARŞİV · güncel hareketli vade değil")
        self.assertEqual(monthly_reference_rows(root,"1H",clock),[])
        self.assertEqual(monthly_reference_rows(root,"1Y","2020-01-01T00:00:00+00:00"),[])
