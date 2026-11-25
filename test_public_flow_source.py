import unittest
from datetime import date,timedelta
from public_flow_source import parse,collect

class PublicFlowTests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,11,25)
        self.calendar=[date(2026,11,16)+timedelta(days=i) for i in range(9) if (date(2026,11,16)+timedelta(days=i)).weekday()<5]
        self.html='<title>SPY — Fund</title><p>Flows through Nov 23, 2026</p><figure data-chart="daily-net-flows-1m"><table><tbody>'+''.join('<tr><th>'+d.strftime('%b %d')+'</th><td>'+v+'</td></tr>' for d,v in zip(self.calendar[:-1],['$1M','−$2M','$0','$3M','$4M','$5M']))+'</tbody></table></figure>'
    def test_values_and_precision(self):
        raw,meta=parse(self.html,'SPY',self.today,self.calendar)
        self.assertEqual(raw[date(2026,11,17)],-2000000)
        self.assertEqual(raw[date(2026,11,18)],0)
        self.assertEqual(meta['precision'],'PUBLISHER_ROUNDED')
        r=collect('SPY',self.today,self.calendar,lambda _:self.html)
        self.assertEqual(r['status'],'OBSERVED')
        self.assertTrue(r['action'].startswith('BEKLE'))
        self.assertTrue(all(h['magnitude_percentile'] is None for h in r['horizons'].values()))
    def test_identity_units_and_dates_fail_closed(self):
        for html in [self.html.replace('SPY —','QQQ —'),self.html.replace('$1M','1M'),self.html.replace('Nov 23, 2026','Nov 26, 2026'),self.html.replace('Nov 23, 2026','Nov 10, 2026'),self.html.replace('Nov 17</th>','Nov 16</th>')]:
            with self.subTest(html=html[:80]):
                with self.assertRaises(ValueError):parse(html,'SPY',self.today,self.calendar)
    def test_weekly_table_cannot_substitute_for_daily(self):
        with self.assertRaises(ValueError):parse(self.html.replace('daily-net-flows-1m','weekly-net-flows-1m'),'SPY',self.today,self.calendar)

class FarsideTests(unittest.TestCase):
    def test_column_identity_units_missing_and_negative(self):
        from public_flow_source import farside_parse
        days=[date(2026,11,d) for d in (16,17,18,19,20,23,24)]
        html='<h1>Bitcoin ETF Flow (US$m)</h1><table><tr><td></td><td>OTHER</td><td>IBIT</td></tr>'+''.join('<tr><td>'+d.strftime('%d %b %Y')+'</td><td>9999</td><td>(1.2)</td></tr>' for d in days)+'<tr><td>25 Nov 2026</td><td>0</td><td>-</td></tr></table>'
        r=farside_parse(html,'IBIT',date(2026,11,25),days)
        self.assertEqual(len(r),7);self.assertEqual(r[days[-1]],-1200000)
        with self.assertRaises(ValueError):farside_parse(html.replace('US$m','USD'),'IBIT',date(2026,11,25),days)
        with self.assertRaises(ValueError):farside_parse(html.replace('<td>-</td>','<td>0</td>'),'IBIT',date(2026,11,25),days)
