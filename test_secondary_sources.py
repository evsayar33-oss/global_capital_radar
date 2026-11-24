import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from secondary_sources import cot_api,combine_cot,parse_etfiq,capture_etfiq


class SecondarySourcesTests(unittest.TestCase):
    def test_cot_overlap_and_conflict(self):
        today=date(2026,11,20)
        row=dict(cftc_contract_market_code="ABC",report_date_as_yyyy_mm_dd=str(today)+"T00:00:00",
                 open_interest_all="100",noncomm_positions_long_all="40",noncomm_positions_short_all="20")
        data=cot_api(today,{"ABC"},lambda _:json.dumps([row]))
        self.assertEqual(data["ABC"][today],20)
        self.assertTrue(combine_cot(data,data)[1])
        self.assertFalse(combine_cot(data,{"ABC":{today:30}})[1])

    def test_etfiq_no_zero_substitution_and_idempotence(self):
        today=date(2026,11,20)
        p=dict(schemaVersion=1,basis="daily",asOf=str(today),funds=[
            dict(ticker="SPY",basis="daily",status="ok",held=False,flowUsd=1000000,
                 startNetAssetsUsd=100000000,startNetAssetsDate="2026-11-19",navDate="2026-11-19"),
            dict(ticker="GLD",basis="daily",status="held",held=True,flowUsd=0)])
        parsed=parse_etfiq(p,today,{"SPY","GLD","SGOV"})
        self.assertIsNone(parsed["funds"]["GLD"]["flow_usd"])
        self.assertIsNone(parsed["funds"]["SGOV"]["flow_usd"])
        rows=[dict(symbol="SPY",flow_asof=str(today),net_usd_m={"1G":1.})]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for _ in range(2):
                result=capture_etfiq(root,today,rows,lambda _:json.dumps(p))
                self.assertEqual(result["observed"],1)
            self.assertEqual(len(list((root/"history/secondary_flow").glob("*.json"))),1)
            self.assertEqual(rows[0]["secondary_flow"]["same_date_difference_usd"],0)
