from __future__ import annotations

import argparse

import contextlib
import io
import math
import random
import sys
import unittest
from unittest import mock

import mortality_roulette as mr


class MortalityModelSelectionTests(unittest.TestCase):
    def test_interactive_blank_selects_smoothed(self) -> None:
        with mock.patch("builtins.input", return_value=""), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mr.prompt_mortality_model(allow_legacy=True), "smoothed")

    def test_interactive_sol_choices(self) -> None:
        with mock.patch("builtins.input", return_value="o"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mr.prompt_mortality_model(allow_legacy=True), "official")
        with mock.patch("builtins.input", return_value="l"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(mr.prompt_mortality_model(allow_legacy=True), "legacy")

    def test_canada_prompt_does_not_accept_legacy(self) -> None:
        with mock.patch("builtins.input", side_effect=["l", "o"]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                model = mr.prompt_mortality_model(allow_legacy=False)
        self.assertEqual(model, "official")
        self.assertIn("Please enter s or o", out.getvalue())


class CanadianProvinceTests(unittest.TestCase):
    def test_bc_alias_and_full_name(self) -> None:
        self.assertEqual(mr.normalize_canada_province("BC"), "bc")
        self.assertEqual(mr.normalize_canada_province("British Columbia"), "bc")

    def test_national_alias(self) -> None:
        self.assertIsNone(mr.normalize_canada_province("national"))

    def test_same_country_one_province_applies_to_both(self) -> None:
        single, players = mr.resolve_canada_province_assignments(["ca", "ca"], ["BC"])
        self.assertIsNone(single)
        self.assertEqual(players, ["bc", "bc"])

    def test_two_provinces_map_left_to_right(self) -> None:
        _single, players = mr.resolve_canada_province_assignments(["ca", "ca"], ["AB", "BC"])
        self.assertEqual(players, ["ab", "bc"])

    def test_bundled_bc_life_table_resolves_from_base_path(self) -> None:
        source = mr.fetch_statcan_life_table(
            cache_path=mr.BUNDLED_STATCAN_LIFE_TABLE, refresh=False, province="bc"
        )
        self.assertIn("British Columbia", source.name)
        self.assertAlmostEqual(source.data["male"][2024][79], 0.03754, places=12)

    def test_bundled_bc_monthly_resolves_from_base_path(self) -> None:
        source = mr.fetch_statcan_seasonality(
            cache_path=mr.BUNDLED_STATCAN_SEASONAL, refresh=False, province="bc"
        )
        self.assertEqual(source.geography, "British Columbia")
        self.assertEqual(source.data[2024][1], 4155)


class DeathmatchAlcoholEngineAvailabilityTests(unittest.TestCase):
    def test_cause_hazard_v3_reaches_deathmatch_runner(self) -> None:
        old_globals = (
            mr.ACTIVE_COUNTRY,
            mr.ACTIVE_ALCOHOL_MODEL,
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
        )
        argv = [
            "mortality_roulette.py",
            "--deathmatch", "fi", "ca",
            "--sex", "m",
            "--ca-province", "BC",
            "--boozehound-wino",
            "--alcohol-model", "cause-hazard-prototype",
            "--cause-hazard-weight-model", "evidence-v3-popdist",
        ]
        try:
            with mock.patch.object(sys, "argv", argv), mock.patch.object(mr, "run_deathmatch", return_value=77) as runner:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc = mr.main()
            self.assertEqual(rc, 77)
            runner.assert_called_once()
            parsed_args = runner.call_args.args[0]
            self.assertEqual(parsed_args.deathmatch, ["fi", "ca"])
            self.assertEqual(parsed_args.deathmatch_provinces, [None, "bc"])
            self.assertEqual(mr.ACTIVE_ALCOHOL_MODEL, "cause-hazard-prototype")
            self.assertEqual(mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL, "evidence-v3-popdist")
        finally:
            (
                mr.ACTIVE_COUNTRY,
                mr.ACTIVE_ALCOHOL_MODEL,
                mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
                mr.ACTIVE_BOOZEHOUND,
                mr.ACTIVE_BOOZEHOUND_PRESET,
                mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            ) = old_globals


class DeathmatchLifestyleDefaultTests(unittest.TestCase):
    def _globals(self) -> tuple[object, ...]:
        return (
            mr.ACTIVE_COUNTRY,
            mr.ACTIVE_ALCOHOL_MODEL,
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
        )

    def _restore(self, old: tuple[object, ...]) -> None:
        (
            mr.ACTIVE_COUNTRY,
            mr.ACTIVE_ALCOHOL_MODEL,
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
        ) = old

    def test_plain_deathmatch_is_population_baseline(self) -> None:
        old = self._globals()
        argv = [
            "mortality_roulette.py",
            "--deathmatch", "fi", "ca",
            "--sex", "m",
            "--ca-province", "BC",
            "--runs", "1000",
        ]
        try:
            with mock.patch.object(sys, "argv", argv), mock.patch.object(mr, "run_deathmatch", return_value=71) as runner:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc = mr.main()
            self.assertEqual(rc, 71)
            runner.assert_called_once()
            self.assertFalse(mr.ACTIVE_BOOZEHOUND)
            self.assertIsNone(mr.ACTIVE_BOOZEHOUND_PRESET)
            self.assertEqual(mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY, 0.0)
        finally:
            self._restore(old)

    def test_wino_deathmatch_requires_explicit_flag_and_then_activates(self) -> None:
        old = self._globals()
        argv = [
            "mortality_roulette.py",
            "--deathmatch", "fi", "ca",
            "--sex", "m",
            "--ca-province", "BC",
            "--boozehound-wino",
        ]
        try:
            with mock.patch.object(sys, "argv", argv), mock.patch.object(mr, "run_deathmatch", return_value=72) as runner:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc = mr.main()
            self.assertEqual(rc, 72)
            runner.assert_called_once()
            self.assertTrue(mr.ACTIVE_BOOZEHOUND)
            self.assertEqual(mr.ACTIVE_BOOZEHOUND_PRESET, "wino")
            self.assertAlmostEqual(mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY, mr.BOOZEHOUND_WINO_GRAMS_PER_DAY)
        finally:
            self._restore(old)

    def test_nondefault_alcohol_engine_without_exposure_is_rejected(self) -> None:
        old = self._globals()
        argv = [
            "mortality_roulette.py",
            "--deathmatch", "fi", "ca",
            "--sex", "m",
            "--ca-province", "BC",
            "--alcohol-model", "cause-hazard-prototype",
        ]
        try:
            out = io.StringIO()
            err = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = mr.main()
            self.assertEqual(rc, 2)
            self.assertIn("non-default --alcohol-model requires --boozehound or --boozehound-wino", err.getvalue())
        finally:
            self._restore(old)


class MortalityMathRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        )
        mr.ACTIVE_BOOZEHOUND = True
        mr.ACTIVE_BOOZEHOUND_PRESET = "wino"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = mr.BOOZEHOUND_WINO_GRAMS_PER_DAY
        mr.ACTIVE_BOOZEHOUND_START_AGE = mr.BOOZEHOUND_START_AGE
        mr.ACTIVE_BOOZEHOUND_END_AGE = None

    def tearDown(self) -> None:
        (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        ) = self.old

    def test_boozehound_uses_hazard_space_not_naive_probability_multiply(self) -> None:
        q = 0.30
        adjusted, rr = mr.boozehound_adjust_q(q, age=70, sex="male")
        expected = 1.0 - math.exp(-(-math.log1p(-q)) * rr)
        self.assertAlmostEqual(rr, 1.34, places=12)
        self.assertAlmostEqual(adjusted, expected, places=12)
        self.assertNotAlmostEqual(adjusted, q * rr, places=6)


class AlcoholTimingRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        )
        mr.ACTIVE_BOOZEHOUND = True
        mr.ACTIVE_BOOZEHOUND_PRESET = "wino"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = mr.BOOZEHOUND_WINO_GRAMS_PER_DAY
        mr.ACTIVE_BOOZEHOUND_START_AGE = 25
        mr.ACTIVE_BOOZEHOUND_END_AGE = 50

    def tearDown(self) -> None:
        (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        ) = self.old

    def test_start_and_stop_age_gate_current_exposure(self) -> None:
        self.assertFalse(mr.boozehound_active_for_age(24))
        self.assertTrue(mr.boozehound_active_for_age(25))
        self.assertTrue(mr.boozehound_active_for_age(49))
        self.assertFalse(mr.boozehound_active_for_age(50))

    def test_exposure_years_cap_at_stop_age(self) -> None:
        self.assertAlmostEqual(mr.boozehound_exposure_years(30), 5.5)
        self.assertAlmostEqual(mr.boozehound_exposure_years(50), 25.0)
        self.assertAlmostEqual(mr.boozehound_exposure_years(80), 25.0)

    def test_post_stop_current_rr_returns_to_baseline(self) -> None:
        self.assertGreater(mr.boozehound_mortality_multiplier(49, "male"), 1.0)
        self.assertEqual(mr.boozehound_mortality_multiplier(50, "male"), 1.0)

    def test_schedule_lines_show_configured_ages(self) -> None:
        self.assertEqual(
            mr.boozehound_schedule_lines(),
            ["drinking starts at age: 25", "drinking stops at age: 50"],
        )


