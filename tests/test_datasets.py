from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "datasets" / "manifest.json"


class BundledDatasetIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_manifest_lists_existing_files(self) -> None:
        datasets = self.manifest.get("datasets", [])
        self.assertTrue(datasets, "datasets/manifest.json contains no dataset entries")
        for item in datasets:
            with self.subTest(path=item.get("path")):
                path = ROOT / item["path"]
                self.assertTrue(path.is_file(), f"missing bundled dataset: {path}")

    def test_manifest_size_and_sha256_match_files(self) -> None:
        for item in self.manifest.get("datasets", []):
            with self.subTest(path=item.get("path")):
                path = ROOT / item["path"]
                payload = path.read_bytes()
                self.assertEqual(len(payload), item["bytes"], f"size mismatch for {path}")
                digest = hashlib.sha256(payload).hexdigest()
                self.assertEqual(digest, item["sha256"], f"SHA-256 mismatch for {path}")

    def test_manifest_has_source_and_license_metadata(self) -> None:
        required = {"agency", "source", "reference", "url", "license", "attribution"}
        for item in self.manifest.get("datasets", []):
            with self.subTest(path=item.get("path")):
                missing = sorted(k for k in required if not item.get(k))
                self.assertFalse(missing, f"missing provenance fields for {item.get('path')}: {missing}")

    def test_statfin_2024_snapshot_matches_published_anchor_rows(self) -> None:
        path = ROOT / "datasets" / "finland" / "mortality" / "statfin_12ap_2024.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        male = payload["data"]["male"]["2024"]
        female = payload["data"]["female"]["2024"]
        # Statistics Finland 12ap publishes qx in per mille. These anchors are
        # direct 2024 table values converted to fractions, not model outputs.
        self.assertAlmostEqual(male["0"], 0.00205, places=8)
        self.assertAlmostEqual(male["1"], 0.00009, places=8)
        self.assertAlmostEqual(male["80"], 0.05239, places=8)
        self.assertAlmostEqual(male["98"], 0.33953, places=8)
        self.assertAlmostEqual(male["99"], 0.39267, places=8)
        self.assertAlmostEqual(female["98"], 0.30389, places=8)
        self.assertAlmostEqual(female["99"], 0.33027, places=8)
        self.assertEqual(payload["max_exact_age"], 99)
        self.assertEqual(payload["terminal_age_life_expectancy_years"]["male"], 1.85)
        self.assertEqual(payload["terminal_age_life_expectancy_years"]["female"], 1.80)


if __name__ == "__main__":
    unittest.main()
