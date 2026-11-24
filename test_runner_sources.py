import unittest
from datetime import date
from unittest.mock import patch
from urllib.error import HTTPError
from source_recovery import issuer_fields
from runner_sources import verified_page

class RunnerSourcesTests(unittest.TestCase):
    def test_uscf_keyed_data(self):
        html="""<h1>United States Oil Fund</h1><date data-location="USO" data-key="asofdate">As of 11/23/2026</date>
        <div data-location="USO"><table><tr><td data-key="nav">$100.00</td></tr>
        <tr><td data-key="so">10,000</td></tr><tr><td data-key="navtotal">$1,000,000</td></tr></table></div>"""
        d=date(2026,11,24)
        self.assertEqual(issuer_fields(html,"USO",d)["shares"],10000)
        with self.assertRaises(ValueError):issuer_fields(html.replace('data-location="USO"','data-location="CPER"'),"USO",d)
    def test_raw_and_render_fallback(self):
        with patch("runner_sources.raw_page",return_value="no data"),patch("runner_sources.rendered_page",return_value="valid") as render:
            def parse(x):
                if x!="valid":raise ValueError("missing")
                return {"status":"OBSERVED"}
            r,m=verified_page("https://www.uscfinvestments.com/uso",parse)
            self.assertEqual(m,"RENDERED_HTTP_200")
            self.assertEqual(len(r["source_sha256"]),64)
            render.assert_called_once()
    def test_no_access_denial_retry(self):
        with patch("runner_sources.raw_page",side_effect=HTTPError("https://www.uscfinvestments.com/uso",403,"forbidden",{},None)),patch("runner_sources.rendered_page") as render:
            with self.assertRaises(HTTPError):verified_page("https://www.uscfinvestments.com/uso",lambda x:{})
            render.assert_not_called()
