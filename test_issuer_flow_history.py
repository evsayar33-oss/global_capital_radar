import unittest
from datetime import date,timedelta
from issuer_flow_history import parse,collect


def workbook(rows,name='iShares Silver Trust'):
    def row(values):return '<ss:Row>'+''.join('<ss:Cell><ss:Data>'+str(v)+'</ss:Data></ss:Cell>' for v in values)+'</ss:Row>'
    return '<ss:Workbook xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><ss:Worksheet ss:Name="Disclaimers"><ss:Table><ss:Row><ss:Cell ss:HRef="https://example.org/?a=1&b=2"/></ss:Row></ss:Table></ss:Worksheet><ss:Worksheet ss:Name="Performance"><ss:Table>'+row([name])+'</ss:Table></ss:Worksheet><ss:Worksheet ss:Name="Historical"><ss:Table>'+row(['As Of','NAV per Share','Shares Outstanding'])+''.join(row(v) for v in rows)+'</ss:Table></ss:Worksheet></ss:Workbook>'

class IssuerHistoryTests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,11,25)
        self.days=[date(2026,11,2)+timedelta(days=i) for i in range(23) if (date(2026,11,2)+timedelta(days=i)).weekday()<5]
        self.rows=[[d.strftime('%b %d, %Y'),10,100+i*2] for i,d in enumerate(self.days)]
    def test_official_values_not_market_prices(self):
        r=collect('SLV',self.today,self.days,lambda _:workbook(self.rows))
        self.assertEqual(r['daily_flow_usd'],20)
        self.assertEqual(r['daily_count'],len(self.days)-1)
        self.assertEqual(r['provenance']['precision'],'ISSUER_DERIVED_ESTIMATE')
        self.assertIsNotNone(r['horizons']['1H']['flow_aum_pct'])
        self.assertTrue(r['action'].startswith('BEKLE'))
    def test_invalid_identity_duplicates_future_and_values(self):
        bad=[workbook(self.rows,'Other fund'),workbook(self.rows+[self.rows[-1]]),workbook(self.rows+[['Nov 26, 2026',10,100]]),workbook([*self.rows[:-1],[self.rows[-1][0],'NaN',100]]),workbook(self.rows).replace('Shares Outstanding','Market Price')]
        for text in bad:
            with self.subTest(text=text[-100:]):
                with self.assertRaises(ValueError):parse(text,'SLV',self.today)
    def test_missing_session_never_bridged(self):
        rows=self.rows[:];del rows[-3]
        r=collect('SLV',self.today,self.days,lambda _:workbook(rows))
        self.assertEqual(r['daily_count'],1)
        self.assertEqual(r['horizons'],{})
    def test_suspected_split_breaks_history(self):
        rows=[r[:] for r in self.rows]
        for r in rows[-3:]:r[1]*=2;r[2]/=2
        r=collect('SLV',self.today,self.days,lambda _:workbook(rows))
        self.assertEqual(r['daily_count'],2)
        self.assertEqual(len(r['provenance']['skipped_discontinuities']),1)
        self.assertEqual(r['daily_flow_usd'],20)
    def test_entity_declarations_rejected(self):
        with self.assertRaises(ValueError):parse('<!DOCTYPE foo>'+workbook(self.rows),'SLV',self.today)

    def test_iso_dates(self):
        rows=[[d.isoformat(),10,100+i] for i,d in enumerate(self.days)]
        self.assertEqual(len(parse(workbook(rows),"SLV",self.today)),len(rows))
