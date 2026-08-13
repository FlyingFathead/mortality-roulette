from __future__ import annotations

import io
import random
import unittest
from contextlib import redirect_stdout

import mortality_roulette as mr
from mortality_roulette_core.icd_knowledge import IcdKnowledgeBase
from mortality_roulette_core.postmortem_summary import compose_realized_postmortem


class GenericPostmortemSummaryTests(unittest.TestCase):
    def test_exact_car_code_becomes_code_driven_crash_narrative(self) -> None:
        out = compose_realized_postmortem(
            country="ca", sex="male", age=23, knowledge=mr.ICD_KNOWLEDGE,
            cause={"available": True, "label": "External causes"},
            detail={"available": True, "code": "V436", "label": "V43.6 car occupant"},
            deep=None,
            place={"available": True, "label": "Rural road"},
            traffic_context=None, substance_context=None, suicide_reason=None,
            seasonal={"available": True, "month_name": "November"},
        )
        text = "\n".join(out["lines"])
        self.assertIn("23-year-old male", text)
        self.assertIn("car occupant (passenger)", text)
        self.assertIn("collision with a car, pick-up truck or van", text)
        self.assertIn("modeled place roll selected Rural road", text)
        self.assertIn("timing roll placed the death in November", text)

    def test_broad_v40_v79_range_does_not_invent_exact_transport_leaf(self) -> None:
        out = compose_realized_postmortem(
            country="fi", sex="male", age=23, knowledge=mr.ICD_KNOWLEDGE,
            cause={"available": True, "label": "Accidents and violence (V01-Y89)"},
            detail={
                "available": True,
                "code": "004",
                "label": "004 Occupant of other motor vehicle injured in transport accident (V40-V79)",
            },
            deep=None, place=None, traffic_context=None, substance_context=None,
            suicide_reason=None, seasonal=None,
        )
        self.assertEqual(out["code"], "")
        text = "\n".join(out["lines"])
        self.assertIn("V40-V79", text)
        self.assertNotIn("collision with", text)

    def test_v899_stays_unspecified(self) -> None:
        out = compose_realized_postmortem(
            country="ca", sex="male", age=23, knowledge=mr.ICD_KNOWLEDGE,
            detail={"available": True, "code": "V899", "label": "V89.9 Person injured in unspecified vehicle accident"},
            cause=None, deep=None, place=None, traffic_context=None, substance_context=None,
            suicide_reason=None, seasonal=None,
        )
        text = "\n".join(out["lines"])
        self.assertIn("V89.9", text)
        self.assertIn("unspecified vehicle accident", text)
        self.assertNotIn("driver", text.casefold())
        self.assertNotIn("passenger", text.casefold())

    def test_g30_establishes_dementia_and_alzheimer_state(self) -> None:
        out = compose_realized_postmortem(
            country="fi", sex="male", age=87, knowledge=mr.ICD_KNOWLEDGE,
            detail={"available": True, "code": "G30", "label": "G30 Alzheimer disease"},
            cause=None, deep=None, place=None, traffic_context=None, substance_context=None,
            suicide_reason=None, seasonal=None,
        )
        self.assertEqual(out["condition_state"]["dementia"], "present")
        self.assertEqual(out["condition_state"]["alzheimer"], "present")

    def test_g312_is_direct_alcohol_and_neurodegeneration_by_code(self) -> None:
        row = mr.ICD_KNOWLEDGE.lookup("G312", country="fi")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("direct_alcohol_attribution", row["tags"])
        self.assertIn("neurodegeneration", row["genres"])
        self.assertIn("attributes degeneration", row["plain_language"])

    def test_scoped_enrichment_is_country_filtered_without_hiding_code_title(self) -> None:
        kb = IcdKnowledgeBase(
            {"codes": {"G30": "Alzheimer disease"}},
            {"codes": {"G30": {
                "scope": {"countries": "all"},
                "genres": ["dementia"],
                "enrichments": [
                    {"id": "FI_ONLY", "scope": {"countries": ["FI"]}},
                    {"id": "CA_ONLY", "scope": {"countries": ["CA"]}},
                ],
            }}},
        )
        fi = kb.lookup("G30", country="fi")
        ca = kb.lookup("G30", country="ca")
        self.assertEqual([x["id"] for x in fi["enrichments"]], ["FI_ONLY"])
        self.assertEqual([x["id"] for x in ca["enrichments"]], ["CA_ONLY"])
        self.assertEqual(fi["title"], "Alzheimer disease")
        self.assertEqual(ca["title"], "Alzheimer disease")


class CompositePostmortemTests(unittest.TestCase):
    def test_canadian_unsupported_pathway_falls_back_to_factual_doctor(self) -> None:
        out = mr._resolve_postmortem_outcome(
            country="ca", sex="male", age=23, rng=random.Random(5),
            cause={"available": True, "label": "XX External causes (V01-Y89)"},
            detail={"available": True, "code": "V899", "label": "V89.9 Person injured in unspecified vehicle accident"},
            deep=None,
            place={"available": True, "label": "Urban road"},
            traffic_context=None, substance_context=None, suicide_reason=None,
            seasonal={"available": True, "month_name": "June"},
        )
        self.assertEqual(out["presentation"], "generic-factual-postmortem")
        self.assertIn("23-year-old male", out["summary"])
        self.assertIn("Urban road", out["summary"])
        self.assertIn("June", out["summary"])
        self.assertIn("No additional Canada-specific pathway evidence", out["country_footer"])

    def test_finnish_g30_renderer_uses_yes_plus_separate_benchmarks(self) -> None:
        out = mr._resolve_postmortem_outcome(
            country="fi", sex="male", age=87, rng=random.Random(6),
            cause={"available": True, "label": "Dementia / Alzheimer"},
            detail={"available": True, "code": "G30", "label": "G30 Alzheimer disease"},
            deep=None, place=None, traffic_context=None, substance_context=None,
            suicide_reason=None, seasonal=None,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            mr.print_postmortem_pathway(out, country="fi", player_number=1, leading_blank=False)
        text = buf.getvalue()
        self.assertIn("DEMENTIA       : YES", text)
        self.assertIn("ALZHEIMER      : YES", text)
        self.assertIn("EUROPE 85–89 M", text)
        self.assertIn("VANTAA 85+", text)
        self.assertIn("38.7% baseline dementia prevalence", text)
        self.assertNotIn("does not mean the simulated player had dementia", text)
        self.assertIn("not a Mortality Roulette modeled probability", text)

    def test_finland_only_uses_politician_when_no_realized_summary_exists(self) -> None:
        out = mr._resolve_postmortem_outcome(
            country="fi", sex="male", age=50, rng=random.Random(7),
            cause=None, detail=None, deep=None, place=None, traffic_context=None,
            substance_context=None, suicide_reason=None, seasonal=None,
        )
        self.assertEqual(out["presentation"], "fi-public-data-fallback")


if __name__ == "__main__":
    unittest.main()
