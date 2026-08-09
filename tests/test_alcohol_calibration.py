from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "alcohol_calibration.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("alcohol_calibration_test_target", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cal = _load_tool()


class AlcoholCalibrationMathTests(unittest.TestCase):
    def test_legacy_model_underpredicts_wood_high_group(self) -> None:
        ref = cal.exact_period_life_expectancy(
            sex="male", start_age=40, grams_per_day=56.0 / 7.0
        )
        high = cal.exact_period_life_expectancy(
            sex="male", start_age=40, grams_per_day=367.0 / 7.0
        )
        loss = ref.remaining_life_expectancy - high.remaining_life_expectancy
        self.assertAlmostEqual(loss, 1.249, places=2)
        self.assertLess(loss, 4.0)

    def test_legacy_model_is_flat_below_45_g_day(self) -> None:
        ref = cal.exact_period_life_expectancy(
            sex="male", start_age=40, grams_per_day=56.0 / 7.0
        )
        mid = cal.exact_period_life_expectancy(
            sex="male", start_age=40, grams_per_day=208.0 / 7.0
        )
        self.assertAlmostEqual(
            ref.remaining_life_expectancy,
            mid.remaining_life_expectancy,
            places=10,
        )
        self.assertEqual(cal.legacy_target_rr("male", 208.0 / 7.0), 1.0)


    def test_smooth_candidate_hits_wood_midpoint_targets(self) -> None:
        ref = cal.exact_period_life_expectancy(
            sex="male", start_age=40, grams_per_day=cal.WOOD_ROWS[0].grams_per_day
        )
        for row in cal.WOOD_ROWS[1:]:
            rr = cal.wood_smooth_candidate_rr(row.grams_per_day)
            result = cal.exact_period_life_expectancy(
                sex="male",
                start_age=40,
                grams_per_day=row.grams_per_day,
                target_rr=rr,
            )
            loss = ref.remaining_life_expectancy - result.remaining_life_expectancy
            target = (row.observed_loss_low + row.observed_loss_high) / 2.0
            self.assertAlmostEqual(loss, target, places=2)

    def test_smooth_candidate_is_monotone_over_calibrated_and_tail_range(self) -> None:
        doses = [8.0, 17.6, 29.7, 40.0, 52.4, 60.0, 71.0]
        rrs = [cal.wood_smooth_candidate_rr(dose) for dose in doses]
        self.assertTrue(all(a <= b for a, b in zip(rrs, rrs[1:])))
        self.assertAlmostEqual(rrs[0], 1.0, places=10)
        self.assertGreater(rrs[-1], 2.0)

    def test_diagnostic_rr_for_wood_midpoint_is_about_1_65(self) -> None:
        rr = cal.required_uniform_target_rr(
            sex="male", start_age=40, target_years_lost=4.5
        )
        self.assertGreater(rr, 1.60)
        self.assertLess(rr, 1.70)

    def test_high_dose_holdout_is_independent_of_candidate_fit(self) -> None:
        doses = [row.grams_per_day for row in cal.WANG_2014_MALE_ALL_CAUSE_RR]
        self.assertEqual(doses, [10.0, 25.0, 50.0, 75.0, 90.0, 100.0])
        row75 = next(row for row in cal.WANG_2014_MALE_ALL_CAUSE_RR if row.grams_per_day == 75.0)
        candidate75 = cal.wood_smooth_candidate_rr(75.0)
        self.assertAlmostEqual(row75.rr, 1.15, places=10)
        self.assertGreater(candidate75, row75.ci_high)

    def test_severity_bounds_are_context_only_constants(self) -> None:
        self.assertEqual(cal.CIRRHOSIS_MORTALITY_RR[50.0][0], 6.83)
        self.assertEqual(cal.CIRRHOSIS_MORTALITY_RR[100.0][0], 16.38)
        self.assertEqual(cal.HOSPITALIZED_NORDIC_AUD_MRR_RANGE, (3.0, 5.2))
        self.assertEqual(cal.HOSPITALIZED_NORDIC_AUD_LE_LOSS_RANGE, (24.0, 28.0))

    def test_cause_hazard_evidence_v1_is_stronger_for_direct_alcohol_category(self) -> None:
        old_dose = cal.mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY
        old_model = cal.mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL
        old_active = cal.mr.ACTIVE_BOOZEHOUND
        try:
            cal.mr.ACTIVE_BOOZEHOUND = True
            cal.mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = cal.mr.BOOZEHOUND_WINO_GRAMS_PER_DAY
            cal.mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "proxy-v1"
            proxy = cal.mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol", age=70, sex="male"
            )
            cal.mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v1"
            evidence = cal.mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol", age=70, sex="male"
            )
            self.assertGreater(evidence[0], proxy[0])
            self.assertIn("Carr 2024", evidence[4])
        finally:
            cal.mr.ACTIVE_BOOZEHOUND = old_active
            cal.mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = old_dose
            cal.mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = old_model


class AlcoholCalibrationCliTests(unittest.TestCase):
    def test_report_surfaces_benchmark_mismatch(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOOL)],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MORTALITY ROULETTE v0.13.0-dev16 - ALCOHOL CALIBRATION", result.stdout)
        self.assertIn("Wood highest-group modeled loss: 1.25 years", result.stdout)
        self.assertIn("target ~4-5 years", result.stdout)
        self.assertIn("UNDER", result.stdout)
        self.assertIn("NOT proposed alcohol RRs", result.stdout)
        self.assertTrue(
            "CAUSE-HAZARD PROTOTYPE / PROXY-V1" in result.stdout
            or "CAUSE-HAZARD PROTOTYPE (UNFITTED WOOD CHECK; EXPERIMENTAL)" in result.stdout
        )
        self.assertIn("WOOD-SMOOTH CANDIDATE", result.stdout)
        self.assertIn("candidate extrapolation: target x2.182", result.stdout)
        self.assertIn("reach 85", result.stdout)
        self.assertIn("[LOW CONFIDENCE]", result.stdout)
        self.assertIn("INDEPENDENT HIGH-DOSE HOLDOUT", result.stdout)
        self.assertIn("75.0", result.stdout)
        self.assertIn("x1.15 (0.92-1.43)", result.stdout)
        self.assertIn("cirrhosis mortality RR", result.stdout)
        self.assertIn("hospitalized Nordic AUD", result.stdout)
        self.assertIn("warning against treating Wood-smooth as a literal RR", result.stdout)


if __name__ == "__main__":
    unittest.main()
