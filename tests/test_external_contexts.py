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

    def test_icd_range_endpoint_is_not_treated_as_realized_code(self) -> None:
        cause = {
            "available": True,
            "label": "Accidents and violence excl. accidental poisoning by alcohol (V01-X44, X46-Y89, U129)",
        }
        detail = {
            "available": True,
            "code": "003",
            "label": "003 Motor cyclist injured in transport accident (V20-V39)",
        }
        self.assertFalse(cause_stack_has_icd("X44", cause, detail, None))
        self.assertIsNone(
            mr.EXTERNAL_CONTEXT_MODEL.roll_substance_context_for_cause_stack(
                country="fi",
                sex="male",
                x41_rng=random.Random(1),
                x44_rng=random.Random(1),
                cause=cause,
                detail=detail,
            )
        )

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

    def test_x44_canada_rolls_multidrug_capable_context(self) -> None:
        rolled = mr.EXTERNAL_CONTEXT_MODEL.roll_substance_context_for_cause_stack(
            country="ca",
            sex="male",
            x41_rng=random.Random(99),
            x44_rng=random.Random(1),
            detail={"available": True, "code": "X44", "label": "X44 accidental poisoning"},
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertTrue(rolled["available"])
        self.assertEqual(rolled["context_id"], "X44_SUBSTANCE_COUNT_CONTEXT")
        self.assertEqual(rolled["agent_label"], "Multiple drugs from different categories")
        self.assertEqual(rolled["conditional_probability"], 0.64)
        self.assertIn("No single drug category", rolled["context_label"])
        self.assertIn("accidental acute-toxicity reference", rolled["model_label"])

    def test_x44_finland_uses_conservative_icd_semantics_without_fake_roll(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_substance_context_for_cause_stack(
            country="fi",
            sex="female",
            x41_rng=random.Random(1),
            x44_rng=random.Random(1),
            detail={"available": True, "code": "X44", "label": "X44 accidental poisoning"},
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome["context_id"], "X44_ICD_CONTEXT")
        self.assertEqual(outcome["agent_label"], "Other / unspecified drug(s)")
        self.assertNotIn("roll", outcome)
        self.assertIn("multiple drug categories", outcome["context_label"])

    def test_x42_direct_icd_substance_category_needs_no_roll(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_substance_context_for_cause_stack(
            country="ca",
            sex="male",
            x41_rng=random.Random(1),
            x44_rng=random.Random(1),
            detail={"available": True, "code": "X42", "label": "X42 accidental poisoning"},
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome["agent_label"], "Narcotics / hallucinogens")
        self.assertEqual(outcome["model_status"], "ICD-resolved broad substance category")

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


    def test_finland_motorcycle_gets_crash_level_impairment_context(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
            country="fi",
            sex="male",
            age=16,
            rng=random.Random(1),
            cause={
                "available": True,
                "label": "Accidents and violence excl. accidental poisoning by alcohol (V01-X44, X46-Y89, U129)",
            },
            detail={
                "available": True,
                "code": "003",
                "label": "003 Motor cyclist injured in transport accident (V20-V39)",
            },
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome["available"])
        self.assertEqual(outcome["road_user"], "motorcyclist")
        self.assertEqual(outcome["context_id"], "FI_FATAL_MOTOR_VEHICLE_IMPAIRMENT")
        self.assertIn("does not establish", outcome["scope"])
        self.assertIn("OTI", outcome["model_label"])

    def test_finland_pedestrian_model_is_decedent_specific(self) -> None:
        resolved = mr.EXTERNAL_CONTEXT_MODEL._resolve_distribution(
            "FI_TRAFFIC_PEDESTRIAN_INTOXICATION", country="fi", sex="female"
        )
        assert resolved is not None
        self.assertAlmostEqual(resolved["distribution"]["alcohol_involved"], 39 / 216)
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
            country="fi", sex="female", age=70, rng=random.Random(2),
            detail={"available": True, "code": "001", "label": "001 Pedestrian injured in transport accident (V01-V09)"},
        )
        assert outcome is not None
        self.assertEqual(outcome["road_user_label"], "Pedestrian")
        self.assertIn("Deceased road user", outcome["scope"])

    def test_finland_cyclist_distribution_preserves_unknown_status(self) -> None:
        resolved = mr.EXTERNAL_CONTEXT_MODEL._resolve_distribution(
            "FI_TRAFFIC_CYCLIST_INTOXICATION", country="fi", sex="male"
        )
        assert resolved is not None
        self.assertAlmostEqual(resolved["distribution"]["alcohol_involved"], 30 / 160)
        self.assertAlmostEqual(resolved["distribution"]["status_unknown"], 17 / 160)

    def test_railway_collision_does_not_get_generic_road_impairment_context(self) -> None:
        for code, label in (
            (
                "V05.0",
                "V05.0 Pedestrian injured in collision with railway train or railway vehicle : nontraffic accident",
            ),
            (
                "V05.1",
                "V05.1 Pedestrian injured in collision with railway train or railway vehicle : traffic accident",
            ),
        ):
            with self.subTest(code=code):
                outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
                    country="ca", sex="male", age=102, rng=random.Random(1),
                    detail={"available": True, "code": code, "label": label},
                )
                self.assertIsNone(outcome)

    def test_nontraffic_transport_does_not_get_generic_road_impairment_context(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
            country="ca", sex="male", age=40, rng=random.Random(1),
            detail={
                "available": True,
                "code": "V09.0",
                "label": "V09.0 Pedestrian injured in unspecified nontraffic accident",
            },
        )
        self.assertIsNone(outcome)

    def test_canada_road_death_uses_fatal_collision_contributing_factor_reference(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
            country="ca", sex="male", age=35, rng=random.Random(1),
            detail={"available": True, "code": "V29.9", "label": "V29.9 Motorcyclist injured in transport accident"},
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome["context_id"], "CA_FATAL_COLLISION_IMPAIRMENT")
        self.assertEqual(outcome["road_user"], "motorcyclist")
        resolved = mr.EXTERNAL_CONTEXT_MODEL._resolve_distribution(
            "CA_FATAL_COLLISION_IMPAIRMENT", country="ca", sex="male"
        )
        assert resolved is not None
        self.assertEqual(resolved["distribution"]["impairment_reported"], 0.23)
        self.assertIn("does not establish", outcome["scope"])

    def test_nontransport_external_cause_does_not_get_crash_context(self) -> None:
        outcome = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(
            country="fi", sex="male", age=30, rng=random.Random(1),
            cause={"available": True, "label": "Accidents and violence (V01-X44, X46-Y89)"},
            detail={"available": True, "code": "066", "label": "066 Accidental poisoning by other drugs (X44)"},
        )
        self.assertIsNone(outcome)

    def test_traffic_context_roll_is_reproducible_on_independent_rng(self) -> None:
        kwargs = dict(
            country="fi", sex="male", age=44,
            detail={"available": True, "code": "004", "label": "004 Occupant of other motor vehicle injured in transport accident (V40-V79)"},
        )
        a = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(rng=random.Random(555), **kwargs)
        b = mr.EXTERNAL_CONTEXT_MODEL.roll_traffic_context_for_cause_stack(rng=random.Random(555), **kwargs)
        self.assertEqual(a, b)

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
                "substance_context": {
                    "available": True, "context_id": "X41_DRUG_CLASS",
                    "agent_label": "Antidepressants",
                    "context_label": "Modeled broad drug class within ICD-10 X41",
                    "model_label": "Canada", "profile": "male",
                    "conditional_probability": 0.3, "roll": 0.2,
                },
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
        self.assertIn(("📍 PLACE", "Bridge"), rows)
        self.assertIn(("   PLACE MODEL", "Canada"), rows)
        self.assertIn(("AGENT(S)", "Antidepressants"), rows)
        self.assertIn(("CONTEXT", "Modeled broad drug class within ICD-10 X41"), rows)
        self.assertIn(("CONTEXT p", "30.00%"), rows)
        self.assertIn(("CONTEXT ROLL", "20.0000%"), rows)
        self.assertIn(("CONTEXT MODEL", "Canada | male"), rows)


if __name__ == "__main__":
    unittest.main()
