from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import mortality_roulette as mr

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mortality_roulette.py"


class PlayerSpecTests(unittest.TestCase):
    def test_finland_player_spec(self) -> None:
        spec = mr.parse_player_spec("fi:f")
        self.assertEqual((spec.country, spec.province, spec.sex_selection), ("fi", None, "f"))

    def test_canada_ontario_player_spec(self) -> None:
        spec = mr.parse_player_spec("ca:on:m")
        self.assertEqual((spec.country, spec.province, spec.sex_selection), ("ca", "on", "m"))

    def test_verbose_aliases_normalize(self) -> None:
        spec = mr.parse_player_spec("canada:Ontario:male")
        self.assertEqual((spec.country, spec.province, spec.sex_selection), ("ca", "on", "m"))
        spec = mr.parse_player_spec("finland:random")
        self.assertEqual((spec.country, spec.province, spec.sex_selection), ("fi", None, "r"))

    def test_finland_rejects_province_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not include a province"):
            mr.parse_player_spec("fi:on:m")

    def test_player_mode_mixed_sex_batch_runs_offline(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--player", "fi:m",
                "--player", "fi:f",
                "--runs", "20",
                "--no-progress",
                "--seed", "123",
                "--mortality-model", "official",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAYER 1: 🇫🇮 FINLAND", result.stdout)
        self.assertIn("PLAYER 2: 🇫🇮 FINLAND", result.stdout)
        self.assertIn("player sexes: PLAYER 1 male | PLAYER 2 female", result.stdout)


    def test_contestant_label_puts_player_before_geography(self) -> None:
        self.assertEqual(
            mr.deathmatch_contestant_label("ca", "male", province="on", player_number=1),
            "PLAYER 1: 🇨🇦 CANADA (ONTARIO)",
        )
        self.assertEqual(
            mr.deathmatch_contestant_label("fi", "female", player_number=2),
            "PLAYER 2: 🇫🇮 FINLAND",
        )

    def test_legacy_mixed_country_deathmatch_assigns_player_numbers(self) -> None:
        args = type("Args", (), {
            "deathmatch": ["fi", "ca"],
            "deathmatch_provinces": [None, "on"],
            "player_mode": False,
            "log": False,
            "birth_year": None,
            "runs": 1,
            "causes": False,
            "seasonality": False,
            "cause_detail": "auto",
            "seed": 123,
            "start_age": 0,
            "exceptional_tail": False,
            "no_progress": True,
            "deathmatch_win": "long",
            "top_causes": 4,
        })()
        fake_context = lambda _args, country, province=None, **_kwargs: {
            "country": country, "province": province
        }
        with mock.patch.object(mr, "preflight_icd_titles", return_value=None), \
             mock.patch.object(mr, "_preflight_deathmatch_country", side_effect=fake_context), \
             mock.patch.object(mr, "run_deathmatch_batch", return_value=0) as batch:
            rc = mr.run_deathmatch(args, "m")
        self.assertEqual(rc, 0)
        self.assertEqual(batch.call_args.kwargs["player_numbers"], [1, 2])
        self.assertEqual(batch.call_args.kwargs["provinces"], [None, "on"])

    def test_player_random_sexes_are_independent_and_seeded(self) -> None:
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--player", "fi:r",
                "--player", "fi:r",
                "--runs", "1",
                "--no-progress",
                "--seed", "1",
                "--mortality-model", "official",
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAYER 1 random (male 0.00%, female 100.00%)", result.stdout)
        self.assertIn("PLAYER 2 random (male 100.00%, female 0.00%)", result.stdout)

    def test_player_rejects_global_sex(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--player", "fi:m", "--player", "fi:f", "--sex", "m"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--sex/--gender cannot be combined with --player", result.stderr)


class DetailCacheIsolationTests(unittest.TestCase):
    def test_bundled_seed_remains_unchanged_when_runtime_cache_is_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            seed = tmpdir / "seed.json"
            runtime = tmpdir / "runtime.json"
            seed_payload = {
                "version": 1,
                "distributions": {"seed-key": [{"label": "seed", "count": 1}]},
            }
            seed.write_text(json.dumps(seed_payload, separators=(",", ":")), encoding="utf-8")
            before = seed.read_bytes()

            resolver = mr.CauseDetailResolver(cache_path=runtime, seed_path=seed, refresh=False)
            self.assertIn("seed-key", resolver._cache)
            resolver._cache["new-key"] = [{"label": "new", "count": 2}]
            resolver._runtime_cache["new-key"] = resolver._cache["new-key"]
            resolver._save()

            self.assertEqual(seed.read_bytes(), before)
            saved = json.loads(runtime.read_text(encoding="utf-8"))
            self.assertEqual(set(saved["distributions"]), {"new-key"})

    def test_refuses_runtime_write_directly_over_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            seed.write_text('{"version":1,"distributions":{}}', encoding="utf-8")
            resolver = mr.CauseDetailResolver(cache_path=seed, seed_path=seed, refresh=False)
            with self.assertRaisesRegex(mr.CauseDataError, "refusing to write"):
                resolver._save()


if __name__ == "__main__":
    unittest.main()
