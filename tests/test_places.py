from __future__ import annotations

import random
import unittest

import mortality_roulette as mr
from mortality_roulette_core.places import cause_stack_matches_trigger


class PlaceModelTests(unittest.TestCase):
    def test_all_bundled_place_distributions_normalize(self) -> None:
        for context_id, context in mr.PLACE_MODEL.contexts.items():
            for requested_country in context.get("country_model_map", {}):
                model_key = context["country_model_map"][requested_country]
                model = context["models"][model_key]
                profiles = model.get("profiles")
                sexes = profiles.keys() if isinstance(profiles, dict) else ["male"]
                for sex in sexes:
                    resolved = mr.PLACE_MODEL._resolve_distribution(
                        context_id, country=requested_country, sex=sex
                    )
                    self.assertIsNotNone(resolved, (context_id, requested_country, sex))
                    assert resolved is not None
                    self.assertAlmostEqual(sum(resolved["distribution"].values()), 1.0, places=12)
                    self.assertTrue(all(p > 0 for p in resolved["distribution"].values()))

    def test_finland_drowning_uses_native_weighted_event_setting(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="fi", sex="male", rng=random.Random(1),
            detail={"available": True, "code": "W69", "label": "Drowning and submersion while in natural water"},
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertEqual(rolled["context_id"], "DROWNING_EVENT_PLACE")
        self.assertEqual(rolled["semantic"], "event_setting")
        self.assertEqual(rolled["model_country"], "FI")
        self.assertEqual(rolled["category"], "lake")
        self.assertAlmostEqual(rolled["conditional_probability"], 110 / 197)
        self.assertTrue(rolled["constrained"])


    def test_icd_explicit_bathtub_and_pool_settings_do_not_get_incompatible_rolls(self) -> None:
        for country in ("fi", "ca"):
            bathtub = mr.PLACE_MODEL.roll_for_cause_stack(
                country=country, sex="male", rng=random.Random(99),
                detail={"available": True, "code": "W65", "label": "Drowning while in bathtub"},
            )
            pool = mr.PLACE_MODEL.roll_for_cause_stack(
                country=country, sex="male", rng=random.Random(99),
                detail={"available": True, "code": "W67", "label": "Drowning while in swimming pool"},
            )
            assert bathtub is not None and pool is not None
            self.assertEqual(bathtub["label"], "Bathtub")
            self.assertEqual(pool["label"], "Swimming pool")
            self.assertIsNone(bathtub["roll"])
            self.assertIsNone(pool["roll"])
            self.assertEqual(bathtub["conditional_probability"], 1.0)
            self.assertEqual(pool["conditional_probability"], 1.0)

    def test_canada_drowning_uses_native_event_setting(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="female", rng=random.Random(1),
            detail={"available": True, "code": "W74", "label": "Unspecified drowning and submersion"},
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertEqual(rolled["model_country"], "CA")
        self.assertEqual(rolled["category"], "lake_pond")
        self.assertAlmostEqual(rolled["conditional_probability"], 0.35)

    def test_finland_homicide_is_sex_specific(self) -> None:
        male = mr.PLACE_MODEL._resolve_distribution("HOMICIDE_EVENT_PLACE", country="fi", sex="male")
        female = mr.PLACE_MODEL._resolve_distribution("HOMICIDE_EVENT_PLACE", country="fi", sex="female")
        assert male is not None and female is not None
        self.assertEqual(male["profile"], "male")
        self.assertEqual(female["profile"], "female")
        self.assertAlmostEqual(male["distribution"]["victim_home"], 118 / 350)
        self.assertAlmostEqual(female["distribution"]["victim_home"], 83 / 136)
        self.assertNotEqual(male["distribution"], female["distribution"])

    def test_canada_homicide_is_not_faked_with_fallback(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="male", rng=random.Random(2),
            detail={"available": True, "code": "X95", "label": "Assault by firearm"},
        )
        self.assertIsNone(rolled)

    def test_broad_v01_v99_transport_parent_does_not_fake_road_setting(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="fi", sex="male", rng=random.Random(3),
            detail={"available": True, "label": "001-012 Transport accidents (V01-V99)"},
        )
        self.assertIsNone(rolled)

    def test_broad_external_cause_parent_does_not_turn_suicide_into_road_traffic(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="male", rng=random.Random(3),
            cause={
                "available": True,
                "code": "XX",
                "label": "XX External causes of morbidity and mortality (V01-Y89)",
            },
            detail={
                "available": True,
                "code": "X70",
                "label": "X70 Intentional self-harm by hanging, strangulation and suffocation",
            },
        )
        self.assertIsNone(rolled)

    def test_specific_road_traffic_code_rolls_country_native_setting(self) -> None:
        fi = mr.PLACE_MODEL.roll_for_cause_stack(
            country="fi", sex="male", rng=random.Random(4),
            detail={"available": True, "code": "V45", "label": "Car occupant injured in collision"},
        )
        ca = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="male", rng=random.Random(4),
            detail={"available": True, "code": "V45", "label": "Car occupant injured in collision"},
        )
        assert fi is not None and ca is not None
        self.assertEqual(fi["model_country"], "FI")
        self.assertAlmostEqual(fi["conditional_probability"], 0.68)
        self.assertEqual(ca["model_country"], "CA")
        self.assertAlmostEqual(
            mr.PLACE_MODEL._resolve_distribution("ROAD_TRAFFIC_EVENT_PLACE", country="ca", sex="male")["distribution"]["rural_road"],
            932 / 1768,
        )

    def test_drowning_precedence_beats_transport_context(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="male", rng=random.Random(5),
            detail={"available": True, "code": "V90", "label": "Accident to watercraft causing drowning"},
        )
        self.assertIsNotNone(rolled)
        assert rolled is not None
        self.assertEqual(rolled["context_id"], "DROWNING_EVENT_PLACE")

    def test_cancer_is_terminal_place_not_event_setting(self) -> None:
        for country in ("fi", "ca"):
            rolled = mr.PLACE_MODEL.roll_for_cause_stack(
                country=country, sex="female", rng=random.Random(6),
                deep={"available": True, "code": "C34", "label": "Malignant neoplasm of bronchus and lung"},
            )
            self.assertIsNotNone(rolled)
            assert rolled is not None
            self.assertEqual(rolled["context_id"], "CANCER_TERMINAL_PLACE")
            self.assertEqual(rolled["semantic"], "terminal_place")
            self.assertEqual(rolled["model_country"], country.upper())

    def test_finland_neurodegenerative_terminal_place_has_no_canada_fallback(self) -> None:
        fi = mr.PLACE_MODEL.roll_for_cause_stack(
            country="fi", sex="female", rng=random.Random(7),
            deep={"available": True, "code": "G30", "label": "Alzheimer disease"},
        )
        ca = mr.PLACE_MODEL.roll_for_cause_stack(
            country="ca", sex="female", rng=random.Random(7),
            deep={"available": True, "code": "G30", "label": "Alzheimer disease"},
        )
        self.assertIsNotNone(fi)
        assert fi is not None
        self.assertEqual(fi["semantic"], "terminal_place")
        self.assertIsNone(ca)

    def test_place_roll_is_reproducible(self) -> None:
        kwargs = dict(
            country="fi", sex="male",
            detail={"available": True, "code": "W69", "label": "Natural-water drowning"},
        )
        a = mr.PLACE_MODEL.roll_for_cause_stack(rng=random.Random(1234), **kwargs)
        b = mr.PLACE_MODEL.roll_for_cause_stack(rng=random.Random(1234), **kwargs)
        self.assertEqual(a, b)

    def test_nonmatching_death_has_no_place(self) -> None:
        rolled = mr.PLACE_MODEL.roll_for_cause_stack(
            country="fi", sex="male", rng=random.Random(8),
            deep={"available": True, "code": "I21", "label": "Acute myocardial infarction"},
        )
        self.assertIsNone(rolled)

    def test_existing_x80_distribution_and_stream_are_preserved(self) -> None:
        detail = {"available": True, "code": "X80", "label": "X80 Intentional self-harm"}
        x80 = mr.EXTERNAL_CONTEXT_MODEL.roll_x80_location_for_cause_stack(
            country="ca", sex="male", rng=random.Random(12345), detail=detail
        )
        self.assertIsNotNone(x80)
        assert x80 is not None
        self.assertEqual(x80["category"], "residential_building")
        self.assertAlmostEqual(x80["roll"], 0.41661987254534116)
        # The generalized model deliberately does not shadow the legacy X80 branch.
        self.assertIsNone(
            mr.PLACE_MODEL.roll_for_cause_stack(
                country="ca", sex="male", rng=random.Random(12345), detail=detail
            )
        )


class PlaceRenderingTests(unittest.TestCase):
    def test_deathmatch_uses_unified_place_rows_for_existing_x80(self) -> None:
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
                "x80_location": {
                    "available": True, "label": "Bridge", "model_label": "Canada", "roll": 0.25,
                    "conditional_probability": 0.4,
                },
                "place": None,
                "x41_drug_class": None,
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
        self.assertIn(("PLACE p", "40.00%"), rows)
        self.assertIn(("PLACE ROLL", "25.0000%"), rows)
        self.assertIn(("PLACE MODEL", "Canada"), rows)
        self.assertNotIn(("LOCATION", "Bridge"), rows)


if __name__ == "__main__":
    unittest.main()
