from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

import mortality_roulette as mr


class IcdSubtypeContextTests(unittest.TestCase):
    def test_statfin_11bx_parenthetical_f10_is_recognised(self) -> None:
        context = mr.icd_subtype_context(
            "Mental and behavioural disorders due to use of alcohol (F10)"
        )
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["code"], "F10")
        self.assertIn(("F10.4", "Withdrawal state with delirium"), context["children"])
        self.assertIn(("F10.31", "Alcohol withdrawal state with convulsions"), context["finland_extensions"])
        self.assertIn(("F10.41", "Alcohol withdrawal delirium with convulsions"), context["finland_extensions"])

    def test_code_at_start_still_works(self) -> None:
        context = mr.icd_subtype_context("F11 Mental and behavioural disorders due to opioids")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["code"], "F11")

    def test_broad_range_is_not_mistaken_for_leaf(self) -> None:
        self.assertIsNone(
            mr.icd_subtype_context("F10-F19 Mental and behavioural disorders due to psychoactive substance use")
        )

    def test_exposure_wording_does_not_claim_day_by_day_continuity(self) -> None:
        source = (mr.PROJECT_ROOT / "mortality_roulette.py").read_text()
        self.assertIn("ongoing modeled exposure by midpoint of fatal year", source)
        self.assertNotIn("continuous exposure by midpoint of fatal year", source)

    def test_f10_context_output_states_no_probability_roll(self) -> None:
        detail = {"label": "Mental and behavioural disorders due to use of alcohol (F10)"}
        buf = io.StringIO()
        with redirect_stdout(buf):
            mr.print_icd_subtype_context(detail)
        out = buf.getvalue()
        self.assertIn("ADDITIONAL ICD CONTEXT", out)
        self.assertIn("F10.4 Withdrawal state with delirium", out)
        self.assertIn("F10.41 Alcohol withdrawal delirium with convulsions", out)
        self.assertIn("taxonomy only; not probability-weighted", out)
        self.assertIn("are not rolled", out)


if __name__ == "__main__":
    unittest.main()
