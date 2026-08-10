from __future__ import annotations

import random
import unittest

import mortality_roulette as mr
from mortality_roulette_core.external_contexts import cause_stack_has_icd, outcome_has_icd


class ExternalContextModelTests(unittest.TestCase):
    def test_all_bundled_distributions_normalize(self) -> None:
        for context in mr.EXTERNAL_CONTEXT_MODEL.payload["contexts"].values():
            for model in context["models"].values():
                profiles = model.get("profiles")
                if profiles:
                    cells = profiles.values()
                else:
                    cells = [model]
                for cell in cells:
                    self.assertAlmostEqual(sum(cell["distribution"].values()), 1.0, places=9)

    def test_x80_exact_code_and_finland_label_detection(self) -> None:
        self.assertTrue(outcome_has_icd({"available": True, "code": "X80"}, "X80"))
        self.assertTrue(
            cause_stack_has_icd(
                "X80",
                None,
                {"available": True, "label": "X80 Intentional self-harm by jumping from a high place"},
                None,
            )
        )

    def test_x41_finland_detail_label_detection(self) -> None:
        detail = {
            "available": True,
            "label": "063 Accidental poisoning by psychotropic drugs (X41)",
        }
        self.assertTrue(cause_stack_has_icd("X41", None, detail, None))

    def test_x80_canada_uses_native_top_level_model(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
            country="ca",
            sex="male",
            rng=random.Random(7),
            detail={"available": True, "code": "X80", "label": "X80 Intentional self-harm"},
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome["available"])
        self.assertEqual(outcome["model_country"], "CA")
        self.assertEqual(outcome["model_label"], "Canada")
        self.assertFalse(outcome["fallback"])

    def test_x80_finland_uses_labeled_international_reference(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
            country="fi",
            sex="female",
            rng=random.Random(7),
            detail={"available": True, "code": "X80", "label": "X80 Intentional self-harm"},
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome["model_country"], "INTL_REFERENCE")
        self.assertEqual(outcome["model_label"], "International jumping-site reference")
        self.assertTrue(outcome["fallback"])

    def test_x41_canada_is_sex_specific(self) -> None:
        detail = {"available": True, "code": "X41", "label": "X41 Accidental poisoning"}
        male = mr.EXTERNAL_CONTEXT_MODEL._resolve_distribution("X41_DRUG_CLASS", country="ca", sex="male")
        female = mr.EXTERNAL_CONTEXT_MODEL._resolve_distribution("X41_DRUG_CLASS", country="ca", sex="female")
        assert male is not None and female is not None
        self.assertEqual(male["profile"], "male")
        self.assertEqual(female["profile"], "female")
        self.assertNotEqual(male["distribution"], female["distribution"])
        rolled = mr.EXTERNAL_CONTEXT_MODEL.roll_x41_drug_class_for_cause_stack(
            country="ca", sex="male", rng=random.Random(4), detail=detail
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertEqual(rolled["model_country"], "CA")
        self.assertEqual(rolled["profile"], "male")

    def test_x41_finland_uses_native_all_sex_profile(self) -> None:
        rolled = mr.EXTERNAL_CONTEXT_MODEL.roll_x41_drug_class_for_cause_stack(
            country="fi",
            sex="female",
            rng=random.Random(4),
            detail={"available": True, "label": "063 Accidental poisoning by psychotropic drugs (X41)"},
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertEqual(rolled["model_country"], "FI")
        self.assertFalse(rolled["fallback"])
        self.assertEqual(rolled["profile"], "all")

    def test_nonmatching_cause_does_not_roll(self) -> None:
        detail = {"available": True, "code": "C34", "label": "C34 lung cancer"}
        self.assertIsNone(
            mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
                country="ca", sex="male", rng=random.Random(1), detail=detail
            )
        )
        self.assertIsNone(
            mr.EXTERNAL_CONTEXT_MODEL.roll_x41_drug_class_for_cause_stack(
                country="ca", sex="male", rng=random.Random(1), detail=detail
            )
        )

    def test_context_rolls_are_reproducible_on_independent_rngs(self) -> None:
        detail_x80 = {"available": True, "code": "X80", "label": "X80 Intentional self-harm"}
        a = mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
            country="ca", sex="male", rng=random.Random(12345), detail=detail_x80
        )
        b = mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
            country="ca", sex="male", rng=random.Random(12345), detail=detail_x80
        )
        self.assertEqual(a, b)


class DeathmatchContextRowsTests(unittest.TestCase):
    def test_compact_rows_include_location_and_drug_class_when_present(self) -> None:
        ctx = {"country": "ca", "province": None}
        state = {
            "death_age": 25,
            "q": 0.01,
            "baseline_q": 0.01,
            "mult": 1.0,
            "roll": 0.005,
            "cause_stack": {
                "cause": {"available": True, "label": "XX External causes"},
                "detail": {"available": True, "label": "X80 Intentional self-harm"},
                "deep": None,
                "x80_location": {"available": True, "label": "Bridge", "model_label": "Canada"},
                "x41_drug_class": {"available": True, "label": "Antidepressants", "model_label": "Canada", "profile": "male"},
                "suicide_reason": None,
                "seasonal": None,
            },
        }
        old_country = mr.ACTIVE_COUNTRY
        old_province = mr.ACTIVE_CANADA_PROVINCE
        try:
            rows = mr._deathmatch_compact_stats(ctx, state, sex="male", start_age=0)
        finally:
            mr.ACTIVE_COUNTRY = old_country
            mr.ACTIVE_CANADA_PROVINCE = old_province
        self.assertIn(("PLACE", "Bridge"), rows)
        self.assertIn(("PLACE MODEL", "Canada"), rows)
        self.assertIn(("DRUG CLASS", "Antidepressants"), rows)
        self.assertIn(("DRUG MODEL", "Canada | male"), rows)


if __name__ == "__main__":
    unittest.main()