class DeathmatchResultPresentationTests(unittest.TestCase):
    def test_longevity_winner_reason(self) -> None:
        self.assertEqual(mr._deathmatch_win_reason("long"), "lived longer")

    def test_brevity_winner_reason(self) -> None:
        self.assertEqual(mr._deathmatch_win_reason("short"), "died sooner")

    def test_long_mode_awards_outliver_only(self) -> None:
        winner_idx, result_age = mr._deathmatch_result([82, 68], "long")
        self.assertEqual((winner_idx, result_age), (0, 82))
        winner_idx, result_age = mr._deathmatch_result([68, 82], "long")
        self.assertEqual((winner_idx, result_age), (1, 82))

    def test_short_mode_awards_earlier_death_only(self) -> None:
        winner_idx, result_age = mr._deathmatch_result([82, 68], "short")
        self.assertEqual((winner_idx, result_age), (1, 68))
        winner_idx, result_age = mr._deathmatch_result([68, 82], "short")
        self.assertEqual((winner_idx, result_age), (0, 68))

    def test_same_age_is_trophy_free_draw(self) -> None:
        self.assertEqual(mr._deathmatch_result([73, 73], "long"), (None, 73))
        self.assertEqual(mr._deathmatch_result([73, 73], "short"), (None, 73))

    def test_live_canada_tapout_stays_in_right_column(self) -> None:
        original = mr._terminal_emphasis
        try:
            mr._terminal_emphasis = lambda text, **kwargs: text
            row = mr._deathmatch_live_tapout_row(
                [1],
                countries=["fi", "ca"],
                provinces=[None, "bc"],
                player_numbers=[None, None],
                states=[{"dead": False}, {"dead": True, "death_age": 45}],
                sex="male",
                column_width=72,
                blink=False,
            )
        finally:
            mr._terminal_emphasis = original
        left, right = row.split(" │ ", 1)
        self.assertEqual(left.strip(), "")
        self.assertIn("CANADA", right)
        self.assertIn("TAPPED OUT AT AGE 45", right)
        self.assertNotIn("🏆", row)

    def test_live_fatal_roll_uses_neutral_death_marker(self) -> None:
        old_booze = mr.ACTIVE_BOOZEHOUND
        try:
            mr.ACTIVE_BOOZEHOUND = False
            with mock.patch.object(mr, "record_cap_triggered", return_value=False), \
                 mock.patch.object(mr, "q_for_age", return_value=(0.50, False)):
                state = {"dead": False}
                cell = mr._deathmatch_cell(
                    {"country": "fi", "province": None, "period_source": None, "cause_source": None},
                    state,
                    age=50,
                    sex="male",
                    exceptional_tail=False,
                    mortality_roll=0.10,
                )
        finally:
            mr.ACTIVE_BOOZEHOUND = old_booze
        self.assertIn("☠", cell)
        self.assertNotIn("🏆", cell)
        self.assertTrue(state["dead"])

    def test_winner_header_keeps_trophy_and_reason(self) -> None:
        label = mr._deathmatch_result_header_label(
            "🇨🇦 CANADA (BRITISH COLUMBIA)",
            width=60,
            winner=True,
            win_mode="long",
        )
        self.assertIn("🏆 (lived longer)", label)

    def test_loser_header_has_no_trophy(self) -> None:
        label = mr._deathmatch_result_header_label(
            "🇫🇮 FINLAND",
            width=60,
            winner=False,
            win_mode="long",
        )
        self.assertNotIn("🏆", label)

    def test_wrapped_result_cell_keeps_continuation_indent(self) -> None:
        lines = mr._deathmatch_result_cell_lines(
            "CAUSE",
            "Diseases of the circulatory system excl. alcohol-related "
            "(I00-I425, I427-I99)",
            column_width=60,
        )
        self.assertGreater(len(lines), 1)
        self.assertTrue(lines[0].startswith("CAUSE"))
        self.assertTrue(lines[1].startswith(" " * 15))
        self.assertEqual(mr._terminal_display_width(lines[0]), 60)
        self.assertEqual(mr._terminal_display_width(lines[1]), 60)

    def test_result_grid_top_rule_uses_downward_t_junction(self) -> None:
        rule = mr._deathmatch_result_grid_rule(10, junction="┬")
        self.assertEqual(rule, "───────────┬───────────")
        self.assertEqual(mr._terminal_display_width(rule), 23)

    def test_result_grid_body_rule_uses_cross_junction(self) -> None:
        rule = mr._deathmatch_result_grid_rule(10, junction="┼")
        self.assertEqual(rule, "───────────┼───────────")
        self.assertEqual(mr._terminal_display_width(rule), 23)

    def test_result_grid_bottom_rule_uses_upward_t_junction(self) -> None:
        rule = mr._deathmatch_result_grid_rule(10, junction="┴")
        self.assertEqual(rule, "───────────┴───────────")
        self.assertEqual(mr._terminal_display_width(rule), 23)

    def test_result_table_contains_exactly_one_trophy_for_winner(self) -> None:
        original_label = mr.deathmatch_contestant_label
        original_stats = mr._deathmatch_compact_stats
        try:
            mr.deathmatch_contestant_label = lambda country, *args, **kwargs: country.upper()
            mr._deathmatch_compact_stats = lambda *args, **kwargs: [("TAPPED OUT", "age 73")]
            for mode, winner_idx in (("long", 0), ("short", 1)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    mr._print_deathmatch_result_table(
                        [{}, {}], [{}, {}],
                        countries=["fi", "ca"],
                        provinces=[None, None],
                        player_numbers=[None, None],
                        sex="male", start_age=0,
                        winner_idx=winner_idx, win_mode=mode,
                    )
                self.assertEqual(buf.getvalue().count("🏆"), 1)
        finally:
            mr.deathmatch_contestant_label = original_label
            mr._deathmatch_compact_stats = original_stats

    def test_result_table_emits_closing_bottom_rule(self) -> None:
        original_label = mr.deathmatch_contestant_label
        original_stats = mr._deathmatch_compact_stats
        try:
            mr.deathmatch_contestant_label = lambda *args, **kwargs: "PLAYER"
            mr._deathmatch_compact_stats = lambda *args, **kwargs: [("TAPPED OUT", "age 73")]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mr._print_deathmatch_result_table(
                    [{}, {}],
                    [{}, {}],
                    countries=["fi", "ca"],
                    provinces=[None, None],
                    player_numbers=[None, None],
                    sex="male",
                    start_age=0,
                    winner_idx=1,
                    win_mode="long",
                )
        finally:
            mr.deathmatch_contestant_label = original_label
            mr._deathmatch_compact_stats = original_stats

        lines = buf.getvalue().splitlines()
        self.assertTrue(lines[-1])
        self.assertIn("┴", lines[-1])
        self.assertNotIn("┼", lines[-1])

    def test_shared_live_and_result_grid_rule_geometry(self) -> None:
        self.assertEqual(
            mr._deathmatch_grid_rule(10, junction="┬"),
            "───────────┬───────────",
        )
        self.assertEqual(
            mr._deathmatch_grid_rule(10, junction="┼"),
            "───────────┼───────────",
        )
        self.assertEqual(
            mr._deathmatch_grid_rule(10, junction="┴"),
            "───────────┴───────────",
        )

    def test_winner_header_styles_country_but_not_trophy_suffix(self) -> None:
        original = mr._terminal_emphasis
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_emphasis(text: str, **kwargs: object) -> str:
            calls.append((text, kwargs))
            return f"<STYLE>{text}</STYLE>"

        try:
            mr._terminal_emphasis = fake_emphasis
            rendered = mr._deathmatch_result_header_render(
                "🇨🇦 CANADA (BRITISH COLUMBIA)",
                width=60,
                winner=True,
                win_mode="long",
            )
        finally:
            mr._terminal_emphasis = original

        self.assertIn("<STYLE>🇨🇦 CANADA (BRITISH COLUMBIA)</STYLE> 🏆 (lived longer)", rendered)
        self.assertNotIn("<STYLE>🏆", rendered)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].get("bold"))
        self.assertTrue(calls[0][1].get("bright_white"))


