from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mortality_roulette.py"


class VersionCliTests(unittest.TestCase):
    def _version(self, flag: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), flag],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_short_version_flag(self) -> None:
        result = self._version("-v")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Mortality Roulette v0.13.1")
        self.assertEqual(result.stderr, "")
        self.assertNotIn("starting", result.stdout.casefold())

    def test_long_version_flag(self) -> None:
        result = self._version("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Mortality Roulette v0.13.1")
        self.assertEqual(result.stderr, "")


class PrintoutCliTests(unittest.TestCase):
    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_gender_alias_maps_to_existing_sex_option(self) -> None:
        result = self._run(
            "--country", "fi",
            "--gender", "m",
            "--printout",
            "--mortality-model", "official",
            "--start-age", "79",
            "--end-age", "80",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sex: male", result.stdout)
        self.assertIn("age  79 ->  80 | death prob.   4.3800%", result.stdout)
        self.assertIn("age  80 ->  81 | death prob.   5.2390%", result.stdout)
        self.assertIn("Statistics Finland 12ap", result.stdout)

    def test_printout_has_no_rng_roll_or_survival_result(self) -> None:
        result = self._run(
            "--country", "fi",
            "--sex", "m",
            "--odds-table",
            "--mortality-model", "official",
            "--start-age", "81",
            "--end-age", "81",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RNG: OFF", result.stdout)
        self.assertIn("1 in 17.3", result.stdout)
        self.assertNotIn(" | roll ", result.stdout)
        self.assertNotIn(" | survived", result.stdout)
        self.assertNotIn("BIG WIN", result.stdout)

    def test_end_age_requires_printout(self) -> None:
        result = self._run(
            "--country", "fi",
            "--sex", "m",
            "--end-age", "80",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--end-age requires --printout", result.stderr)

    def test_printout_default_continues_through_finland_tail_to_record_ceiling(self) -> None:
        result = self._run(
            "--country", "fi",
            "--gender", "m",
            "--printout",
            "--mortality-model", "official",
            "--start-age", "99",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("age  99 -> 100 | death prob.  39.2670%", result.stdout)
        self.assertIn("age 100 -> 101 | death prob.  39.7000%", result.stdout)
        self.assertIn("age 110 -> 111", result.stdout)
        self.assertNotIn("age 111 -> 112", result.stdout)
        self.assertIn("[tail model]", result.stdout)

    def test_finland_explicit_tail_preserves_centennial_model_anchor(self) -> None:
        result = self._run(
            "--country", "fi", "--gender", "m", "--printout",
            "--mortality-model", "official",
            "--start-age", "99", "--end-age", "100",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("age  99 -> 100 | death prob.  39.2670%", result.stdout)
        self.assertIn("age 100 -> 101 | death prob.  39.7000%", result.stdout)
        self.assertIn("[tail model]", result.stdout)
        self.assertIn("OFFICIAL RAW PERIOD TABLE", result.stdout)

    def test_finland_female_tail_is_sex_specific(self) -> None:
        result = self._run(
            "--country", "fi", "--gender", "f", "--printout",
            "--mortality-model", "official",
            "--start-age", "99", "--end-age", "100",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("age  99 -> 100 | death prob.  33.0270%", result.stdout)
        self.assertIn("age 100 -> 101 | death prob.  36.6000%", result.stdout)
        self.assertIn("[tail model]", result.stdout)

    def test_smoothed_is_default_for_noninteractive_present_day_run(self) -> None:
        result = self._run(
            "--country", "fi", "--gender", "m", "--printout",
            "--start-age", "40", "--end-age", "47",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AGE-GRADUATED OFFICIAL PERIOD MODEL", result.stdout)
        self.assertIn("graduation: 5-age triangular hazard smoother", result.stdout)
        # Adult qx is intentionally graduated to remove the raw 2024 sawtooth.
        rows = [line for line in result.stdout.splitlines() if line.startswith("age ") and "death prob." in line]
        probs = [float(line.split("death prob.", 1)[1].split("%", 1)[0]) for line in rows]
        self.assertEqual(probs, sorted(probs))

    def test_official_mode_preserves_raw_midlife_dips(self) -> None:
        result = self._run(
            "--country", "fi", "--gender", "m", "--printout",
            "--mortality-model", "official",
            "--start-age", "40", "--end-age", "47",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("age  40 ->  41 | death prob.   0.1670%", result.stdout)
        self.assertIn("age  41 ->  42 | death prob.   0.1320%", result.stdout)
        self.assertIn("age  44 ->  45 | death prob.   0.2050%", result.stdout)
        self.assertIn("age  45 ->  46 | death prob.   0.1760%", result.stdout)

    def test_legacy_mortality_reproduces_old_baked_schedule(self) -> None:
        result = self._run(
            "--country", "fi", "--gender", "m", "--printout",
            "--start-age", "79", "--end-age", "80", "--legacy-mortality",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ORIGINAL LEGACY MORTALITY ROULETTE", result.stdout)
        self.assertIn("4.4700%", result.stdout)
        self.assertIn("5.0100%", result.stdout)

    def test_canada_bundled_default_works_without_refresh(self) -> None:
        result = self._run(
            "--country", "ca", "--gender", "m", "--printout",
            "--mortality-model", "official",
            "--start-age", "109", "--end-age", "110",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("age 109 -> 110 | death prob.  52.7840%", result.stdout)
        # First modeled tail age must not fall below the last official qx.
        self.assertIn("age 110 -> 111 | death prob.  52.7840%", result.stdout)
        self.assertIn("[tail model]", result.stdout)


class SingleRunDefaultDetailTests(unittest.TestCase):
    def test_single_run_defaults_to_causes_tree_and_seasonality(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--country", "fi", "--gender", "m",
                "--start-age", "110", "--delay", "0", "--seed", "1",
                "--no-who-detail",
            ],
            cwd=ROOT, stdin=subprocess.DEVNULL, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cause-of-death roulette: ON", result.stdout)
        self.assertIn("cause detail: TREE", result.stdout)
        self.assertIn("seasonal death timing: ON", result.stdout)
        self.assertIn("CAUSE OF DEATH", result.stdout)
        self.assertIn("CAUSE DETAIL", result.stdout)
        self.assertIn("SEASONAL TIMING", result.stdout)

    def test_no_causes_disables_dependent_default_seasonality(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--country", "fi", "--gender", "m",
                "--start-age", "111", "--delay", "0", "--seed", "1",
                "--no-causes",
            ],
            cwd=ROOT, stdin=subprocess.DEVNULL, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cause-of-death roulette: OFF", result.stdout)
        self.assertIn("seasonal death timing: OFF", result.stdout)
        self.assertNotIn("CAUSE DETAIL", result.stdout)


class BatchHistogramCliTests(unittest.TestCase):
    def _batch(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--country", "fi",
                "--sex", "m",
                "--runs", "200",
                "--batch-engine", "fast",
                "--no-progress",
                "--seed", "12345",
                *extra,
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_histogram_is_on_by_default_in_batch_mode(self) -> None:
        result = self._batch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("death-age distribution", result.stdout)
        self.assertIn("survival checkpoints", result.stdout)

    def test_no_histogram_suppresses_only_histogram(self) -> None:
        result = self._batch("--no-histogram")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("death-age distribution", result.stdout)
        self.assertIn("survival checkpoints", result.stdout)
        self.assertIn("death-age percentiles", result.stdout)


if __name__ == "__main__":
    unittest.main()
