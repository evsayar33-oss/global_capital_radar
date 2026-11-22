import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from experiments import persist_selection, record, VERSION

class AutomaticSelection(unittest.TestCase):
    def test_promote_apply_preserve_and_withdraw(self):
        with tempfile.TemporaryDirectory() as folder, patch("experiments.ROOT",Path(folder)):
            (Path(folder)/"history").mkdir()
            accepted={"version":VERSION,"status":"validated","method":"flow","samples":30}
            persist_selection({"GLD/1H":accepted},date(2026,11,22))
            row={"symbol":"GLD","horizons":{"1H":{"strength":"Güçlü giriş","net_usd_m":1,"action":"BEKLE"}}}
            record([row])
            self.assertEqual(row["horizons"]["1H"]["action"],"ALIM ADAYI")
            self.assertEqual(persist_selection({},date(2026,11,23))["GLD/1H"]["method"],"flow")
            failed={"version":VERSION,"status":"insufficient","samples":31}
            persist_selection({"GLD/1H":failed},date(2026,11,24))
            log=json.loads((Path(folder)/"history/method_changes.json").read_text())
            self.assertEqual(len(log),2)
            self.assertIsNone(log[-1]["method"])