class DeathmatchBatchTests(unittest.TestCase):
    def _args(self, win_mode: str = "long") -> object:
        return type("Args", (), {
            "runs": 1000,
            "start_age": 0,
            "exceptional_tail": False,
            "no_progress": True,
            "deathmatch_win": win_mode,
            "top_causes": 4,
        })()

    def test_batch_long_mode_uses_paired_winner_semantics(self) -> None:
        contexts = [
            {"country": "fi", "province": None, "period_source": None, "cause_source": None},
            {"country": "ca", "province": "bc", "period_source": object(), "cause_source": None},
        ]
        original_build = mr.build_death_age_cdf
        try:
            def fake_build(sex: str, **kwargs: object) -> tuple[list[int], list[float]]:
                return ([70], [1.0]) if mr.ACTIVE_COUNTRY == "fi" else ([80], [1.0])
            mr.build_death_age_cdf = fake_build
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = mr.run_deathmatch_batch(
                    self._args("long"), selection="m", countries=["fi", "ca"],
                    provinces=[None, "bc"], player_numbers=[None, None], contexts=contexts,
                    match_seed=123, sex_rng=random.Random(1),
                    mortality_rngs=[random.Random(2), random.Random(3)],
                )
        finally:
            mr.build_death_age_cdf = original_build
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("BATCH DEATHMATCH", out)
        self.assertIn("🇫🇮 FINLAND wins:   0.000%", out)
        self.assertIn("🇨🇦 CANADA (BRITISH COLUMBIA) wins: 100.000%", out)

    def test_batch_short_mode_reverses_winner(self) -> None:
        contexts = [
            {"country": "fi", "province": None, "period_source": None, "cause_source": None},
            {"country": "ca", "province": "bc", "period_source": object(), "cause_source": None},
        ]
        original_build = mr.build_death_age_cdf
        try:
            def fake_build(sex: str, **kwargs: object) -> tuple[list[int], list[float]]:
                return ([70], [1.0]) if mr.ACTIVE_COUNTRY == "fi" else ([80], [1.0])
            mr.build_death_age_cdf = fake_build
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = mr.run_deathmatch_batch(
                    self._args("short"), selection="m", countries=["fi", "ca"],
                    provinces=[None, "bc"], player_numbers=[None, None], contexts=contexts,
                    match_seed=456, sex_rng=random.Random(1),
                    mortality_rngs=[random.Random(2), random.Random(3)],
                )
        finally:
            mr.build_death_age_cdf = original_build
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("🇫🇮 FINLAND wins: 100.000%", out)
        self.assertIn("🇨🇦 CANADA (BRITISH COLUMBIA) wins:   0.000%", out)

    def test_batch_percentile_nearest_rank(self) -> None:
        vals = [10, 20, 30, 40, 50]
        self.assertEqual(mr._deathmatch_batch_percentile(vals, 0.50), 30)
        self.assertEqual(mr._deathmatch_batch_percentile(vals, 0.90), 50)

    def test_canada_grouped_cause_distribution_aggregates_icd_chapters(self) -> None:
        class FakeRaw:
            def load_year(self, year: int) -> dict[str, object]:
                return {
                    "who_list": "104",
                    "data": {
                        "male": {
                            "60 - 64": {
                                "C159": 30,
                                "C189": 20,
                                "I219": 40,
                                "X45": 10,
                            }
                        }
                    },
                }

        source = mr.CanadaCauseOfDeathSource(FakeRaw())
        source.max_year = 2024
        old_active = mr.ACTIVE_BOOZEHOUND
        try:
            mr.ACTIVE_BOOZEHOUND = False
            dist = mr._canada_grouped_cause_distribution(
                source=source, sex="male", age=62, calendar_year=None
            )
        finally:
            mr.ACTIVE_BOOZEHOUND = old_active
        self.assertIsNotNone(dist)
        labels, cumulative, total = dist
        self.assertEqual(total, 100.0)
        by_label = dict(zip(labels, [cumulative[0]] + [b - a for a, b in zip(cumulative, cumulative[1:])]))
        self.assertEqual(by_label["II Neoplasms (C00-D48)"], 50.0)
        self.assertEqual(by_label["IX Diseases of the circulatory system (I00-I99)"], 40.0)
        self.assertEqual(by_label["XX External causes of morbidity and mortality (V01-Y89)"], 10.0)


