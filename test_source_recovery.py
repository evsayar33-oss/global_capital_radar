import unittest
from datetime import date
from source_recovery import parse_issuer,parse_creation,parse_shfe_cn,estimate_adjacent,tff_tbf3
class RecoveryTests(unittest.TestCase):
    def test_shfe(self):
        day=date(2026,11,23)
        html="""上海期货交易所指定交割仓库期货仓单日报 2026年11月23日
        <table><tr><td>铜</td><td>单位：吨</td></tr>
        <tr><th>地区</th><th>仓库</th><th>期货</th><th>增减</th></tr>
        <tr><td>上海</td><td>A</td><td>100</td><td>-5</td></tr>
        <tr><td>合计</td><td>100</td><td>-5</td></tr>
        <tr><td>总计</td><td>100</td><td>-5</td></tr></table>"""
        self.assertEqual(parse_shfe_cn(html,day)["on_warrant_tonnes"],100)
        for bad in (html.replace("23日","22日"),html.replace("铜</td>","铜(BC)</td>"),html.replace("总计</td><td>100","总计</td><td>99")):
            with self.assertRaises(ValueError):parse_shfe_cn(bad,day)
    def test_uscf(self):
        html="United States Copper Index Fund Key Facts As of 11/23/2026 NAV $33.93 NAV Change $0.90 Shares Outstanding 14,900,000 Total Net Assets $505,514,719.70 Performance"
        d=date(2026,11,24)
        r=parse_issuer(html,"CPER",d)
        self.assertEqual(r["shares"],14900000)
        with self.assertRaises(ValueError):parse_issuer(html.replace("14,900,000","149,000"),"CPER",d)
        c=parse_creation("United States Copper Index Fund Creation / Redemption As of 11/23/2026 Shares Created / Redeemed -300,000","CPER",d)
        self.assertEqual(c["net_created_shares"],-300000)
        prior=dict(r,source_date="2026-11-20",shares=15200000)
        self.assertAlmostEqual(estimate_adjacent(prior,r,[date(2026,11,20),date(2026,11,23)]),-300000*33.93)
        self.assertIsNone(estimate_adjacent(prior,r,[date(2026,11,20),date(2026,11,21),date(2026,11,23)]))
    def test_qqq_dated_snapshot(self):
        # Reduced visible field sequence and published figures from Invesco
        # overview observed 2026-11-24 (issuer as-of 2026-11-22).
        html="""<h1>Invesco QQQ</h1> as of 11/22/2026 Fund ticker QQQ Exchange
        Nasdaq/NMS (Global Market) Inception date 03/09/1999 Total Expense Ratio 0.18%
        Number Of Holdings 102 Assets Under Management $450.58B
        30 Day Average Trading Volume 57.13M Shares Outstanding 692.25M
        Cumulative Performance as of 10/30/2026"""
        d=date(2026,11,24);r=parse_issuer(html,"QQQ",d)
        self.assertEqual(r["reported_aum_usd"],450580000000)
        self.assertEqual(r["shares"],692250000)
        self.assertIsNone(r["nav_usd"])
        self.assertFalse(r["flow_eligible"])
        self.assertTrue(r["snapshot_only"])
        self.assertIsNone(estimate_adjacent(r,r,[]))
        for bad in (html.replace("Fund ticker QQQ","Fund ticker QQQM"),
                    html.replace("11/22/2026","11/01/2026"),
                    html.replace("Assets Under Management","Other"),
                    html.replace("Shares Outstanding","as of 11/23/2026 Shares Outstanding")):
            with self.assertRaises(ValueError):parse_issuer(bad,"QQQ",d)
    def test_tff(self):
        self.assertEqual(tff_tbf3(date(2026,11,24),lambda _:"[]")["status"],"NO_CURRENT_COT_SERIES")
        self.assertEqual(tff_tbf3(date(2026,11,24),lambda _:"{}")["status"],"UNAVAILABLE")
