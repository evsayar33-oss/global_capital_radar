"""Keep truncated tool output out of the immutable observation history."""
import hashlib
import json
from pathlib import Path
import unittest


class HistoryIntegrityTests(unittest.TestCase):
    def test_active_history_is_valid_json(self):
        root = Path(__file__).parent / 'history'
        for file in root.rglob('*.json'):
            with self.subTest(file=str(file)):
                json.loads(file.read_text())

    def test_quarantine_preserves_exact_original_bytes(self):
        root = Path(__file__).parent
        receipt = json.loads((root/'history/quarantine/manifest.json').read_text())
        raw = (root/receipt['preserved_as']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt['sha256'])
        self.assertEqual(len(raw), receipt['bytes'])
        self.assertIn(b'tokens truncated', raw)


if __name__ == '__main__':
    unittest.main()
