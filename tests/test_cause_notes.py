from __future__ import annotations

import unittest

import mortality_roulette as mr


class CauseNoteModelTests(unittest.TestCase):
    def test_m17_statfin_detail_gets_underlying_cause_note(self) -> None:
        note = mr.CAUSE_NOTE_MODEL.note_for_cause_stack(
            country="fi",
            detail={
                "available": True,
                "label": "M17 Gonarthrosis [arthrosis of knee]",
                "source": "Statistics Finland 11be",
            },
        )
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note["id"], "M17_UNDERLYING_CAUSE_CHAIN_NOT_SHOWN")
        self.assertIn("underlying cause of death", note["text"])
        self.assertIn("immediate fatal mechanism", note["text"])

    def test_m17_note_is_not_added_to_unrelated_source_or_country(self) -> None:
        for country, source in (
            ("ca", "Statistics Finland 11be"),
            ("fi", "Some unrelated dataset"),
        ):
            with self.subTest(country=country, source=source):
                note = mr.CAUSE_NOTE_MODEL.note_for_cause_stack(
                    country=country,
                    detail={
                        "available": True,
                        "label": "M17 Gonarthrosis [arthrosis of knee]",
                        "source": source,
                    },
                )
                self.assertIsNone(note)

    def test_broad_m00_m99_range_does_not_fake_m17_note(self) -> None:
        note = mr.CAUSE_NOTE_MODEL.note_for_cause_stack(
            country="fi",
            detail={
                "available": True,
                "label": "Diseases of the musculoskeletal system (M00-M99)",
                "source": "Statistics Finland 11be",
            },
        )
        self.assertIsNone(note)

    def test_compact_stats_prints_note_after_detail(self) -> None:
        state = {
            "death_age": 53,
            "q": 0.01,
            "roll": 0.005,
            "cause_stack": {
                "cause": {"available": True, "label": "39 Other diseases excl. alcohol-related"},
                "detail": {"available": True, "label": "M17 Gonarthrosis [arthrosis of knee]"},
                "deep": None,
                "cause_note": {
                    "available": True,
                    "text": "Recorded as the underlying cause of death; the immediate fatal mechanism or intervening complication is not available in this dataset.",
                },
            },
        }
        rows = mr._deathmatch_compact_stats(
            {"country": "fi", "province": None}, state, sex="male", start_age=0
        )
        detail_i = next(i for i, row in enumerate(rows) if row[0] == "DETAIL")
        note_i = next(i for i, row in enumerate(rows) if row[0] == "NOTE")
        self.assertEqual(note_i, detail_i + 1)
        self.assertIn("immediate fatal mechanism", rows[note_i][1])


if __name__ == "__main__":
    unittest.main()
