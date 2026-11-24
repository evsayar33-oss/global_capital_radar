import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import macro_sources as m
import radar
from dashboard_data import macro_rows


class DirectMacroTests(unittest.TestCase):
    def test_bls_series_identity_and_months(self):
        row = {"year":"2026","period":"M10","value":"337.476"}
        payload = {"status":"REQUEST_SUCCEEDED","Results":{"series":[{"seriesID":"CUSR0000SA0","data":[row,dict(row,period="M13")]}]}}
        data, meta = m.bls_series("CPIAUCSL", date(2026,11,24), lambda _:json.dumps(payload))
        self.assertEqual(data, {date(2026,10,1):337.476})
        self.assertFalse(meta["historical_vintage_verified"])
        payload["Results"]["series"][0]["seriesID"]="CUUR0000SA0"
        with self.assertRaises(ValueError):
            m.bls_series("CPIAUCSL",date(2026,11,24),lambda _:json.dumps(payload))

    def test_treasury_partition_and_today_exclusion(self):
        def read(url):
            year = 2025 if "2025/all" in url else 2026
            return f"Date,2 Yr,10 Yr\n11/23/{year},4.1,4.2\n11/24/{year},4.3,4.4\n"
        rows, meta=m.treasury_series("DGS2",date(2026,11,24),read)
        self.assertEqual(rows[date(2026,11,23)],4.1)
        self.assertNotIn(date(2026,11,24),rows)
        self.assertEqual(len(meta["source_sha256"]),2)

    def test_effr_no_weekend_fill_or_wrong_type(self):
        payload={"refRates":[{"effectiveDate":"2026-11-20","type":"EFFR","percentRate":3.88},{"effectiveDate":"2026-11-23","type":"EFFR","percentRate":3.88}]}
        rows, evidence=m.effr_series(date(2026,11,24),lambda _:json.dumps(payload))
        self.assertNotIn(date(2026,11,21),rows)
        self.assertIn("NO_WEEKEND_FILL",evidence["observation_basis"])
        payload["refRates"][0]["type"]="SOFR"
        with self.assertRaises(ValueError):
            m.effr_series(date(2026,11,24),lambda _:json.dumps(payload))

    def test_fred_outage_direct_observation_and_failure(self):
        meta=dict(id="DGS2",freq="D",change="bp",max_age=10)
        d=date(2026,11,24)
        with patch.object(radar,"fred_with_source",side_effect=TimeoutError), patch.object(m,"fresh_series",return_value=({date(2025,11,24):4.0,date(2026,11,23):4.1},{"source":"US Treasury"})):
            row, data=radar.retrieve(meta,d)
            self.assertEqual(row["value"],4.1)
            self.assertEqual(row["source_status"],"DIRECT_SOURCE_OBSERVED")
            self.assertIn("TimeoutError",row["primary_error"])
        with patch.object(radar,"fred_with_source",side_effect=TimeoutError), patch.object(m,"fresh_series",side_effect=ValueError("stale")):
            row,data=radar.retrieve(meta,d)
            self.assertIn("error",row)
            self.assertFalse(data)
            self.assertNotIn("value",row)

    def test_old_verified_values_never_become_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"2026-11-22.json").write_text(json.dumps({"as_of":"2026-11-22T10:00:00Z","indicators":[{"id":"DGS2","period":"2026-11-19","value":4.2,"stale":False}]}))
            rows=[{"id":"DGS2","error":"timeout"}]
            radar.attach_last_verified(rows,root)
            self.assertNotIn("value",rows[0])
            self.assertEqual(rows[0]["last_verified"]["value"],4.2)
            self.assertEqual(macro_rows({"indicators":rows})[0]["Son doğrulanmış değer (eski)"],4.2)
            self.assertTrue(all("veri eksik" in s for s in radar.conditions(rows)))

    def test_fred_api_failure_no_secret_in_report(self):
        import os
        with patch.dict(os.environ,{"FRED_API_KEY":"private-test-key"}), patch.object(radar,"read",side_effect=[ValueError("private-test-key"),"observation_date,DGS2\n2026-11-19,4.2\n"]):
            rows, meta=radar.fred_with_source("DGS2")
            self.assertEqual(rows[date(2026,11,19)],4.2)
            self.assertNotIn("private-test-key",str(meta))
