#!/usr/bin/env python3
"""Mortality Roulette alcohol-model calibration harness.

This utility does not change or monkey-patch the roulette model. It analytically
replays the current v0.12.x *legacy all-cause alcohol hazard* against the
official Finnish present-day period table so the model can be compared with external lifespan
benchmarks before any v0.13.x redesign.

v0.12.11 also evaluates a calibration-only smooth candidate curve. The candidate
is fitted in log-RR space to the midpoint of the Wood lifespan-loss bands using
RR values solved against the same Finnish period table. It is not used by the
main roulette. Doses above Wood's highest observed group mean are explicitly
low-confidence extrapolation.

v0.12.12 adds an independent high-dose holdout panel. It compares the Wood-smooth
effective hazard multipliers with published male all-cause mortality RRs from
Wang et al. (2014), while keeping the incompatible reference populations explicit.
It also prints liver-cirrhosis and hospitalized-AUD severity bounds as context.
None of these holdout values are used by the roulette or to refit the candidate.

v0.13.0-dev2 adds the opt-in cause-hazard prototype to the same analytic life-table
comparison. The prototype is not fitted to Wood. v0.13.0-dev3 adds an A/B cause-hazard
weight model: proxy-v1 preserves dev2 exactly, while evidence-v1 replaces the directly
alcohol-coded StatFin broad hazard with the Carr et al. 2024 AUD/alcohol-poisoning
mortality dose-response. v0.13.0-dev4 adds evidence-v2-popnorm, which normalizes the
direct-alcohol Carr multiplier against a provisional Finnish sex-specific population
mean-dose anchor before applying it to the already alcohol-containing Finnish baseline.
Remaining broad groups stay explicit proxies. v0.13.0-dev8 adds evidence-v3-popdist,
which replaces the mean-dose denominator with a WHO/Rehm/Kehoe-style sex-specific
Gamma exposure distribution among current drinkers plus an abstainer point mass.

Primary benchmark:
    Wood AM et al. Lancet. 2018;391:1513-1523.
    doi:10.1016/S0140-6736(18)30134-X

Wood et al. reported, among current drinkers in 83 prospective studies, mean
usual intakes of 56, 123, 208, and 367 g/week for the >0-100, >100-200,
>200-350, and >350 g/week groups. Relative to the 56 g/week group, remaining
life expectancy at age 40 was approximately 0.5 years, 1-2 years, and 4-5 years
shorter in the successively higher groups.

The current roulette all-cause targets come from the sex-specific categories in:
    Zhao J et al. JAMA Netw Open. 2023;6(3):e236185.
    doi:10.1001/jamanetworkopen.2023.6185

This is a validation/diagnostic tool, not an epidemiological estimator.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "mortality_roulette.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_mortality_roulette():
    spec = importlib.util.spec_from_file_location("mortality_roulette_calibration_target", MAIN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {MAIN}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mr = _load_mortality_roulette()

# Calibration is intentionally pinned to the literal official period table.
# Gameplay may default to the age-graduated presentation/simulation baseline,
# but changing that default must not silently move historical calibration
# benchmarks or A/B diagnostics.
mr.ACTIVE_COUNTRY = "fi"
mr.ACTIVE_MORTALITY_MODEL = "official"
mr.ACTIVE_LEGACY_MORTALITY = False


@dataclass(frozen=True)
class LifeTableResult:
    expected_death_age: float
    remaining_life_expectancy: float
    survival: dict[int, float]


@dataclass(frozen=True)
class WoodBenchmarkRow:
    label: str
    grams_per_week: float
    observed_loss_low: float
    observed_loss_high: float

    @property
    def grams_per_day(self) -> float:
        return self.grams_per_week / 7.0


WOOD_ROWS = (
    WoodBenchmarkRow("reference", 56.0, 0.0, 0.0),
    WoodBenchmarkRow(">100-200 g/week", 123.0, 0.5, 0.5),
    WoodBenchmarkRow(">200-350 g/week", 208.0, 1.0, 2.0),
    WoodBenchmarkRow(">350 g/week", 367.0, 4.0, 5.0),
)


@dataclass(frozen=True)
class PublishedAllCauseRRRow:
    grams_per_day: float
    rr: float
    ci_low: float
    ci_high: float


# Independent holdout evidence. Wang et al. (2014) modelled the male all-cause
# mortality dose-response versus nondrinkers. These values are deliberately NOT
# used to fit the Wood-smooth candidate. They are an external diagnostic only.
WANG_2014_MALE_ALL_CAUSE_RR = (
    PublishedAllCauseRRRow(10.0, 0.95, 0.92, 0.98),
    PublishedAllCauseRRRow(25.0, 0.92, 0.85, 0.99),
    PublishedAllCauseRRRow(50.0, 0.96, 0.83, 1.10),
    PublishedAllCauseRRRow(75.0, 1.15, 0.92, 1.43),
    PublishedAllCauseRRRow(90.0, 1.36, 1.02, 1.80),
    PublishedAllCauseRRRow(100.0, 1.56, 1.12, 2.19),
)

# Cause-specific severity anchor, both sexes combined, versus lifetime abstention.
# Llamosas-Falcón et al. (2024; epub 2023) cirrhosis mortality dose-response.
CIRRHOSIS_MORTALITY_RR = {
    25.0: (2.65, 2.22, 3.16),
    50.0: (6.83, 5.84, 7.97),
    100.0: (16.38, 13.81, 19.42),
}

# Westman et al. (2015 publication; register period 1987-2006): hospitalized AUD
# in Denmark, Finland and Sweden. This is a selected severe clinical population,
# so it is a severity bound, not a dose-equivalent boozehound parameter.
HOSPITALIZED_NORDIC_AUD_MRR_RANGE = (3.0, 5.2)
HOSPITALIZED_NORDIC_AUD_LE_LOSS_RANGE = (24.0, 28.0)


def _normalise_sex(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"m", "male"}:
        return "male"
    if lowered in {"f", "female"}:
        return "female"
    raise argparse.ArgumentTypeError("sex must be m/male or f/female")


def legacy_target_rr(sex: str, grams_per_day: float) -> float:
    """Return the exact v0.12.x all-cause target used by the roulette."""
    return float(mr.boozehound_all_cause_target_rr(sex, grams_per_day=grams_per_day))


def _hazard_adjust_q(q: float, rr: float) -> float:
    q = min(1.0, max(0.0, float(q)))
    rr = max(0.0, float(rr))
    if q <= 0.0 or rr == 1.0:
        return q
    if q >= 1.0:
        return 1.0
    hazard = -math.log1p(-q)
    return min(1.0, max(0.0, -math.expm1(-hazard * rr)))


def _ramped_rr(target_rr: float, age: int, start_age: int, ramp_years: float) -> float:
    if age < start_age:
        return 1.0
    if ramp_years <= 0:
        return target_rr
    exposure_years = max(0.0, float(age) + 0.5 - float(start_age))
    fraction = min(1.0, exposure_years / ramp_years)
    return target_rr ** fraction


def exact_period_life_expectancy(
    *,
    sex: str,
    start_age: int,
    grams_per_day: float,
    target_rr: float | None = None,
    ramp_years: float | None = None,
    checkpoints: tuple[int, ...] = (50, 60, 70, 80, 85, 90, 95, 100),
) -> LifeTableResult:
    """Analytic expected lifespan under the current period-table hazard process.

    Deaths are located at the midpoint of each one-year interval. This avoids a
    systematic integer-age truncation while preserving the roulette's exact qx
    and hazard-space alcohol adjustment. The extreme-age tail is the same
    explicit toy tail used by mortality_roulette.py. The Finnish observed-record
    cap is intentionally *not* used for life-expectancy calibration.
    """
    if start_age < 0:
        raise ValueError("start_age must be non-negative")
    if grams_per_day < 0:
        raise ValueError("grams_per_day must be non-negative")

    # Force the baked Finnish period table without network/data preflight.
    mr.ACTIVE_COUNTRY = "fi"
    mr.ACTIVE_PERIOD_SOURCE = None

    if ramp_years is None:
        ramp_years = float(mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS)
    if target_rr is None:
        target_rr = legacy_target_rr(sex, grams_per_day)

    survival = 1.0
    expected_death_age = 0.0
    survival_at: dict[int, float] = {}
    age = int(start_age)

    checkpoint_set = set(checkpoints)
    if start_age in checkpoint_set:
        survival_at[start_age] = 1.0

    while survival > 1e-15:
        if age in checkpoint_set and age not in survival_at:
            survival_at[age] = survival

        q, _tail = mr.q_for_age(age, sex)
        if grams_per_day > 0.0 or target_rr != 1.0:
            rr = _ramped_rr(float(target_rr), age, start_age, float(ramp_years))
            q = _hazard_adjust_q(q, rr)

        death_mass = survival * q
        expected_death_age += death_mass * (float(age) + 0.5)
        survival -= death_mass
        age += 1

        if age > 1000:
            raise RuntimeError("calibration life table failed to close by age 1000")

    # Negligible floating residual, but keep the expectation normalized.
    if survival > 0.0:
        expected_death_age += survival * (float(age) + 0.5)

    for checkpoint in checkpoints:
        if checkpoint < start_age:
            survival_at[checkpoint] = 1.0
        elif checkpoint not in survival_at:
            survival_at[checkpoint] = 0.0

    return LifeTableResult(
        expected_death_age=expected_death_age,
        remaining_life_expectancy=expected_death_age - float(start_age),
        survival=survival_at,
    )



@contextmanager
def _temporary_boozehound_exposure(*, grams_per_day: float, start_age: int, weight_model: str = "proxy-v1"):
    """Temporarily configure the main module for analytic prototype integration."""
    names = (
        "ACTIVE_COUNTRY",
        "ACTIVE_PERIOD_SOURCE",
        "ACTIVE_BOOZEHOUND",
        "ACTIVE_BOOZEHOUND_PRESET",
        "ACTIVE_BOOZEHOUND_GRAMS_PER_DAY",
        "ACTIVE_BOOZEHOUND_START_AGE",
        "ACTIVE_BOOZEHOUND_END_AGE",
        "ACTIVE_ALCOHOL_MODEL",
        "ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL",
    )
    old = {name: getattr(mr, name) for name in names}
    try:
        mr.ACTIVE_COUNTRY = "fi"
        mr.ACTIVE_PERIOD_SOURCE = None
        mr.ACTIVE_BOOZEHOUND = grams_per_day > 0.0
        mr.ACTIVE_BOOZEHOUND_PRESET = "calibration"
        mr.ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = float(grams_per_day)
        mr.ACTIVE_BOOZEHOUND_START_AGE = int(start_age)
        mr.ACTIVE_BOOZEHOUND_END_AGE = None
        mr.ACTIVE_ALCOHOL_MODEL = "cause-hazard-prototype"
        mr.ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = str(weight_model)
        yield
    finally:
        for name, value in old.items():
            setattr(mr, name, value)


def exact_cause_hazard_prototype_life_expectancy(
    *,
    sex: str,
    start_age: int,
    grams_per_day: float,
    cause_source,
    weight_model: str = "proxy-v1",
    checkpoints: tuple[int, ...] = (50, 60, 70, 80, 85, 90, 95, 100),
) -> LifeTableResult:
    """Analytic LE under the dev cause-hazard engine; no Monte Carlo sampling.

    Unlike Wood-smooth, this function has no fitted lifespan-loss target. It simply
    integrates whatever annual qx the current prototype architecture produces.
    """
    if start_age < 0:
        raise ValueError("start_age must be non-negative")
    if grams_per_day < 0:
        raise ValueError("grams_per_day must be non-negative")

    survival = 1.0
    expected_death_age = 0.0
    survival_at: dict[int, float] = {}
    checkpoint_set = set(checkpoints)
    age = int(start_age)
    if start_age in checkpoint_set:
        survival_at[start_age] = 1.0

    with _temporary_boozehound_exposure(grams_per_day=grams_per_day, start_age=start_age, weight_model=weight_model):
        while survival > 1e-15:
            if age in checkpoint_set and age not in survival_at:
                survival_at[age] = survival
            q0, _tail = mr.q_for_age(age, sex)
            q1, _mult, _diag = mr.boozehound_cause_hazard_prototype_adjust_q(
                q0, age=age, sex=sex, cause_source=cause_source
            )
            death_mass = survival * q1
            expected_death_age += death_mass * (float(age) + 0.5)
            survival -= death_mass
            age += 1
            if age > 1000:
                raise RuntimeError("cause-hazard calibration life table failed to close by age 1000")

    if survival > 0.0:
        expected_death_age += survival * (float(age) + 0.5)
    for checkpoint in checkpoints:
        if checkpoint < start_age:
            survival_at[checkpoint] = 1.0
        elif checkpoint not in survival_at:
            survival_at[checkpoint] = 0.0
    return LifeTableResult(
        expected_death_age=expected_death_age,
        remaining_life_expectancy=expected_death_age - float(start_age),
        survival=survival_at,
    )


def load_cached_prototype_cause_source(cache_path: Path | None = None):
    """Load StatFin 11az only from an existing cache; calibration stays offline-safe."""
    path = Path(cache_path) if cache_path is not None else (Path(mr.BUNDLED_STATFIN_CAUSES) if Path(mr.BUNDLED_STATFIN_CAUSES).exists() else Path(mr.DEFAULT_CAUSE_CACHE))
    if not path.exists():
        return None, path
    return mr.fetch_statfin_causes(cache_path=path, refresh=False), path

def required_uniform_target_rr(
    *,
    sex: str,
    start_age: int,
    target_years_lost: float,
    ramp_years: float | None = None,
) -> float:
    """Diagnostic RR needed for a single-RR model to create a target LE loss.

    This is *not* an estimate of alcohol's true RR. It answers only: if we kept
    the current simplistic architecture and changed one target hazard ratio,
    what target would reproduce the requested lifespan difference?
    """
    if target_years_lost < 0:
        raise ValueError("target_years_lost must be non-negative")
    if ramp_years is None:
        ramp_years = float(mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS)

    baseline = exact_period_life_expectancy(
        sex=sex,
        start_age=start_age,
        grams_per_day=0.0,
        target_rr=1.0,
        ramp_years=ramp_years,
    ).remaining_life_expectancy

    if target_years_lost == 0:
        return 1.0

    low, high = 1.0, 2.0
    while True:
        high_le = exact_period_life_expectancy(
            sex=sex,
            start_age=start_age,
            grams_per_day=1.0,
            target_rr=high,
            ramp_years=ramp_years,
        ).remaining_life_expectancy
        if baseline - high_le >= target_years_lost:
            break
        high *= 2.0
        if high > 128.0:
            raise RuntimeError("could not bracket diagnostic target RR")

    for _ in range(80):
        mid = (low + high) / 2.0
        mid_le = exact_period_life_expectancy(
            sex=sex,
            start_age=start_age,
            grams_per_day=1.0,
            target_rr=mid,
            ramp_years=ramp_years,
        ).remaining_life_expectancy
        loss = baseline - mid_le
        if loss < target_years_lost:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0




def _wood_midpoint_loss(row: WoodBenchmarkRow) -> float:
    return (row.observed_loss_low + row.observed_loss_high) / 2.0


def wood_candidate_knots(
    *, sex: str, start_age: int, ramp_years: float | None = None
) -> tuple[tuple[float, float], ...]:
    """Return (g/day, diagnostic target RR) knots for the smooth candidate.

    The reference Wood mean dose (8 g/day) is anchored at RR 1.0. Each higher
    knot solves for the uniform post-ramp hazard target that reproduces the
    midpoint of Wood's reported age-40 lifespan-loss band under this exact
    Finnish period-table architecture. These are calibration parameters, not
    published epidemiological RRs.
    """
    if ramp_years is None:
        ramp_years = float(mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS)
    knots: list[tuple[float, float]] = [(WOOD_ROWS[0].grams_per_day, 1.0)]
    for row in WOOD_ROWS[1:]:
        target_loss = _wood_midpoint_loss(row)
        rr = required_uniform_target_rr(
            sex=sex,
            start_age=start_age,
            target_years_lost=target_loss,
            ramp_years=ramp_years,
        )
        knots.append((row.grams_per_day, rr))
    return tuple(knots)


def _pchip_slopes(xs: Sequence[float], ys: Sequence[float]) -> list[float]:
    """Dependency-free monotone PCHIP-style slopes for strictly increasing x."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("need at least two x/y points")
    h = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
    if any(step <= 0 for step in h):
        raise ValueError("x points must be strictly increasing")
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(len(h))]
    if len(xs) == 2:
        return [delta[0], delta[0]]

    def endpoint(h0: float, h1: float, d0: float, d1: float) -> float:
        slope = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if slope * d0 <= 0:
            return 0.0
        if d0 * d1 < 0 and abs(slope) > abs(3.0 * d0):
            return 3.0 * d0
        return slope

    slopes = [0.0] * len(xs)
    slopes[0] = endpoint(h[0], h[1], delta[0], delta[1])
    slopes[-1] = endpoint(h[-1], h[-2], delta[-1], delta[-2])

    for i in range(1, len(xs) - 1):
        left = delta[i - 1]
        right = delta[i]
        if left == 0.0 or right == 0.0 or left * right <= 0.0:
            slopes[i] = 0.0
            continue
        w1 = 2.0 * h[i] + h[i - 1]
        w2 = h[i] + 2.0 * h[i - 1]
        slopes[i] = (w1 + w2) / (w1 / left + w2 / right)
    return slopes