class DeathmatchRngRegressionTests(unittest.TestCase):
    def test_stream_is_reproducible(self) -> None:
        a = mr._deathmatch_rng(12345, "fi", 0xABC, contestant_index=0)
        b = mr._deathmatch_rng(12345, "fi", 0xABC, contestant_index=0)
        self.assertEqual([a.random() for _ in range(8)], [b.random() for _ in range(8)])

    def test_same_country_players_are_independent(self) -> None:
        left = mr._deathmatch_rng(12345, "fi", 0xABC, contestant_index=0)
        right = mr._deathmatch_rng(12345, "fi", 0xABC, contestant_index=1)
        self.assertNotEqual([left.random() for _ in range(8)], [right.random() for _ in range(8)])


class BatchHistogramPresentationTests(unittest.TestCase):
    def test_fixed_histogram_buckets_and_boundaries(self) -> None:
        ages = [0, 19, 20, 29, 30, 39, 40, 49, 50, 59, 60, 69, 70, 79, 80, 89, 90, 99, 100, 111]
        rows = mr.death_age_histogram_rows(ages)
        self.assertEqual([label for label, _count, _share in rows], [
            "<20", "20–29", "30–39", "40–49", "50–59",
            "60–69", "70–79", "80–89", "90–99", "100+",
        ])
        self.assertEqual([count for _label, count, _share in rows], [2] * 10)
        self.assertTrue(all(abs(share - 10.0) < 1e-12 for _label, _count, share in rows))

    def test_histogram_prints_counts_and_shares(self) -> None:
        original_get_terminal_size = mr.shutil.get_terminal_size
        try:
            mr.shutil.get_terminal_size = lambda fallback=(120, 24): mr.os.terminal_size((60, 24))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mr.print_death_age_histogram([70, 71, 72, 80, 81, 82, 83, 90])
        finally:
            mr.shutil.get_terminal_size = original_get_terminal_size

        output = buf.getvalue()
        self.assertIn("death-age distribution", output)
        self.assertIn("70–79", output)
        self.assertIn("80–89", output)
        self.assertIn("█", output)



class AlcoholEnginePrototypeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
            mr.ACTIVE_ALCOHOL_MODEL,
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
        )
        mr.ACTIVE_BOOZEHOUND = True
        mr.ACTIVE_BOOZEHOUND_PRESET = "wino"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = mr.BOOZEHOUND_WINO_GRAMS_PER_DAY
        mr.ACTIVE_BOOZEHOUND_START_AGE = 18
        mr.ACTIVE_BOOZEHOUND_END_AGE = None
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "proxy-v1"

    def tearDown(self) -> None:
        (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
            mr.ACTIVE_ALCOHOL_MODEL,
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
        ) = self.old

    @staticmethod
    def _source() -> mr.CauseOfDeathSource:
        return mr.CauseOfDeathSource(
            name="synthetic StatFin",
            min_year=2024,
            max_year=2024,
            data={
                "male": {
                    2024: {
                        "70 - 74": {
                            "41 Alcohol-related diseases and accidental poisoning by alcohol": 50,
                            "54 Other causes": 50,
                        }
                    }
                }
            },
        )

    def test_default_alcohol_model_constant_is_legacy(self) -> None:
        self.assertEqual(mr.DEFAULT_ALCOHOL_MODEL, "legacy")
        self.assertIn(mr.DEFAULT_ALCOHOL_MODEL, mr.ALCOHOL_MODELS)

    def test_legacy_dispatch_matches_existing_adjuster(self) -> None:
        mr.ACTIVE_ALCOHOL_MODEL = "legacy"
        direct_q, direct_mult = mr.boozehound_adjust_q(0.20, age=70, sex="male")
        dispatch_q, dispatch_mult, diag = mr.alcohol_adjust_q(
            0.20, age=70, sex="male", cause_source=None
        )
        self.assertAlmostEqual(dispatch_q, direct_q, places=15)
        self.assertAlmostEqual(dispatch_mult, direct_mult, places=15)
        self.assertEqual(diag["engine"], "legacy")

    def test_cause_hazard_prototype_recombines_weighted_hazards(self) -> None:
        mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
        source = self._source()
        q0 = 0.20
        adjusted_q, mult, diag = mr.alcohol_adjust_q(
            q0, age=70, sex="male", cause_source=source
        )
        alcohol_mult, *_ = mr._boozehound_finland_broad_hazard_effective_rr(
            "41 Alcohol-related diseases and accidental poisoning by alcohol",
            age=70,
            sex="male",
        )
        other_mult, *_ = mr._boozehound_finland_broad_hazard_effective_rr(
            "54 Other causes", age=70, sex="male"
        )
        expected_mult = 0.5 * alcohol_mult + 0.5 * other_mult
        expected_q = -math.expm1(-(-math.log1p(-q0)) * expected_mult)
        self.assertAlmostEqual(mult, expected_mult, places=12)
        self.assertAlmostEqual(adjusted_q, expected_q, places=12)
        self.assertEqual(diag["engine"], "cause-hazard-prototype")
        self.assertEqual(diag["lookup_year"], 2024)
        self.assertEqual(diag["age_group"], "70 - 74")

    def test_default_cause_hazard_weight_model_preserves_proxy_v1(self) -> None:
        self.assertEqual(mr.DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL, "proxy-v1")
        self.assertIn("evidence-v1", mr.CAUSE_HAZARD_WEIGHT_MODELS)
        self.assertIn("evidence-v2-popnorm", mr.CAUSE_HAZARD_WEIGHT_MODELS)
        self.assertIn("evidence-v3-popdist", mr.CAUSE_HAZARD_WEIGHT_MODELS)

    def test_carr_2024_aud_mortality_knots_and_interpolation(self) -> None:
        self.assertAlmostEqual(mr.carr_2024_aud_mortality_rr(20.0), 1.99, places=12)
        self.assertAlmostEqual(mr.carr_2024_aud_mortality_rr(60.0), 7.82, places=12)
        rr71 = mr.carr_2024_aud_mortality_rr(71.0)
        self.assertGreater(rr71, 7.82)
        self.assertLess(rr71, 15.52)

    def test_evidence_v1_only_replaces_direct_alcohol_broad_weight(self) -> None:
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v1"
        direct = mr._boozehound_finland_broad_hazard_effective_rr(
            "41 Alcohol-related diseases and accidental poisoning by alcohol",
            age=70,
            sex="male",
        )
        cancer = mr._boozehound_finland_broad_hazard_effective_rr(
            "04-22 Neoplasms (C00-D48)", age=70, sex="male"
        )
        proxy_cancer = mr.boozehound_finland_broad_effective_rr(
            "04-22 Neoplasms (C00-D48)", age=70, sex="male"
        )
        self.assertIn("Carr 2024", direct[4])
        self.assertGreater(direct[1], 7.82)
        self.assertEqual(cancer[:4], proxy_cancer)
        self.assertEqual(cancer[4], "proxy-v1 fallback")


    def test_population_distribution_rr_expectation_normalizes_weights(self) -> None:
        dist = [(0.0, 1.0), (20.0, 2.0), (40.0, 1.0)]
        expected = (
            mr.carr_2024_aud_mortality_rr(0.0)
            + 2.0 * mr.carr_2024_aud_mortality_rr(20.0)
            + mr.carr_2024_aud_mortality_rr(40.0)
        ) / 4.0
        self.assertAlmostEqual(mr.alcohol_population_rr_expectation(dist), expected, places=12)

    def test_distribution_normalized_rr_uses_expected_population_risk(self) -> None:
        dist = [(0.0, 0.5), (40.0, 0.5)]
        relative, person, population = mr.carr_2024_distribution_normalized_rr(
            grams_per_day=40.0, dose_weights=dist
        )
        self.assertAlmostEqual(relative, person / population, places=12)
        self.assertGreater(population, mr.carr_2024_aud_mortality_rr(20.0))

    def test_population_distribution_rejects_empty_mass(self) -> None:
        with self.assertRaises(ValueError):
            mr.alcohol_population_rr_expectation([(0.0, 0.0)])

    def test_evidence_v2_population_normalizes_direct_alcohol_weight(self) -> None:
        old_country = mr.ACTIVE_COUNTRY
        try:
            mr.ACTIVE_COUNTRY = "fi"
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v1"
            raw = mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol",
                age=70, sex="male",
            )
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v2-popnorm"
            normalized = mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol",
                age=70, sex="male",
            )
            anchor_g, source = mr.alcohol_population_anchor("fi", "male")
            self.assertGreater(anchor_g, 30.0)
            self.assertIn("OECD", source)
            self.assertLess(normalized[1], raw[1])
            self.assertGreater(normalized[1], 1.0)
            self.assertIn("population APC anchor", normalized[4])
        finally:
            mr.ACTIVE_COUNTRY = old_country

    def test_evidence_v3_uses_who_gamma_population_expectation(self) -> None:
        population_rr, diagnostics = mr.alcohol_population_gamma_rr_expectation(
            country="fi", sex="male"
        )
        anchor_g, _source = mr.alcohol_population_anchor("fi", "male")
        mean_dose_rr = mr.carr_2024_aud_mortality_rr(anchor_g)
        self.assertAlmostEqual(float(diagnostics["abstainer_share"]), 0.10, places=12)
        self.assertAlmostEqual(float(diagnostics["gamma_shape"]), 1.0 / (1.171 ** 2), places=12)
        self.assertGreater(population_rr, mean_dose_rr)
        self.assertLess(float(diagnostics["gamma_retained_mass"]), 1.0)
        self.assertGreater(float(diagnostics["gamma_retained_mass"]), 0.95)

    def test_evidence_v3_gamma_integral_handles_shape_below_one(self) -> None:
        _population_rr, diagnostics = mr.alcohol_population_gamma_rr_expectation(
            country="fi", sex="male"
        )
        # Reference values independently checked against the corresponding
        # truncated Gamma integral; this guards against x-space quadrature
        # losing mass at the integrable singularity near zero.
        self.assertAlmostEqual(float(diagnostics["gamma_retained_mass"]), 0.98183513, places=6)
        self.assertAlmostEqual(float(diagnostics["gamma_truncated_mean_g_day"]), 29.32562, places=4)

    def test_evidence_v3_finland_female_abstainer_input_matches_thl_2023(self) -> None:
        _population_rr, diagnostics = mr.alcohol_population_gamma_rr_expectation(
            country="fi", sex="female"
        )
        self.assertAlmostEqual(float(diagnostics["abstainer_share"]), 0.12, places=12)
        self.assertIn("THL Drinking Habits Survey 2023", str(diagnostics["abstainer_source"]))

    def test_evidence_v3_direct_alcohol_weight_is_distribution_normalized(self) -> None:
        old_country = mr.ACTIVE_COUNTRY
        old_model = mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL
        old_dose = mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY
        try:
            mr.ACTIVE_COUNTRY = "fi"
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 71.0
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v2-popnorm"
            v2 = mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol",
                age=70, sex="male",
            )
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v3-popdist"
            v3 = mr._boozehound_finland_broad_hazard_effective_rr(
                "41 Alcohol-related diseases and accidental poisoning by alcohol",
                age=70, sex="male",
            )
            self.assertGreater(v3[1], 1.0)
            self.assertLess(v3[1], v2[1])
            self.assertIn("WHO Gamma population E[RR]", v3[4])
        finally:
            mr.ACTIVE_COUNTRY = old_country
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = old_model
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = old_dose

    def test_evidence_v3_canada_has_explicit_abstainer_fallback(self) -> None:
        population_rr, diagnostics = mr.alcohol_population_gamma_rr_expectation(
            country="ca", sex="male"
        )
        self.assertGreater(population_rr, 1.0)
        self.assertAlmostEqual(float(diagnostics["abstainer_share"]), 0.23, places=12)
        self.assertIn("sex-neutral fallback", str(diagnostics["abstainer_source"]))

    def test_evidence_v4_is_selectable(self) -> None:
        self.assertIn("evidence-v4-cancer", mr.CAUSE_HAZARD_WEIGHT_MODELS)
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v4-cancer"
        self.assertIn("EVIDENCE-V4 CANCER", mr.cause_hazard_weight_model_label())

    def test_nature_2026_cancer_table3_knots(self) -> None:
        self.assertAlmostEqual(mr.nature_2026_cancer_rr("oesophageal", 10.0), 1.32, places=12)
        self.assertAlmostEqual(mr.nature_2026_cancer_rr("pharyngeal", 40.0), 2.73, places=12)
        self.assertAlmostEqual(mr.nature_2026_cancer_rr("laryngeal", 100.0), 3.64, places=12)
        # The published table ends at 100 g/day; DEV9 does not invent extrapolation.
        self.assertAlmostEqual(
            mr.nature_2026_cancer_rr("laryngeal", 150.0),
            mr.nature_2026_cancer_rr("laryngeal", 100.0),
            places=12,
        )

    def test_evidence_v4_cancer_icd_partitions(self) -> None:
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C00", sex="male"), "lip_oral")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C08", sex="male"), "lip_oral")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C09", sex="male"), "pharyngeal")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C14", sex="male"), "pharyngeal")
        self.assertIsNone(mr._nature_2026_cancer_site_for_icd("C11", sex="male"))
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C15", sex="male"), "oesophageal")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C18", sex="male"), "colorectal")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C21", sex="male"), "colorectal")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C22", sex="male"), "liver")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C25", sex="male"), "pancreatic")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C32", sex="male"), "laryngeal")
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C50", sex="female"), "breast")
        self.assertIsNone(mr._nature_2026_cancer_site_for_icd("C50", sex="male"))
        self.assertEqual(mr._nature_2026_cancer_site_for_icd("C61", sex="male"), "prostate")

    def test_evidence_v4_finland_71g_population_normalized_targets(self) -> None:
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v4-cancer"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 71.0
        expected = {
            "C15": 2.0209,
            "C09": 2.0733,
            "C32": 1.7773,
            "C00": 1.7533,
            "C22": 1.5855,
            "C18": 1.2333,
            "C25": 1.1028,
            "C61": 1.0859,
            "C16": 1.1138,
        }
        for code, wanted in expected.items():
            _effective, target, _profile, _fraction, basis = mr._boozehound_icd_hazard_effective_rr(
                code, age=70, sex="male", country="fi"
            )
            self.assertAlmostEqual(target, wanted, places=4, msg=code)
            self.assertIn("Nature Health 2026", basis)

    def test_v4_reconciles_suppressed_neoplasm_mass(self) -> None:
        rows = [
            {"label": "C15 Oesophagus", "count": 25},
            {"label": "C22 Liver", "count": 15},
        ]
        reconciled = mr._reconcile_statfin_detail_rows(
            rows, parent_count=50, parent_label="test neoplasm parent"
        )
        self.assertEqual(sum(int(row["count"]) for row in reconciled), 50)
        self.assertEqual(int(reconciled[-1]["count"]), 10)
        self.assertEqual(reconciled[-1]["detail_resolution"], "residual")
        with self.assertRaises(mr.CauseDataError):
            mr._reconcile_statfin_detail_rows(
                rows, parent_count=30, parent_label="test neoplasm parent"
            )

    def test_v4_broad_neoplasm_matches_reconciled_icd_weights(self) -> None:
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "evidence-v4-cancer"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 71.0

        class FakeResolver:
            def _fetch_rows(self, **_kwargs):
                return [
                    {"label": "C15 Oesophageal cancer", "count": 40},
                    {"label": "C22 Liver cancer", "count": 20},
                ]

        resolver = FakeResolver()
        broad = mr._statfin_neoplasm_hazard_rr_from_detail(
            resolver=resolver, parent_count=100, year=2024, sex="male", age=70
        )
        c15 = mr._boozehound_icd_hazard_effective_rr("C15", age=70, sex="male", country="fi")
        c22 = mr._boozehound_icd_hazard_effective_rr("C22", age=70, sex="male", country="fi")
        expected_effective = (40 * c15[0] + 20 * c22[0] + 40 * 1.0) / 100
        expected_target = (40 * c15[1] + 20 * c22[1] + 40 * 1.0) / 100
        self.assertAlmostEqual(broad[0], expected_effective, places=12)
        self.assertAlmostEqual(broad[1], expected_target, places=12)
        self.assertIn("unresolved/suppressed residual=40", broad[4])

    def test_canada_cause_hazard_uses_who_icd_cell(self) -> None:
        old_country = mr.ACTIVE_COUNTRY
        old_model = mr.ACTIVE_ALCOHOL_MODEL
        try:
            mr.ACTIVE_COUNTRY = "ca"
            mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
            mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = "proxy-v1"
            source = object.__new__(mr.CanadaCauseOfDeathSource)
            source.counts_for = lambda **kwargs: {
                "available": True,
                "lookup_year": 2024,
                "age_group": "70 - 74",
                "counts": {"K70": 50, "C18": 50},
            }
            adjusted_q, mult, diag = mr.alcohol_adjust_q(
                0.20, age=70, sex="male", cause_source=source
            )
            self.assertGreater(mult, 1.0)
            self.assertGreater(adjusted_q, 0.20)
            self.assertEqual(diag["country"], "ca")
            self.assertEqual(diag["age_group"], "70 - 74")
        finally:
            mr.ACTIVE_COUNTRY = old_country
            mr.ACTIVE_ALCOHOL_MODEL = old_model

    def test_prototype_requires_cause_source(self) -> None:
        mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
        with self.assertRaises(mr.CauseDataError):
            mr.alcohol_adjust_q(0.10, age=70, sex="male", cause_source=None)

    def test_engine_label_is_explicitly_experimental(self) -> None:
        mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
        self.assertIn("EXPERIMENTAL", mr.alcohol_model_label())


class FastGroupedCauseSamplerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        )
        mr.ACTIVE_BOOZEHOUND = False
        mr.ACTIVE_BOOZEHOUND_PRESET = None
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 0.0
        mr.ACTIVE_BOOZEHOUND_START_AGE = 18
        mr.ACTIVE_BOOZEHOUND_END_AGE = None

    def tearDown(self) -> None:
        (
            mr.ACTIVE_BOOZEHOUND,
            mr.ACTIVE_BOOZEHOUND_PRESET,
            mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY,
            mr.ACTIVE_BOOZEHOUND_START_AGE,
            mr.ACTIVE_BOOZEHOUND_END_AGE,
        ) = self.old

    @staticmethod
    def _source() -> mr.CauseOfDeathSource:
        return mr.CauseOfDeathSource(
            name="synthetic StatFin",
            min_year=2024,
            max_year=2024,
            data={
                "male": {
                    2024: {
                        "70 - 74": {
                            "27-30 Diseases of the circulatory system excl. alcohol-related": 700,
                            "04-22 Neoplasms": 300,
                        }
                    }
                }
            },
        )

    def test_default_grouped_sampler_constant(self) -> None:
        self.assertEqual(mr.DEFAULT_CAUSE_BATCH_SAMPLER, "fast-grouped")
        self.assertIn("reference-slow", mr.CAUSE_BATCH_SAMPLERS)

    def test_grouped_sampler_matches_synthetic_probabilities(self) -> None:
        source = self._source()
        n = 100_000
        counts = mr.sample_statfin_broad_causes_grouped(
            batch_results=[(72, "male")] * n,
            source=source,
            rng=random.Random(12345),
            birth_year=None,
        )
        circulatory = counts["Diseases of the circulatory system excl. alcohol-related"] / n
        neoplasms = counts["Neoplasms"] / n
        self.assertAlmostEqual(circulatory, 0.70, delta=0.01)
        self.assertAlmostEqual(neoplasms, 0.30, delta=0.01)
        self.assertEqual(sum(counts.values()), n)

    def test_grouped_sampler_falls_back_for_specific_detail(self) -> None:
        actual, reason = mr._resolve_cause_batch_sampler(
            requested="fast-grouped",
            cause_source=self._source(),
            cause_detail_mode="specific",
            seasonal_source=None,
        )
        self.assertEqual(actual, "reference-slow")
        self.assertIsNotNone(reason)



class MortalityModelGraduationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = (
            mr.ACTIVE_COUNTRY,
            mr.ACTIVE_PERIOD_SOURCE,
            mr.ACTIVE_MORTALITY_MODEL,
            mr.ACTIVE_LEGACY_MORTALITY,
        )
        mr.ACTIVE_COUNTRY = "fi"
        mr.ACTIVE_PERIOD_SOURCE = mr.fetch_statfin_life_table(mr.BUNDLED_STATFIN_LIFE_TABLE, refresh=False)
        mr.ACTIVE_LEGACY_MORTALITY = False

    def tearDown(self) -> None:
        (
            mr.ACTIVE_COUNTRY,
            mr.ACTIVE_PERIOD_SOURCE,
            mr.ACTIVE_MORTALITY_MODEL,
            mr.ACTIVE_LEGACY_MORTALITY,
        ) = self.old

    def test_official_mode_is_literal_statfin(self) -> None:
        mr.ACTIVE_MORTALITY_MODEL = "official"
        self.assertAlmostEqual(mr.q_for_age(40, "male")[0], 0.00167, places=12)
        self.assertAlmostEqual(mr.q_for_age(41, "male")[0], 0.00132, places=12)
        self.assertAlmostEqual(mr.q_for_age(99, "male")[0], 0.39267, places=12)

    def test_smoothed_adult_curve_is_nondecreasing(self) -> None:
        mr.ACTIVE_MORTALITY_MODEL = "smoothed"
        values = [mr.q_for_age(age, "male")[0] for age in range(30, 100)]
        self.assertTrue(all(a <= b + 1e-15 for a, b in zip(values, values[1:])))

    def test_smoothed_leaves_infant_q0_untouched(self) -> None:
        mr.ACTIVE_MORTALITY_MODEL = "smoothed"
        self.assertAlmostEqual(mr.q_for_age(0, "male")[0], 0.00205, places=12)
        self.assertAlmostEqual(mr.q_for_age(0, "female")[0], 0.00211, places=12)

    def test_legacy_remains_distinct(self) -> None:
        mr.ACTIVE_MORTALITY_MODEL = "legacy"
        mr.ACTIVE_LEGACY_MORTALITY = True
        self.assertAlmostEqual(mr.q_for_age(79, "male")[0], 0.04470, places=12)
        self.assertAlmostEqual(mr.q_for_age(80, "male")[0], 0.05010, places=12)

    def test_finland_tail_anchor_is_preserved_in_smoothed_mode(self) -> None:
        mr.ACTIVE_MORTALITY_MODEL = "smoothed"
        q100, tail = mr.q_for_age(100, "male")
        self.assertTrue(tail)
        self.assertAlmostEqual(q100, 0.397, places=12)

