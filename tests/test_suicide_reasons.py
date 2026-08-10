from __future__ import annotations

import random
import unittest

import mortality_roulette as mr
from mortality_roulette_core.suicide_reasons import cause_stack_is_suicide


class SuicideReasonModelTests(unittest.TestCase):
    def test_all_bundled_distributions_normalize(self) -> None:
        payload = mr.SUICIDE_REASON_MODEL.payload
        for model in payload["models"].values():
            for rows in model["profiles"].values():
                for cell in rows.values():
                    self.assertAlmostEqual(sum(cell["distribution"].values()), 1.0, places=9)

    def test_finland_and_canada_use_native_profiles(self) -> None:
        fi = mr.SUICIDE_REASON_MODEL.resolve(country="fi", sex="male", age=55)
        ca = mr.SUICIDE_REASON_MODEL.resolve(country="ca", sex="female", age=70)
        self.assertIsNotNone(fi)
        self.assertIsNotNone(ca)
        assert fi is not None and ca is not None
        self.assertEqual(fi.model_country, "FI")
        self.assertFalse(fi.fallback)
        self.assertEqual(fi.age_group, "50-64")
        self.assertEqual(ca.model_country, "CA")
        self.assertFalse(ca.fallback)
        self.assertEqual(ca.age_group, "65-74")

    def test_unknown_country_uses_finnish_canadian_reference(self) -> None:
        profile = mr.SUICIDE_REASON_MODEL.resolve(country="de", sex="male", age=55)
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertTrue(profile.fallback)
        self.assertEqual(profile.model_country, "FI_CA_REFERENCE")
        self.assertEqual(profile.model_label, "Finnish-Canadian reference")

    def test_finland_detail_label_triggers_suicide_reason(self) -> None:
        detail = {
            "available": True,
            "label": "073-097 Suicides (X60-X84, Y870) — specific subcategory unavailable",
        }
        self.assertTrue(cause_stack_is_suicide(None, detail, None))

    def test_canada_complete_icd_code_triggers_suicide_reason(self) -> None:
        detail = {"available": True, "code": "X70", "label": "X70 Intentional self-harm"}
        self.assertTrue(cause_stack_is_suicide(None, detail, None))

    def test_non_suicide_cause_does_not_trigger_reason(self) -> None:
        detail = {"available": True, "code": "C34", "label": "C34 Malignant neoplasm of bronchus and lung"}
        self.assertFalse(cause_stack_is_suicide(None, detail, None))
        rolled = mr.SUICIDE_REASON_MODEL.roll_for_cause_stack(
            country="fi", sex="male", age=55, rng=random.Random(1), detail=detail
        )
        self.assertIsNone(rolled)

    def test_reason_roll_is_deterministic_for_its_own_rng(self) -> None:
        detail = {"available": True, "code": "X70", "label": "X70 Intentional self-harm"}
        left = mr.SUICIDE_REASON_MODEL.roll_for_cause_stack(
            country="ca", sex="male", age=75, rng=random.Random(1234), detail=detail
        )
        right = mr.SUICIDE_REASON_MODEL.roll_for_cause_stack(
            country="ca", sex="male", age=75, rng=random.Random(1234), detail=detail
        )
        self.assertEqual(left, right)
        self.assertIsNotNone(left)
        assert left is not None
        self.assertTrue(left["available"])
        self.assertEqual(left["model_label"], "Canada")

    def test_finland_unresolved_residual_has_noncausal_label_and_provenance(self) -> None:
        category = mr.SUICIDE_REASON_MODEL.categories["unresolved"]
        self.assertEqual(category["label"], "No specific recent life event reported")
        self.assertIn("does not mean there was no reason", category["semantics"].casefold())
        profile = mr.SUICIDE_REASON_MODEL.resolve(country="fi", sex="male", age=55)
        assert profile is not None
        self.assertAlmostEqual(profile.distribution["unresolved"], 0.2, places=9)
        self.assertIn("national reported-life-event residual", profile.provenance)
        self.assertIn("not an age/sex-specific observation", profile.provenance)

    def test_canadian_old_age_profile_tracks_alberta_physical_health_gradient(self) -> None:
        p55 = mr.SUICIDE_REASON_MODEL.resolve(country="ca", sex="male", age=55)
        p70 = mr.SUICIDE_REASON_MODEL.resolve(country="ca", sex="male", age=70)
        p80 = mr.SUICIDE_REASON_MODEL.resolve(country="ca", sex="male", age=80)
        assert p55 is not None and p70 is not None and p80 is not None
        self.assertLess(p55.distribution["physical_health"], p70.distribution["physical_health"])
        self.assertLess(p70.distribution["physical_health"], p80.distribution["physical_health"])


if __name__ == "__main__":
    unittest.main()
