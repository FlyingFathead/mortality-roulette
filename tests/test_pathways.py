from __future__ import annotations

import random
import re
import subprocess
import sys
import unittest
from pathlib import Path

from mortality_roulette_core.pathways import PostmortemContextModel, PostmortemPathwayModel
import mortality_roulette as mr

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mortality_roulette.py"
MODEL_PATH = ROOT / "datasets" / "pathways" / "ca_postmortem_pathway_model_v1.json"
FI_CONTEXT_PATH = ROOT / "datasets" / "pathways" / "fi_postmortem_context_v1.json"


class PostmortemPathwayModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = PostmortemPathwayModel.from_path(MODEL_PATH)

    def test_alzheimer_multiple_cause_rule_is_modeled_not_observed(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="ca",
            sex="female",
            age=84,
            rng=random.Random(1234),
            detail={"available": True, "code": "G30", "label": "G30 Alzheimer's disease"},
        )
        self.assertTrue(out["available"])
        self.assertTrue(out["modeled"])
        self.assertFalse(out["fallback"])
        self.assertEqual(out["rule_id"], "CA_ALZHEIMER_MULTIPLE_CAUSE_2004_2011")
        self.assertEqual(out["kind"], "marginal_associations")
        self.assertIn("not a temporal or causal sequence", out["limitations"])

    def test_fatal_fall_gets_evidence_summary_without_invented_fracture_site(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="CA",
            sex="male",
            age=88,
            rng=random.Random(7),
            detail={"available": True, "code": "W19", "label": "W19 Unspecified fall"},
        )
        self.assertEqual(out["rule_id"], "CA_FATAL_FALL_INJURY_CONTEXT_2017")
        self.assertEqual(out["kind"], "evidence_summary")
        self.assertIn("hip and head fractures", out["summary"])
        self.assertIn("no fracture site is randomly assigned", out["limitations"])

    def test_motorcycle_event_rule_uses_published_marginals(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="ca",
            sex="male",
            age=61,
            rng=random.Random(2),
            detail={"available": True, "code": "V23.4", "label": "Motorcycle rider injured in collision"},
        )
        self.assertEqual(out["rule_id"], "CA_MOTORCYCLE_FATAL_EVENT_2016_2020")
        self.assertEqual(out["kind"], "two_stage_weighted")
        self.assertEqual(len(out["stages"]), 1)
        self.assertAlmostEqual(sum(x["probability"] for x in self.model.payload["rules"][2]["stages"][0]["options"]), 1.0)

    def test_broad_external_range_label_does_not_fake_specific_trigger(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="ca",
            sex="male",
            age=50,
            rng=random.Random(3),
            cause={"available": True, "label": "External causes V01-X59"},
        )
        self.assertTrue(out["fallback"])
        self.assertEqual(out["rule_id"], "NO_SUPPORTED_PATHWAY")

    def test_unsupported_cause_fails_closed(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="ca",
            sex="male",
            age=68,
            rng=random.Random(4),
            detail={"available": True, "code": "C34.9", "label": "Malignant neoplasm of bronchus or lung"},
        )
        self.assertTrue(out["fallback"])
        self.assertFalse(out["modeled"])
        self.assertIn("no pathway invented", out["basis"])

    def test_non_canadian_cause_fails_closed(self) -> None:
        out = self.model.roll_for_cause_stack(
            country="fi",
            sex="male",
            age=80,
            rng=random.Random(5),
            detail={"available": True, "code": "G30", "label": "Alzheimer's disease"},
        )
        self.assertTrue(out["fallback"])


class FinnishPostmortemContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = PostmortemContextModel.from_path(FI_CONTEXT_PATH)

    def test_male_80_84_dementia_context_is_11_1_percent(self) -> None:
        out = self.model.context_for(
            country="fi", sex="male", age=82, rng=random.Random(11),
            detail={"available": True, "code": "G30", "label": "G30 Alzheimer's disease"},
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["presentation"], "fi-dementia-prevalence-context")
        self.assertEqual(out["age_band"], "80–84")
        self.assertAlmostEqual(out["prevalence"], 0.111)
        self.assertFalse(out["modeled"])
        self.assertTrue(out["contextual"])

    def test_female_90plus_dementia_context_is_44_7_percent(self) -> None:
        out = self.model.context_for(
            country="FI", sex="f", age=93, rng=random.Random(12),
            detail={"available": True, "code": "F03", "label": "F03 Unspecified dementia"},
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["age_band"], "90+")
        self.assertAlmostEqual(out["prevalence"], 0.447)

    def test_under_75_has_no_dementia_context(self) -> None:
        self.assertIsNone(self.model.context_for(
            country="fi", sex="male", age=74, rng=random.Random(13),
            detail={"available": True, "code": "G30", "label": "G30 Alzheimer's disease"},
        ))

    def test_old_age_alone_does_not_trigger_dementia_context_for_stroke(self) -> None:
        self.assertIsNone(self.model.context_for(
            country="fi", sex="male", age=92, rng=random.Random(14),
            detail={"available": True, "code": "I63", "label": "I63 Cerebral infarction"},
        ))


class AlcoholPostmortemContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_active = mr.ACTIVE_BOOZEHOUND
        self.old_preset = mr.ACTIVE_BOOZEHOUND_PRESET
        self.old_grams = mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY
        self.old_model = mr.ACTIVE_ALCOHOL_MODEL
        self.old_weight = mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL
        mr.ACTIVE_BOOZEHOUND = True
        mr.ACTIVE_BOOZEHOUND_PRESET = "wino"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 71.0
        mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v4-cancer"

    def tearDown(self) -> None:
        mr.ACTIVE_BOOZEHOUND = self.old_active
        mr.ACTIVE_BOOZEHOUND_PRESET = self.old_preset
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = self.old_grams
        mr.ACTIVE_ALCOHOL_MODEL = self.old_model
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = self.old_weight

    def test_direct_alcohol_code_gets_context(self) -> None:
        out = mr._boozehound_postmortem_context(
            country="ca", sex="male", age=76, cause=None, deep=None, rng=random.Random(1),
            detail={
                "available": True, "code": "K701", "label": "K70.1 Alcoholic hepatitis",
                "boozehound_adjusted": True, "cause_modifier": 4.04,
                "cause_modifier_target": 4.04, "boozehound_profile": "direct_chronic",
                "boozehound_exposure_years": 58.5, "baseline_conditional_probability": 0.0040,
                "conditional_probability": 0.0067,
            },
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["presentation"], "alcohol-model-context")
        self.assertTrue(out["direct_alcohol_code"])
        self.assertEqual(out["code"], "K701")

    def test_proxy_only_stroke_does_not_become_alcohol_postmortem(self) -> None:
        out = mr._boozehound_postmortem_context(
            country="fi", sex="male", age=92, cause=None, deep=None, rng=random.Random(2),
            detail={
                "available": True, "label": "I63 Cerebral infarction",
                "boozehound_adjusted": True, "cause_modifier": 1.76,
                "cause_modifier_target": 1.76, "boozehound_profile": "vascular",
                "boozehound_exposure_years": 74.5, "baseline_conditional_probability": 0.0565,
                "conditional_probability": 0.0728,
            },
        )
        self.assertIsNone(out)


class PostmortemCliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help_exposes_postmortem_and_canadian_death_machine(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--postmortem", result.stdout)
        self.assertIn("--deathmachine-ca", result.stdout)

    def test_canadian_death_machine_rejects_finland(self) -> None:
        result = self._run("--deathmachine-ca", "--country", "fi", "--sex", "m", "--delay", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Canada-only showcase", result.stderr)

    def test_postmortem_requires_causes(self) -> None:
        result = self._run(
            "--country", "fi", "--sex", "m", "--postmortem", "--no-causes",
            "--mortality-model", "official", "--delay", "0",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires cause-of-death roulette", result.stderr)


    def test_deathmatch_postmortem_follows_result_table_with_compact_spacing(self) -> None:
        result = self._run(
            "--player", "fi:m", "--player", "fi:m",
            "--postmortem", "--seed", "8675309", "--delay", "0",
            "--mortality-model", "official", "--cause-detail", "broad", "--no-seasonality",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        result_pos = out.index("DEATHMATCH RESULT\n=================")
        post_pos = out.index("POSTMORTEM\n==========")
        winner_pos = out.rindex("WINS DEATHMATCH")
        self.assertLess(result_pos, post_pos)
        self.assertLess(post_pos, winner_pos)
        self.assertIn("POSTMORTEM\n==========\n┌", out)
        post_section = out[post_pos:winner_pos]
        self.assertGreaterEqual(post_section.count("┌"), 2)
        self.assertIn("┘\n\n┌", post_section)
        final_cards = out[:result_pos]
        self.assertNotIn("WHAT CAN WE SAY ABOUT PLAYER", final_cards)
        self.assertNotIn("WHAT LIKELY HAPPENED TO PLAYER", final_cards)

    def test_enabling_postmortem_does_not_change_seeded_mortality_or_cause(self) -> None:
        common = [
            "--country", "fi", "--sex", "m", "--seed", "8675309", "--delay", "0",
            "--mortality-model", "official", "--cause-detail", "broad", "--no-seasonality",
        ]
        base = self._run(*common)
        with_pm = self._run(*common, "--postmortem")
        self.assertEqual(base.returncode, 0, base.stderr)
        self.assertEqual(with_pm.returncode, 0, with_pm.stderr)
        age_re = re.compile(r"BIG WIN at age (\d+)")
        self.assertEqual(age_re.search(base.stdout).group(1), age_re.search(with_pm.stdout).group(1))
        marker = "CAUSE OF DEATH\n-----------------\n"
        def cause_block(text: str) -> str:
            block = text.split(marker, 1)[1]
            return block.split("conditional cause probability:", 1)[0].strip()
        self.assertEqual(cause_block(base.stdout), cause_block(with_pm.stdout))
        self.assertTrue(
            "WHAT CAN WE SAY ABOUT THIS PLAYER?" in with_pm.stdout
            or "WHAT HAPPENED TO THIS PLAYER?" in with_pm.stdout
        )


if __name__ == "__main__":
    unittest.main()
