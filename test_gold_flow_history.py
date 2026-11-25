import unittest,io,zipfile
from datetime import date,timedelta
from unittest.mock import patch
from gold_flow_history import parse,parse_rows,collect

class GoldFlowTests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,11,25)
        self.header={'A':'Date','D':'NAV/Share at 10:30am NYT','K':'Total Net Asset Value in the Trust'}
    def test_schema_and_holiday(self):
        rows=[self.header,{'A':'23-Nov-2026','D':'10','K':'1000'},{'A':'24-Nov-2026','D':'US Holiday','K':'US Holiday'}]
        self.assertEqual(parse_rows(rows,self.today),{date(2026,11,23):(10,1000)})
        for bad in [rows+[rows[1]],[self.header,{'A':'26-Nov-2026','D':'10','K':'1000'}],[self.header,{'A':'23-Nov-2026','D':'NaN','K':'1000'}]]:
            with self.assertRaises(ValueError):parse_rows(bad,self.today)
    def test_nav_change_is_not_flow(self):
        days=[date(2026,11,16)+timedelta(days=i) for i in range(9) if (date(2026,11,16)+timedelta(days=i)).weekday()<5]
        records={d:(10+i,(10+i)*100) for i,d in enumerate(days)}
        with patch('gold_flow_history.parse',return_value=records):
            r=collect(self.today,days,lambda:b'test')
        self.assertAlmostEqual(r['daily_flow_usd'],0)
        records[days[-1]]=(16,1760)
        with patch('gold_flow_history.parse',return_value=records):r=collect(self.today,days,lambda:b'test')
        self.assertAlmostEqual(r['daily_flow_usd'],160)
        self.assertTrue(r['action'].startswith('BEKLE'))
    def test_real_xlsx_structure(self):
        n='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        root='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('xl/workbook.xml',f'<workbook xmlns="{n}" xmlns:r="{root}"><sheets><sheet name="US GLD Historical Archive" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            rows=[self.header,{'A':'24-Nov-2026','D':'10','K':'1000'}]
            data=''.join('<row>'+''.join(f'<c r="{k}{i}" t="inlineStr"><is><t>{v}</t></is></c>' for k,v in row.items())+'</row>' for i,row in enumerate(rows,1))
            z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{n}"><sheetData>{data}</sheetData></worksheet>')
        self.assertEqual(parse(b.getvalue(),self.today),{date(2026,11,24):(10,1000)})