class MortalityModelPromptRegressionTests(unittest.TestCase):
    def test_captured_stdout_disables_interactive_model_prompt(self) -> None:
        args = argparse.Namespace(
            legacy_mortality=False,
            mortality_model=None,
            birth_year=None,
            deathmatch=None,
        )
        old_country = mr.ACTIVE_COUNTRY
        try:
            mr.ACTIVE_COUNTRY = "fi"
            with mock.patch.object(mr.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(mr.sys.stdout, "isatty", return_value=False), \
                 mock.patch.object(mr, "prompt_mortality_model") as prompt:
                self.assertEqual(mr.resolve_requested_mortality_model(args), mr.DEFAULT_MORTALITY_MODEL)
                prompt.assert_not_called()
        finally:
            mr.ACTIVE_COUNTRY = old_country

    def test_full_tty_session_keeps_interactive_model_prompt(self) -> None:
        args = argparse.Namespace(
            legacy_mortality=False,
            mortality_model=None,
            birth_year=None,
            deathmatch=None,
        )
        old_country = mr.ACTIVE_COUNTRY
        try:
            mr.ACTIVE_COUNTRY = "fi"
            with mock.patch.object(mr.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(mr.sys.stdout, "isatty", return_value=True), \
                 mock.patch.object(mr, "prompt_mortality_model", return_value="official") as prompt:
                self.assertEqual(mr.resolve_requested_mortality_model(args), "official")
                prompt.assert_called_once_with(allow_legacy=True)
        finally:
            mr.ACTIVE_COUNTRY = old_country


if __name__ == "__main__":
    unittest.main()