def _monotone_cubic_value(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Monotone cubic Hermite interpolation, with conservative tail extrapolation."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        # Do not extend the steeper endpoint derivative into unobserved high doses.
        # Continue only the final observed secant in log-RR space.
        tail_slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
        return ys[-1] + tail_slope * (x - xs[-1])

    slopes = _pchip_slopes(xs, ys)
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            h = xs[i + 1] - xs[i]
            t = (x - xs[i]) / h
            h00 = 2 * t**3 - 3 * t**2 + 1
            h10 = t**3 - 2 * t**2 + t
            h01 = -2 * t**3 + 3 * t**2
            h11 = t**3 - t**2
            return (
                h00 * ys[i]
                + h10 * h * slopes[i]
                + h01 * ys[i + 1]
                + h11 * h * slopes[i + 1]
            )
    raise RuntimeError("failed to locate interpolation interval")


def wood_smooth_candidate_rr(
    grams_per_day: float,
    *,
    sex: str = "male",
    start_age: int = 40,
    ramp_years: float | None = None,
) -> float:
    """Calibration-only smooth all-cause candidate target RR.

    RR=1.0 at and below Wood's 56 g/week reference mean. Between calibration
    means, interpolate monotonically in log(RR). Above 367 g/week (~52.4 g/day),
    extend only the last log-RR secant and treat results as low-confidence.
    """
    if grams_per_day < 0:
        raise ValueError("grams_per_day must be non-negative")
    knots = wood_candidate_knots(sex=sex, start_age=start_age, ramp_years=ramp_years)
    xs = [dose for dose, _rr in knots]
    ys = [math.log(rr) for _dose, rr in knots]
    log_rr = _monotone_cubic_value(xs, ys, float(grams_per_day))
    return math.exp(log_rr)


def _observed_label(row: WoodBenchmarkRow) -> str:
    if row.observed_loss_low == row.observed_loss_high:
        if row.observed_loss_low == 0:
            return "reference"
        return f"~{row.observed_loss_low:.1f} y"
    return f"~{row.observed_loss_low:.0f}-{row.observed_loss_high:.0f} y"


def _status(modeled_loss: float, row: WoodBenchmarkRow) -> str:
    if row.observed_loss_low == row.observed_loss_high == 0.0:
        return "reference"
    if modeled_loss < row.observed_loss_low - 0.05:
        return "UNDER"
    if modeled_loss > row.observed_loss_high + 0.05:
        return "OVER"
    return "within band"


def build_report(*, sex: str = "male", start_age: int = 40, ramp_years: float | None = None, prototype_cause_cache: Path | None = None) -> str:
    if ramp_years is None:
        ramp_years = float(mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS)

    ref = exact_period_life_expectancy(
        sex=sex,
        start_age=start_age,
        grams_per_day=WOOD_ROWS[0].grams_per_day,
        ramp_years=ramp_years,
    )

    lines = [
        f"MORTALITY ROULETTE v{mr.VERSION} - ALCOHOL CALIBRATION",
        "=" * 72,
        f"period table: Finland, {sex}",
        f"calibration starting age: {start_age}",
        f"legacy all-cause RR ramp: {ramp_years:g} years",
        "method: exact period-life-table integration; no Monte Carlo noise",
        "record ceiling: disabled for life-expectancy calibration",
        "status note: UNDER / OVER / within band are rough numeric comparators to the displayed Wood point/band;",
        "             they are NOT statistical-significance tests or confidence-interval verdicts",
        "",
        "WOOD ET AL. 2018 BENCHMARK",
        "current drinkers in 83 prospective studies; mean usual intake per group",
        "reference: mean 56 g/week; reported LE differences are from age 40",
        "",
        "group                mean g/wk  g/day  legacy RR  modeled loss  observed     status",
        "-------------------  ---------  -----  ---------  ------------  -----------  -----------",
    ]

    for row in WOOD_ROWS:
        result = exact_period_life_expectancy(
            sex=sex,
            start_age=start_age,
            grams_per_day=row.grams_per_day,
            ramp_years=ramp_years,
        )
        loss = ref.remaining_life_expectancy - result.remaining_life_expectancy
        lines.append(
            f"{row.label:<19}  {row.grams_per_week:9.0f}  {row.grams_per_day:5.1f}  "
            f"x{legacy_target_rr(sex, row.grams_per_day):8.3f}  {loss:10.2f} y  "
            f"{_observed_label(row):<11}  {_status(loss, row)}"
        )

    prototype_source, prototype_cache_path = load_cached_prototype_cause_source(prototype_cause_cache)
    prototype_results_by_model: dict[str, dict[float, LifeTableResult]] = {}
    prototype_refs: dict[str, LifeTableResult] = {}
    prototype_winos: dict[str, LifeTableResult] = {}
    prototype_wino_losses: dict[str, float] = {}
    if prototype_source is not None:
        for weight_model in mr.CAUSE_HAZARD_WEIGHT_MODELS:
            model_results: dict[float, LifeTableResult] = {}
            model_ref = exact_cause_hazard_prototype_life_expectancy(
                sex=sex,
                start_age=start_age,
                grams_per_day=WOOD_ROWS[0].grams_per_day,
                cause_source=prototype_source,
                weight_model=weight_model,
            )
            prototype_refs[weight_model] = model_ref
            prototype_results_by_model[weight_model] = model_results
            if weight_model == "proxy-v1":
                title = "CAUSE-HAZARD PROTOTYPE / PROXY-V1 (UNFITTED WOOD CHECK)"
            elif weight_model == "evidence-v1":
                title = "CAUSE-HAZARD PROTOTYPE / EVIDENCE-V1 HYBRID (UNFITTED WOOD CHECK)"
            elif weight_model == "evidence-v2-popnorm":
                title = "CAUSE-HAZARD PROTOTYPE / EVIDENCE-V2 POPNORM (UNFITTED WOOD CHECK)"
            elif weight_model == "evidence-v3-popdist":
                title = "CAUSE-HAZARD PROTOTYPE / EVIDENCE-V3 POPDIST (UNFITTED WOOD CHECK)"
            else:
                title = "CAUSE-HAZARD PROTOTYPE / EVIDENCE-V4 CANCER (UNFITTED WOOD CHECK)"
            lines.extend([
                "",
                title,
                f"StatFin broad-cause cache: {prototype_cache_path}",
            ])
            if weight_model == "proxy-v1":
                lines.append("dev1/dev2 provisional broad-cause hazard weights; NOT fitted to Wood")
            elif weight_model == "evidence-v1":
                lines.extend([
                    "direct alcohol-related broad hazard: raw Carr et al. 2024 dose-response",
                    "remaining broad hazards: proxy-v1 fallback; background population alcohol still embedded",
                ])
            elif weight_model == "evidence-v2-popnorm":
                anchor_g, anchor_source = mr.alcohol_population_anchor("fi", sex)
                lines.extend([
                    "direct alcohol-related broad hazard: Carr et al. 2024 / provisional population mean-dose normalization",
                    f"Finnish {sex} population anchor: {anchor_g:.2f} g/day | {anchor_source}",
                    "remaining broad hazards: proxy-v1 fallback; full exposure-distribution deconvolution NOT implemented",
                ])
            else:
                population_rr, diagnostics = mr.alcohol_population_gamma_rr_expectation(country="fi", sex=sex)
                lines.extend([
                    "direct alcohol-related broad hazard: Carr et al. 2024 / WHO-style Gamma population E[RR] normalization",
                    (
                        f"Finnish {sex} exposure model: abstainers {float(diagnostics['abstainer_share']) * 100:.1f}% | "
                        f"current-drinker mean {float(diagnostics['drinker_mean_g_day']):.2f} g/day | "
                        f"population Carr E[RR]={population_rr:.3f}"
                    ),
                    (
                        f"Gamma: shape {float(diagnostics['gamma_shape']):.3f} | "
                        f"scale {float(diagnostics['gamma_scale']):.2f} g/day | cap {mr.ALCOHOL_GAMMA_MAX_G_DAY:.0f} g/day"
                    ),
                    f"APC source: {diagnostics['apc_source']}",
                    f"abstainer source: {diagnostics['abstainer_source']}",
                    (
                        f"method caveat: WHO-style model uses {mr.ALCOHOL_GAMMA_APC_CONSUMED_FRACTION:.0%} of APC; "
                        f"Carr RR held flat above {mr.ALCOHOL_CARR_POPDIST_RR_CAP_G_DAY:.0f} g/day inside population E[RR]"
                    ),
                    (
                        "v4 cancer detail note: standalone calibration has no StatFin 11be detail resolver attached, so its neoplasm row remains the proxy fallback in this harness"
                        if weight_model == "evidence-v4-cancer"
                        else "remaining broad hazards: proxy-v1 fallback; population-distribution normalization currently covers direct alcohol only"
                    ),
                ])
            lines.extend([
                "",
                "group                mean g/wk  g/day  modeled loss  observed     status",
                "-------------------  ---------  -----  ------------  -----------  -----------",
            ])
            for row in WOOD_ROWS:
                result = exact_cause_hazard_prototype_life_expectancy(
                    sex=sex,
                    start_age=start_age,
                    grams_per_day=row.grams_per_day,
                    cause_source=prototype_source,
                    weight_model=weight_model,
                )
                model_results[row.grams_per_day] = result
                loss = model_ref.remaining_life_expectancy - result.remaining_life_expectancy
                observed = _observed_label(row)
                status = _status(loss, row)
                lines.append(
                    f"{row.label:<19}  {row.grams_per_week:9.0f}  {row.grams_per_day:5.1f}  "
                    f"{loss:10.2f} y  {observed:<11}  {status}"
                )
            wino_result = exact_cause_hazard_prototype_life_expectancy(
                sex=sex,
                start_age=start_age,
                grams_per_day=mr.BOOZEHOUND_WINO_GRAMS_PER_DAY,
                cause_source=prototype_source,
                weight_model=weight_model,
            )
            prototype_winos[weight_model] = wino_result
            prototype_wino_losses[weight_model] = model_ref.remaining_life_expectancy - wino_result.remaining_life_expectancy
    else:
        lines.extend([
            "",
            "CAUSE-HAZARD PROTOTYPE (UNFITTED WOOD CHECK; EXPERIMENTAL)",
            f"UNAVAILABLE: no existing StatFin 11az cache at {prototype_cache_path}",
            "Bundled StatFin causes were unavailable; run one Finland prototype/cause simulation first, or pass --prototype-cause-cache PATH.",
        ])

    if prototype_source is not None:
        lines.extend([
            "",
            "EVIDENCE-V1/V2/V3 COVERAGE / DEFERRED BROAD MAPPINGS",
            "41 alcohol-related diseases + accidental alcohol poisoning: Carr 2024; v2 mean-dose-normalizes and v3 Gamma-distribution-normalizes this bucket",
            "04-22 neoplasms: PROXY — broad bucket mixes alcohol-sensitive and insensitive cancer sites",
            "27-30 circulatory: PROXY — broad bucket mixes positively associated subtypes and myocardial infarction",
            "42-53 accidents/violence: PROXY — published acute injury curves are per-occasion exposure, not average g/day",
            "36 digestive excl. alcohol-related: PROXY — cirrhosis evidence does not map cleanly to the whole residual bucket",
            "other broad groups: PROXY — awaiting compatible cause-specific mapping",
            "",
            "This is intentional: evidence-v1/v2/v3 only replace a broad hazard when the published outcome is close enough",
            "to the StatFin bucket to make the mapping auditable. v3 improves the population-baseline denominator for",
            "the direct-alcohol bucket; it does not fill missing cause evidence with invented precision.",
        ])

    lines.extend(
        [
            "",
            "WOOD-SMOOTH CANDIDATE (CALIBRATION ONLY; NOT USED BY ROULETTE)",
            "monotone cubic interpolation in log(RR) through Wood midpoint lifespan-loss targets",
            "above 367 g/week (~52.4 g/day): conservative log-linear extrapolation; LOW CONFIDENCE",
            "",
            "group                mean g/wk  g/day  candidate RR  modeled loss  observed     status",
            "-------------------  ---------  -----  ------------  ------------  -----------  -----------",
        ]
    )
    for row in WOOD_ROWS:
        candidate_rr = wood_smooth_candidate_rr(
            row.grams_per_day, sex=sex, start_age=start_age, ramp_years=ramp_years
        )
        result = exact_period_life_expectancy(
            sex=sex,
            start_age=start_age,
            grams_per_day=row.grams_per_day,
            target_rr=candidate_rr,
            ramp_years=ramp_years,
        )
        loss = ref.remaining_life_expectancy - result.remaining_life_expectancy
        lines.append(
            f"{row.label:<19}  {row.grams_per_week:9.0f}  {row.grams_per_day:5.1f}  "
            f"x{candidate_rr:11.3f}  {loss:10.2f} y  "
            f"{_observed_label(row):<11}  {_status(loss, row)}"
        )

    wino_daily = float(mr.BOOZEHOUND_WINO_GRAMS_PER_DAY)
    wino_weekly = wino_daily * 7.0
    wino = exact_period_life_expectancy(
        sex=sex,
        start_age=start_age,
        grams_per_day=wino_daily,
        ramp_years=ramp_years,
    )
    wino_loss = ref.remaining_life_expectancy - wino.remaining_life_expectancy
    candidate_wino_rr = wood_smooth_candidate_rr(
        wino_daily, sex=sex, start_age=start_age, ramp_years=ramp_years
    )
    candidate_wino = exact_period_life_expectancy(
        sex=sex,
        start_age=start_age,
        grams_per_day=wino_daily,
        target_rr=candidate_wino_rr,
        ramp_years=ramp_years,
    )
    candidate_wino_loss = ref.remaining_life_expectancy - candidate_wino.remaining_life_expectancy
    candidate_knots = wood_candidate_knots(sex=sex, start_age=start_age, ramp_years=ramp_years)


    wood_high = WOOD_ROWS[-1]
    wood_high_result = exact_period_life_expectancy(
        sex=sex,
        start_age=start_age,
        grams_per_day=wood_high.grams_per_day,
        ramp_years=ramp_years,
    )
    wood_high_loss = ref.remaining_life_expectancy - wood_high_result.remaining_life_expectancy

    lines.extend(
        [
            "",
            "INDEPENDENT HIGH-DOSE HOLDOUT (NOT USED TO FIT CANDIDATE)",
            "Wang et al. 2014 male all-cause mortality RR versus nondrinkers",
            "Wood-smooth column is an architecture-specific effective hazard multiplier",
            "relative to the Finnish period-table calibration reference, so values are NOT",
            "directly interchangeable with the published RR column.",
            "",
            "dose g/day  Wood-effective  Wang male RR (95% CI)   note",
            "----------  --------------  ----------------------  ----------------------------",
        ]
    )
    for row in WANG_2014_MALE_ALL_CAUSE_RR:
        if row.grams_per_day < 50.0:
            continue
        candidate_rr = wood_smooth_candidate_rr(
            row.grams_per_day, sex=sex, start_age=start_age, ramp_years=ramp_years
        )
        note = "within Wood range" if row.grams_per_day <= WOOD_ROWS[-1].grams_per_day else "Wood extrapolation"
        lines.append(
            f"{row.grams_per_day:10.1f}  x{candidate_rr:13.3f}  "
            f"x{row.rr:.2f} ({row.ci_low:.2f}-{row.ci_high:.2f})      {note}"
        )

    lines.extend(
        [
            "",
            "SEVERITY BOUNDS / CAUSE-SPECIFIC CONTEXT (NOT DOSE-EQUIVALENT)",
            "cirrhosis mortality RR vs lifetime abstention (Llamosas-Falcón et al.):",
        ]
    )
    for dose in (25.0, 50.0, 100.0):
        rr, low, high = CIRRHOSIS_MORTALITY_RR[dose]
        lines.append(f"  {dose:5.1f} g/day -> x{rr:.2f} ({low:.2f}-{high:.2f})")
    lines.extend(
        [
            f"hospitalized Nordic AUD: all-cause MRR x{HOSPITALIZED_NORDIC_AUD_MRR_RANGE[0]:.1f}-x{HOSPITALIZED_NORDIC_AUD_MRR_RANGE[1]:.1f}; "
            f"life expectancy {HOSPITALIZED_NORDIC_AUD_LE_LOSS_RANGE[0]:.0f}-{HOSPITALIZED_NORDIC_AUD_LE_LOSS_RANGE[1]:.0f} years shorter",
            "  [selected severe clinical population; severity bound only]",
            "",
            "HOLDOUT READOUT",
            "- Wood-smooth rises much faster above ~52 g/day than the Wang male all-cause",
            "  dose-response. Because their references differ, this is not a formal failure",
            "  test, but it is a strong warning against treating Wood-smooth as a literal RR.",
            "- Cause-specific alcohol risks can be far larger than all-cause RR; cirrhosis",
            "  mortality is one example. This supports moving toward cause-specific hazards",
            "  rather than searching for one universal high-dose multiplier.",
        ]
    )

    lines.extend(
        [
            "",
            "CURRENT MODEL DIAGNOSTICS",
            f"reference remaining LE at {start_age}: {ref.remaining_life_expectancy:.2f} years",
            f"Wood highest-group modeled loss: {wood_high_loss:.2f} years (target ~4-5 years)",
            f"BOOZEHOUND-WINO {wino_daily:.1f} g/day ({wino_weekly:.0f} g/week) legacy modeled loss: {wino_loss:.2f} years",
            f"BOOZEHOUND-WINO candidate extrapolation: target x{candidate_wino_rr:.3f}; modeled loss {candidate_wino_loss:.2f} years [LOW CONFIDENCE]",
        ]
    )
    for weight_model in mr.CAUSE_HAZARD_WEIGHT_MODELS:
        if weight_model in prototype_wino_losses:
            lines.append(
                f"BOOZEHOUND-WINO cause-hazard {weight_model} loss vs its 56 g/week ref: {prototype_wino_losses[weight_model]:.2f} years [UNFITTED]"
            )
    lines.extend(
        [
            "",
            "BOOZEHOUND-WINO 71 g/day SENSITIVITY (conditional on alive at age 40)",
            "metric                     legacy       Wood-smooth candidate",
            "------------------------  -----------  ---------------------",
            f"remaining LE at 40        {wino.remaining_life_expectancy:9.2f} y  {candidate_wino.remaining_life_expectancy:17.2f} y",
            f"loss vs 56 g/week ref     {wino_loss:9.2f} y  {candidate_wino_loss:17.2f} y",
        ]
    )
    for checkpoint in (60, 70, 80, 85, 90, 95, 100):
        lines.append(
            f"reach {checkpoint:<3}                 {wino.survival[checkpoint] * 100:9.3f}%  {candidate_wino.survival[checkpoint] * 100:17.3f}%"
        )

    for weight_model in mr.CAUSE_HAZARD_WEIGHT_MODELS:
        if weight_model not in prototype_winos or weight_model not in prototype_refs:
            continue
        prototype_wino = prototype_winos[weight_model]
        prototype_ref = prototype_refs[weight_model]
        prototype_wino_loss = prototype_wino_losses[weight_model]
        lines.extend(
            [
                "",
                f"CAUSE-HAZARD 71 g/day SENSITIVITY — {weight_model.upper()} (UNFITTED; conditional on alive at age 40)",
                f"prototype reference LE at 56 g/week: {prototype_ref.remaining_life_expectancy:.2f} y",
                f"prototype remaining LE at 71 g/day: {prototype_wino.remaining_life_expectancy:.2f} y",
                f"prototype loss vs 56 g/week ref: {prototype_wino_loss:.2f} y",
            ]
        )
        for checkpoint in (60, 70, 80, 85, 90, 95, 100):
            lines.append(f"reach {checkpoint:<3}: {prototype_wino.survival[checkpoint] * 100:8.3f}%")

    lines.extend(
        [
            "",
            "Candidate dose curve preview (target RR; >52.4 g/day is extrapolation):",
        ]
    )
    for dose in (8.0, 17.6, 29.7, 40.0, 52.4, 60.0, 71.0):
        rr = wood_smooth_candidate_rr(
            dose, sex=sex, start_age=start_age, ramp_years=ramp_years
        )
        suffix = "  [EXTRAPOLATED]" if dose > WOOD_ROWS[-1].grams_per_day else ""
        lines.append(f"  {dose:4.1f} g/day -> x{rr:.3f}{suffix}")

    lines.extend(
        [
            "",
            "Candidate calibration knots (diagnostic effective RRs, NOT published alcohol RRs):",
        ]
    )
    for (dose, rr), row in zip(candidate_knots, WOOD_ROWS):
        lines.append(
            f"  {row.grams_per_week:3.0f} g/week ({dose:4.1f} g/day) -> x{rr:.3f}"
        )

    lines.extend(
        [
            "",
            "Single-RR diagnostic only (NOT proposed alcohol RRs):",
        ]
    )

    for loss_target in (4.0, 4.5, 5.0):
        rr = required_uniform_target_rr(
            sex=sex,
            start_age=start_age,
            target_years_lost=loss_target,
            ramp_years=ramp_years,
        )
        lines.append(
            f"  target {loss_target:.1f} y LE loss -> uniform post-ramp hazard target about x{rr:.3f}"
        )

    lines.extend(
        [
            "",
            "INTERPRETATION",
            "- The legacy model is flat at RR=1.0 below 45 g/day, so it predicts no",
            "  lifespan difference for the Wood 123 and 208 g/week mean-intake groups.",
            "- At 367 g/week (~52.4 g/day), the current male target is x1.15 and the",
            "  modeled lifespan penalty is substantially below Wood's ~4-5 year estimate.",
            "- The Wood-smooth candidate is deliberately calibrated to the midpoint of each",
            "  Wood lifespan-loss band. Its RR knots are architecture-specific diagnostics, not",
            "  published causal alcohol RRs and not yet suitable for gameplay.",
            "- The 71 g/day boozehound value lies above Wood's highest observed group mean;",
            "  the candidate result there is extrapolation and is explicitly low-confidence.",
            "- The independent Wang holdout is not an apples-to-apples reference match, but",
            "  its much shallower male all-cause curve is a warning that the Wood-effective",
            "  extrapolation should not be promoted to a literal epidemiological RR.",
            "- The cause-hazard Wood panels are unfitted diagnostics. proxy-v1 preserves dev2;",
            "  evidence-v1 applies raw Carr 2024 to the directly alcohol-coded broad hazard;",
            "  evidence-v2-popnorm divides that direct-alcohol multiplier by a provisional Finnish",
            "  population mean-dose Carr anchor; evidence-v3-popdist instead divides by a WHO-style",
            "  sex-specific Gamma population E[RR(D)] with abstainers represented separately;",
            "  evidence-v4-cancer adds Dai 2026 cancer subhazards in gameplay (the standalone",
            "  calibration harness does not attach the 11be neoplasm detail resolver).",
            "  Other heterogeneous broad groups remain proxies.",
            "- The diagnostic RR values above show how strong a *single-RR* architecture",
            "  would need to be to mimic the benchmark; they are not epidemiological estimates.",
            "- The Finnish population table already contains real-world alcohol exposure. evidence-v3-popdist",
            "  is the first model here to use an explicit exposure distribution for the direct alcohol bucket,",
            "  but cause mapping, age-specific exposure distributions, former-drinker effects and confounding remain unsolved.",
            "- Wood's benchmark is pooled high-income current-drinker evidence, not a Finnish",
            "  male-specific dose-response curve. Use it as a calibration anchor, not gospel.",
            "",
            "Sources:",
            "  Wood AM et al. Lancet 2018;391:1513-1523. doi:10.1016/S0140-6736(18)30134-X",
            "  Zhao J et al. JAMA Netw Open 2023;6:e236185. doi:10.1001/jamanetworkopen.2023.6185",
            "  Wang C et al. J Womens Health 2014;23:373-381. doi:10.1089/jwh.2013.4414",
            "  Llamosas-Falcón L et al. Hepatol Int 2024;18:216-224. doi:10.1007/s12072-023-10584-z",
            "  Westman J et al. Acta Psychiatr Scand 2015;131:297-306. PMID:25243359",
            "  Carr T et al. Addiction 2024;119:1174-1187. doi:10.1111/add.16456",
            "  Kehoe T et al. Popul Health Metr 2012;10:6. doi:10.1186/1478-7954-10-6",
            "  WHO alcohol exposure methodology: Gamma current-drinker distribution capped at 150 g/day",
            "  THL Drinking Habits Survey 2023: Finnish abstainer prevalence inputs",
            "  OECD Preventing Harmful Alcohol Use — Finland country note 2025 (sex-specific APC anchors)",
            "  WHO GISAH Canada 2020 total alcohol per-capita consumption (Canada popnorm fallback anchor)",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Mortality Roulette's legacy alcohol hazard model against lifespan benchmarks."
    )
    parser.add_argument("--sex", type=_normalise_sex, default="male", help="m/male or f/female (default: male)")
    parser.add_argument("--start-age", type=int, default=40, help="calibration start age (default: 40)")
    parser.add_argument(
        "--ramp-years",
        type=float,
        default=float(mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS),
        help=f"legacy RR ramp duration (default: {mr.BOOZEHOUND_ALL_CAUSE_RAMP_YEARS:g})",
    )
    parser.add_argument(
        "--prototype-cause-cache",
        type=Path,
        default=None,
        help="existing StatFin 11az cache used for the unfitted cause-hazard panel (default: main program cache)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.start_age < 0:
        raise SystemExit("--start-age must be non-negative")
    if args.ramp_years < 0:
        raise SystemExit("--ramp-years must be non-negative")
    print(build_report(sex=args.sex, start_age=args.start_age, ramp_years=args.ramp_years, prototype_cause_cache=args.prototype_cause_cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
