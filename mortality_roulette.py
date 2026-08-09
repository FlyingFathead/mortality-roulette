#!/usr/bin/env python3
"""
mortality_roulette.py

A Finland/Canada life-table "mortality roulette" toy.

Country selection:
    default / --country fi   Finland
    --country ca / --canada Canada

For Finnish present-day mode, exact-age qx values through age 99 come from
the bundled official Statistics Finland 12ap 2024 snapshot. Age 100 is the
terminal/open interval in that source table, so age 100+ uses a clearly labelled
sex-specific model tail. Canadian mode uses bundled Statistics Canada table
13-10-0837-01 snapshots where available and retains the downloader/cache path.
At each age x, q[x] means:

    P(die before age x+1 | alive at exact age x)

Beyond the last exact-age qx available in the active period table, the script
uses an explicitly labelled tail approximation. Finland begins that model at age
100 from a sex-specific centenarian anchor and then uses the historical +2.5
percentage-point progression with a nominal 50% ceiling. Other sources continue
from their last published exact-age qx and are never forced downward by that
nominal ceiling. The tail is NOT an observed life-table estimate.

Random sex selection uses an approximate sex ratio at birth:
51.2% male / 48.8% female. Change MALE_BIRTH_SHARE if desired.

Residential long-term-care statistics are a separate Finnish register-study
benchmark for 2014–2018, conditional on reaching age 65. They are used to
calculate expected care use in batch mode; care placement itself is NOT
randomly simulated year by year.

Optional cohort mode:

    --birth-year YEAR

uses the mortality probability for calendar year (YEAR + age) rather than
reusing one modern period life table for the entire simulated lifetime.

Data backends:
- Human Mortality Database (HMD) Finland 1x1 period life-table files, if
  supplied locally, cover 1878–2024.
- Otherwise the script can download/cache Statistics Finland's open 12ap
  life table, which supplies age/sex qx for 1986–2024.

For calendar years after the newest observed year, cohort mode holds the
newest observed age-specific mortality schedule constant. It does NOT invent
future mortality improvements.

Cause-of-death mode is ON by default for normal single-run roulette. Use
--no-causes to suppress it. --causes remains accepted explicitly.

After death occurs, Finland uses StatFin
11az plus 11be/11b2/11bx. Canada derives a mutually exclusive standard ICD-10
chapter roll and complete-code detail from Canada's civil-registration data
submitted to the WHO Mortality Database, conditional on sex, age group and
calendar year.

Seasonal timing is ON by default for normal single-run roulette. Use
--no-seasonality to suppress it. --seasonality / --death-month remain accepted.

The timing layer rolls a death month only after death and the broad underlying cause have
already been determined. Finland uses StatFin 11bf (broad cause + sex + year,
not age). Canada uses Statistics Canada 13-10-0708-01, which is an all-cause
monthly distribution for the selected Canadian geography (national or province)
and therefore is not conditioned on cause, sex or age. Neither timing layer feeds
back into annual qx or cause selection.

Batch mode defaults to a mathematically equivalent inverse-CDF death-age
sampler rather than replaying every annual roll. Use --batch-engine step to
retain the literal year-by-year Monte Carlo engine for validation.
"""

from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import json
import io
import math
import os
import random
import re
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from itertools import product
from pathlib import Path

from mortality_roulette_core.terminal import (
    terminal_display_width as _terminal_display_width,
    terminal_emphasis as _terminal_emphasis,
    terminal_pad as _terminal_pad,
    terminal_rule as _terminal_rule,
    terminal_truncate as _terminal_truncate,
    terminal_wrap as _terminal_wrap,
)

VERSION = "0.13.0-dev16"
__version__ = VERSION

PROJECT_ROOT = Path(__file__).resolve().parent
DATASETS_ROOT = PROJECT_ROOT / "datasets"
BUNDLED_STATFIN_LIFE_TABLE = DATASETS_ROOT / "finland" / "mortality" / "statfin_12ap_2024.json"
BUNDLED_STATFIN_CAUSES = DATASETS_ROOT / "finland" / "causes" / "statfin_11az_through_2024.json"
BUNDLED_STATFIN_DETAIL = DATASETS_ROOT / "finland" / "causes" / "statfin_cause_detail_2024.json"
BUNDLED_STATFIN_SEASONAL = DATASETS_ROOT / "finland" / "seasonality" / "statfin_11bf_through_2024.json"
BUNDLED_STATCAN_LIFE_TABLE = DATASETS_ROOT / "canada" / "mortality" / "statcan_13100837_2024.json"
BUNDLED_STATCAN_LIFE_TABLE_BC = DATASETS_ROOT / "canada" / "mortality" / "statcan_13100837_2024_bc.json"
BUNDLED_STATCAN_SEASONAL = DATASETS_ROOT / "canada" / "seasonality" / "statcan_13100708_2024.json"
BUNDLED_STATCAN_SEASONAL_BC = DATASETS_ROOT / "canada" / "seasonality" / "statcan_13100708_2024_bc.json"
BUNDLED_WHO_ICD_TITLES = DATASETS_ROOT / "who" / "icd10" / "who_icd10_titles_2019.json"

MALE_BIRTH_SHARE = 0.512
TAIL_CAP = 0.50
TAIL_STEP = 0.025

# Finland 12ap publishes exact one-year qx only through age 99; age 100 is
# the terminal/open age in the published table.  The prototype's sex-specific
# centenarian values are retained ONLY as explicit age-100 tail anchors.  They
# are modeled values, not StatFin observations.  In particular, the male
# q100=0.397 anchor plus the historical +2.5 percentage-point tail reproduces
# the published age-100 remaining-life-expectancy target (~1.85 y) to rounding.
# The full prototype schedules remain separately opt-in via --legacy-mortality.
FINLAND_TAIL_Q100 = {
    "male": 0.397,
    "female": 0.366,
}

# Present-day mortality-model selection.  "official" is the literal published
# single-age qx table.  "smoothed" is a deterministic age-graduated derivative
# of that same official table, intended to suppress single-calendar-year
# sawtooth noise in simulation.  "legacy" preserves the original baked
# Mortality Roulette schedule for historical comparison/reproducibility.
MORTALITY_MODELS = ("smoothed", "official", "legacy")
DEFAULT_MORTALITY_MODEL = "smoothed"
ACTIVE_MORTALITY_MODEL = DEFAULT_MORTALITY_MODEL

# Age-graduation recipe (dependency-free and deliberately transparent):
#   1. transform qx to annual hazard h=-ln(1-q),
#   2. leave age 0 untouched,
#   3. ages 1+ receive a centered five-age triangular hazard smoother
#      with weights 1,2,3,2,1 (truncated/renormalized at boundaries),
#   4. from exact age 30 onward, apply nondecreasing isotonic regression
#      (PAVA) to the smoothed hazard sequence.
# Raw official qx always remain selectable and are never overwritten.
AGE_GRADUATION_MONOTONIC_FROM = 30
AGE_GRADUATION_WEIGHTS = (1.0, 2.0, 3.0, 2.0, 1.0)
_AGE_GRADUATED_Q_CACHE: dict[tuple[int, str, int, int], dict[int, float]] = {}

# Terminal chatter from data/cache/network backends.
#   0 = errors only (no normal [data] lines)
#   1 = major preflight/backend milestones
#   2 = full cache paths, URLs, archive inspection and download progress
# Errors that abort or materially disable a requested feature are still printed
# independently of this setting. Keep 2 as the development/default level.
DATA_VERBOSITY = 2

# Human-readable WHO ICD-10 terminology for complete cause codes.
# The companion file uses WHO ICD-10 2019 as its base terminology and includes
# subsequent WHO emergency-use COVID-19 updates (U08-U12).
# True  = load the companion who_icd10_titles_2019.json and append titles
#         to both Canadian WHO details and Finnish WHO deep refinements.
# False = preserve raw-code-only behaviour (apart from legacy built-in fallbacks).
USE_ICD_TITLES = True
ICD_TITLES_FILENAME = "who_icd10_titles_2019.json"
DEFAULT_ICD_TITLES_PATH = BUNDLED_WHO_ICD_TITLES
LEGACY_ICD_TITLES_PATH = PROJECT_ROOT / ICD_TITLES_FILENAME
FALLBACK_ICD_TITLES_PATH = (
    Path.home() / ".cache" / "mortality_roulette" / ICD_TITLES_FILENAME
)
_ICD_TITLE_LOOKUP: dict[str, str] | None = None
_ICD_TITLES_SOURCE_PATH: Path | None = None

# Optional heavy-drinking scenarios. These are isolated from generic mode.
#
# --boozehound      = 60 g pure ethanol/day from age 18.
# --boozehound-wino = one 750 mL bottle of 12% ABV wine/day. Using ethanol
#                     density 0.789 g/mL, that is about 71.0 g ethanol/day.
#
# All-cause mortality targets come from Zhao et al., JAMA Network Open 2023
# (doi:10.1001/jamanetworkopen.2023.6185), sex-specific categories versus
# lifetime nondrinkers:
#   men:   45-64 g/day RR 1.15; >=65 g/day RR 1.34
#   women: 45-64 g/day RR 1.34; >=65 g/day RR 1.61
#
# v0.11.21+ applies those relative risks on the annual *mortality hazard* rather
# than multiplying qx directly. Repeated yearly hazards automatically compound
# into a cumulative survival penalty; the RR does NOT need to grow without
# bound merely because lifetime kilograms increase. The exposure summary now
# reports this cumulative survival/hazard effect explicitly.
BOOZEHOUND_GRAMS_PER_DAY = 60.0
BOOZEHOUND_WINO_BOTTLE_ML = 750.0
BOOZEHOUND_WINO_ABV = 0.12
ETHANOL_DENSITY_G_PER_ML = 0.789
BOOZEHOUND_WINO_GRAMS_PER_DAY = (
    BOOZEHOUND_WINO_BOTTLE_ML * BOOZEHOUND_WINO_ABV * ETHANOL_DENSITY_G_PER_ML
)

# Human-readable cumulative beverage equivalents used in the final exposure
# summary. These convert the same amount of pure ethanol into familiar package
# sizes; they are NOT additional consumption and do not affect risk.
BOOZEHOUND_EQ_VODKA_BOTTLE_ML = 700.0
BOOZEHOUND_EQ_VODKA_ABV = 0.40
BOOZEHOUND_START_AGE = 18
ACTIVE_BOOZEHOUND_START_AGE = BOOZEHOUND_START_AGE
ACTIVE_BOOZEHOUND_END_AGE: int | None = None
BOOZEHOUND_ALL_CAUSE_RR_45_64 = {"male": 1.15, "female": 1.34}
BOOZEHOUND_ALL_CAUSE_RR_65_PLUS = {"male": 1.34, "female": 1.61}

# Published alcohol RRs generally describe established habitual exposure, not
# the first weeks after somebody starts drinking. We therefore interpolate from
# RR=1 to the chronic-drinker RR on the log-RR scale. The latency profiles are
# transparent scenario assumptions used only inside boozehound modes; they are
# NOT claimed to be measured disease-incidence curves.
BOOZEHOUND_ALL_CAUSE_RAMP_YEARS = 10.0
BOOZEHOUND_LATENCY_PROFILES = {
    # name: (lag years before excess risk begins, years from onset to full RR)
    "acute": (0.0, 0.0),
    "direct_chronic": (1.0, 4.0),
    "vascular": (0.0, 5.0),
    "liver": (2.0, 8.0),
    "pancreas": (2.0, 8.0),
    "cancer": (10.0, 10.0),
    "neuro": (5.0, 10.0),
    "dementia": (15.0, 10.0),
    "chronic": (0.0, 10.0),
}
ACTIVE_BOOZEHOUND = False
ACTIVE_BOOZEHOUND_PRESET: str | None = None
ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 0.0

# Alcohol mortality engine selection. Keep the default in one obvious place so
# a future validated engine can graduate without hunting through argparse or
# simulation code for a second hard-coded default.
ALCOHOL_MODELS = ("legacy", "cause-hazard-prototype")
DEFAULT_ALCOHOL_MODEL = "legacy"
ACTIVE_ALCOHOL_MODEL = DEFAULT_ALCOHOL_MODEL

# Cause-hazard broad-weight model selection. proxy-v1 is the exact dev1/dev2
# architecture-sensitivity model. evidence-v1 is deliberately incremental: it
# replaces only the directly alcohol-coded StatFin broad hazard with a published
# dose-response curve (Carr et al., Addiction 2024) and leaves the remaining
# broad groups on the existing transparent proxies until compatible evidence is
# mapped to those heterogeneous StatFin buckets.
CAUSE_HAZARD_WEIGHT_MODELS = (
    "proxy-v1",
    "evidence-v1",
    "evidence-v2-popnorm",
    "evidence-v3-popdist",
    "evidence-v4-cancer",
)
DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL = "proxy-v1"
ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL

# Carr et al. 2024, systematic review/meta-analysis of alcohol consumption and
# mortality due to AUD / alcohol poisoning. Outcome definitions included acute
# and chronic 100%-alcohol-attributable causes; the StatFin 41 broad group is a
# close (not perfectly identical) match. Values are RR versus current non-drinkers.
# These are used only by the opt-in evidence-v1 experimental cause-hazard model.
CARR_2024_AUD_MORTALITY_RR = (
    (0.0, 1.00),
    (20.0, 1.99),
    (40.0, 3.94),
    (60.0, 7.82),
    (80.0, 15.52),
    (100.0, 30.81),
)

# Dai et al., Nature Health 2026 (GBD 2023 Burden of Proof), Table 3.
# Mean relative risks versus no alcohol at one-standard-drink (10 g/day)
# intervals. evidence-v4-cancer normalizes these disease-specific RRs by the
# same WHO-style country/sex population exposure distribution used by
# evidence-v3-popdist, then applies the existing cancer latency ramp.
#
# The published table reports through 100 g/day.  v4 therefore holds the RR
# flat above 100 g/day rather than inventing a high-dose extrapolation.
NATURE_2026_CANCER_RR: dict[str, tuple[tuple[float, float], ...]] = {
    "breast": ((0.0, 1.00), (10.0, 1.13), (20.0, 1.25), (30.0, 1.33), (40.0, 1.40), (50.0, 1.44), (60.0, 1.46), (70.0, 1.47), (80.0, 1.48), (90.0, 1.49), (100.0, 1.49)),
    "colorectal": ((0.0, 1.00), (10.0, 1.17), (20.0, 1.28), (30.0, 1.35), (40.0, 1.41), (50.0, 1.46), (60.0, 1.50), (70.0, 1.53), (80.0, 1.56), (90.0, 1.57), (100.0, 1.57)),
    "oesophageal": ((0.0, 1.00), (10.0, 1.32), (20.0, 1.74), (30.0, 2.26), (40.0, 2.79), (50.0, 3.28), (60.0, 3.73), (70.0, 4.14), (80.0, 4.51), (90.0, 4.83), (100.0, 5.11)),
    "laryngeal": ((0.0, 1.00), (10.0, 1.23), (20.0, 1.48), (30.0, 1.74), (40.0, 2.02), (50.0, 2.31), (60.0, 2.61), (70.0, 2.92), (80.0, 3.20), (90.0, 3.44), (100.0, 3.64)),
    "lip_oral": ((0.0, 1.00), (10.0, 1.03), (20.0, 1.11), (30.0, 1.26), (40.0, 1.46), (50.0, 1.73), (60.0, 2.05), (70.0, 2.43), (80.0, 2.83), (90.0, 3.24), (100.0, 3.68)),
    "liver": ((0.0, 1.00), (10.0, 1.02), (20.0, 1.07), (30.0, 1.17), (40.0, 1.30), (50.0, 1.48), (60.0, 1.71), (70.0, 1.98), (80.0, 2.24), (90.0, 2.46), (100.0, 2.64)),
    "pancreatic": ((0.0, 1.00), (10.0, 1.05), (20.0, 1.10), (30.0, 1.13), (40.0, 1.16), (50.0, 1.18), (60.0, 1.19), (70.0, 1.20), (80.0, 1.20), (90.0, 1.21), (100.0, 1.21)),
    "pharyngeal": ((0.0, 1.00), (10.0, 1.16), (20.0, 1.56), (30.0, 2.16), (40.0, 2.73), (50.0, 3.23), (60.0, 3.67), (70.0, 4.04), (80.0, 4.35), (90.0, 4.58), (100.0, 4.75)),
    "prostate": ((0.0, 1.00), (10.0, 1.04), (20.0, 1.08), (30.0, 1.10), (40.0, 1.11), (50.0, 1.13), (60.0, 1.14), (70.0, 1.16), (80.0, 1.17), (90.0, 1.18), (100.0, 1.19)),
    "stomach": ((0.0, 1.00), (10.0, 1.03), (20.0, 1.06), (30.0, 1.09), (40.0, 1.12), (50.0, 1.15), (60.0, 1.17), (70.0, 1.19), (80.0, 1.21), (90.0, 1.21), (100.0, 1.22)),
}
NATURE_2026_CANCER_RR_CAP_G_DAY = 100.0
_NATURE_2026_CANCER_POPDIST_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, float | str]]] = {}

# v0.13.0-dev4 first-order population normalization anchors.  These are
# annual litres of pure alcohol per person aged 15+ converted to an average
# g/day exposure before evaluating the Carr curve.  Finland has sex-specific
# OECD 2025 country-note estimates; Canada currently uses the WHO 2020 total
# population APC for both sexes because a matching sex-specific figure is not
# bundled.  This is deliberately a *mean-dose* normalization, not E[RR(D)] over
# the full drinking distribution, and is labelled provisional everywhere.
ALCOHOL_POPULATION_APC_LITRES = {
    "fi": {
        "male": (16.8, "OECD 2025 Finland country note, male APC"),
        "female": (5.1, "OECD 2025 Finland country note, female APC"),
    },
    "ca": {
        "male": (10.09, "WHO GISAH 2020 Canada total APC; sex-neutral fallback"),
        "female": (10.09, "WHO GISAH 2020 Canada total APC; sex-neutral fallback"),
    },
}

# v0.13.0-dev8 distribution-based normalization inputs.  evidence-v3-popdist
# follows the established WHO/Rehm/Kehoe burden-of-disease exposure model:
# current drinkers are represented by a sex-specific Gamma distribution, with
# sigma inferred from the drinker mean (men 1.171*mu; women 1.258*mu), and the
# drinker distribution is normalized over 0..150 g/day.  WHO burden modelling
# uses 80% of APC when constructing the exposure distribution to account for
# alcohol not consumed / epidemiological undercoverage.  Abstainers remain a
# separate point mass at 0 g/day.
#
# Finland abstainer shares come from THL's 2023 Drinking Habits Survey
# (20-69-year-olds: men 10%, women 12%).  Canada's 2023 CCHS reported 77% of
# adults in the provinces drank in the past 12 months; until a matching
# sex-specific national series is bundled, both sexes explicitly use the 23%
# sex-neutral fallback.  These age/geography mismatches are printed in model
# diagnostics instead of being hidden.
ALCOHOL_POPULATION_ABSTAINER_SHARE = {
    "fi": {
        "male": (0.10, "THL Drinking Habits Survey 2023, men 20-69"),
        "female": (0.12, "THL Drinking Habits Survey 2023, women 20-69"),
    },
    "ca": {
        "male": (0.23, "Statistics Canada CCHS 2023, adults in provinces; sex-neutral fallback"),
        "female": (0.23, "Statistics Canada CCHS 2023, adults in provinces; sex-neutral fallback"),
    },
}

ALCOHOL_GAMMA_SD_PER_MEAN = {"male": 1.171, "female": 1.258}
ALCOHOL_GAMMA_APC_CONSUMED_FRACTION = 0.80
ALCOHOL_GAMMA_MAX_G_DAY = 150.0
ALCOHOL_CARR_POPDIST_RR_CAP_G_DAY = 100.0
ALCOHOL_GAMMA_INTEGRATION_BINS = 3000
_ALCOHOL_POPDIST_CACHE: dict[tuple[str, str], tuple[float, dict[str, float | str]]] = {}

# Batch cause-assignment engine. fast-grouped preserves the same broad conditional
# distributions but resolves each sex/age/year cell once and samples it in bulk.
# reference-slow retains the original one-death-at-a-time implementation for A/B
# validation and for features that require individual cause outcome objects.
CAUSE_BATCH_SAMPLERS = ("fast-grouped", "reference-slow")
DEFAULT_CAUSE_BATCH_SAMPLER = "fast-grouped"


# Once preflight finishes, ordinary [data] chatter is suppressed so cache/network
# messages never interrupt the actual roulette transcript. Fatal errors still use
# normal stderr paths and remain visible.
DATA_PREFLIGHT_COMPLETE = False

# Country mode. Finland remains the default for backward compatibility.
# --canada is shorthand for --country ca.
ACTIVE_COUNTRY = "fi"
ACTIVE_PERIOD_SOURCE: "CohortMortalitySource | None" = None
# Backward-compatible mirror for older internal/tests/CLI paths. The canonical
# selector is ACTIVE_MORTALITY_MODEL; legacy is true iff that model is selected.
ACTIVE_LEGACY_MORTALITY = False
# Canadian subnational selector used by the active contestant/run.  None means
# national Canada.  Cause-of-death roulette remains national until a suitable
# province+age+sex+ICD backend is wired in.
ACTIVE_CANADA_PROVINCE: str | None = None

COUNTRY_DISPLAY = {
    "fi": ("🇫🇮", "Finland"),
    "ca": ("🇨🇦", "Canada"),
}

# Statistics Canada 13-10-0837 publishes single-year complete life tables for
# Canada and these provinces.  Prince Edward Island is a province too, but its
# population is too small for this single-year table; StatCan publishes a
# three-year abridged table instead (13-10-0140), which is deliberately not
# silently mixed into the exact-age engine yet.
CANADA_PROVINCES: dict[str, dict[str, object]] = {
    "nl": {"name": "Newfoundland and Labrador", "single_year": True},
    "pe": {"name": "Prince Edward Island", "single_year": False},
    "ns": {"name": "Nova Scotia", "single_year": True},
    "nb": {"name": "New Brunswick", "single_year": True},
    "qc": {"name": "Quebec", "single_year": True},
    "on": {"name": "Ontario", "single_year": True},
    "mb": {"name": "Manitoba", "single_year": True},
    "sk": {"name": "Saskatchewan", "single_year": True},
    "ab": {"name": "Alberta", "single_year": True},
    "bc": {"name": "British Columbia", "single_year": True},
}

def _normalize_region_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


CANADA_PROVINCE_ALIASES: dict[str, str | None] = {
    "canada": None, "national": None, "none": None,
}
for _province_code, _province_meta in CANADA_PROVINCES.items():
    CANADA_PROVINCE_ALIASES[_normalize_region_token(_province_code)] = _province_code
    CANADA_PROVINCE_ALIASES[_normalize_region_token(str(_province_meta["name"]))] = _province_code
# Common province-name variants.
CANADA_PROVINCE_ALIASES.update({
    "newfoundland": "nl",
    "newfoundlandlabrador": "nl",
    "pei": "pe",
    "quebec": "qc",
})


def normalize_canada_province(value: str) -> str | None:
    token = _normalize_region_token(value)
    if token not in CANADA_PROVINCE_ALIASES:
        allowed = ", ".join(CANADA_PROVINCES)
        raise ValueError(
            f"unknown Canadian province {value!r}; use a postal code ({allowed}) or a province name"
        )
    key = CANADA_PROVINCE_ALIASES[token]
    if key is not None and not bool(CANADA_PROVINCES[key]["single_year"]):
        raise ValueError(
            "Prince Edward Island is not available in Statistics Canada 13-10-0837 single-year complete life tables; "
            "StatCan uses the three-year abridged table 13-10-0140 for PEI, which this exact-age engine does not mix in yet"
        )
    return key


def canada_province_name(province: str | None) -> str | None:
    if province is None:
        return None
    meta = CANADA_PROVINCES.get(province)
    return str(meta["name"]) if meta else province


def statcan_geography_name(province: str | None) -> str:
    return canada_province_name(province) or "Canada"


def _regional_cache_path(base: Path, province: str | None) -> Path:
    if province is None:
        return base
    return base.with_name(f"{base.stem}_{province}{base.suffix}")


def resolve_canada_province_assignments(
    countries: list[str] | None,
    raw_values: list[str] | None,
) -> tuple[str | None, list[str | None]]:
    """Resolve --ca-province for single-country or two-player deathmatch mode.

    Returns (single_run_province, deathmatch_parallel_provinces).  In a Canada
    vs Canada match one province value applies to both players; two values map
    left-to-right.  The special value ``national`` selects national Canada.
    """
    raw = list(raw_values or [])
    normalized: list[str | None] = [normalize_canada_province(v) for v in raw]

    if not countries:
        if len(normalized) > 1:
            raise ValueError("--ca-province accepts one province in ordinary single-country mode")
        return (normalized[0] if normalized else None), []

    canada_slots = [idx for idx, code in enumerate(countries) if code == "ca"]
    if not canada_slots:
        if normalized:
            raise ValueError("--ca-province was supplied but this deathmatch has no Canadian contestant")
        return None, [None for _ in countries]

    assignments: list[str | None] = [None for _ in countries]
    if not normalized:
        return None, assignments
    if len(normalized) == 1:
        for idx in canada_slots:
            assignments[idx] = normalized[0]
        return None, assignments
    if len(normalized) == len(canada_slots):
        for idx, province in zip(canada_slots, normalized):
            assignments[idx] = province
        return None, assignments
    raise ValueError(
        f"--ca-province received {len(normalized)} values for {len(canada_slots)} Canadian contestant(s); "
        "use one value for all Canadian players or one value per Canadian player"
    )


def deathmatch_contestant_label(
    country_code: str,
    sex: str,
    *,
    province: str | None = None,
    player_number: int | None = None,
) -> str:
    """Universal deathmatch label: flag + uppercase country/region + optional player tag."""
    flag, name = COUNTRY_DISPLAY.get(country_code, ("🏳️", country_code.upper()))
    label = f"{flag} {name.upper()}"
    if country_code == "ca" and province is not None:
        region_name = canada_province_name(province) or province
        label += f" ({region_name.upper()})"
    if player_number is not None:
        label += f" (PLAYER {player_number})"
    return label


def country_flag(country_code: str | None = None) -> str:
    """UTF-8 country flag for the active mortality-data backend."""
    code = ACTIVE_COUNTRY if country_code is None else country_code
    flag, _name = COUNTRY_DISPLAY.get(code, ("🏳️", code.upper()))
    return flag


def country_display_label(
    country_code: str | None = None,
    *,
    province: str | None = None,
) -> str:
    """UTF-8 flag + country name, with Canadian province when selected."""
    code = ACTIVE_COUNTRY if country_code is None else country_code
    if country_code is None and code == "ca" and province is None:
        province = ACTIVE_CANADA_PROVINCE
    flag, name = COUNTRY_DISPLAY.get(code, ("🏳️", code.upper()))
    label = f"{flag} {name}"
    if code == "ca" and province is not None:
        label += f" ({canada_province_name(province) or province})"
    return label


def _print_startup_banner() -> None:
    """Print the versioned startup banner across the current terminal width."""
    line = _terminal_rule()
    print(line, flush=True)
    print(f"Mortality Roulette v{VERSION} starting...", flush=True)
    print(line, flush=True)


def _deathmatch_tapout_banner(
    country_code: str,
    sex: str,
    age: int,
    *,
    province: str | None = None,
    player_number: int | None = None,
) -> str:
    label = deathmatch_contestant_label(
        country_code, sex, province=province, player_number=player_number
    )
    return f"*** {label} TAPPED OUT AT AGE {age} !!! ***"


def _print_deathmatch_tapout(
    country_code: str,
    sex: str,
    age: int,
    *,
    blink: bool,
    province: str | None = None,
    player_number: int | None = None,
) -> None:
    banner = _deathmatch_tapout_banner(
        country_code, sex, age, province=province, player_number=player_number
    )
    print(_terminal_emphasis(banner, bold=True, blink=blink), flush=True)


def _deathmatch_live_tapout_row(
    newly_dead: list[int],
    *,
    countries: list[str],
    provinces: list[str | None],
    player_numbers: list[int | None],
    states: list[dict[str, object]],
    sex: str,
    column_width: int,
    blink: bool = True,
) -> str:
    """Render live tap-out announcements in the contestant's own arena column."""
    cells = ["", ""]
    for idx in newly_dead:
        banner = _deathmatch_tapout_banner(
            countries[idx],
            sex,
            int(states[idx]["death_age"]),
            province=provinces[idx],
            player_number=player_numbers[idx],
        )
        # Pad before styling so ANSI escape sequences never affect grid geometry.
        cells[idx] = _terminal_emphasis(
            _terminal_pad(banner, column_width), bold=True, blink=blink
        )
    left = cells[0] if cells[0] else " " * column_width
    right = cells[1]
    return f"{left} │ {right}"


def print_country_section_heading(title: str) -> None:
    """Print a UTF-8 country-tagged heading with a matching-width underline."""
    heading = f"{country_flag()} {title}"
    print(heading)
    print("-" * _terminal_display_width(heading))


def data_status(message: str, *, level: int = 2) -> None:
    """Emit an immediate terminal status update when verbosity permits.

    Levels intentionally mirror DATA_VERBOSITY:
      1 = major backend/preflight milestone
      2 = detailed cache/network/parser chatter
    Fatal errors are printed by their callers and are not hidden here.
    """
    if DATA_PREFLIGHT_COMPLETE:
        return
    if DATA_VERBOSITY >= level:
        print(f"[data] {message}", file=sys.stderr, flush=True)


def data_progress_enabled() -> bool:
    """Whether byte-level download progress should be painted to stderr."""
    return (not DATA_PREFLIGHT_COMPLETE) and DATA_VERBOSITY >= 2

STATCAN_LIFE_TABLE_URL = (
    "https://www150.statcan.gc.ca/n1/tbl/csv/13100837-eng.zip"
)
STATCAN_LIFE_TABLE_FIRST_YEAR = 1980
DEFAULT_STATCAN_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statcan_canada_lifetable_13100837.json"
)
DEFAULT_STATCAN_ZIP = (
    Path.home() / ".cache" / "mortality_roulette" / "statcan_13100837-eng.zip"
)

STATCAN_MONTHLY_URL = (
    "https://www150.statcan.gc.ca/n1/tbl/csv/13100708-eng.zip"
)
STATCAN_MONTHLY_FIRST_YEAR = 1991
DEFAULT_STATCAN_MONTHLY_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statcan_canada_monthly_13100708.json"
)
DEFAULT_STATCAN_MONTHLY_ZIP = (
    Path.home() / ".cache" / "mortality_roulette" / "statcan_13100708-eng.zip"
)

WHO_CANADA_COUNTRY_CODE = "2090"
WHO_CANADA_FIRST_ICD10_YEAR = 2000
WHO_CANADA_LATEST_YEAR = 2024

STATFIN_LIFE_TABLE_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/kuol/12ap.px"
)
STATFIN_FIRST_YEAR = 1986
HMD_FINLAND_FIRST_YEAR = 1878
HMD_OPEN_AGE = 110  # HMD's 110+ interval has qx=1 by construction; do not use it as an exact age.
DEFAULT_STATFIN_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statfin_finland_lifetable_qx.json"
)

STATFIN_CAUSE_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/11az.px"
)
STATFIN_CAUSE_FIRST_YEAR = 1969
DEFAULT_CAUSE_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statfin_finland_causes_11az.json"
)

STATFIN_ICD_DETAIL_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/11be.px"
)
STATFIN_EXTERNAL_DETAIL_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/11b2.px"
)
STATFIN_ALCOHOL_DETAIL_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/11bx.px"
)
DEFAULT_DETAIL_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statfin_finland_cause_detail.json"
)

# WHO Mortality Database raw ICD-10 files. Finland reports detailed mortality
# to WHO using complete ICD codes, which can preserve fourth-character (and
# occasionally deeper) detail that StatFin's public 11be table does not expose.
# This is a refinement layer only: StatFin remains authoritative for the broad
# and 3-character rolls, and WHO children are used only after an exact checksum
# against the already-selected StatFin parent count.
WHO_MORTALITY_RAW_BASE = (
    "https://cdn.who.int/media/docs/default-source/"
    "world-health-data-platform/mortality-raw-data"
)
WHO_FINLAND_COUNTRY_CODE = "4070"
DEFAULT_WHO_DETAIL_CACHE_DIR = (
    Path.home() / ".cache" / "mortality_roulette" / "who_mortality"
)

STATFIN_SEASONAL_API = (
    "https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/ksyyt/11bf.px"
)
STATFIN_SEASONAL_FIRST_YEAR = 1969
DEFAULT_SEASONAL_CACHE = (
    Path.home() / ".cache" / "mortality_roulette" / "statfin_finland_seasonality_11bf_v2.json"
)

# Mutually exclusive top-level groups from Statistics Finland's national
# time-series cause-of-death classification. These partition total deaths
# without double-counting subcategories.
BROAD_CAUSE_PREFIXES = (
    "00 ",
    "01-03 ",
    "04-22 ",
    "23-24 ",
    "25 ",
    "26 ",
    "27-30 ",
    "31-35 ",
    "36 ",
    "37 ",
    "38 ",
    "39 ",
    "40 ",
    "41 ",
    "42-53 ",
    "54 ",
)

# Validated Finnish longevity records.
# Whole-year simulation: exact day-level record breaking is not resolved.
FINNISH_RECORDS = {
    "male": {"name": "Aarne Arvonen", "years": 111, "days": 150},
    "female": {"name": "Maria Rothovius", "years": 112, "days": 259},
}

# Finnish residential long-term-care benchmark.
#
# Source:
# Korhonen K, Moustgaard H, Murphy M, Martikainen P. (2024)
# "Trends in Life Expectancy in Residential Long-Term Care by
# Sociodemographic Position in 1999–2018: A Multistate Life Table
# Study of Finnish Older Adults"
# J Gerontol B Psychol Sci Soc Sci. 79(7):gbae067.
# DOI: 10.1093/geronb/gbae067
#
# Latest period reported in the study: 2014–2018.
# These are synthetic-cohort estimates conditional on being alive at exact age 65.
#
# LTC in the study included nursing homes, health centres, hospitals,
# service housing with 24-hour assistance and rehabilitation when the stay
# lasted >=90 days or had an administrative LTC decision. Therefore this is
# broader than "permanent nursing-home placement" in the narrowest sense.
FINNISH_LTC = {
    "period": "2014–2018",
    "starting_age": 65,
    "male": {
        "ever_enter_pct": 33.8,
        "median_first_entry_age": 84.0,
        "years_in_ltc_if_entered": 2.37,
        "expected_ltc_years_at_65": 0.80,
    },
    "female": {
        "ever_enter_pct": 48.9,
        "median_first_entry_age": 86.2,
        "years_in_ltc_if_entered": 3.09,
        "expected_ltc_years_at_65": 1.51,
    },
}

# Original legacy Mortality Roulette mortality schedule.
#
# These baked arrays powered the earliest present-day Finland prototype. They
# are retained in code for historical comparison and exact reproducibility via
# --mortality-model legacy / --legacy-mortality. They are not official StatFin
# observations and are not the default model. Values are annual death
# probabilities as fractions.
MALE_Q = [
    0.0017, 0.0003, 0.0002, 0.00008, 0.00006, 0.00004, 0.00004, 0.00003, 0.00003, 0.00004,
    0.00004, 0.00005, 0.00006, 0.00008, 0.00010, 0.00020, 0.00020, 0.00030, 0.00050, 0.00060,
    0.00070, 0.00070, 0.00070, 0.00070, 0.00070, 0.00070, 0.00070, 0.00080, 0.00080, 0.00080,
    0.00080, 0.00080, 0.00090, 0.00090, 0.00090, 0.00090, 0.00100, 0.00110, 0.00110, 0.00120,
    0.00130, 0.00140, 0.00150, 0.00160, 0.00170, 0.00190, 0.00200, 0.00220, 0.00250, 0.00280,
    0.00310, 0.00340, 0.00370, 0.00400, 0.00440, 0.00480, 0.00530, 0.00590, 0.00650, 0.00710,
    0.00790, 0.00870, 0.00960, 0.01060, 0.01160, 0.01260, 0.01350, 0.01460, 0.01580, 0.01710,
    0.01860, 0.02030, 0.02210, 0.02420, 0.02660, 0.02920, 0.03230, 0.03590, 0.04000, 0.04470,
    0.05010, 0.05620, 0.06330, 0.07160, 0.08150, 0.09290, 0.10500, 0.11900, 0.13400, 0.15000,
    0.16700, 0.18600, 0.20700, 0.23000, 0.25400, 0.27700, 0.30100, 0.32500, 0.34900, 0.37300,
    0.39700,
]

FEMALE_Q = [
    0.0015, 0.0002, 0.00009, 0.00005, 0.00004, 0.00003, 0.00003, 0.00004, 0.00004, 0.00005,
    0.00005, 0.00006, 0.00007, 0.00008, 0.00009, 0.00010, 0.00010, 0.00020, 0.00020, 0.00020,
    0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00030,
    0.00030, 0.00030, 0.00030, 0.00030, 0.00030, 0.00040, 0.00040, 0.00040, 0.00050, 0.00050,
    0.00060, 0.00060, 0.00070, 0.00070, 0.00080, 0.00090, 0.00100, 0.00110, 0.00120, 0.00140,
    0.00160, 0.00170, 0.00190, 0.00200, 0.00220, 0.00240, 0.00260, 0.00280, 0.00310, 0.00340,
    0.00380, 0.00420, 0.00460, 0.00510, 0.00560, 0.00620, 0.00670, 0.00720, 0.00780, 0.00860,
    0.00950, 0.01050, 0.01160, 0.01280, 0.01430, 0.01600, 0.01800, 0.02050, 0.02350, 0.02690,
    0.03090, 0.03550, 0.04090, 0.04750, 0.05520, 0.06430, 0.07460, 0.08630, 0.09940, 0.11400,
    0.13100, 0.14800, 0.16800, 0.18800, 0.21100, 0.23500, 0.26000, 0.28600, 0.31300, 0.34000,
    0.36600,
]

assert len(MALE_Q) == 101
assert len(FEMALE_Q) == 101


def choose_sex(selection: str, rng: random.Random) -> str:
    selection = selection.lower()
    if selection == "m":
        return "male"
    if selection == "f":
        return "female"
    if selection == "r":
        return "male" if rng.random() < MALE_BIRTH_SHARE else "female"
    raise ValueError("sex must be m, f, or r")


def _pava_nondecreasing(values: list[float]) -> list[float]:
    """Return the least-squares nondecreasing fit using pooled adjacent violators.

    This is intentionally tiny and dependency-free. Equal observation weights
    are appropriate here because the goal is presentation/simulation graduation
    of already-estimated single-age qx values, not refitting the underlying
    population exposures from death/person-year counts.
    """
    if not values:
        return []
    blocks: list[list[float | int]] = []
    for idx, value in enumerate(values):
        blocks.append([idx, idx, float(value), 1])
        while len(blocks) >= 2 and float(blocks[-2][2]) > float(blocks[-1][2]):
            right = blocks.pop()
            left = blocks.pop()
            left_n = int(left[3])
            right_n = int(right[3])
            n = left_n + right_n
            mean = (float(left[2]) * left_n + float(right[2]) * right_n) / n
            blocks.append([int(left[0]), int(right[1]), mean, n])

    fitted = [0.0] * len(values)
    for start, end, mean, _n in blocks:
        for idx in range(int(start), int(end) + 1):
            fitted[idx] = float(mean)
    return fitted


def age_graduated_q_table(source: "CohortMortalitySource", sex: str) -> dict[int, float]:
    """Build the deterministic age-graduated qx table for one period source/sex.

    The raw source is never modified. Graduation uses the active source's latest
    published period year, so a refreshed/newer official table automatically
    produces a correspondingly refreshed smoothed model.
    """
    key = (id(source), sex, int(source.max_year), int(source.max_exact_age))
    cached = _AGE_GRADUATED_Q_CACHE.get(key)
    if cached is not None:
        return cached

    latest = source.data.get(sex, {}).get(source.max_year, {})
    ages = [age for age in range(source.max_exact_age + 1) if age in latest]
    if not ages:
        raise CohortDataError(f"no {sex} qx rows available for age graduation")
    if ages[0] != 0 or ages != list(range(ages[-1] + 1)):
        raise CohortDataError("age graduation requires contiguous exact-age qx beginning at age 0")

    hazards = {
        age: -math.log1p(-min(max(float(latest[age]), 0.0), 1.0 - 1e-15))
        for age in ages
    }
    smoothed_h: dict[int, float] = {0: hazards[0]}
    offsets = (-2, -1, 0, 1, 2)
    for age in ages[1:]:
        numerator = 0.0
        denominator = 0.0
        for offset, weight in zip(offsets, AGE_GRADUATION_WEIGHTS):
            neighbor = age + offset
            if neighbor < 1 or neighbor not in hazards:
                continue
            numerator += float(weight) * hazards[neighbor]
            denominator += float(weight)
        smoothed_h[age] = numerator / denominator if denominator else hazards[age]

    monotonic_start = max(AGE_GRADUATION_MONOTONIC_FROM, 1)
    adult_ages = [age for age in ages if age >= monotonic_start]
    if adult_ages:
        fitted = _pava_nondecreasing([smoothed_h[age] for age in adult_ages])
        for age, hazard in zip(adult_ages, fitted):
            smoothed_h[age] = hazard

    graduated = {
        age: min(max(1.0 - math.exp(-smoothed_h[age]), 0.0), 1.0)
        for age in ages
    }
    _AGE_GRADUATED_Q_CACHE[key] = graduated
    return graduated


def mortality_model_display_name(model: str | None = None) -> str:
    selected = ACTIVE_MORTALITY_MODEL if model is None else model
    if selected == "smoothed":
        return "AGE-GRADUATED OFFICIAL PERIOD MODEL"
    if selected == "official":
        return "OFFICIAL RAW PERIOD TABLE"
    if selected == "legacy":
        return "ORIGINAL LEGACY MORTALITY ROULETTE"
    return str(selected).upper()


def prompt_mortality_model(*, allow_legacy: bool) -> str:
    """Interactive S/O/L model selector used only when stdin is a terminal."""
    print("Choose mortality model:")
    print("  (s) age-graduated official baseline  [recommended for simulation]")
    print("  (o) official raw period table        [literal published single-age qx]")
    if allow_legacy:
        print("  (l) original legacy Mortality Roulette")
        print("      original baked schedule retained for comparison/reproducibility")
    while True:
        answer = input("Selection [s]: ").strip().lower()
        if answer in {"", "s", "smoothed"}:
            return "smoothed"
        if answer in {"o", "official"}:
            return "official"
        if allow_legacy and answer in {"l", "legacy"}:
            return "legacy"
        allowed = "s, o, or l" if allow_legacy else "s or o"
        print(f"Please enter {allowed}.")


def resolve_requested_mortality_model(args: argparse.Namespace) -> str:
    """Resolve CLI/interactive/default mortality-model selection.

    Birth-cohort mode remains literal calendar-year data and therefore always
    uses the official model unless the user explicitly asks for an unsupported
    present-day model, in which case main() reports an argument error.
    """
    if args.legacy_mortality:
        return "legacy"
    if args.mortality_model is not None:
        return str(args.mortality_model)
    if args.birth_year is not None:
        return "official"

    countries = list(args.deathmatch or [ACTIVE_COUNTRY])
    allow_legacy = bool(countries) and all(country == "fi" for country in countries)
    # Treat the process as interactive only when both ends of the prompt are
    # attached to a terminal. Test runners commonly capture stdout while
    # leaving stdin attached to the user's TTY; checking stdin alone would
    # make those subprocesses block waiting for a mortality-model answer.
    stdin_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    stdout_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if stdin_tty and stdout_tty:
        return prompt_mortality_model(allow_legacy=allow_legacy)
    return DEFAULT_MORTALITY_MODEL


def q_for_age(age: int, sex: str) -> tuple[float, bool]:
    """Return present-day period qx and whether an explicit tail was used.

    Normal operation reads the active official period source for either
    country. The old baked Finland arrays are available only through the
    explicitly opt-in original-legacy compatibility mode. Library
    callers that bypass CLI preflight lazily load the bundled default source.
    """
    global ACTIVE_PERIOD_SOURCE
    if ACTIVE_COUNTRY == "fi" and ACTIVE_MORTALITY_MODEL == "legacy":
        table = MALE_Q if sex == "male" else FEMALE_Q
        if age <= 100:
            return table[age], False
        q100 = table[100]
        return min(TAIL_CAP, q100 + TAIL_STEP * (age - 100)), True

    if ACTIVE_PERIOD_SOURCE is None:
        if ACTIVE_COUNTRY == "fi" and BUNDLED_STATFIN_LIFE_TABLE.exists():
            ACTIVE_PERIOD_SOURCE = fetch_statfin_life_table(BUNDLED_STATFIN_LIFE_TABLE, refresh=False)
        elif ACTIVE_COUNTRY == "ca" and ACTIVE_CANADA_PROVINCE is None and BUNDLED_STATCAN_LIFE_TABLE.exists():
            ACTIVE_PERIOD_SOURCE = fetch_statcan_life_table(BUNDLED_STATCAN_LIFE_TABLE, refresh=False, province=None)

    if ACTIVE_PERIOD_SOURCE is not None:
        source = ACTIVE_PERIOD_SOURCE
        latest = source.data.get(sex, {}).get(source.max_year, {})
        exact_table = (
            age_graduated_q_table(source, sex)
            if ACTIVE_MORTALITY_MODEL == "smoothed"
            else {int(a): float(q) for a, q in latest.items()}
        )
        if age <= source.max_exact_age and age in exact_table:
            return float(exact_table[age]), False
        if latest:
            base_age = max(a for a in latest if a <= source.max_exact_age)
            base_q = float(exact_table.get(base_age, latest[base_age]))

            # Statistics Finland 12ap ends with an open age-100 interval and
            # therefore has no observed q100.  Keep the established
            # sex-specific centenarian tail anchor, but label every such row as
            # modeled.  This is intentionally separate from --legacy-mortality:
            # ages 0..99 still come from the official 2024 StatFin snapshot.
            if ACTIVE_COUNTRY == "fi" and age >= 100:
                q100 = max(base_q, FINLAND_TAIL_Q100[sex])
                q = min(TAIL_CAP, q100 + TAIL_STEP * (age - 100))
                return q, True

            # Other sources continue from their last published exact-age qx.
            # Never let an extrapolated tail step *down* below that value.
            # StatCan 2024 male q109 already exceeds the historical 50% nominal
            # tail ceiling, so in that case the conservative approximation is
            # to hold the last official qx rather than manufacture a decrease.
            tail_ceiling = max(TAIL_CAP, base_q)
            q = min(tail_ceiling, base_q + TAIL_STEP * max(1, age - base_age))
            return q, True

    raise CohortDataError(
        f"no active present-day mortality source for {ACTIVE_COUNTRY!r}; data preflight was not completed"
    )



class CohortDataError(RuntimeError):
    pass


class CohortMortalitySource:
    """Age/sex/calendar-year mortality lookup for --birth-year mode."""

    def __init__(
        self,
        name: str,
        data: dict[str, dict[int, dict[int, float]]],
        min_year: int,
        max_year: int,
        max_exact_age: int,
    ) -> None:
        self.name = name
        self.data = data
        self.min_year = min_year
        self.max_year = max_year
        self.max_exact_age = max_exact_age

    def q_for(
        self,
        *,
        age: int,
        sex: str,
        calendar_year: int,
    ) -> tuple[float, str, bool]:
        """
        Return qx, source label, and whether an explicit fallback/tail was used.

        Observed years use that exact calendar year's qx.
        Future years hold the newest observed year's qx constant.
        Extreme ages not represented as exact ages use the toy tail model.
        """
        lookup_year = calendar_year
        future_hold = False

        if calendar_year > self.max_year:
            lookup_year = self.max_year
            future_hold = True
        elif calendar_year < self.min_year:
            raise CohortDataError(
                f"calendar year {calendar_year} is earlier than the available "
                f"{self.name} mortality data ({self.min_year}–{self.max_year})"
            )

        if age <= self.max_exact_age:
            q = self.data.get(sex, {}).get(lookup_year, {}).get(age)
            if q is not None:
                if future_hold:
                    return (
                        q,
                        f"future hold: {self.max_year} {self.name}",
                        True,
                    )
                return q, f"{self.name} {calendar_year}", False

        # Do not treat an open 110+ interval as an exact annual qx.
        # Fall back to the explicitly labelled extreme-age toy model.
        q, _ = q_for_age(age, sex)
        if future_hold:
            return q, f"extreme-age tail after {self.max_year} hold", True
        return q, "extreme-age tail model", True


def _metadata_variable(meta: dict, wanted_text: str) -> dict:
    wanted = wanted_text.casefold()
    for var in meta.get("variables", []):
        if str(var.get("text", "")).casefold() == wanted:
            return var
    for var in meta.get("variables", []):
        if wanted in str(var.get("text", "")).casefold():
            return var
    raise CohortDataError(f"Statistics Finland API variable not found: {wanted_text}")


def _value_code(var: dict, wanted_text: str) -> str:
    wanted = wanted_text.casefold()
    values = var.get("values", [])
    texts = var.get("valueTexts", [])
    for code, label in zip(values, texts):
        if str(label).casefold() == wanted:
            return str(code)
    for code, label in zip(values, texts):
        if wanted in str(label).casefold():
            return str(code)
    raise CohortDataError(
        f"Statistics Finland API value not found in {var.get('text')}: {wanted_text}"
    )


def _jsonstat_categories(dataset: dict, dim_id: str) -> list[str]:
    category = dataset["dimension"][dim_id]["category"]
    index = category.get("index")

    if isinstance(index, list):
        return [str(x) for x in index]

    if isinstance(index, dict):
        return [
            str(key)
            for key, _ in sorted(index.items(), key=lambda item: item[1])
        ]

    labels = category.get("label", {})
    if isinstance(labels, dict):
        return list(labels.keys())

    raise CohortDataError(f"Cannot decode JSON-stat2 category order for {dim_id}")


def _parse_statfin_jsonstat2(dataset: dict) -> dict[str, dict[int, dict[int, float]]]:
    ids = list(dataset["id"])
    sizes = list(dataset["size"])
    values = dataset["value"]

    categories = {dim_id: _jsonstat_categories(dataset, dim_id) for dim_id in ids}

    if len(values) != _product_int(sizes):
        raise CohortDataError("Unexpected Statistics Finland JSON-stat2 value count")

    # Identify dimensions by their category contents rather than hardcoding
    # Finnish/legacy PxWeb variable identifiers.
    year_dim = next(
        dim_id for dim_id in ids
        if categories[dim_id] and all(v.isdigit() and len(v) == 4 for v in categories[dim_id])
    )

    age_dim = next(
        dim_id for dim_id in ids
        if dim_id != year_dim
        and categories[dim_id]
        and all(v.isdigit() for v in categories[dim_id])
        and max(int(v) for v in categories[dim_id]) >= 90
    )

    sex_dim = next(
        dim_id for dim_id in ids
        if dim_id not in {year_dim, age_dim} and len(categories[dim_id]) == 2
    )

    result: dict[str, dict[int, dict[int, float]]] = {"male": {}, "female": {}}

    # The POST selects only males/females, all ages, all years, and one information item.
    sex_codes = categories[sex_dim]
    sex_map = {sex_codes[0]: "male", sex_codes[1]: "female"}

    # PxWeb/JSON-stat2 stores a flat row-major array in id/size order.
    dim_positions = {dim_id: pos for pos, dim_id in enumerate(ids)}

    flat = 0
    ranges = [range(size) for size in sizes]
    for coords in product(*ranges):
        value = values[flat]
        flat += 1
        if value is None:
            continue

        year_code = categories[year_dim][coords[dim_positions[year_dim]]]
        age_code = categories[age_dim][coords[dim_positions[age_dim]]]
        sex_code = categories[sex_dim][coords[dim_positions[sex_dim]]]

        sex = sex_map[sex_code]
        year = int(year_code)
        age = int(age_code)
        # StatFin 12ap terminates at age 100/open 100+; it is not a one-year
        # 100->101 interval. Keep exact annual qx only through age 99.
        if age >= 100:
            continue

        # StatFin reports qx in per mille.
        q = float(value) / 1000.0
        result.setdefault(sex, {}).setdefault(year, {})[age] = q

    return result


def _product_int(values: list[int]) -> int:
    out = 1
    for value in values:
        out *= value
    return out


def fetch_statfin_life_table(
    cache_path: Path = DEFAULT_STATFIN_CACHE,
    refresh: bool = False,
) -> CohortMortalitySource:
    """Download/cache Statistics Finland 12ap qx values for 1986–latest."""
    if cache_path.exists() and not refresh:
        data_status(f"Statistics Finland life table: using parsed cache {cache_path}")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        data = {
            sex: {
                int(year): {int(age): float(q) for age, q in ages.items() if int(age) <= 99}
                for year, ages in years.items()
            }
            for sex, years in payload["data"].items()
        }
        return CohortMortalitySource(
            name=payload["name"],
            data=data,
            min_year=int(payload["min_year"]),
            max_year=int(payload["max_year"]),
            max_exact_age=min(99, int(payload["max_exact_age"])),
        )

    data_status("Statistics Finland life table: fetching 12ap metadata...")
    try:
        request = urllib.request.Request(
            STATFIN_LIFE_TABLE_API,
            headers={"User-Agent": "mortality-roulette/0.8"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            meta = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CohortDataError(
            "Could not download Statistics Finland life-table metadata and no "
            f"usable cache exists at {cache_path}: {exc}"
        ) from exc

    year_var = _metadata_variable(meta, "Year")
    sex_var = _metadata_variable(meta, "Sex")
    age_var = _metadata_variable(meta, "Age")
    info_var = _metadata_variable(meta, "Information")

    male_code = _value_code(sex_var, "Males")
    female_code = _value_code(sex_var, "Females")
    q_code = _value_code(info_var, "Probability of death")

    years = [str(x) for x in year_var["values"]]
    ages = [str(x) for x in age_var["values"]]

    query = {
        "query": [
            {
                "code": year_var["code"],
                "selection": {"filter": "item", "values": years},
            },
            {
                "code": sex_var["code"],
                "selection": {
                    "filter": "item",
                    "values": [male_code, female_code],
                },
            },
            {
                "code": age_var["code"],
                "selection": {"filter": "item", "values": ages},
            },
            {
                "code": info_var["code"],
                "selection": {"filter": "item", "values": [q_code]},
            },
        ],
        "response": {"format": "json-stat2"},
    }

    body = json.dumps(query).encode("utf-8")
    data_status("Statistics Finland life table: downloading qx rows...")
    try:
        request = urllib.request.Request(
            STATFIN_LIFE_TABLE_API,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "mortality-roulette/0.8",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            dataset = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CohortDataError(
            f"Statistics Finland life-table download failed: {exc}"
        ) from exc

    data = _parse_statfin_jsonstat2(dataset)
    available_years = sorted(set(data["male"]) & set(data["female"]))
    if not available_years:
        raise CohortDataError("Statistics Finland response contained no usable qx data")

    max_exact_age = min(
        max(data["male"][available_years[-1]]),
        max(data["female"][available_years[-1]]),
    )

    data_status(
        f"Statistics Finland life table: parsed {available_years[0]}–{available_years[-1]} "
        f"through exact age {max_exact_age}"
    )
    source = CohortMortalitySource(
        name="Statistics Finland 12ap",
        data=data,
        min_year=available_years[0],
        max_year=available_years[-1],
        max_exact_age=max_exact_age,
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "name": source.name,
        "min_year": source.min_year,
        "max_year": source.max_year,
        "max_exact_age": source.max_exact_age,
        "data": data,
    }
    cache_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return source


def _download_cached_zip(
    url: str,
    path: Path,
    refresh: bool = False,
    *,
    label: str = "data archive",
    attempts: int = 3,
    timeout_seconds: int = 120,
    retry_delay_seconds: float = 3.0,
) -> Path:
    """Download/cache a ZIP with bounded retries for transient network stalls.

    Statistics Canada's bulk endpoints can occasionally accept a connection and
    then fail a read with a timeout.  Retry the complete transfer instead of
    aborting the whole simulation after a single transient failure.  Each retry
    starts from a clean temporary file; the final cache is replaced only after
    ZIP validation succeeds.
    """
    if path.exists() and not refresh:
        data_status(f"{label}: using cached ZIP {path}")
        return path
    if attempts < 1:
        raise ValueError("download attempts must be at least 1")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": f"mortality-roulette/{VERSION}"})
    data_status(f"{label}: source URL: {url}")
    data_status(f"{label}: final cache path: {path}")
    data_status(f"{label}: temporary download path: {tmp}")

    last_exc: BaseException | None = None
    retryable = (TimeoutError, ConnectionError, urllib.error.URLError, zipfile.BadZipFile)

    for attempt in range(1, attempts + 1):
        downloaded = 0
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

        suffix = f" (attempt {attempt}/{attempts})" if attempts > 1 else ""
        data_status(f"{label}: connecting to data source{suffix}...")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response, tmp.open("wb") as out:
                total_header = response.headers.get("Content-Length")
                try:
                    total_bytes = int(total_header) if total_header else None
                except (TypeError, ValueError):
                    total_bytes = None
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes:
                        pct = downloaded / total_bytes * 100.0
                        progress = f"{downloaded / 1048576:.1f}/{total_bytes / 1048576:.1f} MiB ({pct:5.1f}%)"
                    else:
                        progress = f"{downloaded / 1048576:.1f} MiB"
                    if data_progress_enabled():
                        print(
                            f"\r[data] {label}: downloading... {progress}",
                            end="", file=sys.stderr, flush=True,
                        )
            if downloaded and data_progress_enabled():
                print(file=sys.stderr, flush=True)

            data_status(f"{label}: validating downloaded ZIP...")
            with zipfile.ZipFile(tmp) as zf:
                if not any(name.casefold().endswith(".csv") for name in zf.namelist()):
                    raise CohortDataError("downloaded ZIP contained no CSV file")
            tmp.replace(path)
            data_status(f"{label}: cached at {path}")
            return path

        except retryable as exc:
            last_exc = exc
            if downloaded and data_progress_enabled():
                print(file=sys.stderr, flush=True)
            if attempt >= attempts:
                raise
            data_status(
                f"{label}: download attempt {attempt}/{attempts} failed: {exc}; "
                f"retrying in {retry_delay_seconds:g}s...",
                level=1,
            )
            if retry_delay_seconds > 0:
                time.sleep(retry_delay_seconds)
        finally:
            if tmp.exists() and (attempt == attempts or last_exc is not None):
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # Defensive: the loop either returns or raises.
    if last_exc is not None:
        raise last_exc
    raise CohortDataError(f"{label}: download failed without an error")


def _largest_csv_name(zf: zipfile.ZipFile) -> str:
    infos = [info for info in zf.infolist() if info.filename.casefold().endswith(".csv")]
    if not infos:
        raise CohortDataError("ZIP contained no CSV file")
    return max(infos, key=lambda info: info.file_size).filename


# WHO's raw mortality archives are CSV *content* but the principal member is
# historically extensionless (for example ``Morticd10_part6``).  Never infer
# file type from the member suffix.  Identify the data member by its header.
_WHO_MORTALITY_REQUIRED_COLUMNS = {
    "Country", "Year", "List", "Cause", "Sex", "Frmat"
}


def _who_archive_member_summary(zf: zipfile.ZipFile, limit: int = 20) -> str:
    infos = [info for info in zf.infolist() if not info.is_dir()]
    if not infos:
        return "<empty archive>"
    pieces: list[str] = []
    for info in infos[:limit]:
        pieces.append(f"{info.filename!r} ({info.file_size / 1048576:.2f} MiB uncompressed)")
    if len(infos) > limit:
        pieces.append(f"... +{len(infos) - limit} more")
    return "; ".join(pieces)


def _who_mortality_data_member_name(zf: zipfile.ZipFile) -> str:
    """Return the WHO mortality data member, regardless of filename suffix."""
    infos = [info for info in zf.infolist() if not info.is_dir() and info.file_size > 0]
    # The mortality file is normally by far the largest member.  Checking by
    # descending size avoids wasting time on ancillary files if WHO adds any.
    for info in sorted(infos, key=lambda item: item.file_size, reverse=True):
        try:
            with zf.open(info, "r") as raw:
                sample = raw.read(64 * 1024)
        except (KeyError, OSError, RuntimeError):
            continue
        if not sample:
            continue
        decoded = sample.decode("utf-8-sig", errors="replace")
        try:
            header = next(csv.reader(io.StringIO(decoded)))
        except (StopIteration, csv.Error):
            continue
        fields = {str(field).strip() for field in header}
        if _WHO_MORTALITY_REQUIRED_COLUMNS.issubset(fields):
            return info.filename
    raise CauseDataError(
        "WHO mortality ZIP contained no recognizable mortality data member; "
        "archive members: " + _who_archive_member_summary(zf)
    )


def _inspect_who_mortality_archive(path: Path, *, label: str) -> str:
    """Validate a WHO mortality ZIP and report exactly what is inside it."""
    try:
        with zipfile.ZipFile(path) as zf:
            data_status(f"{label}: archive members: {_who_archive_member_summary(zf)}")
            member = _who_mortality_data_member_name(zf)
            info = zf.getinfo(member)
            data_status(
                f"{label}: selected mortality data member: {member!r} "
                f"({info.file_size / 1048576:.2f} MiB uncompressed)"
            )
            return member
    except zipfile.BadZipFile as exc:
        raise CauseDataError(f"WHO mortality archive is not a valid ZIP: {path}: {exc}") from exc


def _dated_sibling(path: Path, tag: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.stem}.{tag}-{stamp}{path.suffix}")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.{tag}-{stamp}-{n}{path.suffix}")
        n += 1
    return candidate


def _download_who_mortality_archive(
    *,
    part: int,
    cache_dir: Path,
    refresh: bool,
    label: str,
    part_cache: dict[int, Path],
    member_cache: dict[int, str],
    failure_cache: dict[int, str],
) -> tuple[Path, str]:
    """Download/validate one WHO ICD-10 archive at most once per process.

    Failed or partial downloads are preserved with a timestamped filename so a
    parser/network failure is inspectable.  A failed part is memoized for the
    rest of the process, preventing the year-probing logic from downloading the
    same broken archive repeatedly.
    """
    if part in part_cache:
        path = part_cache[part]
        member = member_cache[part]
        data_status(f"{label}: process cache hit: {path} -> {member!r}")
        return path, member
    if part in failure_cache:
        message = failure_cache[part]
        data_status(f"{label}: previous failure remembered; NOT downloading this part again")
        raise CauseDataError(message)

    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"morticd10_part{part}.zip"
    url = f"{WHO_MORTALITY_RAW_BASE}/morticd10_part{part}.zip"
    tmp = path.with_name(path.name + ".download")

    data_status(f"{label}: source URL: {url}")
    data_status(f"{label}: final cache path: {path}")

    # A previously successful archive can be reused immediately.  Validate it
    # once in this process so old/broken cache files do not fail mysteriously.
    if path.exists() and not refresh:
        data_status(f"{label}: cache hit; validating existing archive...")
        try:
            member = _inspect_who_mortality_archive(path, label=label)
        except Exception as exc:
            invalid = _dated_sibling(path, "invalid")
            try:
                path.replace(invalid)
                data_status(f"{label}: invalid cached archive preserved at: {invalid}")
            except OSError as move_exc:
                message = f"{label}: cached archive invalid ({exc}); could not preserve it: {move_exc}"
                failure_cache[part] = message
                raise CauseDataError(message) from exc
            data_status(f"{label}: cached archive was invalid; downloading a fresh copy")
        else:
            part_cache[part] = path
            member_cache[part] = member
            return path, member

    # Never silently delete an old partial download. Preserve it before retry.
    if tmp.exists():
        stale = _dated_sibling(path, "stale-download")
        try:
            tmp.replace(stale)
            data_status(f"{label}: previous unfinished download preserved at: {stale}")
        except OSError as exc:
            message = f"{label}: cannot preserve stale temporary download {tmp}: {exc}"
            failure_cache[part] = message
            raise CauseDataError(message) from exc

    data_status(f"{label}: temporary download path: {tmp}")
    request = urllib.request.Request(url, headers={"User-Agent": f"mortality-roulette/{VERSION}"})
    downloaded = 0
    try:
        data_status(f"{label}: connecting to WHO...")
        with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
            total_header = response.headers.get("Content-Length")
            try:
                total_bytes = int(total_header) if total_header else None
            except (TypeError, ValueError):
                total_bytes = None
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if total_bytes:
                    suffix = (
                        f"{downloaded / 1048576:.1f}/{total_bytes / 1048576:.1f} MiB "
                        f"({downloaded / total_bytes * 100.0:5.1f}%)"
                    )
                else:
                    suffix = f"{downloaded / 1048576:.1f} MiB"
                if data_progress_enabled():
                    print(
                        f"\r[data] {label}: downloading {url} -> {tmp} ... {suffix}",
                        end="", file=sys.stderr, flush=True,
                    )
        if downloaded and data_progress_enabled():
            print(file=sys.stderr, flush=True)
        data_status(f"{label}: download complete: {downloaded / 1048576:.2f} MiB")
        data_status(f"{label}: validating downloaded archive at: {tmp}")
        member = _inspect_who_mortality_archive(tmp, label=label)
        tmp.replace(path)
        data_status(f"{label}: validation OK; cached archive at: {path}")
        part_cache[part] = path
        member_cache[part] = member
        return path, member
    except Exception as exc:
        preserved: Path | None = None
        if tmp.exists():
            preserved = _dated_sibling(path, "failed-download")
            try:
                tmp.replace(preserved)
                data_status(f"{label}: FAILED download/archive preserved at: {preserved}")
            except OSError as move_exc:
                data_status(f"{label}: WARNING: could not preserve failed temp file {tmp}: {move_exc}")
        message = f"{label}: {exc}"
        if preserved is not None:
            message += f"; failed archive preserved at {preserved}"
        failure_cache[part] = message
        if isinstance(exc, CauseDataError):
            raise CauseDataError(message) from exc
        raise CauseDataError(message) from exc


def _parse_statcan_age(label: str) -> int | None:
    text = label.strip().casefold()
    if "and over" in text or "and older" in text:
        return None
    match = re.match(r"^(\d+)\s+year", text)
    return int(match.group(1)) if match else None


def fetch_statcan_life_table(
    cache_path: Path = DEFAULT_STATCAN_CACHE,
    zip_path: Path = DEFAULT_STATCAN_ZIP,
    refresh: bool = False,
    *,
    province: str | None = None,
) -> CohortMortalitySource:
    """Download/cache Statistics Canada 13-10-0837-01 qx for Canada/province."""
    geography = statcan_geography_name(province)
    cache_path = _regional_cache_path(cache_path, province)
    if cache_path.exists() and not refresh:
        data_status(f"Statistics Canada life table ({geography}): using parsed cache {cache_path}")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_geo = str(payload.get("geography", "Canada"))
        if cached_geo.casefold() != geography.casefold():
            raise CohortDataError(
                f"Statistics Canada life-table cache geography mismatch: expected {geography!r}, found {cached_geo!r} in {cache_path}"
            )
        data = {
            sex: {
                int(year): {int(age): float(q) for age, q in ages.items()}
                for year, ages in years.items()
            }
            for sex, years in payload["data"].items()
        }
        return CohortMortalitySource(
            name=payload["name"], data=data,
            min_year=int(payload["min_year"]), max_year=int(payload["max_year"]),
            max_exact_age=int(payload["max_exact_age"]),
        )

    path = _download_cached_zip(
        STATCAN_LIFE_TABLE_URL, zip_path, refresh=refresh,
        label="Statistics Canada 13-10-0837 life table",
    )
    data_status("Statistics Canada life table: parsing CSV rows...")
    data: dict[str, dict[int, dict[int, float]]] = {"male": {}, "female": {}}
    with zipfile.ZipFile(path) as zf:
        name = _largest_csv_name(zf)
        with zf.open(name, "r") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.DictReader(text)
            if not reader.fieldnames:
                raise CohortDataError("Statistics Canada life-table CSV has no header")
            fields = {f.casefold(): f for f in reader.fieldnames}
            def field_contains(*parts: str) -> str:
                for original in reader.fieldnames or []:
                    low = original.casefold()
                    if all(part in low for part in parts):
                        return original
                raise CohortDataError(f"Statistics Canada CSV field not found: {parts}")
            ref_field = fields.get("ref_date") or field_contains("ref", "date")
            geo_field = fields.get("geo") or field_contains("geo")
            sex_field = fields.get("sex") or field_contains("sex")
            elem_field = fields.get("element") or field_contains("element")
            age_field = fields.get("age group") or field_contains("age")
            value_field = fields.get("value") or field_contains("value")

            seen_elements: Counter[str] = Counter()
            geography_rows = 0
            qx_rows = 0
            target_geo = re.sub(r"\s+", " ", geography.casefold()).strip()
            for row in reader:
                geo_text = re.sub(r"\s+", " ", str(row.get(geo_field, "")).strip().casefold()).strip()
                if geo_text != target_geo:
                    continue
                geography_rows += 1
                element_raw = str(row.get(elem_field, "")).strip()
                element = element_raw.casefold()
                if element_raw:
                    seen_elements[element_raw] += 1
                # Current StatCan wording is:
                #   "Death probability between age x and x+1 (qx)"
                # Older/alternate exports may use slightly different wording,
                # so key primarily on qx + death/probability rather than one
                # brittle English phrase.
                is_qx = (
                    "qx" in element
                    and "probab" in element
                    and ("death" in element or "dying" in element)
                    and "margin of error" not in element
                )
                if not is_qx:
                    continue
                qx_rows += 1
                sex_text = str(row.get(sex_field, "")).strip().casefold()
                if sex_text.startswith("male"):
                    sex = "male"
                elif sex_text.startswith("female"):
                    sex = "female"
                else:
                    continue
                age = _parse_statcan_age(str(row.get(age_field, "")))
                if age is None:
                    continue  # 110+ is an open interval, not exact-age qx.
                try:
                    year = int(str(row.get(ref_field, "")).strip())
                    q = float(str(row.get(value_field, "")).strip())
                except (TypeError, ValueError):
                    continue
                if not (0.0 <= q <= 1.0):
                    raise CohortDataError(
                        f"unexpected Statistics Canada qx value {q} for {sex} age {age} year {year}"
                    )
                data[sex].setdefault(year, {})[age] = q

    common_years = sorted(set(data["male"]) & set(data["female"]))
    if not common_years:
        element_preview = "; ".join(
            f"{label!r} ({count})" for label, count in seen_elements.most_common(6)
        ) or "<none>"
        raise CohortDataError(
            f"Statistics Canada 13-10-0837 CSV contained no usable qx data for {geography} "
            f"(geography rows={geography_rows}, qx rows matched={qx_rows}; "
            f"sample Element values: {element_preview})"
        )
    latest = common_years[-1]
    max_exact_age = min(max(data["male"][latest]), max(data["female"][latest]))
    data_status(
        f"Statistics Canada life table ({geography}): parsed {common_years[0]}–{latest} "
        f"through exact age {max_exact_age}"
    )
    source = CohortMortalitySource(
        name=f"Statistics Canada 13-10-0837-01 complete life table — {geography}",
        data=data, min_year=common_years[0], max_year=latest,
        max_exact_age=max_exact_age,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "name": source.name, "geography": geography, "min_year": source.min_year,
        "max_year": source.max_year, "max_exact_age": source.max_exact_age,
        "data": data,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return source


def _find_hmd_file(base: Path, sex: str) -> Path | None:
    filename = "mltper_1x1.txt" if sex == "male" else "fltper_1x1.txt"
    candidates = [
        base / filename,
        base / "STATS" / filename,
        base / "FIN" / "STATS" / filename,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _parse_hmd_life_table(path: Path) -> dict[int, dict[int, float]]:
    """
    Parse an HMD 1x1 period life table and return year -> age -> qx.

    Expected columns include Year, Age, and qx. The 110+ open interval is
    deliberately excluded because HMD sets its qx to 1 by construction.
    """
    result: dict[int, dict[int, float]] = {}

    with path.open("r", encoding="utf-8-sig") as fh:
        header = None
        for raw in fh:
            line = raw.strip()
            if not line:
                continue

            fields = line.split()

            if header is None:
                lowered = [x.casefold() for x in fields]
                if "year" in lowered and "age" in lowered and "qx" in lowered:
                    header = lowered
                continue

            if len(fields) < len(header):
                continue

            row = dict(zip(header, fields))
            year_text = row["year"]
            age_text = row["age"]
            q_text = row["qx"]

            if not year_text.isdigit():
                continue
            if age_text.endswith("+"):
                continue
            if not age_text.isdigit():
                continue
            if q_text in {".", "NA", "nan"}:
                continue

            year = int(year_text)
            age = int(age_text)
            if age >= HMD_OPEN_AGE:
                continue

            try:
                q = float(q_text)
            except ValueError:
                continue

            result.setdefault(year, {})[age] = q

    if not result:
        raise CohortDataError(f"No usable HMD qx rows found in {path}")

    return result


def load_hmd_finland(hmd_dir: Path, needed_sexes: set[str]) -> CohortMortalitySource:
    data: dict[str, dict[int, dict[int, float]]] = {}

    for sex in needed_sexes:
        path = _find_hmd_file(hmd_dir, sex)
        if path is None:
            filename = "mltper_1x1.txt" if sex == "male" else "fltper_1x1.txt"
            raise CohortDataError(
                f"HMD file {filename} not found under {hmd_dir}"
            )
        data[sex] = _parse_hmd_life_table(path)

    # Populate an unused sex with an empty dict so q_for() remains simple.
    data.setdefault("male", {})
    data.setdefault("female", {})

    year_sets = [set(data[sex]) for sex in needed_sexes]
    common_years = sorted(set.intersection(*year_sets))
    if not common_years:
        raise CohortDataError("HMD files have no common usable calendar years")

    return CohortMortalitySource(
        name="HMD Finland 1x1 period life table",
        data=data,
        min_year=common_years[0],
        max_year=common_years[-1],
        max_exact_age=HMD_OPEN_AGE - 1,
    )


def prepare_cohort_source(
    *,
    birth_year: int,
    start_age: int,
    selection: str,
    hmd_dir: Path | None,
    statfin_cache: Path,
    refresh_statfin: bool,
) -> CohortMortalitySource:
    needed_sexes = (
        {"male", "female"}
        if selection == "r"
        else {"male"} if selection == "m" else {"female"}
    )

    first_calendar_year = birth_year + start_age

    if hmd_dir is not None:
        source = load_hmd_finland(hmd_dir, needed_sexes)
    else:
        # Auto-detect HMD files in the working directory before going online.
        auto_hmd = Path.cwd()
        found_all = all(_find_hmd_file(auto_hmd, sex) for sex in needed_sexes)
        if found_all:
            source = load_hmd_finland(auto_hmd, needed_sexes)
        else:
            if first_calendar_year < STATFIN_FIRST_YEAR:
                raise CohortDataError(
                    f"--birth-year {birth_year} with --start-age {start_age} begins "
                    f"in calendar year {first_calendar_year}, but Statistics Finland's "
                    f"open age-specific qx table starts in {STATFIN_FIRST_YEAR}. "
                    "For older cohorts, download the HMD Finland 1x1 period life-table "
                    "files (mltper_1x1.txt / fltper_1x1.txt) and use --hmd-dir PATH."
                )
            source = fetch_statfin_life_table(
                cache_path=statfin_cache,
                refresh=refresh_statfin,
            )

    if first_calendar_year < source.min_year:
        raise CohortDataError(
            f"cohort simulation begins in {first_calendar_year}, before "
            f"{source.name} starts in {source.min_year}"
        )

    return source


def cohort_q_for_age(
    *,
    age: int,
    sex: str,
    birth_year: int,
    source: CohortMortalitySource,
) -> tuple[float, str, bool]:
    calendar_year = birth_year + age
    return source.q_for(age=age, sex=sex, calendar_year=calendar_year)

def one_in_x(q: float) -> float:
    return float("inf") if q <= 0 else 1.0 / q


def fmt_one_in(q: float) -> str:
    x = one_in_x(q)
    if x >= 100:
        return f"1 in {x:,.0f}"
    if x >= 10:
        return f"1 in {x:,.1f}"
    return f"1 in {x:,.2f}"


def record_label(sex: str) -> str:
    rec = FINNISH_RECORDS[sex]
    return f"{rec['name']} — {rec['years']} years, {rec['days']} days"


def print_record_banner(sex: str) -> None:
    if ACTIVE_COUNTRY == "ca":
        print("Canadian longevity record ceiling: not applied")
        return
    print(f"Finnish {sex} longevity record: {record_label(sex)}")


def maybe_print_record_milestone(age: int, sex: str) -> None:
    if ACTIVE_COUNTRY == "ca":
        return
    rec = FINNISH_RECORDS[sex]

    if age == rec["years"]:
        print()
        print(
            f"🏅 RECORD TERRITORY: reached age {age}. "
            f"Finnish {sex} record holder: {rec['name']} "
            f"({rec['years']}y {rec['days']}d)."
        )
        print(
            f"   Whole-year simulation: reaching {rec['years'] + 1} "
            f"guarantees the exact Finnish record has been exceeded."
        )
        print()

    elif age == rec["years"] + 1:
        print()
        print(
            f"👑 FINNISH RECORD BEATEN: reached age {age}, exceeding "
            f"{rec['name']}'s {rec['years']}y {rec['days']}d record."
        )
        print()





class CauseDataError(RuntimeError):
    pass


def _jsonstat_category_label(dataset: dict, dim_id: str, code: str) -> str:
    category = dataset["dimension"][dim_id]["category"]
    labels = category.get("label", {})
    if isinstance(labels, dict):
        return str(labels.get(code, code))
    return str(code)


def _selected_codes_by_prefix(var: dict, prefixes: tuple[str, ...]) -> list[str]:
    values = [str(x) for x in var.get("values", [])]
    texts = [str(x) for x in var.get("valueTexts", [])]
    selected: list[str] = []

    for prefix in prefixes:
        matches = [
            code
            for code, label in zip(values, texts)
            if label.startswith(prefix)
        ]
        if len(matches) != 1:
            raise CauseDataError(
                f"Could not uniquely identify StatFin cause group {prefix!r}; "
                f"found {len(matches)} matches"
            )
        selected.append(matches[0])

    return selected


def _parse_age_interval(label: str) -> tuple[int, int | None] | None:
    """
    Parse StatFin age labels such as:
      '0', '1 - 4', '15 - 64', '65 -', '95 -'

    Aggregate ranges remain valid candidates, but choose_age_label() always
    prefers the narrowest matching interval.
    """
    cleaned = label.strip()
    if cleaned.casefold() == "total":
        return None

    if cleaned.isdigit():
        value = int(cleaned)
        return value, value

    if "-" not in cleaned:
        return None

    left, right = (part.strip() for part in cleaned.split("-", 1))
    if not left.isdigit():
        return None

    lo = int(left)
    if right == "":
        return lo, None
    if right.isdigit():
        return lo, int(right)
    return None


def choose_age_label(age: int, available_labels: list[str]) -> str | None:
    candidates: list[tuple[float, int, str]] = []

    for label in available_labels:
        interval = _parse_age_interval(label)
        if interval is None:
            continue

        lo, hi = interval
        if hi is None:
            if age < lo:
                continue
            # Prefer the highest lower bound among open-ended groups.
            width = 10000.0 - lo
        else:
            if not (lo <= age <= hi):
                continue
            width = float(hi - lo)

        # Narrowest range first; for equal-width/open ranges prefer larger lo.
        candidates.append((width, -lo, label))

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][2]


def boozehound_active_for_age(age: int) -> bool:
    return (
        ACTIVE_BOOZEHOUND
        and ACTIVE_BOOZEHOUND_GRAMS_PER_DAY > 0.0
        and age >= ACTIVE_BOOZEHOUND_START_AGE
        and (ACTIVE_BOOZEHOUND_END_AGE is None or age < ACTIVE_BOOZEHOUND_END_AGE)
    )


def boozehound_exposure_has_started(age: int, *, midpoint: bool = True) -> bool:
    if not ACTIVE_BOOZEHOUND or ACTIVE_BOOZEHOUND_GRAMS_PER_DAY <= 0.0:
        return False
    offset = 0.5 if midpoint else 0.0
    return float(age) + offset > float(ACTIVE_BOOZEHOUND_START_AGE)


def boozehound_schedule_lines() -> list[str]:
    lines = [f"drinking starts at age: {ACTIVE_BOOZEHOUND_START_AGE}"]
    if ACTIVE_BOOZEHOUND_END_AGE is not None:
        lines.append(f"drinking stops at age: {ACTIVE_BOOZEHOUND_END_AGE}")
    return lines


def boozehound_preset_label() -> str:
    if ACTIVE_BOOZEHOUND_PRESET == "wino":
        return "BOOZEHOUND-WINO"
    return "BOOZEHOUND"


def boozehound_preset_icon() -> str:
    return "🍷" if ACTIVE_BOOZEHOUND_PRESET == "wino" else "🍺"


def boozehound_all_cause_target_rr(sex: str, grams_per_day: float | None = None) -> float:
    """Published sex-specific all-cause mortality RR category for the active dose.

    The two shipped presets deliberately sit in categories directly reported by
    Zhao et al. (2023), avoiding interpolation of the all-cause endpoint:
      60 g/day -> 45-64 g/day category
      ~71 g/day -> >=65 g/day category
    """
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    if dose >= 65.0:
        return float(BOOZEHOUND_ALL_CAUSE_RR_65_PLUS.get(sex, 1.0))
    if dose >= 45.0:
        return float(BOOZEHOUND_ALL_CAUSE_RR_45_64.get(sex, 1.0))
    return 1.0


def boozehound_exposure_years(age: int, *, midpoint: bool = True) -> float:
    """Years of preset exposure accumulated by this age interval."""
    offset = 0.5 if midpoint else 0.0
    observation_age = float(age) + offset
    if ACTIVE_BOOZEHOUND_END_AGE is not None:
        observation_age = min(observation_age, float(ACTIVE_BOOZEHOUND_END_AGE))
    return max(0.0, observation_age - float(ACTIVE_BOOZEHOUND_START_AGE))


def boozehound_cumulative_ethanol_kg(age: int, *, midpoint: bool = True) -> float:
    """Approximate cumulative pure ethanol consumed under the active preset."""
    years = boozehound_exposure_years(age, midpoint=midpoint)
    return years * 365.2425 * ACTIVE_BOOZEHOUND_GRAMS_PER_DAY / 1000.0


def _boozehound_dose_scale_rr(rr_at_60g: float) -> float:
    """Scale a 60-g/day cause-shape RR to the active preset dose.

    Most detailed cause weights in this script are heavy-drinker/dose-response
    proxies rather than exact values at 71 g/day. For the wino preset we use a
    deliberately conservative linear scaling of *excess* RR around the 60 g/day
    reference: 1 + (RR60-1)*(dose/60). The all-cause mortality RR is NOT scaled
    this way; it uses the directly published 45-64 and >=65 g/day categories.
    """
    rr = max(1e-12, float(rr_at_60g))
    if rr == 1.0 or ACTIVE_BOOZEHOUND_GRAMS_PER_DAY <= 0.0:
        return rr
    return 1.0 + (rr - 1.0) * (ACTIVE_BOOZEHOUND_GRAMS_PER_DAY / 60.0)


def _boozehound_profile_fraction(age: int, profile: str) -> float:
    """0..1 maturity of a duration/latency profile for this age interval."""
    if not boozehound_active_for_age(age):
        return 0.0
    years = boozehound_exposure_years(age)
    lag, ramp = BOOZEHOUND_LATENCY_PROFILES.get(
        profile, BOOZEHOUND_LATENCY_PROFILES["chronic"]
    )
    if years <= lag:
        return 0.0
    if ramp <= 0.0:
        return 1.0
    return min(1.0, max(0.0, (years - lag) / ramp))


def _boozehound_duration_rr(target_rr: float, *, age: int, profile: str) -> tuple[float, float]:
    """Return (effective RR, maturity fraction) using log-RR interpolation."""
    target_rr = max(1e-12, float(target_rr))
    fraction = _boozehound_profile_fraction(age, profile)
    if fraction <= 0.0 or target_rr == 1.0:
        return 1.0, fraction
    return target_rr ** fraction, fraction


def boozehound_mortality_multiplier(age: int, sex: str) -> float:
    """Duration-aware all-cause mortality-hazard multiplier for active preset."""
    if not boozehound_active_for_age(age):
        return 1.0
    target = boozehound_all_cause_target_rr(sex)
    years = boozehound_exposure_years(age)
    fraction = min(1.0, max(0.0, years / BOOZEHOUND_ALL_CAUSE_RAMP_YEARS))
    return target ** fraction


def boozehound_adjust_q(q: float, *, age: int, sex: str) -> tuple[float, float]:
    """Return (adjusted_q, effective hazard RR).

    v0.11.21 treats the epidemiological RR as a mortality-rate/hazard ratio.
    Annual qx is converted to an integrated hazard H=-ln(1-q), H is multiplied,
    then converted back with q*=1-exp(-H*RR). This avoids the increasingly poor
    approximation q*=q*RR at high old-age qx.
    """
    q = min(1.0, max(0.0, float(q)))
    mult = boozehound_mortality_multiplier(age, sex)
    if q <= 0.0 or mult == 1.0:
        return q, mult
    if q >= 1.0:
        return 1.0, mult
    hazard = -math.log1p(-q)
    adjusted = -math.expm1(-hazard * mult)
    return min(1.0, max(0.0, adjusted)), mult


def alcohol_model_label() -> str:
    """Human-readable active alcohol mortality engine label."""
    if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
        return "CAUSE-HAZARD PROTOTYPE (EXPERIMENTAL)"
    return "LEGACY ALL-CAUSE RR"


def boozehound_cause_hazard_prototype_adjust_q(
    q: float,
    *,
    age: int,
    sex: str,
    cause_source: "CauseOfDeathSource",
) -> tuple[float, float, dict[str, object]]:
    """Experimental broad-cause hazard reconstruction for present-day Finland.

    Split the observed all-cause integrated hazard according to the current
    StatFin broad-cause shares for the requested sex/age cell. Apply the
    existing duration/dose-aware boozehound broad-cause weights as provisional
    *hazard* multipliers, then sum the modified cause hazards back into a new
    annual all-cause qx.

    IMPORTANT: this is an architecture prototype, not a calibrated alcohol
    model. The broad cause weights were originally conditional cause-shape
    proxies; they are not yet validated causal cause-specific hazard RRs, and
    population alcohol exposure is not fully deconvolved. evidence-v2-popnorm applies only a first-order mean-dose normalization to the direct-alcohol hazard; evidence-v3-popdist improves that denominator to an explicit WHO-style exposure distribution; evidence-v4-cancer additionally maps population-normalized Dai et al. 2026 cancer subhazards, while remaining non-cancer broad mappings stay provisional.
    """
    q = min(1.0, max(0.0, float(q)))
    if not boozehound_active_for_age(age) or q <= 0.0:
        return q, 1.0, {
            "available": True,
            "engine": "cause-hazard-prototype",
            "rows": [],
            "effective_multiplier": 1.0,
        }

    cell = cause_source.counts_for(sex=sex, age=age, calendar_year=None)
    if not cell.get("available"):
        raise CauseDataError(
            "cause-hazard prototype could not resolve StatFin cause cell: "
            + str(cell.get("reason", "unknown cause-data error"))
        )

    counts = dict(cell["counts"])
    total = sum(max(0, int(v)) for v in counts.values())
    if total <= 0:
        raise CauseDataError("cause-hazard prototype resolved an empty StatFin cause cell")

    rows: list[dict[str, object]] = []
    weighted_multiplier = 0.0
    for label, raw_count in counts.items():
        count = max(0, int(raw_count))
        if count <= 0:
            continue
        baseline_share = count / total
        mult, target_mult, profile, maturity, evidence_basis = _boozehound_finland_broad_hazard_effective_rr(
            label, age=age, sex=sex,
            parent_count=count,
            lookup_year=int(cell["lookup_year"]),
            detail_resolver=getattr(cause_source, "_alcohol_detail_resolver", None),
        )
        weighted_multiplier += baseline_share * mult
        rows.append({
            "label": label,
            "count": count,
            "baseline_share": baseline_share,
            "effective_multiplier": mult,
            "target_multiplier": target_mult,
            "profile": profile,
            "maturity": maturity,
            "evidence_basis": evidence_basis,
            "adjusted_weight": count * mult,
        })

    if not rows or weighted_multiplier <= 0.0:
        raise CauseDataError("cause-hazard prototype produced no usable adjusted cause hazards")

    if q >= 1.0:
        baseline_hazard = math.inf
        adjusted_q = 1.0
        adjusted_hazard = math.inf
    else:
        baseline_hazard = -math.log1p(-q)
        adjusted_hazard = baseline_hazard * weighted_multiplier
        adjusted_q = -math.expm1(-adjusted_hazard)
        adjusted_q = min(1.0, max(0.0, adjusted_q))

    adjusted_weight_total = sum(float(row["adjusted_weight"]) for row in rows)
    for row in rows:
        row["adjusted_share"] = float(row["adjusted_weight"]) / adjusted_weight_total

    return adjusted_q, weighted_multiplier, {
        "available": True,
        "engine": "cause-hazard-prototype",
        "weight_model": ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
        "lookup_year": cell["lookup_year"],
        "age_group": cell["age_group"],
        "baseline_hazard": baseline_hazard,
        "adjusted_hazard": adjusted_hazard,
        "effective_multiplier": weighted_multiplier,
        "rows": rows,
        "warning": (
            "experimental broad-cause hazard sensitivity; evidence-v2 uses first-order mean-dose "
            "population normalization for the direct alcohol bucket; full exposure-distribution "
            "deconvolution is not yet implemented"
        ),
    }


def boozehound_canada_cause_hazard_prototype_adjust_q(
    q: float,
    *,
    age: int,
    sex: str,
    cause_source: "CanadaCauseOfDeathSource",
) -> tuple[float, float, dict[str, object]]:
    """Experimental Canada cause-hazard reconstruction from WHO complete ICD cells."""
    q = min(1.0, max(0.0, float(q)))
    if not boozehound_active_for_age(age) or q <= 0.0:
        return q, 1.0, {
            "available": True,
            "engine": "cause-hazard-prototype",
            "country": "ca",
            "rows": [],
            "effective_multiplier": 1.0,
        }

    cell = cause_source.counts_for(sex=sex, age=age, calendar_year=None)
    if not cell.get("available"):
        raise CauseDataError(
            "Canada cause-hazard prototype could not resolve WHO cause cell: "
            + str(cell.get("reason", "unknown cause-data error"))
        )
    counts = dict(cell["counts"])
    total = sum(max(0, int(v)) for v in counts.values())
    if total <= 0:
        raise CauseDataError("Canada cause-hazard prototype resolved an empty WHO cause cell")

    rows: list[dict[str, object]] = []
    weighted_multiplier = 0.0
    for code, raw_count in counts.items():
        count = max(0, int(raw_count))
        if count <= 0:
            continue
        baseline_share = count / total
        mult, target_mult, profile, maturity, evidence_basis = _boozehound_icd_hazard_effective_rr(
            str(code), age=age, sex=sex, country="ca"
        )
        weighted_multiplier += baseline_share * mult
        rows.append({
            "code": str(code),
            "count": count,
            "baseline_share": baseline_share,
            "effective_multiplier": mult,
            "target_multiplier": target_mult,
            "profile": profile,
            "maturity": maturity,
            "evidence_basis": evidence_basis,
            "adjusted_weight": count * mult,
        })

    if not rows or weighted_multiplier <= 0.0:
        raise CauseDataError("Canada cause-hazard prototype produced no usable adjusted cause hazards")

    if q >= 1.0:
        baseline_hazard = adjusted_hazard = math.inf
        adjusted_q = 1.0
    else:
        baseline_hazard = -math.log1p(-q)
        adjusted_hazard = baseline_hazard * weighted_multiplier
        adjusted_q = min(1.0, max(0.0, -math.expm1(-adjusted_hazard)))

    adjusted_weight_total = sum(float(row["adjusted_weight"]) for row in rows)
    for row in rows:
        row["adjusted_share"] = float(row["adjusted_weight"]) / adjusted_weight_total

    return adjusted_q, weighted_multiplier, {
        "available": True,
        "engine": "cause-hazard-prototype",
        "country": "ca",
        "weight_model": ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL,
        "lookup_year": cell["lookup_year"],
        "age_group": cell["age_group"],
        "baseline_hazard": baseline_hazard,
        "adjusted_hazard": adjusted_hazard,
        "effective_multiplier": weighted_multiplier,
        "rows": rows,
        "warning": (
            "experimental WHO complete-ICD hazard reconstruction; evidence-v2 uses first-order "
            "mean-dose population normalization, not full exposure-distribution deconvolution"
        ),
    }


def alcohol_adjust_q(
    q: float,
    *,
    age: int,
    sex: str,
    cause_source: object | None = None,
) -> tuple[float, float, dict[str, object]]:
    """Dispatch the selected alcohol mortality engine."""
    if ACTIVE_ALCOHOL_MODEL == "legacy":
        adjusted, mult = boozehound_adjust_q(q, age=age, sex=sex)
        return adjusted, mult, {
            "available": True,
            "engine": "legacy",
            "effective_multiplier": mult,
            "target_multiplier": boozehound_all_cause_target_rr(sex),
        }
    if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
        if cause_source is None:
            raise CauseDataError("cause-hazard prototype requires country cause-of-death data")
        if ACTIVE_COUNTRY == "ca":
            if not isinstance(cause_source, CanadaCauseOfDeathSource):
                raise CauseDataError("Canada cause-hazard prototype requires the WHO Canada cause source")
            return boozehound_canada_cause_hazard_prototype_adjust_q(
                q, age=age, sex=sex, cause_source=cause_source
            )
        if not isinstance(cause_source, CauseOfDeathSource):
            raise CauseDataError("Finland cause-hazard prototype requires the StatFin broad-cause source")
        return boozehound_cause_hazard_prototype_adjust_q(
            q, age=age, sex=sex, cause_source=cause_source
        )
    raise ValueError(f"unknown alcohol model: {ACTIVE_ALCOHOL_MODEL}")


def _icd_letter_number(code: str) -> tuple[str, int] | None:
    norm = _normalise_who_icd_code(code)
    match = re.match(r"^([A-Z])(\d{2})", norm)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _boozehound_icd_target(code: str, *, sex: str) -> tuple[float, str]:
    """Return (full chronic-exposure target RR, latency profile) for an ICD code.

    RRs are cause-shape proxies used conditionally after death. They are not
    independent extra all-cause multipliers. Duration is applied separately by
    boozehound_icd_effective_rr().
    """
    norm = _normalise_who_icd_code(code)
    if not norm:
        return 1.0, "chronic"

    # Alcohol poisoning is an acute exposure pathway.
    if norm == "X45":
        return 4.2, "acute"

    # Directly alcohol-coded chronic conditions: scenario floor, not a diagnosis
    # automatically assigned to every 60 g/day drinker.
    if norm.startswith("F10") or norm.startswith("K70"):
        return 4.2, "direct_chronic"
    if norm in {"G312", "G4051", "G621", "G721", "K292"}:
        return 4.2, "direct_chronic"

    parsed = _icd_letter_number(norm)
    if parsed is None:
        return 1.0, "chronic"
    letter, number = parsed

    # Dementia: the 2020 Lancet Commission meta-analysis estimated RR 1.18 for
    # all-cause dementia with >21 UK units/week in midlife vs lighter drinking.
    # Apply this conservative incidence-based proxy to F01/F03 only; G30 remains
    # unmodified because the evidence does not justify treating Alzheimer
    # pathology itself as equivalent to generic alcohol-associated dementia.
    if norm.startswith("F01") or norm.startswith("F03"):
        return 1.18, "dementia"

    # Cancer: heavy-drinker vs non/occasional-drinker meta-analysis (Bagnardi
    # et al.; IARC summary of Br J Cancer 2015 dose-response meta-analysis).
    if letter == "C":
        if 0 <= number <= 14:
            return 5.13, "cancer"   # oral cavity / pharynx proxy
        if number == 15:
            return 4.95, "cancer"   # oesophageal cancer proxy (strongest for SCC)
        if number == 16:
            return 1.21, "cancer"   # stomach
        if 18 <= number <= 21:
            return 1.44, "cancer"   # colorectal
        if number == 22:
            return 2.07, "cancer"   # liver
        if number == 23:
            return 2.64, "cancer"   # gallbladder
        if number == 25:
            return 1.19, "cancer"   # pancreas
        if number == 32:
            return 2.65, "cancer"   # larynx
        if number == 34:
            return 1.15, "cancer"   # lung; conservative proxy, smoking confounding remains
        if number == 50 and sex == "female":
            return 1.61, "cancer"   # female breast

    # Liver cirrhosis: 50 g/day morbidity RR 3.54 and 100 g/day RR 8.15;
    # retain the rounded 60 g/day proxy around 4.2.
    if letter == "K" and number in {73, 74}:
        return 4.2, "liver"

    # Pancreatitis: quantitative heavy-drinking estimates used by the prior model.
    if letter == "K" and number == 85:
        return 4.2, "pancreas"
    if letter == "K" and number == 86:
        return 9.2, "pancreas"

    # Stroke >60 g/day vs abstainers (Reynolds et al., JAMA 2003 meta-analysis).
    if letter == "I" and 60 <= number <= 69:
        return 1.64, "vascular"

    # Hypertension incidence at roughly >=5 standard drinks/day (Roerecke et al.
    # JAHA 2018): men 1.74; women 1.42.
    if letter == "I" and 10 <= number <= 15:
        return (1.74 if sex == "male" else 1.42), "vascular"

    # Atrial fibrillation incidence around 60 g/day: Samokhvalov et al. reported
    # RR 1.44 in men and 1.42 in women. This was missing from v0.11.19.
    if norm.startswith("I48"):
        return (1.44 if sex == "male" else 1.42), "vascular"

    # Current-drinker individual-participant meta-analysis (Wood et al., Lancet
    # 2018): heart failure and fatal aortic aneurysm rise with intake. Retain the
    # prior conservative shape proxies but make their effect duration-aware.
    if norm.startswith("I50"):
        return 1.32, "vascular"
    if norm.startswith("I71"):
        return 1.56, "vascular"

    # Fatal injury proxy for a heavy per-occasion pattern. This pathway is
    # acute/current-exposure driven, so no chronic latency ramp is applied.
    if letter in {"V", "W", "X", "Y"}:
        return 1.90, "acute"

    return 1.0, "chronic"


def boozehound_icd_target_rr(code: str, *, sex: str) -> float:
    """Dose-adjusted chronic-exposure target RR for the active preset."""
    target_60, _profile = _boozehound_icd_target(code, sex=sex)
    return _boozehound_dose_scale_rr(target_60)


def boozehound_icd_effective_rr(
    code: str,
    *,
    age: int,
    sex: str,
) -> tuple[float, float, str, float]:
    """Return (effective RR, dose-adjusted target RR, profile, maturity fraction)."""
    target_60, profile = _boozehound_icd_target(code, sex=sex)
    target = _boozehound_dose_scale_rr(target_60)
    effective, fraction = _boozehound_duration_rr(target, age=age, profile=profile)
    return effective, target, profile, fraction


def _log_linear_rr_from_knots(dose_g_day: float, knots: tuple[tuple[float, float], ...]) -> float:
    """Log-linear interpolation of a positive RR dose-response table.

    The source tables are sparse dose points, so interpolation is performed on
    log(RR), which preserves positivity and treats multiplicative risk changes
    naturally. Above the final knot we continue the last log-linear segment;
    callers must label such extrapolation appropriately.
    """
    dose = max(0.0, float(dose_g_day))
    if len(knots) < 2:
        raise ValueError("RR interpolation needs at least two knots")
    xs = [float(x) for x, _ in knots]
    ys = [max(1e-12, float(y)) for _, y in knots]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("RR knot doses must be strictly increasing")
    if dose <= xs[0]:
        return ys[0]
    idx = len(xs) - 2
    for i in range(len(xs) - 1):
        if dose <= xs[i + 1]:
            idx = i
            break
    x0, x1 = xs[idx], xs[idx + 1]
    y0, y1 = math.log(ys[idx]), math.log(ys[idx + 1])
    fraction = (dose - x0) / (x1 - x0)
    return math.exp(y0 + fraction * (y1 - y0))


def carr_2024_aud_mortality_rr(grams_per_day: float | None = None) -> float:
    """Dose-response RR for AUD/alcohol-poisoning mortality from Carr 2024."""
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    return _log_linear_rr_from_knots(dose, CARR_2024_AUD_MORTALITY_RR)


def _apc_litres_to_grams_day(litres_per_year: float) -> float:
    return max(0.0, float(litres_per_year)) * 1000.0 * ETHANOL_DENSITY_G_PER_ML / 365.0


def alcohol_population_anchor(country: str, sex: str) -> tuple[float, str]:
    """Return provisional population-average alcohol exposure anchor in g/day."""
    country_key = str(country).lower()
    sex_key = "male" if str(sex).lower().startswith("m") else "female"
    try:
        litres, source = ALCOHOL_POPULATION_APC_LITRES[country_key][sex_key]
    except KeyError as exc:
        raise CauseDataError(f"no alcohol population-normalization anchor for {country}/{sex}") from exc
    return _apc_litres_to_grams_day(litres), source


def alcohol_population_rr_expectation(
    dose_weights: list[tuple[float, float]],
    *,
    rr_function=carr_2024_aud_mortality_rr,
) -> float:
    """Return E[RR(D)] for a discrete population alcohol-exposure distribution.

    Scaffolding for distribution-based population deconvolution.
    Each tuple is (grams_per_day, population_weight). Weights need not sum to
    one, but must be finite/non-negative and have positive total mass. The
    helper is deliberately not wired into gameplay until defensible country/sex
    exposure bins are sourced and documented.
    """
    total_weight = 0.0
    weighted_rr = 0.0
    for dose, weight in dose_weights:
        dose = float(dose)
        weight = float(weight)
        if not math.isfinite(dose) or dose < 0.0:
            raise ValueError("alcohol population distribution doses must be finite and >= 0")
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("alcohol population distribution weights must be finite and >= 0")
        if weight == 0.0:
            continue
        total_weight += weight
        weighted_rr += weight * float(rr_function(dose))
    if total_weight <= 0.0:
        raise ValueError("alcohol population distribution must have positive total weight")
    return weighted_rr / total_weight


def carr_2024_distribution_normalized_rr(
    *,
    grams_per_day: float,
    dose_weights: list[tuple[float, float]],
) -> tuple[float, float, float]:
    """Return person RR / E[RR(D)] for a supplied discrete exposure distribution.

    Not yet used by the CLI. This isolates the mathematically correct v3
    normalization target so later country-specific data work does not require
    another mortality-engine rewrite.
    """
    person_rr = carr_2024_aud_mortality_rr(float(grams_per_day))
    population_rr = alcohol_population_rr_expectation(dose_weights)
    return person_rr / max(population_rr, 1e-12), person_rr, population_rr


def alcohol_population_abstainer_share(country: str, sex: str) -> tuple[float, str]:
    """Return past-year abstainer share used by evidence-v3-popdist."""
    country_key = str(country).lower()
    sex_key = "male" if str(sex).lower().startswith("m") else "female"
    try:
        share, source = ALCOHOL_POPULATION_ABSTAINER_SHARE[country_key][sex_key]
    except KeyError as exc:
        raise CauseDataError(f"no alcohol abstainer-share input for {country}/{sex}") from exc
    return float(share), str(source)


def _carr_2024_aud_mortality_rr_for_popdist(grams_per_day: float) -> float:
    """Carr RR used inside the population exposure integral.

    Carr reports the AUD-mortality curve through 100 g/day.  The WHO exposure
    distribution itself extends to 150 g/day, but extrapolating Carr's
    log-linear curve beyond its reported support would make the upper tail
    dominate E[RR(D)] through an invented exponential continuation.  For the
    population-normalization denominator only, hold RR flat above 100 g/day.
    """
    dose = min(max(0.0, float(grams_per_day)), ALCOHOL_CARR_POPDIST_RR_CAP_G_DAY)
    return carr_2024_aud_mortality_rr(dose)


def alcohol_population_gamma_rr_expectation(
    *,
    country: str,
    sex: str,
) -> tuple[float, dict[str, float | str]]:
    """Estimate population E[Carr RR(D)] using the WHO Gamma exposure method.

    Returns (population_mean_rr, diagnostics).  The Gamma component describes
    current drinkers only; abstainers are a point mass at RR=1.  The density is
    numerically normalized on (0, 150] g/day, matching WHO's distribution cap.
    """
    country_key = str(country).lower()
    sex_key = "male" if str(sex).lower().startswith("m") else "female"
    cache_key = (country_key, sex_key)
    cached = _ALCOHOL_POPDIST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    apc_dose, apc_source = alcohol_population_anchor(country_key, sex_key)
    abstainer_share, abstainer_source = alcohol_population_abstainer_share(country_key, sex_key)
    current_drinker_share = 1.0 - abstainer_share
    if current_drinker_share <= 0.0:
        diagnostics: dict[str, float | str] = {
            "abstainer_share": abstainer_share,
            "current_drinker_share": current_drinker_share,
            "apc_g_day": apc_dose,
            "drinker_mean_g_day": 0.0,
            "drinker_sd_g_day": 0.0,
            "gamma_shape": 0.0,
            "gamma_scale": 0.0,
            "gamma_retained_mass": 0.0,
            "gamma_truncated_mean_g_day": 0.0,
            "drinker_mean_rr": 1.0,
            "population_mean_rr": 1.0,
            "apc_source": apc_source,
            "abstainer_source": abstainer_source,
        }
        result = (1.0, diagnostics)
        _ALCOHOL_POPDIST_CACHE[cache_key] = result
        return result

    consumed_population_mean = ALCOHOL_GAMMA_APC_CONSUMED_FRACTION * apc_dose
    drinker_mean = consumed_population_mean / current_drinker_share
    sd_ratio = ALCOHOL_GAMMA_SD_PER_MEAN[sex_key]
    drinker_sd = sd_ratio * drinker_mean
    shape = (drinker_mean / drinker_sd) ** 2
    scale = (drinker_sd * drinker_sd) / drinker_mean

    # For the fitted alcohol distributions shape is commonly < 1, so the
    # ordinary Gamma density has an integrable singularity at x=0.  Integrate
    # after the substitution u=x**shape: the x**(shape-1) term cancels with
    # dx/du, leaving a smooth integrand at the origin.  This avoids the
    # systematic near-zero error of a fixed-width x-space midpoint rule while
    # keeping the implementation dependency-free and deterministic.
    upper = ALCOHOL_GAMMA_MAX_G_DAY
    bins = max(1, int(ALCOHOL_GAMMA_INTEGRATION_BINS))
    u_upper = upper ** shape
    du = u_upper / bins
    transformed_norm = math.gamma(shape) * (scale ** shape) * shape
    retained_mass = 0.0
    weighted_rr = 0.0
    weighted_dose = 0.0
    for idx in range(bins):
        u = (idx + 0.5) * du
        dose = u ** (1.0 / shape)
        mass = math.exp(-dose / scale) * du / transformed_norm
        retained_mass += mass
        weighted_rr += mass * _carr_2024_aud_mortality_rr_for_popdist(dose)
        weighted_dose += mass * dose

    if retained_mass <= 0.0 or not math.isfinite(retained_mass):
        raise CauseDataError(f"failed to normalize alcohol Gamma distribution for {country}/{sex}")

    drinker_mean_rr = weighted_rr / retained_mass
    truncated_mean = weighted_dose / retained_mass
    population_mean_rr = abstainer_share * 1.0 + current_drinker_share * drinker_mean_rr
    diagnostics = {
        "abstainer_share": abstainer_share,
        "current_drinker_share": current_drinker_share,
        "apc_g_day": apc_dose,
        "consumed_population_mean_g_day": consumed_population_mean,
        "drinker_mean_g_day": drinker_mean,
        "drinker_sd_g_day": drinker_sd,
        "gamma_shape": shape,
        "gamma_scale": scale,
        "gamma_retained_mass": retained_mass,
        "gamma_truncated_mean_g_day": truncated_mean,
        "drinker_mean_rr": drinker_mean_rr,
        "population_mean_rr": population_mean_rr,
        "apc_source": apc_source,
        "abstainer_source": abstainer_source,
    }
    result = (population_mean_rr, diagnostics)
    _ALCOHOL_POPDIST_CACHE[cache_key] = result
    return result


def carr_2024_population_distribution_normalized_rr(
    *,
    country: str,
    sex: str,
    grams_per_day: float | None = None,
) -> tuple[float, float, float, dict[str, float | str]]:
    """Normalize a person's Carr RR by WHO-style population E[RR(D)]."""
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    person_rr = carr_2024_aud_mortality_rr(dose)
    population_rr, diagnostics = alcohol_population_gamma_rr_expectation(country=country, sex=sex)
    return person_rr / max(population_rr, 1e-12), person_rr, population_rr, diagnostics


def alcohol_population_distribution_summary(country: str, sex: str) -> list[str]:
    """Human-readable evidence-v3-popdist normalization diagnostics."""
    population_rr, d = alcohol_population_gamma_rr_expectation(country=country, sex=sex)
    return [
        (
            f"population exposure model: WHO-style Gamma current-drinker distribution | "
            f"abstainers {float(d['abstainer_share']) * 100:.1f}% | "
            f"current-drinker mean {float(d['drinker_mean_g_day']):.1f} g/day"
        ),
        (
            f"Gamma parameters: shape {float(d['gamma_shape']):.3f} | "
            f"scale {float(d['gamma_scale']):.1f} g/day | cap {ALCOHOL_GAMMA_MAX_G_DAY:.0f} g/day | "
            f"population Carr E[RR] {population_rr:.3f}"
        ),
        (
            f"population exposure sources: APC {d['apc_source']} | abstainers {d['abstainer_source']}"
        ),
        (
            f"population-model caveat: WHO/Rehm/Kehoe Gamma method uses {ALCOHOL_GAMMA_APC_CONSUMED_FRACTION:.0%} of APC; "
            f"Carr RR is held flat above {ALCOHOL_CARR_POPDIST_RR_CAP_G_DAY:.0f} g/day inside E[RR] because Carr reports through 100 g/day"
        ),
    ]


def carr_2024_population_normalized_rr(
    *,
    country: str,
    sex: str,
    grams_per_day: float | None = None,
) -> tuple[float, float, float, str]:
    """Normalize Carr RR to the population exposure already embedded in qx.

    Returns (relative_multiplier, raw_person_rr, anchor_rr, source).  dev4 uses
    Carr(RR at mean dose) as a first-order approximation to the population mean
    risk.  It is intentionally not presented as full exposure-distribution
    deconvolution.
    """
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    anchor_dose, source = alcohol_population_anchor(country, sex)
    person_rr = carr_2024_aud_mortality_rr(dose)
    anchor_rr = carr_2024_aud_mortality_rr(anchor_dose)
    return person_rr / max(anchor_rr, 1e-12), person_rr, anchor_rr, source


def nature_2026_cancer_rr(site: str, grams_per_day: float | None = None) -> float:
    """Dai et al. 2026 mean cancer RR versus no alcohol, capped at 100 g/day."""
    try:
        knots = NATURE_2026_CANCER_RR[str(site)]
    except KeyError as exc:
        raise ValueError(f"unknown Nature 2026 cancer site: {site!r}") from exc
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    dose = min(max(0.0, dose), NATURE_2026_CANCER_RR_CAP_G_DAY)
    return _log_linear_rr_from_knots(dose, knots)


def _nature_2026_cancer_site_for_icd(code: str, *, sex: str) -> str | None:
    """Map an ICD-10 code to one of the ten Dai et al. 2026 cancer outcomes."""
    norm = _normalise_who_icd_code(code)
    match = re.match(r"^C(\d{2})", norm)
    if not match:
        return None
    number = int(match.group(1))
    if 0 <= number <= 8:
        return "lip_oral"
    if number in {9, 10, 12, 13, 14}:
        # The Nature outcome is other pharyngeal cancer and explicitly excludes C11 nasopharynx.
        return "pharyngeal"
    if number == 15:
        return "oesophageal"
    if number == 16:
        return "stomach"
    if 18 <= number <= 21:
        return "colorectal"
    if number == 22:
        return "liver"
    if number == 25:
        return "pancreatic"
    if number == 32:
        return "laryngeal"
    if number == 50 and str(sex).lower().startswith("f"):
        return "breast"
    if number == 61 and str(sex).lower().startswith("m"):
        return "prostate"
    return None


def nature_2026_cancer_population_gamma_rr_expectation(
    *,
    site: str,
    country: str,
    sex: str,
) -> tuple[float, dict[str, float | str]]:
    """Population E[site-specific cancer RR(D)] using the v3 WHO Gamma exposure model."""
    country_key = str(country).lower()
    sex_key = "male" if str(sex).lower().startswith("m") else "female"
    site_key = str(site)
    cache_key = (site_key, country_key, sex_key)
    cached = _NATURE_2026_CANCER_POPDIST_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Reuse the v3 distribution diagnostics so v4 is mathematically anchored to
    # exactly the same country/sex exposure distribution as direct-alcohol risk.
    _carr_population_rr, base = alcohol_population_gamma_rr_expectation(
        country=country_key, sex=sex_key
    )
    abstainer_share = float(base["abstainer_share"])
    current_drinker_share = float(base["current_drinker_share"])
    if current_drinker_share <= 0.0:
        diagnostics = dict(base)
        diagnostics.update({"site": site_key, "drinker_mean_rr": 1.0, "population_mean_rr": 1.0})
        result = (1.0, diagnostics)
        _NATURE_2026_CANCER_POPDIST_CACHE[cache_key] = result
        return result

    shape = float(base["gamma_shape"])
    scale = float(base["gamma_scale"])
    upper = ALCOHOL_GAMMA_MAX_G_DAY
    bins = max(1, int(ALCOHOL_GAMMA_INTEGRATION_BINS))
    u_upper = upper ** shape
    du = u_upper / bins
    transformed_norm = math.gamma(shape) * (scale ** shape) * shape
    retained_mass = 0.0
    weighted_rr = 0.0
    for idx in range(bins):
        u = (idx + 0.5) * du
        dose = u ** (1.0 / shape)
        mass = math.exp(-dose / scale) * du / transformed_norm
        retained_mass += mass
        weighted_rr += mass * nature_2026_cancer_rr(site_key, dose)

    if retained_mass <= 0.0 or not math.isfinite(retained_mass):
        raise CauseDataError(
            f"failed to normalize Nature 2026 cancer RR distribution for {site_key} {country}/{sex}"
        )
    drinker_mean_rr = weighted_rr / retained_mass
    population_mean_rr = abstainer_share + current_drinker_share * drinker_mean_rr
    diagnostics = dict(base)
    diagnostics.update({
        "site": site_key,
        "drinker_mean_rr": drinker_mean_rr,
        "population_mean_rr": population_mean_rr,
    })
    result = (population_mean_rr, diagnostics)
    _NATURE_2026_CANCER_POPDIST_CACHE[cache_key] = result
    return result


def nature_2026_cancer_population_distribution_normalized_rr(
    *,
    site: str,
    country: str,
    sex: str,
    grams_per_day: float | None = None,
) -> tuple[float, float, float, dict[str, float | str]]:
    """Return site RR relative to the alcohol exposure already embedded in population qx."""
    dose = ACTIVE_BOOZEHOUND_GRAMS_PER_DAY if grams_per_day is None else float(grams_per_day)
    person_rr = nature_2026_cancer_rr(site, dose)
    population_rr, diagnostics = nature_2026_cancer_population_gamma_rr_expectation(
        site=site, country=country, sex=sex
    )
    return person_rr / max(population_rr, 1e-12), person_rr, population_rr, diagnostics


def cause_hazard_weight_model_label() -> str:
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
        return "EVIDENCE-V4 CANCER (V3 DIRECT-ALCOHOL + NATURE HEALTH 2026 CANCER SUBHAZARDS)"
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v3-popdist":
        return "EVIDENCE-V3 POPDIST (CARR DIRECT-ALCOHOL HAZARD / WHO GAMMA POPULATION E[RR])"
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
        return "EVIDENCE-V2 POPNORM (CARR DIRECT-ALCOHOL HAZARD / POPULATION APC ANCHOR)"
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v1":
        return "EVIDENCE-V1 HYBRID (CARR 2024 DIRECT-ALCOHOL HAZARD)"
    return "PROXY-V1 (DEV1/DEV2 BROAD WEIGHTS)"


def _is_direct_alcohol_icd(code: str) -> bool:
    norm = _normalise_who_icd_code(code)
    if not norm:
        return False
    if norm == "X45":
        return True
    if norm.startswith("F10") or norm.startswith("K70"):
        return True
    return norm in {"G312", "G4051", "G621", "G721", "I426", "K292", "K852", "K860"}


def _boozehound_icd_hazard_effective_rr(
    code: str,
    *,
    age: int,
    sex: str,
    country: str,
) -> tuple[float, float, str, float, str]:
    """ICD-level hazard multiplier used by Canada cause-hazard prototype."""
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {"evidence-v1", "evidence-v2-popnorm", "evidence-v3-popdist", "evidence-v4-cancer"} and _is_direct_alcohol_icd(code):
        if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {"evidence-v3-popdist", "evidence-v4-cancer"}:
            target, raw_rr, population_rr, diagnostics = carr_2024_population_distribution_normalized_rr(
                country=country, sex=sex
            )
            basis = (
                f"Carr 2024 direct-alcohol mortality / WHO Gamma population E[RR]; "
                f"raw RR={raw_rr:.3f}, population E[RR]={population_rr:.3f}; "
                f"{diagnostics['apc_source']}; {diagnostics['abstainer_source']}"
            )
        elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
            target, raw_rr, anchor_rr, source = carr_2024_population_normalized_rr(
                country=country, sex=sex
            )
            basis = (
                f"Carr 2024 direct-alcohol mortality / population APC anchor; "
                f"raw RR={raw_rr:.3f}, anchor RR={anchor_rr:.3f}; {source}"
            )
        else:
            target = carr_2024_aud_mortality_rr()
            basis = "Carr 2024 AUD/alcohol-poisoning mortality dose-response"
        profile = "direct_chronic"
        effective, fraction = _boozehound_duration_rr(target, age=age, profile=profile)
        return effective, target, profile, fraction, basis

    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
        site = _nature_2026_cancer_site_for_icd(code, sex=sex)
        if site is not None:
            target, raw_rr, population_rr, diagnostics = nature_2026_cancer_population_distribution_normalized_rr(
                site=site, country=country, sex=sex
            )
            profile = "cancer"
            effective, fraction = _boozehound_duration_rr(target, age=age, profile=profile)
            basis = (
                f"Dai et al. Nature Health 2026 {site} cancer RR / WHO Gamma population E[RR]; "
                f"raw RR={raw_rr:.3f}, population E[RR]={population_rr:.3f}; "
                f"{diagnostics['apc_source']}; {diagnostics['abstainer_source']}"
            )
            return effective, target, profile, fraction, basis

    effective, target, profile, fraction = boozehound_icd_effective_rr(code, age=age, sex=sex)
    return effective, target, profile, fraction, "proxy-v1 fallback"


def _boozehound_finland_broad_hazard_effective_rr(
    label: str,
    *,
    age: int,
    sex: str,
    parent_count: int | None = None,
    lookup_year: int | None = None,
    detail_resolver: "CauseDetailResolver | None" = None,
) -> tuple[float, float, str, float, str]:
    """Cause-hazard weight used by the experimental mortality engine.

    evidence-v4-cancer keeps v3's direct-alcohol normalization and replaces
    the heterogeneous flat neoplasm proxy with a count-weighted 11be ICD-10
    reconstruction.  The same ICD-level v4 function is used by the specific
    cause-detail roulette, including unresolved/suppressed residual mass at
    multiplier 1.0.
    """
    if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {
        "evidence-v1", "evidence-v2-popnorm", "evidence-v3-popdist", "evidence-v4-cancer"
    } and label.startswith("41 "):
        if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {"evidence-v3-popdist", "evidence-v4-cancer"}:
            target, raw_rr, population_rr, diagnostics = carr_2024_population_distribution_normalized_rr(
                country="fi", sex=sex
            )
            basis = (
                f"Carr 2024 direct-alcohol mortality / WHO Gamma population E[RR]; "
                f"raw RR={raw_rr:.3f}, population E[RR]={population_rr:.3f}; "
                f"{diagnostics['apc_source']}; {diagnostics['abstainer_source']}"
            )
        elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
            target, raw_rr, anchor_rr, source = carr_2024_population_normalized_rr(
                country="fi", sex=sex
            )
            basis = (
                f"Carr 2024 direct-alcohol mortality / population APC anchor; "
                f"raw RR={raw_rr:.3f}, anchor RR={anchor_rr:.3f}; {source}"
            )
        else:
            target = carr_2024_aud_mortality_rr()
            basis = "Carr 2024 AUD/alcohol-poisoning mortality dose-response"
        profile = "direct_chronic"
        effective, fraction = _boozehound_duration_rr(target, age=age, profile=profile)
        return effective, target, profile, fraction, basis

    if (
        ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer"
        and (label.startswith("04-22 ") or "neoplasm" in label.casefold())
        and parent_count is not None
        and lookup_year is not None
        and detail_resolver is not None
    ):
        return _statfin_neoplasm_hazard_rr_from_detail(
            resolver=detail_resolver,
            parent_count=max(0, int(parent_count)),
            year=int(lookup_year),
            sex=sex,
            age=age,
        )

    effective, target, profile, fraction = boozehound_finland_broad_effective_rr(
        label, age=age, sex=sex
    )
    basis = (
        "proxy-v1 fallback (v4 neoplasm detail context unavailable)"
        if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer"
        and (label.startswith("04-22 ") or "neoplasm" in label.casefold())
        else "proxy-v1 fallback"
    )
    return effective, target, profile, fraction, basis

def _boozehound_finland_broad_target(label: str, *, sex: str) -> tuple[float, str]:
    """Full target weight + latency profile for broad StatFin cause groups."""
    text = label.casefold()
    if label.startswith("41 "):
        return 4.2, "direct_chronic"
    if label.startswith("04-22 ") or "neoplasm" in text:
        return 1.30, "cancer"
    if label.startswith("25 ") or "dementia" in text or "alzheimer" in text:
        return 1.18, "dementia"
    if label.startswith("27-30 ") or "circulatory" in text:
        return 1.35, "vascular"
    if label.startswith("36 ") or "digestive" in text:
        return 2.00, "liver"
    if label.startswith("42-53 ") or "accidents and violence" in text:
        return 1.90, "acute"
    if label.startswith("26 ") or "nervous system" in text:
        return 1.15, "neuro"
    if label.startswith("23-24 ") or "endocrine" in text:
        return 1.10, "chronic"
    if label.startswith("31-35 ") or "respiratory" in text:
        return 1.05, "chronic"
    if label.startswith("01-03 ") or "infectious" in text:
        return 1.10, "chronic"
    if label.startswith("37 ") or "genitourinary" in text:
        return 1.05, "chronic"
    return 1.0, "chronic"


def boozehound_finland_broad_rr(label: str, *, sex: str) -> float:
    """Dose-adjusted full target broad cause-shape weight."""
    target_60, _profile = _boozehound_finland_broad_target(label, sex=sex)
    return _boozehound_dose_scale_rr(target_60)


def boozehound_finland_broad_effective_rr(
    label: str,
    *,
    age: int,
    sex: str,
) -> tuple[float, float, str, float]:
    target_60, profile = _boozehound_finland_broad_target(label, sex=sex)
    target = _boozehound_dose_scale_rr(target_60)
    effective, fraction = _boozehound_duration_rr(target, age=age, profile=profile)
    return effective, target, profile, fraction


def boozehound_cumulative_survival_metrics(
    exact_age: int,
    sex: str,
    *,
    start_age: int = 0,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> dict[str, float]:
    """Model cumulative survival effect from exposure start to exact_age.

    This is the mathematically valid cumulative component of the alcohol model:
    elevated annual hazards compound through the survival product. It is not a
    clinical damage score and does not invent unobserved diagnoses.
    """
    first_age = ACTIVE_BOOZEHOUND_START_AGE
    if birth_year is not None and cohort_source is not None:
        first_age = max(first_age, int(cohort_source.min_year) - int(birth_year))
    last_age = max(first_age, int(exact_age))
    baseline_survival = 1.0
    adjusted_survival = 1.0
    baseline_hazard = 0.0
    adjusted_hazard = 0.0

    for a in range(first_age, last_age):
        if birth_year is None:
            q0, _tail = q_for_age(a, sex)
        else:
            if cohort_source is None:
                raise CohortDataError("internal error: cumulative boozehound metrics missing cohort source")
            q0, _source, _tail = cohort_q_for_age(
                age=a,
                sex=sex,
                birth_year=birth_year,
                source=cohort_source,
            )
        q1, _rr, _diag = alcohol_adjust_q(
            q0,
            age=a,
            sex=sex,
            cause_source=alcohol_cause_source,
        )
        q0 = min(1.0, max(0.0, q0))
        q1 = min(1.0, max(0.0, q1))
        baseline_survival *= (1.0 - q0)
        adjusted_survival *= (1.0 - q1)
        if q0 < 1.0:
            baseline_hazard += -math.log1p(-q0)
        else:
            baseline_hazard = math.inf
        if q1 < 1.0:
            adjusted_hazard += -math.log1p(-q1)
        else:
            adjusted_hazard = math.inf

    if baseline_survival > 0.0:
        survival_ratio = adjusted_survival / baseline_survival
    else:
        survival_ratio = float("nan")
    excess_hazard = adjusted_hazard - baseline_hazard
    return {
        "baseline_survival": baseline_survival,
        "adjusted_survival": adjusted_survival,
        "survival_ratio": survival_ratio,
        "relative_survival_reduction": max(0.0, 1.0 - survival_ratio) if math.isfinite(survival_ratio) else float("nan"),
        "baseline_hazard": baseline_hazard,
        "adjusted_hazard": adjusted_hazard,
        "cumulative_excess_hazard": excess_hazard,
    }


def boozehound_beverage_equivalents(ethanol_kg: float) -> dict[str, float]:
    """Return descriptive package-volume equivalents for pure ethanol mass.

    These are display-only conversions using the same ethanol density already
    used by the wino preset. They do not feed back into mortality or cause risk.
    """
    ethanol_g = max(0.0, float(ethanol_kg)) * 1000.0
    pure_ethanol_l = ethanol_g / (ETHANOL_DENSITY_G_PER_ML * 1000.0)
    wine_g_per_bottle = (
        BOOZEHOUND_WINO_BOTTLE_ML
        * BOOZEHOUND_WINO_ABV
        * ETHANOL_DENSITY_G_PER_ML
    )
    vodka_g_per_bottle = (
        BOOZEHOUND_EQ_VODKA_BOTTLE_ML
        * BOOZEHOUND_EQ_VODKA_ABV
        * ETHANOL_DENSITY_G_PER_ML
    )
    return {
        "pure_ethanol_l": pure_ethanol_l,
        "wine_bottles": ethanol_g / wine_g_per_bottle if wine_g_per_bottle > 0 else float("nan"),
        "vodka_bottles": ethanol_g / vodka_g_per_bottle if vodka_g_per_bottle > 0 else float("nan"),
    }


def print_boozehound_exposure_summary(
    age: int,
    sex: str,
    *,
    start_age: int = 0,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> None:
    if not boozehound_exposure_has_started(age):
        return
    years = boozehound_exposure_years(age)
    kg = boozehound_cumulative_ethanol_kg(age)
    if ACTIVE_ALCOHOL_MODEL == "legacy":
        effective = boozehound_mortality_multiplier(age, sex)
        target = boozehound_all_cause_target_rr(sex)
    else:
        _q_preview, effective, _diag = alcohol_adjust_q(
            0.01,
            age=age,
            sex=sex,
            cause_source=alcohol_cause_source,
        )
        target = None
    icon = boozehound_preset_icon()
    label = boozehound_preset_label()
    metrics = boozehound_cumulative_survival_metrics(
        age,
        sex,
        start_age=start_age,
        birth_year=birth_year,
        cohort_source=cohort_source,
        alcohol_cause_source=alcohol_cause_source,
    )
    print()
    print_country_section_heading(f"{label} EXPOSURE")
    if ACTIVE_BOOZEHOUND_END_AGE is None or age < ACTIVE_BOOZEHOUND_END_AGE:
        print(
            f"continuous exposure by midpoint of fatal year: {years:.1f} years at "
            f"{ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g/day"
        )
    else:
        print(
            f"completed exposure before death: {years:.1f} years at "
            f"{ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g/day"
        )
    for line in boozehound_schedule_lines():
        print(line)
    if ACTIVE_BOOZEHOUND_PRESET == "wino":
        print(
            f"preset: one {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottle of "
            f"{BOOZEHOUND_WINO_ABV * 100:.0f}% ABV wine per day"
        )
    equivalents = boozehound_beverage_equivalents(kg)
    print(
        f"approx. cumulative pure ethanol: {kg:,.0f} kg "
        f"(≈{equivalents['pure_ethanol_l']:,.0f} L pure ethanol)"
    )
    print("same ethanol quantity as (descriptive equivalents, not additional consumption):")
    print(
        f"  ≈{equivalents['wine_bottles']:,.0f} × {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottles "
        f"of {BOOZEHOUND_WINO_ABV * 100:.0f}% ABV wine"
    )
    print(
        f"  ≈{equivalents['vodka_bottles']:,.0f} × {BOOZEHOUND_EQ_VODKA_BOTTLE_ML:.0f} mL bottles "
        f"of {BOOZEHOUND_EQ_VODKA_ABV * 100:.0f}% ABV vodka"
    )
    print(f"alcohol risk engine: {alcohol_model_label()}")
    if ACTIVE_ALCOHOL_MODEL == "legacy":
        print(f"all-cause hazard RR this year: ×{effective:.3f} (chronic-exposure target ×{target:.2f})")
    else:
        print(f"prototype effective total-hazard multiplier this year: ×{effective:.3f}")
        print(f"cause-hazard weight model: {cause_hazard_weight_model_label()}")
        if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
            for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                print(line)
            print("evidence-v4 coverage: v3 direct-alcohol normalization + Dai et al. Nature Health 2026 cancer subhazards; Finland neoplasms are reconstructed from the reconciled StatFin 11be C00-D48 cell")
            print("prototype warning: non-cancer/non-direct alcohol-sensitive causes still include proxy-v1 fallbacks")
        elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v3-popdist":
            for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                print(line)
            print("prototype warning: distribution-based population normalization is implemented only for the direct-alcohol hazard; remaining broad hazards still include proxy-v1 fallbacks")
        elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
            anchor_g, source = alcohol_population_anchor(ACTIVE_COUNTRY, sex)
            print(f"population-normalization anchor: {anchor_g:.1f} g/day mean-dose equivalent | {source}")
            print("prototype warning: first-order mean-dose population normalization; full exposure-distribution deconvolution not yet implemented")
        elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v1":
            print("prototype warning: raw Carr direct-alcohol RR is layered onto a population baseline that already contains alcohol exposure")
        else:
            print("prototype warning: provisional cause weights; background population alcohol not deconvolved")
    if ACTIVE_BOOZEHOUND_END_AGE is not None and age >= ACTIVE_BOOZEHOUND_END_AGE:
        print(
            "cessation model: current alcohol hazard/cause reweighting returns to baseline after the stop age; "
            "post-cessation residual-risk decay is not yet calibrated"
        )
    print(
        f"modeled survival from exposure-model age {ACTIVE_BOOZEHOUND_START_AGE} to exact age {age}: "
        f"baseline {metrics['baseline_survival'] * 100:.2f}% | {icon} preset {metrics['adjusted_survival'] * 100:.2f}%"
    )
    print(
        f"cumulative survival ratio: {metrics['survival_ratio']:.3f} "
        f"({metrics['relative_survival_reduction'] * 100:.1f}% relative survival reduction vs baseline by this age)"
    )
    print(f"cumulative excess mortality hazard: {metrics['cumulative_excess_hazard']:.3f}")
    if ACTIVE_ALCOHOL_MODEL == "legacy":
        print("mortality math: alcohol RR is applied to annual hazard; repeated yearly excess hazards compound automatically")
    else:
        if ACTIVE_COUNTRY == "ca":
            print("mortality math: WHO Canada complete-ICD cause hazards are provisionally reweighted, summed, and converted back to annual qx")
        else:
            print("mortality math: StatFin broad-cause hazards are provisionally reweighted, summed, and converted back to annual qx")
    print("generic mortality tables remain untouched; cumulative ethanol kilograms are descriptive, not a direct risk multiplier")
    print("note: disease-specific latency profiles remain scenario assumptions; named comorbidity onset is not invented without incidence data")


def _extract_icd_from_label(label: str) -> str | None:
    match = re.search(r"\b([A-Z][0-9]{2}(?:\.?[A-Z0-9]{1,2})?)\b", label.upper())
    if not match:
        return None
    return _normalise_who_icd_code(match.group(1))


def _weighted_choice_rows_with_weights(
    rows: list[dict[str, object]],
    rng: random.Random,
    *,
    weight_key: str = "_weight",
) -> dict[str, object] | None:
    usable: list[tuple[dict[str, object], float]] = []
    for row in rows:
        try:
            weight = float(row.get(weight_key, row.get("count", 0)))
        except (TypeError, ValueError):
            continue
        if weight > 0:
            usable.append((row, weight))
    total = sum(weight for _, weight in usable)
    if total <= 0:
        return None
    target = rng.random() * total
    running = 0.0
    for row, weight in usable:
        running += weight
        if target < running:
            out = dict(row)
            out["adjusted_denominator"] = total
            out["conditional_probability"] = weight / total
            return out
    row, weight = usable[-1]
    out = dict(row)
    out["adjusted_denominator"] = total
    out["conditional_probability"] = weight / total
    return out


class CauseOfDeathSource:
    """Cached conditional cause-of-death distributions from StatFin 11az."""

    def __init__(
        self,
        *,
        name: str,
        min_year: int,
        max_year: int,
        data: dict[str, dict[int, dict[str, dict[str, int]]]],
    ) -> None:
        self.name = name
        self.min_year = min_year
        self.max_year = max_year
        self.data = data
        self._compiled: dict[
            tuple[str, int, str],
            tuple[list[float], list[str], float],
        ] = {}
        self._age_label_cache: dict[tuple[str, int, int], str | None] = {}

    def _distribution(
        self,
        sex: str,
        lookup_year: int,
        age: int,
    ) -> tuple[list[float], list[str], float, str] | None:
        year_data = self.data.get(sex, {}).get(lookup_year)
        if not year_data:
            return None

        age_cache_key = (sex, lookup_year, age)
        if age_cache_key in self._age_label_cache:
            age_label = self._age_label_cache[age_cache_key]
        else:
            age_label = choose_age_label(age, list(year_data.keys()))
            self._age_label_cache[age_cache_key] = age_label
        if age_label is None:
            return None

        key = (sex, lookup_year, age_label)
        compiled = self._compiled.get(key)

        if compiled is None:
            counts = year_data[age_label]
            labels: list[str] = []
            cumulative: list[float] = []
            running = 0.0

            # Stable source order for reproducibility.
            for label, count in counts.items():
                count = int(count)
                if count <= 0:
                    continue
                running += count
                labels.append(label)
                cumulative.append(running)

            if running <= 0:
                return None

            compiled = (cumulative, labels, running)
            self._compiled[key] = compiled

        cumulative, labels, total = compiled
        return cumulative, labels, total, age_label

    def counts_for(
        self,
        *,
        sex: str,
        age: int,
        calendar_year: int | None,
    ) -> dict[str, object]:
        """Return the resolved broad-cause cell without consuming RNG."""
        if calendar_year is None:
            requested_year = self.max_year
            lookup_year = self.max_year
            year_status = "latest observed year"
        elif calendar_year < self.min_year:
            return {
                "available": False,
                "reason": (
                    f"cause-of-death data begin in {self.min_year}; "
                    f"requested year is {calendar_year}"
                ),
                "calendar_year": calendar_year,
            }
        elif calendar_year > self.max_year:
            requested_year = calendar_year
            lookup_year = self.max_year
            year_status = f"future hold at {self.max_year}"
        else:
            requested_year = calendar_year
            lookup_year = calendar_year
            year_status = "observed year"

        dist = self._distribution(sex, lookup_year, age)
        if dist is None:
            return {
                "available": False,
                "reason": (
                    f"no usable {self.name} distribution for "
                    f"{sex}, age {age}, year {lookup_year}"
                ),
                "calendar_year": requested_year,
            }
        _cumulative, _labels, total, age_label = dist
        counts = self.data[sex][lookup_year][age_label]
        return {
            "available": True,
            "calendar_year": requested_year,
            "lookup_year": lookup_year,
            "year_status": year_status,
            "age_group": age_label,
            "denominator": int(total),
            "counts": dict(counts),
        }

    def roll(
        self,
        *,
        sex: str,
        age: int,
        calendar_year: int | None,
        rng: random.Random,
    ) -> dict[str, object]:
        if calendar_year is None:
            requested_year = self.max_year
            lookup_year = self.max_year
            year_status = "latest observed year"
        elif calendar_year < self.min_year:
            return {
                "available": False,
                "reason": (
                    f"cause-of-death data begin in {self.min_year}; "
                    f"death occurred in {calendar_year}"
                ),
                "calendar_year": calendar_year,
            }
        elif calendar_year > self.max_year:
            requested_year = calendar_year
            lookup_year = self.max_year
            year_status = f"future hold at {self.max_year}"
        else:
            requested_year = calendar_year
            lookup_year = calendar_year
            year_status = "observed year"

        dist = self._distribution(sex, lookup_year, age)
        if dist is None:
            return {
                "available": False,
                "reason": (
                    f"no usable {self.name} distribution for "
                    f"{sex}, age {age}, year {lookup_year}"
                ),
                "calendar_year": requested_year,
            }

        cumulative, labels, total, age_label = dist
        baseline_probability = None
        cause_modifier = 1.0

        if boozehound_active_for_age(age):
            counts = self.data[sex][lookup_year][age_label]
            rows: list[dict[str, object]] = []
            for candidate_label, raw_count in counts.items():
                count_i = int(raw_count)
                if count_i <= 0:
                    continue
                if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                    mult, target_mult, profile, maturity, evidence_basis = _boozehound_finland_broad_hazard_effective_rr(
                        candidate_label, age=age, sex=sex,
                        parent_count=count_i,
                        lookup_year=lookup_year,
                        detail_resolver=getattr(self, "_alcohol_detail_resolver", None),
                    )
                else:
                    mult, target_mult, profile, maturity = boozehound_finland_broad_effective_rr(
                        candidate_label, age=age, sex=sex
                    )
                    evidence_basis = "legacy conditional cause proxy"
                rows.append({
                    "label": candidate_label,
                    "count": count_i,
                    "_weight": count_i * mult,
                    "cause_modifier": mult,
                    "cause_modifier_target": target_mult,
                    "boozehound_profile": profile,
                    "boozehound_maturity": maturity,
                    "cause_weight_basis": evidence_basis,
                })
            chosen = _weighted_choice_rows_with_weights(rows, rng)
            if chosen is None:
                return {"available": False, "reason": "boozehound-adjusted cause cell contains no usable deaths"}
            label = str(chosen["label"])
            count = int(chosen["count"])
            cause_modifier = float(chosen.get("cause_modifier", 1.0))
            baseline_probability = count / total
            conditional_probability = float(chosen["conditional_probability"])
        else:
            roll = rng.random() * total
            index = bisect.bisect_right(cumulative, roll)
            if index >= len(labels):
                index = len(labels) - 1
            label = labels[index]
            count = (
                cumulative[index]
                - (cumulative[index - 1] if index > 0 else 0.0)
            )
            conditional_probability = count / total

        result = {
            "available": True,
            "label": label,
            "count": int(count),
            "denominator": int(total),
            "conditional_probability": conditional_probability,
            "age_group": age_label,
            "calendar_year": requested_year,
            "lookup_year": lookup_year,
            "year_status": year_status,
            "no_death_certificate": label.startswith("54 "),
            "ill_defined": label.startswith("40 "),
        }
        if baseline_probability is not None:
            result["baseline_conditional_probability"] = baseline_probability
            result["cause_modifier"] = cause_modifier
            result["cause_modifier_target"] = float(chosen.get("cause_modifier_target", cause_modifier))
            result["boozehound_profile"] = str(chosen.get("boozehound_profile", "chronic"))
            result["boozehound_maturity"] = float(chosen.get("boozehound_maturity", 1.0))
            result["boozehound_exposure_years"] = boozehound_exposure_years(age)
            result["boozehound_adjusted"] = True
        return result


def _parse_statfin_cause_jsonstat2(
    dataset: dict,
    *,
    cause_dim: str,
    age_dim: str,
    sex_dim: str,
    year_dim: str,
) -> dict[str, dict[int, dict[str, dict[str, int]]]]:
    ids = list(dataset["id"])
    sizes = list(dataset["size"])
    values = dataset["value"]
    categories = {dim_id: _jsonstat_categories(dataset, dim_id) for dim_id in ids}
    positions = {dim_id: i for i, dim_id in enumerate(ids)}

    if len(values) != _product_int(sizes):
        raise CauseDataError("Unexpected Statistics Finland cause-table value count")

    result: dict[str, dict[int, dict[str, dict[str, int]]]] = {
        "male": {},
        "female": {},
    }

    flat = 0
    for coords in product(*(range(size) for size in sizes)):
        value = values[flat]
        flat += 1

        if value is None:
            continue

        sex_code = categories[sex_dim][coords[positions[sex_dim]]]
        sex_label = _jsonstat_category_label(dataset, sex_dim, sex_code).casefold()
        if sex_label.startswith("male"):
            sex = "male"
        elif sex_label.startswith("female"):
            sex = "female"
        else:
            continue

        year_code = categories[year_dim][coords[positions[year_dim]]]
        try:
            year = int(year_code)
        except ValueError:
            year_label = _jsonstat_category_label(dataset, year_dim, year_code)
            year = int(year_label)

        age_code = categories[age_dim][coords[positions[age_dim]]]
        age_label = _jsonstat_category_label(dataset, age_dim, age_code)

        cause_code = categories[cause_dim][coords[positions[cause_dim]]]
        cause_label = _jsonstat_category_label(dataset, cause_dim, cause_code)

        try:
            count = int(value)
        except (TypeError, ValueError):
            continue

        result[sex].setdefault(year, {}).setdefault(age_label, {})[
            cause_label
        ] = count

    return result


def fetch_statfin_causes(
    cache_path: Path = DEFAULT_CAUSE_CACHE,
    refresh: bool = False,
) -> CauseOfDeathSource:
    """Download/cache Statistics Finland 11az broad cause-of-death counts."""
    if cache_path.exists() and not refresh:
        data_status(f"Statistics Finland causes: using parsed cache {cache_path}")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        data = {
            sex: {
                int(year): {
                    age_label: {
                        cause: int(count)
                        for cause, count in causes.items()
                    }
                    for age_label, causes in ages.items()
                }
                for year, ages in years.items()
            }
            for sex, years in payload["data"].items()
        }
        return CauseOfDeathSource(
            name=payload["name"],
            min_year=int(payload["min_year"]),
            max_year=int(payload["max_year"]),
            data=data,
        )

    data_status("Statistics Finland causes: fetching 11az metadata...")
    try:
        request = urllib.request.Request(
            STATFIN_CAUSE_API,
            headers={"User-Agent": "mortality-roulette/0.9"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            meta = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CauseDataError(
            "Could not download Statistics Finland cause-of-death metadata and "
            f"no usable cache exists at {cache_path}: {exc}"
        ) from exc

    cause_var = _metadata_variable(
        meta, "Underlying cause of death (time series classification)"
    )
    age_var = _metadata_variable(meta, "Age")
    sex_var = _metadata_variable(meta, "Sex")
    year_var = _metadata_variable(meta, "Year")
    info_var = _metadata_variable(meta, "Information")

    cause_codes = _selected_codes_by_prefix(cause_var, BROAD_CAUSE_PREFIXES)
    male_code = _value_code(sex_var, "Males")
    female_code = _value_code(sex_var, "Females")
    info_code = str(info_var["values"][0])

    query = {
        "query": [
            {
                "code": cause_var["code"],
                "selection": {"filter": "item", "values": cause_codes},
            },
            {
                "code": age_var["code"],
                "selection": {
                    "filter": "item",
                    "values": [str(x) for x in age_var["values"]],
                },
            },
            {
                "code": sex_var["code"],
                "selection": {
                    "filter": "item",
                    "values": [male_code, female_code],
                },
            },
            {
                "code": year_var["code"],
                "selection": {
                    "filter": "item",
                    "values": [str(x) for x in year_var["values"]],
                },
            },
            {
                "code": info_var["code"],
                "selection": {"filter": "item", "values": [info_code]},
            },
        ],
        "response": {"format": "json-stat2"},
    }

    body = json.dumps(query).encode("utf-8")

    data_status("Statistics Finland causes: downloading 11az counts...")
    try:
        request = urllib.request.Request(
            STATFIN_CAUSE_API,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "mortality-roulette/0.9",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            dataset = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CauseDataError(
            f"Statistics Finland cause-of-death download failed: {exc}"
        ) from exc

    data = _parse_statfin_cause_jsonstat2(
        dataset,
        cause_dim=str(cause_var["code"]),
        age_dim=str(age_var["code"]),
        sex_dim=str(sex_var["code"]),
        year_dim=str(year_var["code"]),
    )

    common_years = sorted(set(data["male"]) & set(data["female"]))
    if not common_years:
        raise CauseDataError("Statistics Finland response contained no usable cause data")

    source = CauseOfDeathSource(
        name="Statistics Finland 11az",
        min_year=common_years[0],
        max_year=common_years[-1],
        data=data,
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "name": source.name,
        "min_year": source.min_year,
        "max_year": source.max_year,
        "broad_cause_prefixes": list(BROAD_CAUSE_PREFIXES),
        "data": data,
    }
    cache_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    return source


# Standard ICD-10 chapters used for Canadian broad-cause roulette. Canada mode
# derives these from Canada's own civil-registration mortality submission to WHO.
_CANADA_ICD_CHAPTERS: tuple[tuple[str, str], ...] = (
    ("I", "Certain infectious and parasitic diseases (A00-B99)"),
    ("II", "Neoplasms (C00-D48)"),
    ("III", "Diseases of the blood and blood-forming organs and immune disorders (D50-D89)"),
    ("IV", "Endocrine, nutritional and metabolic diseases (E00-E90)"),
    ("V", "Mental and behavioural disorders (F00-F99)"),
    ("VI", "Diseases of the nervous system (G00-G99)"),
    ("VII", "Diseases of the eye and adnexa (H00-H59)"),
    ("VIII", "Diseases of the ear and mastoid process (H60-H95)"),
    ("IX", "Diseases of the circulatory system (I00-I99)"),
    ("X", "Diseases of the respiratory system (J00-J99)"),
    ("XI", "Diseases of the digestive system (K00-K93)"),
    ("XII", "Diseases of the skin and subcutaneous tissue (L00-L98)"),
    ("XIII", "Diseases of the musculoskeletal system and connective tissue (M00-M99)"),
    ("XIV", "Diseases of the genitourinary system (N00-N99)"),
    ("XV", "Pregnancy, childbirth and the puerperium (O00-O99)"),
    ("XVI", "Certain conditions originating in the perinatal period (P00-P96)"),
    ("XVII", "Congenital malformations, deformations and chromosomal abnormalities (Q00-Q99)"),
    ("XVIII", "Symptoms, signs and abnormal findings, not elsewhere classified (R00-R99)"),
    ("XXII", "Codes for special purposes (U00-U99)"),
    ("XX", "External causes of morbidity and mortality (V01-Y89)"),
)
_CANADA_CHAPTER_LABEL = dict(_CANADA_ICD_CHAPTERS)


def _canada_icd_chapter(code: str) -> str:
    code = _normalise_who_icd_code(code)
    if len(code) < 3:
        return "OTHER"
    letter = code[0]
    try:
        num = int(code[1:3])
    except ValueError:
        return "OTHER"
    if letter in {"A", "B"}: return "I"
    if letter == "C" or (letter == "D" and num <= 48): return "II"
    if letter == "D" and 50 <= num <= 89: return "III"
    if letter == "E": return "IV"
    if letter == "F": return "V"
    if letter == "G": return "VI"
    if letter == "H": return "VII" if num <= 59 else "VIII"
    if letter == "I": return "IX"
    if letter == "J": return "X"
    if letter == "K": return "XI"
    if letter == "L": return "XII"
    if letter == "M": return "XIII"
    if letter == "N": return "XIV"
    if letter == "O": return "XV"
    if letter == "P": return "XVI"
    if letter == "Q": return "XVII"
    if letter == "R": return "XVIII"
    if letter == "U": return "XXII"
    if letter in {"V", "W", "X", "Y"}: return "XX"
    return "OTHER"


_CANADA_COMMON_ICD3_LABELS = {
    "C18": "Malignant neoplasm of colon",
    "C20": "Malignant neoplasm of rectum",
    "F10": "Mental and behavioural disorders due to use of alcohol",
    "F11": "Mental and behavioural disorders due to use of opioids",
    "F70": "Mild mental retardation",
    "F71": "Moderate mental retardation",
    "G30": "Alzheimer disease",
    "I21": "Acute myocardial infarction",
    "I25": "Chronic ischaemic heart disease",
    "I50": "Heart failure",
    "I63": "Cerebral infarction",
    "J44": "Other chronic obstructive pulmonary disease",
    "K70": "Alcoholic liver disease",
    "W19": "Unspecified fall",
    "X45": "Accidental poisoning by and exposure to alcohol",
}


def _canada_code_label(code: str) -> str:
    norm = _normalise_who_icd_code(code)
    labelled = _icd_code_label(norm)
    if labelled != _format_icd_code(norm):
        return labelled
    base = _CANADA_COMMON_ICD3_LABELS.get(norm[:3])
    if base and len(norm) == 3:
        return f"{_format_icd_code(norm)} {base}"
    return labelled


class WhoCountryRawMortality:
    """Country/year WHO detailed ICD rows across supported WHO age layouts.

    WHO partitions ICD-10 mortality by archive ranges.  Each archive is opened
    and scanned at most once per process for this country; all usable years in
    that part are cached together.  This avoids the old pathological behaviour
    of reopening/re-downloading one archive once for every candidate year.
    """
    def __init__(self, *, country_code: str, country_name: str, cache_dir: Path, refresh: bool = False) -> None:
        self.country_code = country_code
        self.country_name = country_name
        self.cache_dir = cache_dir
        self.refresh = refresh
        self._year_cache: dict[int, dict[str, object]] = {}
        self._part_cache: dict[int, Path] = {}
        self._part_member_cache: dict[int, str] = {}
        self._part_failures: dict[int, str] = {}
        self._preflight_failures: dict[int, str] = {}
        self._part_scanned: set[int] = set()
        self._part_years: dict[int, set[int]] = {}

    def _zip_path(self, part: int) -> Path:
        return self.cache_dir / f"morticd10_part{part}.zip"

    def _year_json_path(self, year: int) -> Path:
        slug = self.country_name.casefold().replace(" ", "_")
        return self.cache_dir / f"{slug}_complete_icd_{year}.json"

    def _download_part(self, part: int) -> tuple[Path, str]:
        label = f"WHO Mortality Database {self.country_name} ICD-10 archive part {part}"
        return _download_who_mortality_archive(
            part=part,
            cache_dir=self.cache_dir,
            refresh=self.refresh,
            label=label,
            part_cache=self._part_cache,
            member_cache=self._part_member_cache,
            failure_cache=self._part_failures,
        )

    @staticmethod
    def _row_count(row: dict[str, str], columns: tuple[str, ...]) -> int:
        total = 0
        for column in columns:
            value = str(row.get(column, "") or "").strip()
            if not value:
                continue
            try:
                total += int(float(value))
            except ValueError:
                continue
        return total

    @staticmethod
    def _empty_admin_value(value: object) -> bool:
        return str(value or "").strip().casefold() in {"", "nan", "na", "none"}

    @staticmethod
    def _numeric_code(value: object) -> str:
        raw = str(value or "").strip()
        try:
            return str(int(float(raw)))
        except (TypeError, ValueError):
            return raw

    def _write_year_cache(self, payload: dict[str, object]) -> None:
        year = int(payload["year"])
        path = self._year_json_path(year)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        data_status(f"WHO Mortality Database {self.country_name}: parsed year cache written: {path}")

    def _parse_part(self, part: int) -> None:
        if part in self._part_scanned:
            data_status(
                f"WHO Mortality Database {self.country_name}: archive part {part} "
                "already scanned in this process"
            )
            return

        path, member = self._download_part(part)
        label = f"WHO Mortality Database {self.country_name} ICD-10 archive part {part}"
        data_status(f"{label}: opening archive: {path}")
        data_status(f"{label}: reading member: {member!r}")
        data_status(
            f"{label}: scanning ONCE for all {self.country_name} national complete-ICD years in this part..."
        )

        # year -> WHO list -> sex -> age group -> cause -> count
        by_year: dict[int, dict[str, dict[str, dict[str, dict[str, int]]]]] = {}
        seen_frmats: dict[int, set[str]] = {}
        rows_scanned = 0
        country_rows = 0
        usable_rows = 0

        with zipfile.ZipFile(path) as zf:
            with zf.open(member, "r") as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
                reader = csv.DictReader(text)
                if not reader.fieldnames or not _WHO_MORTALITY_REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
                    raise CauseDataError(
                        "WHO mortality data schema changed; required columns missing; "
                        f"header={reader.fieldnames!r}"
                    )
                for row in reader:
                    rows_scanned += 1
                    if self._numeric_code(row.get("Country")) != self._numeric_code(self.country_code):
                        continue
                    country_rows += 1
                    if not self._empty_admin_value(row.get("Admin1")):
                        continue
                    if not self._empty_admin_value(row.get("SubDiv")):
                        continue
                    try:
                        year = int(float(str(row.get("Year", "")).strip()))
                    except ValueError:
                        continue
                    try:
                        sex_num = int(float(str(row.get("Sex", "")).strip()))
                    except ValueError:
                        continue
                    sex = "male" if sex_num == 1 else "female" if sex_num == 2 else None
                    if sex is None:
                        continue
                    try:
                        frmat = f"{int(float(str(row.get('Frmat', '')).strip())):02d}"
                    except ValueError:
                        frmat = str(row.get("Frmat", "")).strip().zfill(2)
                    seen_frmats.setdefault(year, set()).add(frmat)
                    age_columns = _WHO_AGE_COLUMNS_BY_FRMAT.get(frmat)
                    if age_columns is None:
                        continue
                    list_code = self._numeric_code(row.get("List")).upper()
                    # 104 is ICD-10 4-character detail. 10M is mixed 3/4
                    # character detail with mutually exclusive rows. 103 is
                    # 3-character detail: still perfectly usable for Canada's
                    # broad/ICD3 cause roulette, although it cannot refine to
                    # a fourth character. Prefer 104/10M when multiple lists
                    # exist for the same year.
                    if list_code not in {"104", "10M", "103"}:
                        continue
                    cause = _normalise_who_icd_code(str(row.get("Cause", "")))
                    if not re.fullmatch(r"[A-Z][0-9]{2}[A-Z0-9]*", cause):
                        continue
                    usable_rows += 1
                    year_list = by_year.setdefault(year, {})
                    sex_data = year_list.setdefault(
                        list_code, {"male": {}, "female": {}}
                    )[sex]
                    for age_label, columns in age_columns.items():
                        if age_label == "0 - 14":
                            continue
                        count = self._row_count(row, columns)
                        if count <= 0:
                            continue
                        age_counts = sex_data.setdefault(age_label, {})
                        age_counts[cause] = int(age_counts.get(cause, 0)) + count

        usable_years: set[int] = set()
        for year, lists in by_year.items():
            selected = (
                "104" if "104" in lists
                else "10M" if "10M" in lists
                else "103" if "103" in lists
                else None
            )
            if selected is None:
                continue
            formats = sorted(seen_frmats.get(year, set()))
            payload: dict[str, object] = {
                "year": year,
                "who_list": selected,
                "frmat": formats[0] if len(formats) == 1 else formats,
                "data": lists[selected],
            }
            self._year_cache[year] = payload
            usable_years.add(year)
            self._write_year_cache(payload)

        self._part_scanned.add(part)
        self._part_years[part] = usable_years
        years_text = (
            f"{min(usable_years)}–{max(usable_years)} ({len(usable_years)} year(s))"
            if usable_years else "none"
        )
        data_status(
            f"{label}: scan complete: {rows_scanned:,} rows total; "
            f"{country_rows:,} {self.country_name} rows; {usable_rows:,} usable complete-ICD rows; "
            f"usable years: {years_text}"
        )
        if not usable_years and seen_frmats:
            formats = sorted({fmt for values in seen_frmats.values() for fmt in values})
            data_status(f"{label}: {self.country_name} age formats seen: {formats}")

    def latest_available_year(self, *, max_year: int, min_year: int) -> int:
        max_part = _who_icd_part_for_year(max_year)
        min_part = _who_icd_part_for_year(min_year)
        if max_part is None:
            raise CauseDataError(f"WHO ICD-10 mortality unavailable at max year {max_year}")
        if min_part is None:
            min_part = 1
        data_status(
            f"WHO Mortality Database {self.country_name}: finding newest usable year "
            f"{min_year}–{max_year} by archive part (not year-by-year downloads)..."
        )
        for part in range(max_part, min_part - 1, -1):
            try:
                self._parse_part(part)
            except Exception as exc:
                # Structural/network failure is not evidence that Canada lacks
                # data in this period. Stop instead of cascading through and
                # downloading every older WHO archive.
                data_status(
                    f"WHO Mortality Database {self.country_name}: part {part} FAILED; "
                    "stopping latest-year probe instead of downloading older parts"
                )
                raise CauseDataError(
                    f"cannot determine newest {self.country_name} WHO mortality year: "
                    f"archive part {part} failed: {exc}"
                ) from exc
            candidates = [
                year for year in self._part_years.get(part, set())
                if min_year <= year <= max_year
            ]
            if candidates:
                latest = max(candidates)
                data_status(f"WHO Mortality Database {self.country_name}: newest usable year is {latest}")
                return latest
        raise CauseDataError(
            f"no usable {self.country_name} complete-ICD year found in the WHO Mortality Database"
        )

    def load_year(self, year: int) -> dict[str, object]:
        if year in self._year_cache:
            data_status(f"WHO Mortality Database {self.country_name}: process year-cache hit: {year}")
            return self._year_cache[year]

        path = self._year_json_path(year)
        if path.exists() and not self.refresh:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                frmat = payload.get("frmat")
                cached_formats = {str(x).zfill(2) for x in frmat} if isinstance(frmat, list) else {str(frmat).zfill(2)}
                if (
                    int(payload.get("year", -1)) == year
                    and cached_formats
                    and cached_formats.issubset(set(_WHO_AGE_COLUMNS_BY_FRMAT))
                ):
                    data_status(
                        f"WHO Mortality Database {self.country_name}: using parsed {year} cache: "
                        f"{path} (Frmat={sorted(cached_formats)})"
                    )
                    self._year_cache[year] = payload
                    return payload
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                data_status(f"WHO Mortality Database {self.country_name}: parsed {year} cache invalid; reparsing source archive")

        part = _who_icd_part_for_year(year)
        if part is None:
            raise CauseDataError(f"WHO ICD-10 mortality is unavailable for year {year}")
        self._parse_part(part)
        payload = self._year_cache.get(year)
        if payload is not None:
            return payload

        formats = ""
        raise CauseDataError(
            f"no {self.country_name} {year} WHO complete-ICD rows found in archive part {part}"
        )


class CanadaCauseOfDeathSource:
    def __init__(self, raw: WhoCountryRawMortality) -> None:
        self.raw = raw
        self.name = "WHO Mortality Database — Canada civil-registration submission"
        self.min_year = WHO_CANADA_FIRST_ICD10_YEAR
        # 2024 is the newest Canadian mortality year targeted by this release,
        # but WHO submissions can lag. resolve_latest_year() verifies the actual
        # newest Canada year present in the raw complete-ICD files before use.
        self.max_year = WHO_CANADA_LATEST_YEAR

    def resolve_latest_year(self) -> int:
        self.max_year = self.raw.latest_available_year(
            max_year=WHO_CANADA_LATEST_YEAR,
            min_year=self.min_year,
        )
        return self.max_year

    def counts_for(self, *, sex: str, age: int, calendar_year: int | None) -> dict[str, object]:
        """Return the resolved WHO complete-ICD cell without consuming RNG."""
        if calendar_year is None:
            requested_year = lookup_year = self.max_year
            status = "latest observed year"
        elif calendar_year < self.min_year:
            return {
                "available": False,
                "reason": f"Canadian ICD-10 cause data begin in {self.min_year}",
                "calendar_year": calendar_year,
            }
        elif calendar_year > self.max_year:
            requested_year, lookup_year = calendar_year, self.max_year
            status = f"future hold at {self.max_year}"
        else:
            requested_year = lookup_year = calendar_year
            status = "observed year"
        try:
            payload = self.raw.load_year(lookup_year)
            sex_data = dict(dict(payload.get("data", {})).get(sex, {}))
            age_label = choose_age_label(age, list(sex_data.keys()))
            counts = sex_data.get(age_label, {}) if age_label is not None else {}
        except Exception as exc:
            return {
                "available": False,
                "reason": f"Canadian cause lookup failed: {exc}",
                "calendar_year": requested_year,
            }
        if not counts or age_label is None:
            return {
                "available": False,
                "reason": (
                    f"no Canada WHO cell covering {sex}, exact age {age}, {lookup_year}; "
                    f"available age groups={sorted(sex_data) if 'sex_data' in locals() else []}"
                ),
                "calendar_year": requested_year,
            }
        clean = {str(code): max(0, int(count)) for code, count in counts.items() if int(count) > 0}
        return {
            "available": True,
            "calendar_year": requested_year,
            "lookup_year": lookup_year,
            "year_status": status,
            "age_group": age_label,
            "denominator": sum(clean.values()),
            "counts": clean,
            "who_list": payload.get("who_list"),
            "country": "Canada",
        }

    def roll(self, *, sex: str, age: int, calendar_year: int | None, rng: random.Random) -> dict[str, object]:
        if calendar_year is None:
            requested_year = lookup_year = self.max_year
            status = "latest observed year"
        elif calendar_year < self.min_year:
            return {"available": False, "reason": f"Canadian ICD-10 cause data begin in {self.min_year}", "calendar_year": calendar_year}
        elif calendar_year > self.max_year:
            requested_year, lookup_year = calendar_year, self.max_year
            status = f"future hold at {self.max_year}"
        else:
            requested_year = lookup_year = calendar_year
            status = "observed year"
        try:
            payload = self.raw.load_year(lookup_year)
            sex_data = dict(dict(payload.get("data", {})).get(sex, {}))
            age_label = choose_age_label(age, list(sex_data.keys()))
            counts = sex_data.get(age_label, {}) if age_label is not None else {}
        except Exception as exc:
            return {"available": False, "reason": f"Canadian cause lookup failed: {exc}", "calendar_year": requested_year}
        if not counts or age_label is None:
            return {
                "available": False,
                "reason": (
                    f"no Canada WHO cell covering {sex}, exact age {age}, {lookup_year}; "
                    f"available age groups={sorted(sex_data) if 'sex_data' in locals() else []}"
                ),
                "calendar_year": requested_year,
            }
        chapter_counts: dict[str, int] = {}
        chapter_weights: dict[str, float] = {}
        chapter_target_weights: dict[str, float] = {}
        for code, count in counts.items():
            count_i = max(0, int(count))
            if count_i <= 0:
                continue
            chapter = _canada_icd_chapter(str(code))
            chapter_counts[chapter] = chapter_counts.get(chapter, 0) + count_i
            if boozehound_active_for_age(age):
                if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                    mult, target_mult, _profile, _maturity, _basis = _boozehound_icd_hazard_effective_rr(
                        str(code), age=age, sex=sex, country="ca"
                    )
                else:
                    mult, target_mult, _profile, _maturity = boozehound_icd_effective_rr(
                        str(code), age=age, sex=sex
                    )
            else:
                mult = target_mult = 1.0
            chapter_weights[chapter] = chapter_weights.get(chapter, 0.0) + count_i * mult
            chapter_target_weights[chapter] = chapter_target_weights.get(chapter, 0.0) + count_i * target_mult
        rows=[]
        observed_total = sum(chapter_counts.values())
        for key,count in chapter_counts.items():
            if count <= 0: continue
            label = _CANADA_CHAPTER_LABEL.get(key, "Other / unclassified ICD-10 causes")
            weight = chapter_weights.get(key, float(count))
            rows.append({
                "label": f"{key} {label}", "count": count, "chapter_key": key,
                "_weight": weight,
                "_target_weight": chapter_target_weights.get(key, float(count)),
            })
        chosen = (
            _weighted_choice_rows_with_weights(rows, rng)
            if boozehound_active_for_age(age)
            else _weighted_choice_rows(rows, rng)
        )
        if chosen is None:
            return {"available": False, "reason": "Canadian cause cell contains no usable deaths"}
        if boozehound_active_for_age(age):
            chosen["baseline_conditional_probability"] = (
                int(chosen["count"]) / observed_total if observed_total > 0 else 0.0
            )
            chosen["cause_modifier"] = (
                float(chosen.get("_weight", chosen["count"])) / int(chosen["count"])
                if int(chosen["count"]) > 0 else 1.0
            )
            chosen["cause_modifier_target"] = (
                float(chosen.get("_target_weight", chosen["count"])) / int(chosen["count"])
                if int(chosen["count"]) > 0 else 1.0
            )
            chosen["boozehound_exposure_years"] = boozehound_exposure_years(age)
            chosen["boozehound_adjusted"] = True
        chosen.update({
            "available": True, "age_group": age_label, "calendar_year": requested_year,
            "lookup_year": lookup_year, "year_status": status,
            "no_death_certificate": False, "ill_defined": False,
            "country": "Canada", "who_list": payload.get("who_list"),
        })
        return chosen


class CanadaCauseDetailResolver:
    def __init__(self, raw: WhoCountryRawMortality) -> None:
        self.raw = raw
    def roll_detail(self, *, broad_outcome: dict[str, object], sex: str, age: int, calendar_year: int | None, rng: random.Random) -> dict[str, object]:
        if not broad_outcome.get("available"):
            return {"available": False, "reason": "broad cause unavailable"}
        year = int(broad_outcome.get("lookup_year", WHO_CANADA_LATEST_YEAR))
        age_label = str(broad_outcome.get("age_group", ""))
        chapter = str(broad_outcome.get("chapter_key", "OTHER"))
        try:
            payload = self.raw.load_year(year)
            sex_data = dict(dict(payload.get("data", {})).get(sex, {}))
            if age_label not in sex_data:
                resolved = choose_age_label(age, list(sex_data.keys()))
                age_label = resolved or age_label
            counts = sex_data.get(age_label, {})
        except Exception as exc:
            return {"available": False, "reason": f"Canadian detail lookup failed: {exc}"}
        rows=[]
        for code,count in counts.items():
            if _canada_icd_chapter(str(code)) != chapter or int(count) <= 0: continue
            norm=_normalise_who_icd_code(str(code))
            row = {
                "label": _canada_code_label(norm), "code": norm, "count": int(count),
                "detail_resolution": "WHO complete ICD code" if len(norm) > 3 else "WHO reported 3-character code",
            }
            if boozehound_active_for_age(age):
                if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                    mult, target_mult, profile, maturity, _basis = _boozehound_icd_hazard_effective_rr(
                        norm, age=age, sex=sex, country="ca"
                    )
                else:
                    mult, target_mult, profile, maturity = boozehound_icd_effective_rr(
                        norm, age=age, sex=sex
                    )
                row["_weight"] = int(count) * mult
                row["cause_modifier"] = mult
                row["cause_modifier_target"] = target_mult
                row["boozehound_profile"] = profile
                row["boozehound_maturity"] = maturity
            rows.append(row)
        chosen = (
            _weighted_choice_rows_with_weights(rows, rng)
            if boozehound_active_for_age(age)
            else _weighted_choice_rows(rows,rng)
        )
        if chosen is None:
            return {"available": False, "reason": "Canadian detailed cause cell contains no usable deaths"}
        if boozehound_active_for_age(age):
            observed_total = sum(int(row["count"]) for row in rows)
            chosen["baseline_conditional_probability"] = (
                int(chosen["count"]) / observed_total if observed_total > 0 else 0.0
            )
            chosen["boozehound_exposure_years"] = boozehound_exposure_years(age)
            chosen["boozehound_adjusted"] = True
        chosen.update({
            "available": True, "source": "WHO Mortality Database raw ICD-10 — Canada submission",
            "age_group": age_label, "lookup_year": year, "country": "Canada",
            "who_list": payload.get("who_list"),
        })
        return chosen


def print_cause_outcome(outcome: dict[str, object]) -> None:
    print()
    print_country_section_heading("CAUSE OF DEATH")

    if not outcome.get("available"):
        print("unavailable")
        print(f"reason: {outcome.get('reason', 'unknown')}")
        return

    label = str(outcome["label"])
    p = float(outcome["conditional_probability"])
    age_group = str(outcome["age_group"])
    lookup_year = int(outcome["lookup_year"])
    year_status = str(outcome["year_status"])

    if outcome.get("no_death_certificate"):
        print(r"¯\_(ツ)_/¯")
        print("No death certificate.")
        print("*** never fucking heard from again ***")
    elif outcome.get("ill_defined"):
        print("Ill-defined or unknown cause of mortality.")
        print(f"classification: {label}")
    else:
        # Strip the numeric game-class prefix for a cleaner display while
        # preserving the full official label underneath.
        parts = label.split(" ", 1)
        clean = parts[1] if len(parts) == 2 else label
        print(clean)
        print(f"classification: {label}")

    print(
        f"conditional cause probability: {p * 100:.2f}% "
        f"(given death in this sex/age/year cell)"
    )
    if outcome.get("boozehound_adjusted"):
        baseline_p = float(outcome.get("baseline_conditional_probability", 0.0))
        modifier = float(outcome.get("cause_modifier", 1.0))
        target = float(outcome.get("cause_modifier_target", modifier))
        years = outcome.get("boozehound_exposure_years")
        suffix = f" (target ×{target:.2f}"
        if years is not None:
            suffix += f"; {float(years):.1f}y exposure"
        suffix += ")"
        print(
            f"{boozehound_preset_icon()} boozehound cause adjustment: baseline {baseline_p * 100:.2f}% "
            f"| duration-aware cause weight ×{modifier:.2f}{suffix}"
        )
    print(f"{'WHO/Canada' if outcome.get('country') == 'Canada' else 'StatFin'} age group: {age_group}")
    print(f"cause-data year: {lookup_year} ({year_status})")
    if outcome.get("country") == "Canada" and ACTIVE_CANADA_PROVINCE is not None:
        print("cause geography: Canada national (WHO cause distribution is not province-conditioned)")


def cause_key_for_batch(outcome: dict[str, object]) -> str:
    if not outcome.get("available"):
        return "CAUSE DATA UNAVAILABLE"
    if outcome.get("no_death_certificate"):
        return "No death certificate"
    if outcome.get("ill_defined"):
        return "Ill-defined / unknown cause"

    label = str(outcome["label"])
    parts = label.split(" ", 1)
    return parts[1] if len(parts) == 2 else label


def print_batch_causes(
    *,
    counts: Counter[str],
    runs: int,
    source: CauseOfDeathSource,
    birth_year: int | None,
    top_n: int,
) -> None:
    print()
    print("cause-of-death roulette")
    print("-----------------------")
    print(f"source: {source.name} ({source.min_year}–{source.max_year})")
    if birth_year is None:
        print(
            f"calendar-year rule: use latest observed cause distribution "
            f"({source.max_year})"
        )
    else:
        print(
            "calendar-year rule: birth year + death age; "
            f"future years hold {source.max_year} cause distribution constant"
        )
    print(
        "cause is rolled only after death, conditional on sex + death-age group "
        "+ calendar year"
    )
    print()

    shown = counts.most_common(max(1, top_n))
    for rank, (cause, count) in enumerate(shown, start=1):
        pct = count / runs * 100.0
        print(f"{rank:2d}. {cause:<58} {pct:7.3f}%  ({count:,})")

    shown_total = sum(count for _, count in shown)
    if shown_total < runs:
        remainder = runs - shown_total
        print(
            f"    {'all other cause groups':<58} "
            f"{remainder / runs * 100:7.3f}%  ({remainder:,})"
        )


# ---------------------------------------------------------------------------
# v10 detailed cause drill-down
# ---------------------------------------------------------------------------

def _standard_detail_age_label(age: int) -> str:
    if age <= 0:
        return "0"
    if age <= 4:
        return "1 - 4"
    if age >= 95:
        return "95 -"
    lo = (age // 5) * 5
    return f"{lo} - {lo + 4}"


def _alcohol_detail_age_label(age: int) -> str:
    if age <= 14:
        return "0 - 14"
    if age >= 95:
        return "95 -"
    lo = (age // 5) * 5
    if lo < 15:
        lo = 15
    return f"{lo} - {lo + 4}"


def _leaf_icd_code(label: str) -> str | None:
    match = re.match(r"^([A-Z][0-9]{2})(?:\s|$)", label.strip())
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# ICD classification context below StatFin's public 3-character resolution
# ---------------------------------------------------------------------------
#
# Statistics Finland 11be deliberately stops at the ICD-10 3-character level.
# For a few families that are especially misleading without their fourth
# character, we can still show the legitimate ICD classification children as
# *context*. These are NOT empirical StatFin child probabilities and MUST NOT be
# randomly selected as though they were observed deaths.
#
# F10-F19 share the same WHO ICD-10 fourth-character clinical-state scheme
# (not every modifier is necessarily applicable to every substance). This is
# particularly useful for F11: the 3-character result alone cannot distinguish
# intoxication, harmful use, dependence, withdrawal, psychotic disorder, etc.
_SUBSTANCE_USE_4CHAR = (
    ("0", "Acute intoxication"),
    ("1", "Harmful use"),
    ("2", "Dependence syndrome"),
    ("3", "Withdrawal state"),
    ("4", "Withdrawal state with delirium"),
    ("5", "Psychotic disorder"),
    ("6", "Amnesic syndrome"),
    ("7", "Residual and late-onset psychotic disorder"),
    ("8", "Other mental and behavioural disorders"),
    ("9", "Unspecified mental and behavioural disorder"),
)

# WHO ICD-10 F70-F79 use a fourth character to qualify associated behavioural
# impairment. The historical StatFin/ICD wording is retained because the game
# prints the published classification labels verbatim.
_INTELLECTUAL_DISABILITY_4CHAR = (
    ("0", "With statement of no, or minimal, impairment of behaviour"),
    ("1", "Significant impairment of behaviour requiring attention or treatment"),
    ("8", "Other impairments of behaviour"),
    ("9", "Without mention of impairment of behaviour"),
)


def icd_subtype_context(label: str) -> dict[str, object] | None:
    """Return non-probabilistic ICD children when 3-char detail is insufficient.

    This layer is explanatory only. It deliberately never feeds the RNG because
    StatFin 11be supplies no age/sex/year counts below the 3-character level.
    """
    code = _leaf_icd_code(label)
    if code is None:
        return None

    if re.fullmatch(r"F1[0-9]", code):
        children = [(f"{code}.{suffix}", desc) for suffix, desc in _SUBSTANCE_USE_4CHAR]
        return {
            "code": code,
            "children": children,
            "source": "WHO ICD-10 fourth-character clinical-state classification",
            "note": (
                "classification context only; StatFin 11be stops at 3 characters, "
                "so these subtypes have no age/sex/year weights in the public data "
                "and are not rolled"
            ),
            "applicability_note": (
                "not every fourth-character modifier is necessarily applicable to "
                "every substance category"
            ),
        }

    if code in {"F70", "F71", "F72", "F73", "F78", "F79"}:
        children = [(f"{code}.{suffix}", desc) for suffix, desc in _INTELLECTUAL_DISABILITY_4CHAR]
        return {
            "code": code,
            "children": children,
            "source": "WHO ICD-10 fourth-character behavioural-impairment classification",
            "note": (
                "classification context only; StatFin 11be stops at 3 characters, "
                "so these subtypes have no age/sex/year weights in the public data "
                "and are not rolled"
            ),
        }

    return None


def print_icd_subtype_context(detail: dict[str, object]) -> None:
    context = icd_subtype_context(str(detail.get("label", "")))
    if context is None:
        return

    print()
    print_country_section_heading("ADDITIONAL ICD CONTEXT")
    print(f"StatFin detail stops at: {context['code']} (3-character ICD-10)")
    print("possible lower-level ICD states:")
    for code, description in context["children"]:
        print(f"  {code} {description}")
    print(f"context source: {context['source']}")
    print(f"resolution note: {context['note']}")
    if context.get("applicability_note"):
        print(f"classification note: {context['applicability_note']}")


_EXTERNAL_CLASS_PREFIX_RE = re.compile(
    r"^\s*(\d{3}(?:-\d{3})?(?:,\s*\d{3}(?:-\d{3})?)*)\s+"
)


def _external_class_numbers(label: str) -> frozenset[int] | None:
    """Return the 11b2 short-list numeric members represented by a label.

    Examples:
      ``001 Pedestrian ...`` -> {1}
      ``001-012 Transport accidents ...`` -> {1, ..., 12}
      ``001-072, 121-122 Total accidents ...`` -> {1, ..., 72, 121, 122}

    Statistics Finland's 11b2 dimension is hierarchical. Some genuine terminal
    categories are ranges rather than single three-digit rows, so treating only
    ``^\\d{3} `` labels as leaves loses real probability mass.
    """
    match = _EXTERNAL_CLASS_PREFIX_RE.match(label)
    if not match:
        return None
    members: set[int] = set()
    for chunk in match.group(1).split(','):
        chunk = chunk.strip()
        if '-' in chunk:
            lo_s, hi_s = chunk.split('-', 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                return None
            members.update(range(lo, hi + 1))
        else:
            members.add(int(chunk))
    return frozenset(members) if members else None


def _external_terminal_labels(meta: dict) -> set[str]:
    """Find a non-overlapping terminal partition of StatFin 11b2 metadata.

    A classification row is terminal when no other classification row denotes a
    strict subset of its short-list numbers. This keeps legitimate grouped leaf
    rows while discarding subtotal/parent rows. Exact duplicate numeric sets are
    collapsed to one label, preferring a non-"Total" label when available.
    """
    cause_var = _metadata_variable(
        meta, "Accidents and violence (classification of external causes)"
    )
    by_members: dict[frozenset[int], list[str]] = {}
    for label in map(str, cause_var.get('valueTexts', [])):
        members = _external_class_numbers(label)
        if members is not None:
            by_members.setdefault(members, []).append(label)

    if not by_members:
        raise CauseDataError("could not parse StatFin 11b2 classification hierarchy")

    member_sets = list(by_members)
    terminal_sets = [
        members for members in member_sets
        if not any(other < members for other in member_sets)
    ]

    # A usable leaf partition must not contain overlapping siblings. If StatFin
    # ever changes the short list into a non-hierarchical classification, fail
    # closed rather than double-counting deaths.
    for i, left in enumerate(terminal_sets):
        for right in terminal_sets[i + 1:]:
            if left & right:
                raise CauseDataError(
                    "StatFin 11b2 terminal classification rows overlap; "
                    "refusing to double-count external causes"
                )

    labels: set[str] = set()
    for members in terminal_sets:
        candidates = by_members[members]
        label = min(
            candidates,
            key=lambda text: ("total" in text.casefold(), len(text), text),
        )
        labels.add(label)
    return labels


def _external_hierarchy_partition(
    meta: dict,
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Build the deepest non-overlapping *published* 11b2 partition available.

    StatFin 11b2 is hierarchical. Fine cells can be confidential (returned as
    null), while their parent subtotal remains published. A leaf-only chooser
    therefore loses potentially large amounts of probability mass. This helper
    starts with visible terminal rows, then walks upward from smaller to larger
    published parent groups and adds only the parent's *unexplained residual*.

    Example: if ``073-097 Suicides`` is published as 40 deaths but only 12
    deaths are visible among its method-level children, the partition gets a
    28-death bucket labelled ``Suicides — specific subcategory unavailable``.
    Thus we preserve what StatFin actually reveals without inventing a method.

    Accidental alcohol poisoning (X45) is removed because the broad 11az
    category 42-53 explicitly excludes it; X45 belongs to alcohol-related
    category 41 in this simulator.
    """
    cause_var = _metadata_variable(
        meta, "Accidents and violence (classification of external causes)"
    )
    metadata_labels = [str(x) for x in cause_var.get("valueTexts", [])]

    labels_by_members: dict[frozenset[int], list[str]] = {}
    for label in metadata_labels:
        members = _external_class_numbers(label)
        if members is not None:
            labels_by_members.setdefault(members, []).append(label)
    if not labels_by_members:
        raise CauseDataError("could not parse StatFin 11b2 classification hierarchy")

    # Identify the singleton short-list member corresponding to X45.  Do not
    # infer it from its numeric position: use the metadata label itself.
    x45_members: set[int] = set()
    for members, labels in labels_by_members.items():
        if len(members) == 1 and any(re.search(r"(?<![A-Z0-9])X45(?![A-Z0-9])", label.upper()) for label in labels):
            x45_members.update(members)
    x45_members_fs = frozenset(x45_members)

    # Visible rows only: PxWeb confidential cells arrive as null and _fetch_rows
    # intentionally omits them.
    visible_by_members: dict[frozenset[int], dict[str, object]] = {}
    for row in rows:
        label = str(row.get("label", ""))
        members = _external_class_numbers(label)
        if members is None:
            continue
        count = max(0, int(row.get("count", 0)))
        current = visible_by_members.get(members)
        if current is None or (
            "total" in str(current.get("label", "")).casefold()
            and "total" not in label.casefold()
        ):
            visible_by_members[members] = {"label": label, "count": count}

    # If the X45 leaf itself is published, ancestor subtotals can safely be
    # adjusted by subtracting it. If X45 is confidential, skip any ancestor
    # fallback that contains it; the final broad-parent checksum will preserve
    # that mass as generic unresolved rather than misclassifying alcohol deaths.
    x45_count: int | None = None
    if x45_members_fs:
        x45_row = visible_by_members.get(x45_members_fs)
        if x45_row is not None:
            x45_count = int(x45_row["count"])

    terminal_labels = _external_terminal_labels(meta)
    terminal_sets = {
        _external_class_numbers(label) for label in terminal_labels
    }
    terminal_sets.discard(None)

    buckets: list[dict[str, object]] = []

    # Exact/deepest visible rows first.
    for members in sorted(terminal_sets, key=lambda m: (len(m), min(m))):
        if members & x45_members_fs:
            # X45 itself, or any hypothetical terminal group containing it,
            # does not belong to broad category 42-53.
            continue
        row = visible_by_members.get(members)
        if row is None or int(row["count"]) <= 0:
            continue
        buckets.append({
            "label": str(row["label"]),
            "count": int(row["count"]),
            "_scope_members": members,
            "detail_resolution": "specific",
        })

    all_sets = list(labels_by_members)
    root_sets = [
        members for members in all_sets
        if not any(members < other for other in all_sets)
    ]
    root = max(root_sets, key=len) if root_sets else max(all_sets, key=len)

    # Then progressively recover suppressed detail from published subtotals.
    # The overall root adds no information beyond 11az, so leave any final root
    # remainder to the generic broad-parent residual below.
    parents = [m for m in all_sets if m not in terminal_sets and m != root]
    parents.sort(key=lambda m: (len(m), min(m)))

    for members in parents:
        row = visible_by_members.get(members)
        if row is None:
            continue

        adjusted_members = members - x45_members_fs
        if not adjusted_members:
            continue

        adjusted_count = int(row["count"])
        if members & x45_members_fs:
            if x45_count is None:
                # We cannot tell how much of this subtotal is the excluded X45.
                continue
            adjusted_count -= x45_count
        if adjusted_count <= 0:
            continue

        covered = sum(
            int(bucket["count"])
            for bucket in buckets
            if frozenset(bucket["_scope_members"]) <= adjusted_members
        )
        residual = adjusted_count - covered
        if residual <= 0:
            continue

        labels = labels_by_members[members]
        label = min(
            labels,
            key=lambda text: ("total" in text.casefold(), len(text), text),
        )
        buckets.append({
            "label": f"{label} — specific subcategory unavailable in public data",
            "count": residual,
            "_scope_members": frozenset(adjusted_members),
            "detail_resolution": "group fallback",
        })

    # Remove private bookkeeping before caching/rolling.
    return [
        {k: v for k, v in bucket.items() if k != "_scope_members"}
        for bucket in buckets
    ]


def _weighted_choice_rows(rows: list[dict[str, object]], rng: random.Random) -> dict[str, object] | None:
    usable = [row for row in rows if int(row.get("count", 0)) > 0]
    total = sum(int(row["count"]) for row in usable)
    if total <= 0:
        return None
    target = rng.random() * total
    running = 0
    for row in usable:
        running += int(row["count"])
        if target < running:
            out = dict(row)
            out["denominator"] = total
            out["conditional_probability"] = int(row["count"]) / total
            return out
    out = dict(usable[-1])
    out["denominator"] = total
    out["conditional_probability"] = int(out["count"]) / total
    return out


# WHO Mortality Database general-mortality age layouts.
#
# Frmat=00 is the standard single-year 0..4 + 5-year layout through 95+.
# Frmat=01 keeps ages 0..4 separate but combines all deaths 85+ in Deaths23.
# Frmat=02 combines ages 1-4 in Deaths3 and also combines all deaths 85+ in
# Deaths23. WHO documents that combined age groups are stored in the first
# standard column covered by that group, with the remaining columns blank.
# Canada and Finland use Frmat=02 in recent WHO submissions, so country-specific
# parsers must accept all supported WHO age layouts rather than hard-coding 00.
_WHO_FRMAT00_AGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "0": ("Deaths2",),
    "1 - 4": ("Deaths3", "Deaths4", "Deaths5", "Deaths6"),
    "5 - 9": ("Deaths7",),
    "10 - 14": ("Deaths8",),
    "15 - 19": ("Deaths9",),
    "20 - 24": ("Deaths10",),
    "25 - 29": ("Deaths11",),
    "30 - 34": ("Deaths12",),
    "35 - 39": ("Deaths13",),
    "40 - 44": ("Deaths14",),
    "45 - 49": ("Deaths15",),
    "50 - 54": ("Deaths16",),
    "55 - 59": ("Deaths17",),
    "60 - 64": ("Deaths18",),
    "65 - 69": ("Deaths19",),
    "70 - 74": ("Deaths20",),
    "75 - 79": ("Deaths21",),
    "80 - 84": ("Deaths22",),
    "85 - 89": ("Deaths23",),
    "90 - 94": ("Deaths24",),
    "95 -": ("Deaths25",),
    "0 - 14": ("Deaths2", "Deaths3", "Deaths4", "Deaths5", "Deaths6", "Deaths7", "Deaths8"),
}

_WHO_FRMAT01_AGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "0": ("Deaths2",),
    "1 - 4": ("Deaths3", "Deaths4", "Deaths5", "Deaths6"),
    "5 - 9": ("Deaths7",),
    "10 - 14": ("Deaths8",),
    "15 - 19": ("Deaths9",),
    "20 - 24": ("Deaths10",),
    "25 - 29": ("Deaths11",),
    "30 - 34": ("Deaths12",),
    "35 - 39": ("Deaths13",),
    "40 - 44": ("Deaths14",),
    "45 - 49": ("Deaths15",),
    "50 - 54": ("Deaths16",),
    "55 - 59": ("Deaths17",),
    "60 - 64": ("Deaths18",),
    "65 - 69": ("Deaths19",),
    "70 - 74": ("Deaths20",),
    "75 - 79": ("Deaths21",),
    "80 - 84": ("Deaths22",),
    "85 -": ("Deaths23",),
    "0 - 14": ("Deaths2", "Deaths3", "Deaths4", "Deaths5", "Deaths6", "Deaths7", "Deaths8"),
}

_WHO_FRMAT02_AGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "0": ("Deaths2",),
    # In Frmat=02 WHO stores the combined 1-4 count in Deaths3 and leaves
    # Deaths4-Deaths6 unused.
    "1 - 4": ("Deaths3",),
    "5 - 9": ("Deaths7",),
    "10 - 14": ("Deaths8",),
    "15 - 19": ("Deaths9",),
    "20 - 24": ("Deaths10",),
    "25 - 29": ("Deaths11",),
    "30 - 34": ("Deaths12",),
    "35 - 39": ("Deaths13",),
    "40 - 44": ("Deaths14",),
    "45 - 49": ("Deaths15",),
    "50 - 54": ("Deaths16",),
    "55 - 59": ("Deaths17",),
    "60 - 64": ("Deaths18",),
    "65 - 69": ("Deaths19",),
    "70 - 74": ("Deaths20",),
    "75 - 79": ("Deaths21",),
    "80 - 84": ("Deaths22",),
    "85 -": ("Deaths23",),
    "0 - 14": ("Deaths2", "Deaths3", "Deaths7", "Deaths8"),
}

_WHO_AGE_COLUMNS_BY_FRMAT: dict[str, dict[str, tuple[str, ...]]] = {
    "00": _WHO_FRMAT00_AGE_COLUMNS,
    "01": _WHO_FRMAT01_AGE_COLUMNS,
    "02": _WHO_FRMAT02_AGE_COLUMNS,
}


def _who_icd_part_for_year(year: int) -> int | None:
    if year < 1996:
        return None
    if year <= 2002:
        return 1
    if year <= 2007:
        return 2
    if year <= 2012:
        return 3
    if year <= 2016:
        return 4
    if year <= 2020:
        return 5
    return 6


def _normalise_who_icd_code(value: str) -> str:
    """Normalise WHO raw codes such as F10.2/F102 to F102."""
    return re.sub(r"[^A-Z0-9]", "", value.strip().upper())


def _format_icd_code(code: str) -> str:
    code = _normalise_who_icd_code(code)
    if len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def _load_icd_title_lookup() -> dict[str, str]:
    """Load the shared WHO ICD-10 terminology companion once.

    The JSON is deliberately separate from mortality-count caches: it answers
    "what does this ICD code mean?", while StatFin/StatCan/WHO mortality data
    answer "how often did this code occur?".  Exact complete-code titles are
    preferred; callers may fall back to the 3-character parent when necessary.
    """
    global _ICD_TITLE_LOOKUP, _ICD_TITLES_SOURCE_PATH
    if _ICD_TITLE_LOOKUP is not None:
        return _ICD_TITLE_LOOKUP
    if not USE_ICD_TITLES:
        _ICD_TITLE_LOOKUP = {}
        return _ICD_TITLE_LOOKUP

    candidates = (DEFAULT_ICD_TITLES_PATH, LEGACY_ICD_TITLES_PATH, FALLBACK_ICD_TITLES_PATH)
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        raise CauseDataError(
            f"ICD title lookup is enabled but {ICD_TITLES_FILENAME} was not found; "
            f"expected bundled dataset at {DEFAULT_ICD_TITLES_PATH}, legacy companion at "
            f"{LEGACY_ICD_TITLES_PATH}, or cache at {FALLBACK_ICD_TITLES_PATH}"
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, dict) or not raw_codes:
        raise CauseDataError(f"ICD title file {path} has no usable 'codes' mapping")

    lookup: dict[str, str] = {}
    for raw_code, raw_title in raw_codes.items():
        code = str(raw_code).strip().upper()
        title = str(raw_title).strip()
        if not title:
            continue
        # Mortality rows use category/subcategory codes, not chapter/block IDs.
        if re.fullmatch(r"[A-Z]\d{2}(?:\.[A-Z0-9]+)?", code):
            lookup[_normalise_who_icd_code(code)] = title

    if not lookup:
        raise CauseDataError(f"ICD title file {path} contained no ICD category/subcategory titles")
    _ICD_TITLE_LOOKUP = lookup
    _ICD_TITLES_SOURCE_PATH = path
    data_status(
        f"WHO ICD-10 terminology: loaded {len(lookup):,} category/subcategory titles from {path}",
        level=1,
    )
    return lookup


def preflight_icd_titles() -> None:
    """Resolve terminology before the roulette transcript starts."""
    if not USE_ICD_TITLES:
        data_status("WHO ICD-10 terminology: disabled by USE_ICD_TITLES=False", level=1)
        return
    _load_icd_title_lookup()


def _icd_title(code: str, *, allow_parent: bool = True) -> str | None:
    if not USE_ICD_TITLES:
        return None
    try:
        lookup = _load_icd_title_lookup()
    except CauseDataError:
        return None
    norm = _normalise_who_icd_code(code)
    title = lookup.get(norm)
    if title:
        return title
    if allow_parent and len(norm) > 3:
        return lookup.get(norm[:3])
    return None


def _icd_code_label(code: str) -> str:
    norm = _normalise_who_icd_code(code)
    display = _format_icd_code(norm)
    title = _icd_title(norm, allow_parent=True)
    if title:
        return f"{display} {title}"
    deep = _deep_icd_description(norm)
    if deep:
        return f"{display} {deep}"
    return display


def _deep_icd_description(code: str) -> str | None:
    """Descriptions for the families whose fourth character is systematic.

    WHO raw mortality files contain the complete code but not a human-readable
    label in each mortality row. For other families we still expose the exact
    deeper code without pretending to know a description locally.
    """
    code = _normalise_who_icd_code(code)
    exact_title = _icd_title(code, allow_parent=False)
    if exact_title:
        return exact_title
    if len(code) != 4:
        return None
    parent = code[:3]
    suffix = code[3]
    if re.fullmatch(r"F1[0-9]", parent):
        return dict(_SUBSTANCE_USE_4CHAR).get(suffix)
    if parent in {"F70", "F71", "F72", "F73", "F78", "F79"}:
        return dict(_INTELLECTUAL_DISABILITY_4CHAR).get(suffix)
    return None


class WhoDeepDetailResolver:
    """Refine a StatFin 3-character cause using WHO's complete ICD data.

    Finland transmits detailed national cause-of-death data to the WHO
    Mortality Database. WHO requests the complete ICD code (normally the
    fourth character for ICD-10), while StatFin's public 11be table stops at
    three characters. This resolver therefore uses WHO only as a *child
    partition* beneath an already-selected StatFin detail result.

    Safety rule: a WHO child distribution is rolled only when the sum of the
    WHO rows for the same Finland/year/sex/age cell exactly equals the StatFin
    3-character parent count. Any mismatch fails closed.
    """

    def __init__(
        self,
        cache_dir: Path = DEFAULT_WHO_DETAIL_CACHE_DIR,
        refresh: bool = False,
    ) -> None:
        self.cache_dir = cache_dir
        self.refresh = refresh
        self._year_cache: dict[int, dict[str, object]] = {}
        self._part_cache: dict[int, Path] = {}
        self._part_member_cache: dict[int, str] = {}
        self._part_failures: dict[int, str] = {}
        self._preflight_failures: dict[int, str] = {}

    def _zip_path(self, part: int) -> Path:
        return self.cache_dir / f"morticd10_part{part}.zip"

    def _year_json_path(self, year: int) -> Path:
        return self.cache_dir / f"finland_complete_icd_{year}.json"

    def _download_part(self, part: int) -> tuple[Path, str]:
        label = f"WHO Mortality Database Finland ICD-10 archive part {part}"
        return _download_who_mortality_archive(
            part=part,
            cache_dir=self.cache_dir,
            refresh=self.refresh,
            label=label,
            part_cache=self._part_cache,
            member_cache=self._part_member_cache,
            failure_cache=self._part_failures,
        )

    @staticmethod
    def _row_count(row: dict[str, str], columns: tuple[str, ...]) -> int:
        total = 0
        for column in columns:
            text = str(row.get(column, "") or "").strip()
            if not text:
                continue
            try:
                total += int(float(text))
            except ValueError:
                continue
        return total

    def _parse_finland_year(self, year: int) -> dict[str, object]:
        part = _who_icd_part_for_year(year)
        if part is None:
            raise CauseDataError(f"WHO ICD-10 raw detail is unavailable for year {year}")
        path, data_member = self._download_part(part)
        data_status(f"WHO Mortality Database Finland: opening archive {path}")
        data_status(f"WHO Mortality Database Finland: reading member {data_member!r} for year {year}")

        # Gather Finland rows separately by WHO age format and ICD list.
        # Modern Finland submissions can use Frmat=02 (combined ages 1-4 and
        # 85+), just like modern Canada. Keeping both dimensions separate
        # prevents accidental double-counting if more than one format/list is
        # present in the same archive year. Prefer List 104 over 10M, then the
        # most detailed supported age layout (00, 01, 02).
        by_frmat: dict[str, dict[str, dict[str, dict[str, dict[str, int]]]]] = {}
        seen_frmats: set[str] = set()

        with zipfile.ZipFile(path) as zf:
            with zf.open(data_member, "r") as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
                reader = csv.DictReader(text)
                required = {"Country", "Year", "List", "Cause", "Sex", "Frmat"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    raise CauseDataError(
                        "WHO mortality CSV schema changed; required columns are missing"
                    )

                for row in reader:
                    if str(row.get("Country", "")).strip() != WHO_FINLAND_COUNTRY_CODE:
                        continue
                    if str(row.get("Year", "")).strip() != str(year):
                        continue
                    # National rows only. Empty Admin1/SubDiv is the standard
                    # national series in the WHO raw files.
                    if str(row.get("Admin1", "") or "").strip():
                        continue
                    if str(row.get("SubDiv", "") or "").strip():
                        continue

                    sex_code = str(row.get("Sex", "")).strip()
                    if sex_code == "1":
                        sex = "male"
                    elif sex_code == "2":
                        sex = "female"
                    else:
                        continue

                    try:
                        frmat = f"{int(float(str(row.get('Frmat', '')).strip())):02d}"
                    except ValueError:
                        frmat = str(row.get("Frmat", "")).strip().zfill(2)
                    seen_frmats.add(frmat)
                    age_columns = _WHO_AGE_COLUMNS_BY_FRMAT.get(frmat)
                    if age_columns is None:
                        continue

                    list_code = str(row.get("List", "")).strip().upper()
                    if list_code not in {"104", "10M"}:
                        continue

                    cause = _normalise_who_icd_code(str(row.get("Cause", "")))
                    if not re.fullmatch(r"[A-Z][0-9]{2}[A-Z0-9]*", cause):
                        continue

                    format_data = by_frmat.setdefault(frmat, {})
                    list_data = format_data.setdefault(
                        list_code, {"male": {}, "female": {}}
                    )
                    sex_data = list_data[sex]
                    for age_label, columns in age_columns.items():
                        count = self._row_count(row, columns)
                        if count <= 0:
                            continue
                        age_counts = sex_data.setdefault(age_label, {})
                        age_counts[cause] = int(age_counts.get(cause, 0)) + count

        list_priority = {"104": 0, "10M": 1}
        frmat_priority = {"00": 0, "01": 1, "02": 2}
        candidates: list[tuple[int, int, str, str]] = []
        for frmat, lists in by_frmat.items():
            for list_code in lists:
                candidates.append(
                    (
                        list_priority.get(list_code, 99),
                        frmat_priority.get(frmat, 99),
                        frmat,
                        list_code,
                    )
                )

        if not candidates:
            unsupported = sorted(fmt for fmt in seen_frmats if fmt not in _WHO_AGE_COLUMNS_BY_FRMAT)
            if unsupported:
                raise CauseDataError(
                    f"Finland {year} WHO mortality data use unsupported age format(s): "
                    + ", ".join(unsupported)
                )
            raise CauseDataError(
                f"no Finland {year} WHO complete-ICD rows (List 104/10M) were found"
            )

        _, _, selected_frmat, selected_list = min(candidates)
        return {
            "year": year,
            "who_list": selected_list,
            "frmat": selected_frmat,
            "data": by_frmat[selected_frmat][selected_list],
        }

    def _load_year(self, year: int) -> dict[str, object]:
        cached = self._year_cache.get(year)
        if cached is not None:
            return cached

        json_path = self._year_json_path(year)
        if json_path.exists() and not self.refresh:
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                cached_frmat = str(payload.get("frmat", "")).zfill(2)
                if (
                    int(payload.get("year", -1)) == year
                    and cached_frmat in _WHO_AGE_COLUMNS_BY_FRMAT
                ):
                    self._year_cache[year] = payload
                    return payload
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass

        payload = self._parse_finland_year(year)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        self._year_cache[year] = payload
        return payload

    def preflight_year(self, year: int) -> bool:
        """Load/cache one Finland WHO detail year before simulation output starts.

        Deep WHO refinement is optional. A preflight failure is memoized so a
        death later in the run does not retry network/archive work and spray
        [data] lines into the roulette output.
        """
        if year in self._year_cache:
            return True
        if year in self._preflight_failures:
            return False
        try:
            self._load_year(year)
        except (
            CauseDataError,
            OSError,
            urllib.error.URLError,
            zipfile.BadZipFile,
            csv.Error,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            self._preflight_failures[year] = str(exc)
            data_status(
                f"WHO Mortality Database Finland: deep-detail preflight for {year} "
                f"unavailable; continuing without WHO refinement for that year ({exc})",
                level=1,
            )
            return False
        data_status(
            f"WHO Mortality Database Finland: deep-detail year {year} ready before run",
            level=1,
        )
        return True

    def roll(
        self,
        *,
        detail: dict[str, object],
        sex: str,
        rng: random.Random,
    ) -> dict[str, object]:
        if not detail.get("available"):
            return {"available": False, "reason": "3-character detail unavailable"}

        parent_code = _leaf_icd_code(str(detail.get("label", "")))
        if parent_code is None:
            return {"available": False, "silent": True, "reason": "detail is not a 3-character ICD code"}

        try:
            year = int(detail.get("lookup_year", 0))
            age_label = str(detail.get("age_group", ""))
            parent_count = int(detail.get("count", 0))
            if year in self._preflight_failures:
                return {
                    "available": False,
                    "silent": True,
                    "reason": (
                        "WHO deep-detail preflight failed before the run: "
                        + self._preflight_failures[year]
                    ),
                }
            if year <= 0 or parent_count <= 0 or age_label not in _WHO_FRMAT00_AGE_COLUMNS:
                return {
                    "available": False,
                    "silent": True,
                    "reason": "WHO deep-detail cell cannot be aligned to this StatFin parent",
                }

            payload = self._load_year(year)
            sex_data = dict(payload.get("data", {})).get(sex, {})
            counts = dict(sex_data).get(age_label, {})
            if not counts:
                return {
                    "available": False,
                    "reason": f"no WHO Finland {year} {sex} age {age_label} detail cell",
                }

            normal_parent = _normalise_who_icd_code(parent_code)
            finer: list[dict[str, object]] = []
            exact_parent_count = int(counts.get(normal_parent, 0))

            for code, raw_count in counts.items():
                code = _normalise_who_icd_code(str(code))
                count = int(raw_count)
                if count <= 0 or code == normal_parent:
                    continue
                if not code.startswith(normal_parent) or len(code) <= len(normal_parent):
                    continue
                finer.append({
                    "code": code,
                    "label": _icd_code_label(code),
                    "count": count,
                    "detail_resolution": "WHO complete ICD code",
                })

            if not finer:
                return {
                    "available": False,
                    "silent": True,
                    "reason": f"WHO reports no code below {parent_code} in this cell",
                }

            rows = list(finer)
            if exact_parent_count > 0:
                rows.append({
                    "code": normal_parent,
                    "label": f"{parent_code} — no lower-level code reported to WHO",
                    "count": exact_parent_count,
                    "detail_resolution": "WHO 3-character residual",
                })

            who_total = sum(int(row["count"]) for row in rows)
            if who_total != parent_count:
                return {
                    "available": False,
                    "reason": (
                        f"WHO deeper rows sum to {who_total}, but StatFin parent "
                        f"{parent_code} contains {parent_count}; refinement rejected"
                    ),
                    "parent_code": parent_code,
                    "who_total": who_total,
                    "statfin_parent_count": parent_count,
                    "who_list": payload.get("who_list"),
                    "age_group": age_label,
                    "lookup_year": year,
                }

            chosen = _weighted_choice_rows(rows, rng)
            if chosen is None:
                return {"available": False, "reason": "WHO deeper partition contains no usable deaths"}

            chosen.update({
                "available": True,
                "source": "WHO Mortality Database raw ICD-10",
                "parent_code": parent_code,
                "age_group": age_label,
                "lookup_year": year,
                "sex": sex,
                "who_list": payload.get("who_list"),
                "checksum": f"WHO children {who_total} = StatFin {parent_code} parent {parent_count}",
            })
            return chosen

        except (
            CauseDataError,
            OSError,
            urllib.error.URLError,
            zipfile.BadZipFile,
            csv.Error,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            return {"available": False, "reason": f"WHO deep-detail lookup failed: {exc}"}


def print_who_deep_detail(
    broad_outcome: dict[str, object],
    detail: dict[str, object],
    deep: dict[str, object],
) -> None:
    if deep.get("silent"):
        return
    if not deep.get("available"):
        # Only print a failed refinement when WHO actually found an apparent
        # deeper partition but rejected it. Network/data absence remains quiet
        # and the existing ICD context layer can explain the possibilities.
        if deep.get("who_total") is not None:
            print()
            print_country_section_heading("DEEP CAUSE DETAIL")
            print("deeper WHO detail rejected")
            print(f"reason: {deep.get('reason')}")
        return

    parent_p = float(broad_outcome.get("conditional_probability", 0.0))
    detail_p = float(detail.get("conditional_probability", 0.0))
    deep_p = float(deep.get("conditional_probability", 0.0))
    overall = parent_p * detail_p * deep_p

    print()
    print_country_section_heading("DEEP CAUSE DETAIL")
    print(str(deep.get("label", deep.get("code", "unknown"))))
    print(f"within-{deep.get('parent_code')} probability: {deep_p * 100:.2f}%")
    print(f"implied share of all deaths in broad {'Canadian' if broad_outcome.get('country') == 'Canada' else 'StatFin'} cell: {overall * 100:.3f}%")
    print(
        f"deep source: {deep.get('source')} | Finland | {deep.get('sex')} | "
        f"age {deep.get('age_group')} | year {deep.get('lookup_year')}"
    )
    print(f"WHO ICD list: {deep.get('who_list')} | age format: 00")
    print(f"cross-source checksum: {deep.get('checksum')}")
    resolution = str(deep.get("detail_resolution", "WHO complete ICD code"))
    if resolution != "WHO complete ICD code":
        print(f"deep resolution: {resolution}")


def _reconcile_statfin_detail_rows(
    rows: list[dict[str, object]],
    *,
    parent_count: int,
    parent_label: str,
) -> list[dict[str, object]]:
    """Reconcile published child rows to the 11az broad-parent count.

    Missing/suppressed child mass is retained as an explicit residual.  An
    over-inclusive child set is rejected rather than silently renormalized.
    This helper is shared by v4 broad-neoplasm hazard reconstruction and the
    visible detail roulette so the two paths cannot drift apart.
    """
    parent_count = max(0, int(parent_count))
    out = [dict(row) for row in rows]
    child_total = sum(max(0, int(row.get("count", 0))) for row in out)
    if parent_count > 0 and child_total > parent_count:
        raise CauseDataError(
            f"candidate detailed rows sum to {child_total}, exceeding broad parent count "
            f"{parent_count}; 3-character detail cannot safely reproduce {parent_label}"
        )
    if parent_count > child_total:
        out.append({
            "label": "Unresolved / suppressed detail within parent category",
            "count": parent_count - child_total,
            "detail_resolution": "residual",
        })
    return out


def _statfin_neoplasm_detail_rows(
    *,
    resolver: "CauseDetailResolver",
    parent_count: int,
    year: int,
    sex: str,
    age: int,
) -> tuple[list[dict[str, object]], str]:
    """Return the reconciled StatFin 11be C00-D48 partition for one 11az cell."""
    age_label = _standard_detail_age_label(age)
    rows = resolver._fetch_rows(
        api=STATFIN_ICD_DETAIL_API,
        dimension_text="Underlying cause of death (ICD-10, 3-character level)",
        row_selector=lambda label: (
            (code := _leaf_icd_code(label)) is not None and "C00" <= code <= "D48"
        ),
        year=int(year),
        sex=sex,
        age_label=age_label,
        cache_key=f"11be|neoplasms|{int(year)}|{sex}|{age_label}",
    )
    return _reconcile_statfin_detail_rows(
        rows, parent_count=parent_count, parent_label="StatFin 04-22 neoplasms (C00-D48)"
    ), age_label


def _statfin_neoplasm_hazard_rr_from_detail(
    *,
    resolver: "CauseDetailResolver",
    parent_count: int,
    year: int,
    sex: str,
    age: int,
) -> tuple[float, float, str, float, str]:
    """Count-weighted v4 neoplasm hazard RR from the reconciled 11be partition."""
    if parent_count <= 0:
        return 1.0, 1.0, "cancer", 0.0, "StatFin 11be neoplasm cell is empty"
    rows, age_label = _statfin_neoplasm_detail_rows(
        resolver=resolver, parent_count=parent_count, year=year, sex=sex, age=age
    )
    effective_weight = 0.0
    target_weight = 0.0
    residual_count = 0
    mapped_count = 0
    for row in rows:
        count = max(0, int(row.get("count", 0)))
        if count <= 0:
            continue
        code = _extract_icd_from_label(str(row.get("label", "")))
        if code:
            effective, target, _profile, _fraction, basis = _boozehound_icd_hazard_effective_rr(
                code, age=age, sex=sex, country="fi"
            )
            if "Dai et al. Nature Health 2026" in basis:
                mapped_count += count
        else:
            effective = target = 1.0
            residual_count += count
        effective_weight += count * effective
        target_weight += count * target

    total = sum(max(0, int(row.get("count", 0))) for row in rows)
    if total != int(parent_count):
        raise CauseDataError(
            f"v4 neoplasm invariant failed: reconciled 11be total {total} != 11az parent {parent_count}"
        )
    if total <= 0:
        return 1.0, 1.0, "cancer", 0.0, "StatFin 11be neoplasm cell is empty"
    effective = effective_weight / total
    target = target_weight / total
    _dummy, maturity = _boozehound_duration_rr(2.0, age=age, profile="cancer")
    basis = (
        f"evidence-v4 cancer: StatFin 11be C00-D48 count-weighted ICD hazards; "
        f"Dai 2026 mapped deaths={mapped_count}/{total}; unresolved/suppressed residual={residual_count}; "
        f"cell={int(year)} {sex} {age_label}"
    )
    return effective, target, "cancer", maturity, basis


class CauseDetailResolver:
    """Lazy, cached StatFin child-cause distributions for selected broad groups."""

    def __init__(self, cache_path: Path = DEFAULT_DETAIL_CACHE, refresh: bool = False) -> None:
        self.cache_path = cache_path
        self.refresh = refresh
        self._meta: dict[str, dict] = {}
        self._cache: dict[str, list[dict[str, object]]] = {}
        self._refreshed_keys: set[str] = set()
        if cache_path.exists() and not refresh:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self._cache = payload.get("distributions", {})
            except (OSError, json.JSONDecodeError):
                self._cache = {}

    def _save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "distributions": self._cache,
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def _metadata(self, api: str) -> dict:
        if api in self._meta:
            return self._meta[api]
        request = urllib.request.Request(api, headers={"User-Agent": f"mortality-roulette/{VERSION}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            meta = json.load(response)
        self._meta[api] = meta
        return meta

    def _fetch_rows(
        self,
        *,
        api: str,
        dimension_text: str,
        row_selector,
        year: int,
        sex: str,
        age_label: str,
        cache_key: str,
    ) -> list[dict[str, object]]:
        if cache_key in self._cache and (not self.refresh or cache_key in self._refreshed_keys):
            return self._cache[cache_key]

        meta = self._metadata(api)
        cause_var = _metadata_variable(meta, dimension_text)
        age_var = _metadata_variable(meta, "Age")
        year_var = _metadata_variable(meta, "Year")
        sex_var = _metadata_variable(meta, "Sex")
        info_var = _metadata_variable(meta, "Information")

        selected_codes = [
            str(code)
            for code, label in zip(cause_var["values"], cause_var["valueTexts"])
            if row_selector(str(label))
        ]
        if not selected_codes:
            raise CauseDataError(f"no detailed StatFin rows matched {cache_key}")

        age_code = None
        for code, label in zip(age_var["values"], age_var["valueTexts"]):
            if str(label).strip() == age_label:
                age_code = str(code)
                break
        if age_code is None:
            raise CauseDataError(f"StatFin detail table has no age group {age_label!r}")

        year_code = None
        for code, label in zip(year_var["values"], year_var["valueTexts"]):
            if str(label) == str(year):
                year_code = str(code)
                break
        if year_code is None:
            raise CauseDataError(f"StatFin detail table has no year {year}")

        sex_code = _value_code(sex_var, "Males" if sex == "male" else "Females")
        info_code = str(info_var["values"][0])
        query = {
            "query": [
                {"code": cause_var["code"], "selection": {"filter": "item", "values": selected_codes}},
                {"code": age_var["code"], "selection": {"filter": "item", "values": [age_code]}},
                {"code": year_var["code"], "selection": {"filter": "item", "values": [year_code]}},
                {"code": sex_var["code"], "selection": {"filter": "item", "values": [sex_code]}},
                {"code": info_var["code"], "selection": {"filter": "item", "values": [info_code]}},
            ],
            "response": {"format": "json-stat2"},
        }
        body = json.dumps(query).encode("utf-8")
        request = urllib.request.Request(
            api,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": f"mortality-roulette/{VERSION}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            dataset = json.load(response)

        ids = list(dataset["id"])
        sizes = list(dataset["size"])
        values = dataset["value"]
        categories = {dim_id: _jsonstat_categories(dataset, dim_id) for dim_id in ids}
        cause_pos = ids.index(str(cause_var["code"]))
        if len(values) != _product_int(sizes):
            raise CauseDataError("unexpected StatFin detailed value count")

        rows: list[dict[str, object]] = []
        flat = 0
        for coords in product(*(range(size) for size in sizes)):
            value = values[flat]
            flat += 1
            if value is None:
                continue
            cause_code = categories[str(cause_var["code"])][coords[cause_pos]]
            label = _jsonstat_category_label(dataset, str(cause_var["code"]), cause_code)
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            rows.append({"label": label, "count": count})

        self._cache[cache_key] = rows
        self._refreshed_keys.add(cache_key)
        self._save()
        return rows

    def roll_detail(
        self,
        *,
        broad_outcome: dict[str, object],
        sex: str,
        age: int,
        calendar_year: int | None,
        rng: random.Random,
    ) -> dict[str, object]:
        if not broad_outcome.get("available"):
            return {"available": False, "reason": "broad cause unavailable"}

        # Category 54 means Statistics Finland had no death certificate
        # available for cause coding in the published annual statistics.
        # There is therefore no meaningful underlying-cause child to resolve.
        # Treat it as a terminal state and suppress CAUSE DETAIL entirely.
        if broad_outcome.get("no_death_certificate"):
            return {
                "available": False,
                "silent": True,
                "terminal": True,
                "reason": "no death certificate; no cause detail exists to resolve",
            }

        parent = str(broad_outcome["label"])
        requested_year = int(broad_outcome.get("lookup_year", 2024)) if calendar_year is None else calendar_year
        year = min(requested_year, 2024)
        if year < 1998:
            return {"available": False, "reason": "detailed StatFin cause data begin in 1998"}

        try:
            # Dementia / Alzheimer's bundle: exact 3-character ICD leaves.
            if parent.startswith("25 "):
                allowed = {"F01", "F03", "G30", "R54"}
                age_label = _standard_detail_age_label(age)
                rows = self._fetch_rows(
                    api=STATFIN_ICD_DETAIL_API,
                    dimension_text="Underlying cause of death (ICD-10, 3-character level)",
                    row_selector=lambda label: (_leaf_icd_code(label) in allowed),
                    year=year, sex=sex, age_label=age_label,
                    cache_key=f"11be|dementia|{year}|{sex}|{age_label}",
                )
                source = "Statistics Finland 11be"

            # Ill-defined/unknown: R96-R99 leaves.
            elif parent.startswith("40 "):
                allowed = {"R96", "R97", "R98", "R99"}
                age_label = _standard_detail_age_label(age)
                rows = self._fetch_rows(
                    api=STATFIN_ICD_DETAIL_API,
                    dimension_text="Underlying cause of death (ICD-10, 3-character level)",
                    row_selector=lambda label: (_leaf_icd_code(label) in allowed),
                    year=year, sex=sex, age_label=age_label,
                    cache_key=f"11be|illdefined|{year}|{sex}|{age_label}",
                )
                source = "Statistics Finland 11be"

            # Alcohol-related deaths have a dedicated mutually exclusive table.
            elif parent.startswith("41 "):
                if year < 2005:
                    return {"available": False, "reason": "StatFin 11bx alcohol detail begins in 2005"}
                age_label = _alcohol_detail_age_label(age)
                rows = self._fetch_rows(
                    api=STATFIN_ALCOHOL_DETAIL_API,
                    dimension_text="Alcohol-related deaths",
                    row_selector=lambda label: label.strip().casefold() != "total",
                    year=year, sex=sex, age_label=age_label,
                    cache_key=f"11bx|alcohol|{year}|{sex}|{age_label}",
                )
                source = "Statistics Finland 11bx"

            # Neoplasms: use the same reconciled C00-D48 partition as the
            # evidence-v4 broad hazard builder. This is the DEV9 hard invariant:
            # annual neoplasm hazard and visible cancer roulette see identical
            # published + unresolved/suppressed mass.
            elif parent.startswith("04-22 "):
                rows, age_label = _statfin_neoplasm_detail_rows(
                    resolver=self,
                    parent_count=int(broad_outcome.get("count", 0)),
                    year=year,
                    sex=sex,
                    age=age,
                )
                source = "Statistics Finland 11be"

            # Accidents/violence: fetch the whole 11b2 hierarchy for this
            # one cell. Fine method-level cells are sometimes confidential even
            # when an intermediate parent (for example "Suicides") is public.
            # Build the deepest non-overlapping published partition rather than
            # throwing all suppressed leaf mass into a generic unresolved bucket.
            elif parent.startswith("42-53 "):
                age_label = _standard_detail_age_label(age)
                external_meta = self._metadata(STATFIN_EXTERNAL_DETAIL_API)
                hierarchy_rows = self._fetch_rows(
                    api=STATFIN_EXTERNAL_DETAIL_API,
                    dimension_text="Accidents and violence (classification of external causes)",
                    row_selector=lambda label: _external_class_numbers(label) is not None,
                    year=year, sex=sex, age_label=age_label,
                    # v3 deliberately invalidates the v2 leaf-only cache.
                    cache_key=f"11b2|external-hierarchy-v3|{year}|{sex}|{age_label}",
                )
                rows = _external_hierarchy_partition(external_meta, hierarchy_rows)
                source = "Statistics Finland 11b2"

            # A few broad disease groups can be safely decomposed at 3-char level.
            else:
                ranges: list[tuple[str, str]] = []
                extras: set[str] = set()
                excluded_codes: set[str] = set()
                tag = None
                if parent.startswith("00 "):
                    extras = {"U07", "U10"}; tag = "covid"
                elif parent.startswith("01-03 "):
                    ranges = [("A00", "B99")]; extras = {"J65"}; tag = "infectious"
                elif parent.startswith("23-24 "):
                    ranges = [("E00", "E90")]; tag = "endocrine"
                elif parent.startswith("31-35 "):
                    ranges = [("J00", "J64"), ("J66", "J99")]; tag = "respiratory"
                elif parent.startswith("37 "):
                    ranges = [("N00", "N99")]; tag = "genitourinary"
                elif parent.startswith("38 "):
                    ranges = [("Q00", "Q99")]; tag = "congenital"
                elif parent.startswith("27-30 "):
                    ranges = [("I00", "I99")]; tag = "circulatory_candidate"
                elif parent.startswith("36 "):
                    # Broad category 36 explicitly excludes alcohol-related
                    # digestive diseases. StatFin 11be only resolves to the
                    # 3-character level, while alcohol-specific exclusions
                    # occur at both whole-family and subcode level:
                    #   K70   alcoholic liver disease
                    #   K29.2 alcoholic gastritis
                    #   K85.2 alcohol-induced acute pancreatitis
                    #   K86.0 alcohol-induced chronic pancreatitis
                    # K29/K85/K86 therefore cannot be safely split at 3-char
                    # resolution. Exclude those families (and K70) from the
                    # candidate children and preserve their non-alcohol parent
                    # mass as an explicit unresolved residual instead of
                    # overcounting and suppressing the entire drill-down.
                    ranges = [("K00", "K93")]
                    excluded_codes = {"K29", "K70", "K85", "K86"}
                    tag = "digestive_safe_3char"
                elif parent.startswith("26 "):
                    # StatFin category 26 covers nervous-system / sense-organ
                    # diseases but excludes Alzheimer's disease (G30) and four
                    # alcohol-specific subcodes that live inside otherwise valid
                    # 3-character families:
                    #   G31.2  degeneration of nervous system due to alcohol
                    #   G40.51 epilepsy due to alcohol
                    #   G62.1  alcoholic polyneuropathy
                    #   G72.1  alcoholic myopathy
                    #
                    # 11be only exposes 3-character rows, but 11bx publishes
                    # those alcohol exclusions separately. For ages >=15 and
                    # years covered by 11bx, fetch the full G00-H95 11be family
                    # (except G30) and subtract the matching 11bx counts from
                    # G31/G40/G62/G72. This avoids the old v0.11.5 behaviour of
                    # discarding each entire 3-character family and turning the
                    # lost mass into a large "unresolved" residual.
                    #
                    # Before 2005, or for ages <15 where 11bx uses a broader
                    # 0-14 age cell than 11be, retain the conservative partition.
                    if year >= 2005 and age >= 15:
                        ranges = [("G00", "H95")]
                        excluded_codes = {"G30"}
                        tag = "nervous_reconstructed_3char_v2"
                    else:
                        ranges = [
                            ("G00", "G29"),
                            ("G32", "G39"),
                            ("G41", "G61"),
                            ("G63", "G71"),
                            ("G73", "H95"),
                        ]
                        tag = "nervous_safe_3char"
                elif parent.startswith("39 "):
                    ranges = [
                        ("D50", "D89"),
                        ("F04", "F09"),
                        ("F11", "F99"),
                        ("L00", "M99"),
                        ("O00", "P96"),
                        ("R00", "R53"),
                        ("R55", "R95"),
                    ]
                    extras = {"F00", "F02"}
                    tag = "other_diseases_candidate"
                else:
                    return {
                        "available": False,
                        "reason": "no safe detailed partition for this broad category",
                    }

                def in_range(label: str) -> bool:
                    code = _leaf_icd_code(label)
                    if code is None:
                        return False
                    if code in excluded_codes:
                        return False
                    if code in extras:
                        return True
                    return any(lo <= code <= hi for lo, hi in ranges)

                age_label = _standard_detail_age_label(age)
                rows = self._fetch_rows(
                    api=STATFIN_ICD_DETAIL_API,
                    dimension_text="Underlying cause of death (ICD-10, 3-character level)",
                    row_selector=in_range,
                    year=year, sex=sex, age_label=age_label,
                    cache_key=f"11be|{tag}|{year}|{sex}|{age_label}",
                )
                source = "Statistics Finland 11be"

                if tag == "nervous_reconstructed_3char_v2":
                    # Reconstruct StatFin category 26 at 3-character detail by
                    # subtracting its four alcohol-specific exclusions using the
                    # dedicated 11bx table. 11bx has matching 5-year age groups
                    # from age 15 upward, so this is an exact count subtraction
                    # for the sex/year/age cell used here.
                    alcohol_age_label = _alcohol_detail_age_label(age)
                    alcohol_codes = {"G312", "G4051", "G621", "G721"}

                    def is_nervous_alcohol_exclusion(label: str) -> bool:
                        upper = label.upper()
                        return any(
                            re.search(
                                rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])",
                                upper,
                            )
                            for code in alcohol_codes
                        )

                    alcohol_rows = self._fetch_rows(
                        api=STATFIN_ALCOHOL_DETAIL_API,
                        dimension_text="Alcohol-related deaths",
                        row_selector=is_nervous_alcohol_exclusion,
                        year=year,
                        sex=sex,
                        age_label=alcohol_age_label,
                        cache_key=(
                            f"11bx|nervous-exclusions-v1|{year}|{sex}|"
                            f"{alcohol_age_label}"
                        ),
                    )

                    exclusion_family = {
                        "G312": "G31",
                        "G4051": "G40",
                        "G621": "G62",
                        "G721": "G72",
                    }
                    subtract_by_family: Counter[str] = Counter()
                    for alcohol_row in alcohol_rows:
                        label_upper = str(alcohol_row.get("label", "")).upper()
                        for alcohol_code, family in exclusion_family.items():
                            if re.search(
                                rf"(?<![A-Z0-9]){re.escape(alcohol_code)}(?![A-Z0-9])",
                                label_upper,
                            ):
                                subtract_by_family[family] += max(
                                    0, int(alcohol_row.get("count", 0))
                                )
                                break

                    adjusted_rows: list[dict[str, object]] = []
                    for row in rows:
                        adjusted = dict(row)
                        family = _leaf_icd_code(str(adjusted.get("label", "")))
                        subtraction = subtract_by_family.get(family or "", 0)
                        if subtraction:
                            original_count = max(0, int(adjusted.get("count", 0)))
                            if subtraction > original_count:
                                raise CauseDataError(
                                    f"11bx alcohol exclusions for {family} sum to "
                                    f"{subtraction}, exceeding 11be {family} count "
                                    f"{original_count}"
                                )
                            adjusted["count"] = original_count - subtraction
                            adjusted["detail_resolution"] = (
                                "3-character reconstructed (11be minus 11bx alcohol subcode)"
                            )
                        adjusted_rows.append(adjusted)
                    rows = adjusted_rows
                    source = "Statistics Finland 11be + 11bx"

            # The broad 11az count is our checksum. 3-character ICD rows can
            # sometimes be too coarse to reproduce exclusions expressed at the
            # 4-character level (for example alcoholic subcodes). Never silently
            # renormalize an over-inclusive child set. Suppressed/missing child
            # cells, on the other hand, are retained as an unresolved residual.
            parent_count = int(broad_outcome.get("count", 0))
            child_total = sum(max(0, int(row.get("count", 0))) for row in rows)
            if parent_count > 0 and child_total > parent_count:
                return {
                    "available": False,
                    "reason": (
                        f"candidate detailed rows sum to {child_total}, exceeding "
                        f"broad parent count {parent_count}; 3-character detail "
                        "cannot safely reproduce this broad category's exclusions, "
                        "so the broad cause is retained"
                    ),
                }
            if parent_count > child_total:
                residual_label = (
                    "External cause not resolvable below the broad parent from public 11b2 data"
                    if parent.startswith("42-53 ")
                    else "Unresolved / suppressed detail within parent category"
                )
                rows = list(rows) + [{
                    "label": residual_label,
                    "count": parent_count - child_total,
                    "detail_resolution": "broad residual" if parent.startswith("42-53 ") else "residual",
                }]

            if boozehound_active_for_age(age):
                weighted_rows: list[dict[str, object]] = []
                for row in rows:
                    adjusted = dict(row)
                    code = _extract_icd_from_label(str(adjusted.get("label", "")))
                    if code:
                        if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                            mult, target_mult, profile, maturity, _basis = _boozehound_icd_hazard_effective_rr(
                                code, age=age, sex=sex, country="fi"
                            )
                        else:
                            mult, target_mult, profile, maturity = boozehound_icd_effective_rr(
                                code, age=age, sex=sex
                            )
                    else:
                        mult, target_mult, profile, maturity = 1.0, 1.0, "chronic", 0.0
                    adjusted["_weight"] = int(adjusted.get("count", 0)) * mult
                    adjusted["cause_modifier"] = mult
                    adjusted["cause_modifier_target"] = target_mult
                    adjusted["boozehound_profile"] = profile
                    adjusted["boozehound_maturity"] = maturity
                    weighted_rows.append(adjusted)
                chosen = _weighted_choice_rows_with_weights(weighted_rows, rng)
                if chosen is not None:
                    observed_total = sum(max(0, int(row.get("count", 0))) for row in rows)
                    chosen["baseline_conditional_probability"] = (
                        int(chosen.get("count", 0)) / observed_total if observed_total > 0 else 0.0
                    )
                    chosen["boozehound_exposure_years"] = boozehound_exposure_years(age)
                    chosen["boozehound_adjusted"] = True
            else:
                chosen = _weighted_choice_rows(rows, rng)
            if chosen is None:
                return {"available": False, "reason": "detailed cell contains no usable deaths"}
            chosen["available"] = True
            chosen["source"] = source
            chosen["age_group"] = age_label
            chosen["lookup_year"] = year
            return chosen

        except (CauseDataError, CohortDataError, OSError, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
            return {"available": False, "reason": f"detail lookup failed: {exc}"}


def print_cause_detail(
    broad_outcome: dict[str, object],
    detail: dict[str, object],
    *,
    tree: bool,
    deep_detail: dict[str, object] | None = None,
) -> None:
    if detail.get("silent"):
        return
    print()
    print_country_section_heading("CAUSE DETAIL")
    if not detail.get("available"):
        print("specific detail unavailable")
        print(f"reason: {detail.get('reason', 'unknown')}")
        return

    parent_p = float(broad_outcome.get("conditional_probability", 0.0))
    child_p = float(detail.get("conditional_probability", 0.0))
    overall = parent_p * child_p
    label = str(detail["label"])
    if tree:
        parent = str(broad_outcome.get("label", "broad cause"))
        print(parent)
        print(f"└── {label}")
    else:
        print(label)
    print(f"within-parent probability: {child_p * 100:.2f}%")
    if detail.get("boozehound_adjusted"):
        baseline_p = float(detail.get("baseline_conditional_probability", 0.0))
        modifier = float(detail.get("cause_modifier", 1.0))
        target = float(detail.get("cause_modifier_target", modifier))
        years = detail.get("boozehound_exposure_years")
        profile = str(detail.get("boozehound_profile", "chronic"))
        suffix = f" (target ×{target:.2f}; profile={profile}"
        if years is not None:
            suffix += f"; {float(years):.1f}y exposure"
        suffix += ")"
        print(
            f"{boozehound_preset_icon()} boozehound detail adjustment: baseline {baseline_p * 100:.2f}% "
            f"| duration-aware ICD weight ×{modifier:.2f}{suffix}"
        )
    cell_name = "Canadian" if broad_outcome.get("country") == "Canada" else "StatFin"
    print(f"implied share of all deaths in broad {cell_name} cell: {overall * 100:.3f}%")
    print(f"detail source: {detail.get('source')} | age {detail.get('age_group')} | year {detail.get('lookup_year')}")
    resolution = str(detail.get("detail_resolution", "specific"))
    if resolution != "specific":
        print(f"detail resolution: {resolution}")

    # Prefer an empirically weighted WHO complete-code refinement when it
    # exactly reconciles to the StatFin 3-character parent. If that refinement
    # is unavailable, retain the non-probabilistic ICD context for families
    # where the missing fourth character materially changes interpretation.
    if deep_detail is not None and deep_detail.get("available"):
        print_who_deep_detail(broad_outcome, detail, deep_detail)
    else:
        if deep_detail is not None:
            print_who_deep_detail(broad_outcome, detail, deep_detail)
        print_icd_subtype_context(detail)



# ---------------------------------------------------------------------------
# v0.11 seasonal death timing
# ---------------------------------------------------------------------------


def _parse_month_code(value: str) -> tuple[int, int] | None:
    """Parse StatFin month labels/codes such as ``2024M01``."""
    match = re.match(r"^(\d{4})M(0[1-9]|1[0-2])$", value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _build_statfin_query(meta: dict, selections: dict[str, list[str]]) -> dict:
    """Build a PxWeb query while auto-selecting singleton dimensions.

    StatFin's 2026 database migration changed some identifiers. Building the
    request from metadata instead of hard-coding dimension codes makes the
    seasonal table tolerant of those identifier changes. Any unexpected
    non-singleton dimension fails closed rather than being silently aggregated.
    """
    query: list[dict[str, object]] = []
    used: set[str] = set()

    for var in meta.get("variables", []):
        code = str(var.get("code", ""))
        values = [str(x) for x in var.get("values", [])]
        if code in selections:
            selected = selections[code]
            used.add(code)
        elif len(values) == 1:
            selected = values
        else:
            raise CauseDataError(
                f"unhandled non-singleton StatFin dimension {var.get('text', code)!r}"
            )
        query.append(
            {
                "code": code,
                "selection": {"filter": "item", "values": selected},
            }
        )

    missing = set(selections) - used
    if missing:
        raise CauseDataError(
            "StatFin metadata did not contain requested dimensions: "
            + ", ".join(sorted(missing))
        )

    return {"query": query, "response": {"format": "json-stat2"}}


def _parse_statfin_seasonal_jsonstat2(
    dataset: dict,
    *,
    month_dim: str,
    cause_dim: str,
    sex_dim: str,
) -> dict[str, dict[int, dict[str, dict[int, int]]]]:
    """Return sex -> year -> broad cause label -> month -> death count."""
    ids = [str(x) for x in dataset["id"]]
    sizes = list(dataset["size"])
    values = dataset["value"]
    categories = {dim_id: _jsonstat_categories(dataset, dim_id) for dim_id in ids}
    positions = {dim_id: i for i, dim_id in enumerate(ids)}

    if len(values) != _product_int(sizes):
        raise CauseDataError("unexpected Statistics Finland 11bf value count")

    result: dict[str, dict[int, dict[str, dict[int, int]]]] = {
        "male": {},
        "female": {},
    }

    flat = 0
    for coords in product(*(range(size) for size in sizes)):
        value = values[flat]
        flat += 1
        if value is None:
            continue

        sex_code = categories[sex_dim][coords[positions[sex_dim]]]
        sex_label = _jsonstat_category_label(dataset, sex_dim, sex_code).casefold()
        if sex_label.startswith("male"):
            sex = "male"
        elif sex_label.startswith("female"):
            sex = "female"
        else:
            continue

        month_code = categories[month_dim][coords[positions[month_dim]]]
        month_label = _jsonstat_category_label(dataset, month_dim, month_code)
        parsed_month = _parse_month_code(month_label) or _parse_month_code(month_code)
        if parsed_month is None:
            continue
        year, month = parsed_month

        cause_code = categories[cause_dim][coords[positions[cause_dim]]]
        cause_label = _jsonstat_category_label(dataset, cause_dim, cause_code)

        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue

        result[sex].setdefault(year, {}).setdefault(cause_label, {})[month] = count

    return result


class SeasonalTimingSource:
    """Conditional death-month distributions from Statistics Finland 11bf.

    Important: 11bf has month + broad underlying cause + sex, but no age
    dimension. The month roll therefore refines the timestamp of a death that
    has *already* happened; it must never alter annual qx or cause selection.
    """

    def __init__(
        self,
        *,
        name: str,
        min_year: int,
        max_year: int,
        data: dict[str, dict[int, dict[str, dict[int, int]]]],
    ) -> None:
        self.name = name
        self.min_year = min_year
        self.max_year = max_year
        self.data = data
        self._cause_label_cache: dict[tuple[str, int, str], str | None] = {}

    def _matching_cause_label(
        self,
        sex: str,
        year: int,
        broad_label: str,
    ) -> tuple[str | None, str]:
        """Map an 11az broad cause onto the coarser 11bf monthly table.

        11az publishes many more time-series cause rows than 11bf. Prefer the
        exact broad category when 11bf contains it. If it does not, fall back
        explicitly to the 00-41 all-diseases monthly profile for disease
        categories, then to 00-54 all-cause timing as a last resort. The
        resolution string is returned so output never implies false precision.
        """
        key = (sex, year, broad_label)
        cached = self._cause_label_cache.get(key)
        if cached is not None:
            # Cache stores "label\0resolution" to keep this dict lightweight.
            label, resolution = cached.split("\0", 1)
            return (label or None), resolution

        year_data = self.data.get(sex, {}).get(year, {})

        def unique_prefix(prefix: str) -> str | None:
            matches = [label for label in year_data if label.startswith(prefix + " ")]
            return matches[0] if len(matches) == 1 else None

        if broad_label in year_data:
            label = broad_label
            resolution = "exact broad cause"
        else:
            broad_prefix = broad_label.split(" ", 1)[0]
            label = unique_prefix(broad_prefix)
            resolution = "exact broad cause" if label is not None else ""

            # 11bf has only a 21-category short list whereas 11az has a much
            # richer classification. For a missing disease row, the monthly
            # profile of all diseases is a defensible but deliberately broader
            # timing fallback. It must be labelled as such.
            if label is None and broad_prefix not in {"42-53", "54"}:
                label = unique_prefix("00-41")
                if label is not None:
                    resolution = "all-diseases fallback (11bf lacks this exact cause row)"

            if label is None:
                label = unique_prefix("00-54")
                if label is not None:
                    resolution = "all-cause fallback (11bf lacks this exact cause row)"

        packed = (label or "") + "\0" + (resolution or "unavailable")
        self._cause_label_cache[key] = packed
        return label, (resolution or "unavailable")

    def roll(
        self,
        *,
        broad_outcome: dict[str, object],
        sex: str,
        calendar_year: int | None,
        rng: random.Random,
    ) -> dict[str, object]:
        if not broad_outcome.get("available"):
            return {
                "available": False,
                "reason": "broad underlying cause unavailable",
            }

        if calendar_year is None:
            requested_year = self.max_year
            lookup_year = self.max_year
            year_status = "latest observed year"
        elif calendar_year < self.min_year:
            return {
                "available": False,
                "reason": (
                    f"seasonal cause-of-death data begin in {self.min_year}; "
                    f"death occurred in {calendar_year}"
                ),
                "calendar_year": calendar_year,
            }
        elif calendar_year > self.max_year:
            requested_year = calendar_year
            lookup_year = self.max_year
            year_status = f"future hold at {self.max_year}"
        else:
            requested_year = calendar_year
            lookup_year = calendar_year
            year_status = "observed year"

        broad_label = str(broad_outcome["label"])
        cause_label, timing_resolution = self._matching_cause_label(
            sex, lookup_year, broad_label
        )
        if cause_label is None:
            return {
                "available": False,
                "reason": (
                    f"no matching 11bf monthly cause row for {broad_label!r}, "
                    f"{sex}, {lookup_year}"
                ),
                "calendar_year": requested_year,
            }

        counts = self.data[sex][lookup_year][cause_label]
        usable = [(month, int(counts.get(month, 0))) for month in range(1, 13)]
        total = sum(max(0, count) for _, count in usable)
        if total <= 0:
            return {
                "available": False,
                "reason": f"11bf monthly cell contains no usable deaths for {cause_label!r}",
                "calendar_year": requested_year,
            }

        target = rng.random() * total
        running = 0
        chosen_month = 12
        chosen_count = 0
        for month, count in usable:
            count = max(0, count)
            running += count
            if target < running:
                chosen_month = month
                chosen_count = count
                break

        days_in_year = 366 if calendar.isleap(lookup_year) else 365

        # Keep the sampled month distinct from descriptive properties of the
        # full 11bf distribution. "Most common death month" means the calendar
        # month with the largest observed raw share in this 11bf cell. Because calendar months
        # have unequal lengths, also report the month with the highest observed
        # deaths-per-day intensity after normalising by days in month.
        month_stats: list[dict[str, object]] = []
        for month, count in usable:
            count = max(0, count)
            p = count / total
            days = calendar.monthrange(lookup_year, month)[1]
            neutral = days / days_in_year
            idx = p / neutral if neutral > 0 else 0.0
            month_stats.append({
                "month": month,
                "month_name": calendar.month_name[month],
                "count": count,
                "conditional_probability": p,
                "seasonal_index": idx,
                "days_in_month": days,
            })

        chosen_stats = month_stats[chosen_month - 1]
        p_month = float(chosen_stats["conditional_probability"])
        days_in_month = int(chosen_stats["days_in_month"])
        seasonal_index = float(chosen_stats["seasonal_index"])

        most_likely = max(
            month_stats,
            key=lambda item: (float(item["conditional_probability"]), -int(item["month"])),
        )
        peak_daily = max(
            month_stats,
            key=lambda item: (float(item["seasonal_index"]), -int(item["month"])),
        )

        return {
            "available": True,
            "month": chosen_month,
            "month_name": calendar.month_name[chosen_month],
            "count": chosen_count,
            "denominator": total,
            "conditional_probability": p_month,
            "seasonal_index": seasonal_index,
            "days_in_month": days_in_month,
            "cause_label": cause_label,
            "calendar_year": requested_year,
            "lookup_year": lookup_year,
            "year_status": year_status,
            "source": self.name,
            "age_specific": False,
            "timing_resolution": timing_resolution,
            "broad_cause_label": broad_label,
            "most_likely_month": int(most_likely["month"]),
            "most_likely_month_name": str(most_likely["month_name"]),
            "most_likely_month_count": int(most_likely["count"]),
            "most_likely_month_probability": float(most_likely["conditional_probability"]),
            "most_likely_month_index": float(most_likely["seasonal_index"]),
            "peak_daily_month": int(peak_daily["month"]),
            "peak_daily_month_name": str(peak_daily["month_name"]),
            "peak_daily_month_probability": float(peak_daily["conditional_probability"]),
            "peak_daily_month_index": float(peak_daily["seasonal_index"]),
        }


def fetch_statfin_seasonality(
    cache_path: Path = DEFAULT_SEASONAL_CACHE,
    refresh: bool = False,
) -> SeasonalTimingSource:
    """Download/cache StatFin 11bf monthly deaths for the broad 11az groups."""
    if cache_path.exists() and not refresh:
        data_status(f"Statistics Finland seasonality: using parsed cache {cache_path}")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        data = {
            sex: {
                int(year): {
                    cause: {int(month): int(count) for month, count in months.items()}
                    for cause, months in causes.items()
                }
                for year, causes in years.items()
            }
            for sex, years in payload["data"].items()
        }
        return SeasonalTimingSource(
            name=payload["name"],
            min_year=int(payload["min_year"]),
            max_year=int(payload["max_year"]),
            data=data,
        )

    data_status("Statistics Finland seasonality: fetching 11bf metadata...")
    try:
        request = urllib.request.Request(
            STATFIN_SEASONAL_API,
            headers={"User-Agent": f"mortality-roulette/{VERSION}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            meta = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CauseDataError(
            "Could not download Statistics Finland 11bf metadata and no usable "
            f"seasonal cache exists at {cache_path}: {exc}"
        ) from exc

    month_var = _metadata_variable(meta, "Month")
    cause_var = _metadata_variable(
        meta, "Underlying cause of death (time series classification)"
    )
    sex_var = _metadata_variable(meta, "Sex")

    # 11bf deliberately exposes a much shorter cause list than 11az. Download
    # every published monthly cause row (only 21 in the current table) and map
    # the already-rolled 11az cause onto it at death time. Requiring every
    # BROAD_CAUSE_PREFIXES row here makes the entire feature fail on legitimate
    # 11bf omissions such as category 38.
    cause_codes = [str(x) for x in cause_var.get("values", [])]
    if not cause_codes:
        raise CauseDataError("Statistics Finland 11bf metadata contained no causes")
    male_code = _value_code(sex_var, "Males")
    female_code = _value_code(sex_var, "Females")
    month_codes = [str(x) for x in month_var.get("values", [])]
    if not month_codes:
        raise CauseDataError("Statistics Finland 11bf metadata contained no months")

    query = _build_statfin_query(
        meta,
        {
            str(month_var["code"]): month_codes,
            str(cause_var["code"]): cause_codes,
            str(sex_var["code"]): [male_code, female_code],
        },
    )

    body = json.dumps(query).encode("utf-8")
    data_status("Statistics Finland seasonality: downloading monthly counts...")
    try:
        request = urllib.request.Request(
            STATFIN_SEASONAL_API,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"mortality-roulette/{VERSION}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            dataset = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CauseDataError(f"Statistics Finland 11bf download failed: {exc}") from exc

    data = _parse_statfin_seasonal_jsonstat2(
        dataset,
        month_dim=str(month_var["code"]),
        cause_dim=str(cause_var["code"]),
        sex_dim=str(sex_var["code"]),
    )
    common_years = sorted(set(data["male"]) & set(data["female"]))
    if not common_years:
        raise CauseDataError("Statistics Finland 11bf response contained no usable data")

    source = SeasonalTimingSource(
        name="Statistics Finland 11bf",
        min_year=common_years[0],
        max_year=common_years[-1],
        data=data,
    )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "name": source.name,
        "min_year": source.min_year,
        "max_year": source.max_year,
        "cache_schema": 2,
        "cause_selection": "all published 11bf cause rows",
        "note": (
            "11bf has no age dimension and a coarser cause list than 11az; "
            "month timing uses exact broad cause when published, otherwise an "
            "explicitly labelled broader fallback"
        ),
        "data": data,
    }
    cache_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return source


class CanadaSeasonalTimingSource:
    """Canada/province all-cause death-month distribution from StatCan 13-10-0708-01.

    Unlike Finland's 11bf, this public Canadian table does not condition month
    on cause, sex or age. It can, however, condition on place of residence.
    """
    def __init__(
        self, *, min_year: int, max_year: int, data: dict[int, dict[int, int]],
        geography: str = "Canada",
    ) -> None:
        self.name = "Statistics Canada 13-10-0708-01"
        self.min_year = min_year
        self.max_year = max_year
        self.data = data
        self.geography = geography
    def roll(self, *, broad_outcome: dict[str, object], sex: str, calendar_year: int | None, rng: random.Random) -> dict[str, object]:
        if calendar_year is None:
            requested_year=lookup_year=self.max_year; status="latest observed year"
        elif calendar_year < self.min_year:
            return {"available": False, "reason": f"Canadian monthly deaths begin in {self.min_year}", "calendar_year": calendar_year}
        elif calendar_year > self.max_year:
            requested_year,lookup_year=calendar_year,self.max_year; status=f"future hold at {self.max_year}"
        else:
            requested_year=lookup_year=calendar_year; status="observed year"
        counts=self.data.get(lookup_year,{})
        usable=[(m,max(0,int(counts.get(m,0)))) for m in range(1,13)]
        total=sum(c for _,c in usable)
        if total<=0: return {"available":False,"reason":f"no Canadian monthly deaths for {lookup_year}"}
        target=rng.random()*total; running=0; chosen_month=12; chosen_count=0
        for month,count in usable:
            running+=count
            if target<running:
                chosen_month,chosen_count=month,count; break
        days_in_year=366 if calendar.isleap(lookup_year) else 365
        stats=[]
        for month,count in usable:
            p=count/total; days=calendar.monthrange(lookup_year,month)[1]; neutral=days/days_in_year
            stats.append({"month":month,"month_name":calendar.month_name[month],"count":count,
                          "conditional_probability":p,"seasonal_index":p/neutral if neutral else 0.0,
                          "days_in_month":days})
        chosen=stats[chosen_month-1]
        likely=max(stats,key=lambda x:(float(x["conditional_probability"]),-int(x["month"])))
        peak=max(stats,key=lambda x:(float(x["seasonal_index"]),-int(x["month"])))
        return {
            "available":True,"country":"Canada","geography":self.geography,"month":chosen_month,"month_name":calendar.month_name[chosen_month],
            "count":chosen_count,"denominator":total,"conditional_probability":float(chosen["conditional_probability"]),
            "seasonal_index":float(chosen["seasonal_index"]),"lookup_year":lookup_year,"calendar_year":requested_year,
            "year_status":status,"source":self.name,"timing_resolution":f"all-cause {self.geography} month distribution",
            "most_likely_month_name":likely["month_name"],"most_likely_month_count":likely["count"],
            "most_likely_month_probability":likely["conditional_probability"],"most_likely_month_index":likely["seasonal_index"],
            "peak_daily_month_name":peak["month_name"],"peak_daily_month_probability":peak["conditional_probability"],
            "peak_daily_month_index":peak["seasonal_index"],
        }


def fetch_statcan_seasonality(
    cache_path: Path = DEFAULT_STATCAN_MONTHLY_CACHE,
    zip_path: Path = DEFAULT_STATCAN_MONTHLY_ZIP,
    refresh: bool = False,
    *,
    province: str | None = None,
) -> CanadaSeasonalTimingSource:
    geography = statcan_geography_name(province)
    cache_path = _regional_cache_path(cache_path, province)
    if cache_path.exists() and not refresh:
        data_status(f"Statistics Canada monthly deaths ({geography}): using parsed cache {cache_path}")
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        cached_geo = str(payload.get("geography", "Canada"))
        if cached_geo.casefold() != geography.casefold():
            raise CauseDataError(
                f"Statistics Canada monthly-deaths cache geography mismatch: expected {geography!r}, found {cached_geo!r} in {cache_path}"
            )
        data = {
            int(y): {int(m): int(c) for m, c in months.items()}
            for y, months in payload["data"].items()
        }
        return CanadaSeasonalTimingSource(
            min_year=int(payload["min_year"]),
            max_year=int(payload["max_year"]),
            data=data,
            geography=geography,
        )

    path = _download_cached_zip(
        STATCAN_MONTHLY_URL,
        zip_path,
        refresh=refresh,
        label="Statistics Canada 13-10-0708 monthly deaths",
    )
    data_status(f"Statistics Canada monthly deaths: opening ZIP {path}")
    data_status("Statistics Canada monthly deaths: parsing CSV rows...")
    data: dict[int, dict[int, int]] = {}

    rows_total = 0
    geography_rows = 0
    number_rows = 0
    month_rows = 0
    value_rows = 0
    sample_geos: list[str] = []
    sample_characteristics: list[str] = []
    sample_uoms: list[str] = []
    sample_months: list[str] = []

    def remember(bucket: list[str], value: object, limit: int = 8) -> None:
        text = str(value or "").strip()
        if text and text not in bucket and len(bucket) < limit:
            bucket.append(text)

    def parse_month_label(value: object) -> int | None:
        text = str(value or "").strip().casefold()
        if not text:
            return None
        # Reject totals before accepting a month substring.
        if "total" in text or "all month" in text:
            return None
        for month in range(1, 13):
            full = calendar.month_name[month].casefold()
            abbr = calendar.month_abbr[month].casefold()
            if text == full or text == abbr or full in text:
                return month
            # Common labels such as "Jan." or "Jan (January)".
            if re.search(rf"(^|[^a-z]){re.escape(abbr)}(?:\.|[^a-z]|$)", text):
                return month
        return None

    def parse_count(value: object) -> int | None:
        text = str(value or "").strip()
        if not text or text in {"..", "...", "x", "X", "F", "r", "p"}:
            return None
        # Full-table CSV values normally contain no thousands separators, but
        # accepting commas/non-breaking spaces costs nothing and makes this
        # robust to alternate StatCan exports.
        text = text.replace(",", "").replace("\u00a0", "").replace(" ", "")
        try:
            number = float(text)
        except ValueError:
            return None
        if number < 0 or not number.is_integer():
            return None
        return int(number)

    with zipfile.ZipFile(path) as zf:
        name = _largest_csv_name(zf)
        info = zf.getinfo(name)
        data_status(
            f"Statistics Canada monthly deaths: selected CSV member {name!r} "
            f"({info.file_size / 1048576:.2f} MiB uncompressed)"
        )
        with zf.open(name, "r") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
            reader = csv.DictReader(text)
            if not reader.fieldnames:
                raise CauseDataError("Statistics Canada monthly CSV has no header")
            fields = [str(f) for f in reader.fieldnames]
            data_status("Statistics Canada monthly deaths: CSV fields: " + ", ".join(fields))

            def exact_field(name: str) -> str | None:
                wanted = name.casefold()
                return next((f for f in fields if f.casefold() == wanted), None)

            def contains_field(*parts: str) -> str | None:
                wanted = tuple(p.casefold() for p in parts)
                return next(
                    (f for f in fields if all(p in f.casefold() for p in wanted)),
                    None,
                )

            ref = exact_field("REF_DATE") or contains_field("ref", "date")
            geo = exact_field("GEO") or contains_field("geo")
            monthf = exact_field("Month of death") or contains_field("month")
            charf = exact_field("Characteristics") or contains_field("character")
            uomf = exact_field("UOM") or contains_field("unit", "measure")
            valuef = exact_field("VALUE") or contains_field("value")

            missing = [
                name
                for name, field in (("REF_DATE", ref), ("GEO", geo), ("month", monthf), ("VALUE", valuef))
                if field is None
            ]
            if missing:
                raise CauseDataError(
                    "Statistics Canada monthly CSV schema changed; missing required fields "
                    + ", ".join(missing)
                    + f"; header={fields!r}"
                )
            data_status(
                "Statistics Canada monthly deaths: mapped fields: "
                f"year={ref!r}, geography={geo!r}, month={monthf!r}, "
                f"characteristic={charf!r}, unit={uomf!r}, value={valuef!r}"
            )
            data_status(
                f"Statistics Canada monthly deaths: geography selector: {geography} / place of residence"
            )
            target_geo = re.sub(r"\s+", " ", geography.casefold()).strip()

            for row in reader:
                rows_total += 1
                geo_text = str(row.get(geo, "") or "").strip()
                remember(sample_geos, geo_text)
                geo_low = re.sub(r"\s+", " ", geo_text.casefold()).strip()
                is_selected_residence = (
                    geo_low == target_geo
                    or (geo_low.startswith(target_geo + ",") and "residence" in geo_low)
                )
                if not is_selected_residence:
                    continue
                geography_rows += 1

                characteristic = str(row.get(charf, "") or "").strip() if charf else ""
                uom = str(row.get(uomf, "") or "").strip() if uomf else ""
                remember(sample_characteristics, characteristic)
                remember(sample_uoms, uom)

                # Table 13-10-0708 publishes both counts and percentages. Use
                # either dimension label *or* unit metadata to identify the
                # count series, because StatCan has changed dimension wording
                # across table generations.
                characteristic_low = characteristic.casefold()
                uom_low = uom.casefold()
                is_number = (
                    "number" in characteristic_low
                    or "count" in characteristic_low
                    or uom_low in {"number", "count", "deaths"}
                    or uom_low.startswith("number")
                )
                is_percentage = (
                    "percent" in characteristic_low
                    or "percentage" in characteristic_low
                    or "%" in characteristic
                    or "percent" in uom_low
                    or "%" in uom
                )
                if is_percentage or not is_number:
                    continue
                number_rows += 1

                month_text = str(row.get(monthf, "") or "").strip()
                remember(sample_months, month_text)
                month = parse_month_label(month_text)
                if month is None:
                    continue
                month_rows += 1

                try:
                    year = int(float(str(row.get(ref, "") or "").strip()))
                except ValueError:
                    continue
                count = parse_count(row.get(valuef))
                if count is None:
                    continue
                value_rows += 1
                previous = data.setdefault(year, {}).get(month)
                if previous is not None and previous != count:
                    raise CauseDataError(
                        f"Statistics Canada monthly table produced conflicting {geography} "
                        f"counts for {year}-{month:02d}: {previous} vs {count}"
                    )
                data[year][month] = count

    years = sorted(
        y for y, months in data.items()
        if len(months) == 12 and sum(months.values()) > 0
    )
    data_status(
        "Statistics Canada monthly deaths: row diagnostics: "
        f"{rows_total:,} total; {geography_rows:,} {geography}; {number_rows:,} count-series; "
        f"{month_rows:,} named-month; {value_rows:,} usable numeric values"
    )
    if not years:
        diagnostics = (
            f"sample GEO={sample_geos!r}; "
            f"Characteristics={sample_characteristics!r}; "
            f"UOM={sample_uoms!r}; Month={sample_months!r}"
        )
        raise CauseDataError(
            f"Statistics Canada 13-10-0708 contained no complete usable {geography} "
            f"monthly-death year; {diagnostics}"
        )

    # Keep only complete 12-month years. This prevents a partially published
    # latest year from being silently normalized as though it represented a
    # full annual seasonal distribution.
    data = {year: data[year] for year in years}
    data_status(
        f"Statistics Canada monthly deaths: parsed complete years "
        f"{years[0]}–{years[-1]} ({len(years)} year(s))"
    )
    source = CanadaSeasonalTimingSource(
        min_year=years[0], max_year=years[-1], data=data, geography=geography
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "cache_schema": 3,
                "source": "Statistics Canada 13-10-0708-01",
                "geography": geography,
                "min_year": source.min_year,
                "max_year": source.max_year,
                "data": data,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    data_status(f"Statistics Canada monthly deaths: parsed cache written: {cache_path}")
    return source


def print_seasonal_timing(outcome: dict[str, object]) -> None:
    print()
    print_country_section_heading("SEASONAL TIMING")
    if not outcome.get("available"):
        print("death-month timing unavailable")
        print(f"reason: {outcome.get('reason', 'unknown')}")
        return

    if outcome.get("country") == "Canada":
        p = float(outcome["conditional_probability"])
        index = float(outcome["seasonal_index"])
        count = int(outcome["count"]); total = int(outcome["denominator"])
        geography = str(outcome.get("geography", "Canada"))
        print(f"month of death: {outcome['month_name']}")
        print(f"conditional month probability: {p * 100:.2f}% ({count:,}/{total:,} deaths in {geography} in this year)")
        print(f"day-count-adjusted seasonal index: {index:.3f}× (1.000 = uniform death rate per day across the year)")
        print(f"most common death month in this distribution: {outcome['most_likely_month_name']} "
              f"({float(outcome['most_likely_month_probability']) * 100:.2f}%; "
              f"{int(outcome['most_likely_month_count']):,}/{total:,}; seasonal index {float(outcome['most_likely_month_index']):.3f}×)")
        print(f"highest per-day seasonal intensity: {outcome['peak_daily_month_name']} "
              f"({float(outcome['peak_daily_month_index']):.3f}×; raw month probability "
              f"{float(outcome['peak_daily_month_probability']) * 100:.2f}%)")
        print(f"timing-data year: {outcome['lookup_year']} ({outcome['year_status']})")
        print(f"timing source: {outcome['source']}")
        print(f"timing resolution: {outcome.get('timing_resolution', 'all-cause Canada month distribution')}")
        print("conditioning: calendar year + geography only; StatCan 13-10-0708 has no cause, sex or age dimension")
        print("timing roll does not alter annual death probability or cause selection")
        return

    p = float(outcome["conditional_probability"])
    index = float(outcome["seasonal_index"])
    count = int(outcome["count"])
    total = int(outcome["denominator"])
    print(f"month of death: {outcome['month_name']}")
    print(
        f"conditional month probability: {p * 100:.2f}% "
        f"({count:,}/{total:,} deaths in this 11bf cause/sex/year cell)"
    )
    print(
        f"day-count-adjusted seasonal index: {index:.3f}× "
        "(1.000 = uniform death rate per day across the year)"
    )

    likely_name = str(outcome.get("most_likely_month_name", ""))
    likely_p = float(outcome.get("most_likely_month_probability", 0.0))
    likely_count = int(outcome.get("most_likely_month_count", 0))
    likely_index = float(outcome.get("most_likely_month_index", 0.0))
    if likely_name:
        print(
            f"most common death month in this 11bf distribution: {likely_name} "
            f"({likely_p * 100:.2f}%; {likely_count:,}/{total:,}; "
            f"seasonal index {likely_index:.3f}×)"
        )

    peak_name = str(outcome.get("peak_daily_month_name", ""))
    peak_index = float(outcome.get("peak_daily_month_index", 0.0))
    peak_p = float(outcome.get("peak_daily_month_probability", 0.0))
    if peak_name:
        print(
            f"highest per-day seasonal intensity: {peak_name} "
            f"({peak_index:.3f}×; raw month probability {peak_p * 100:.2f}%)"
        )

    print(
        f"timing-data year: {outcome['lookup_year']} "
        f"({outcome['year_status']})"
    )
    print(f"timing source: {outcome['source']}")
    resolution = str(outcome.get("timing_resolution", "exact broad cause"))
    print(f"timing resolution: {resolution}")
    if resolution != "exact broad cause":
        print(f"11az cause rolled: {outcome.get('broad_cause_label')}")
        print(f"11bf timing row used: {outcome.get('cause_label')}")
        if str(outcome.get("broad_cause_label", "")).startswith("54 "):
            print("timing fallback reason: no certified underlying cause is available")
    print(
        "conditioning: underlying-cause timing row + sex + calendar year; "
        "StatFin 11bf has no age dimension"
    )
    print("timing roll does not alter annual death probability or cause selection")


def print_batch_seasonality(
    *,
    counts: Counter[int],
    available: int,
    unavailable: int,
    source: SeasonalTimingSource,
) -> None:
    print()
    print("seasonal death timing")
    print("---------------------")
    print(f"source: {source.name} ({source.min_year}M01–{source.max_year}M12)")
    if ACTIVE_COUNTRY == "ca":
        print("conditioning: calendar year only (NOT cause, sex or age)")
    else:
        print("conditioning: broad underlying cause + sex + calendar year (NOT age)")
    print("month is rolled only after mortality and cause-of-death outcomes are fixed")
    print(f"usable month rolls: {available:,}")
    if unavailable:
        print(f"month rolls unavailable: {unavailable:,}")
    if available <= 0:
        return
    print()
    for month in range(1, 13):
        count = counts.get(month, 0)
        pct = count / available * 100.0
        print(f"{calendar.month_name[month]:>9}: {pct:7.3f}%  ({count:,})")


def detail_key_for_batch(
    broad: dict[str, object],
    detail: dict[str, object] | None,
    deep: dict[str, object] | None = None,
) -> str:
    if deep and deep.get("available"):
        return str(deep["label"])
    if detail and detail.get("available"):
        return str(detail["label"])
    return cause_key_for_batch(broad)


def ltc_stats(sex: str) -> dict[str, float]:
    return FINNISH_LTC[sex]


def print_ltc_benchmark(sex: str, birth_year: int | None = None) -> None:
    if ACTIVE_COUNTRY == "ca":
        return
    stats = ltc_stats(sex)
    print()
    print("🏠 FINNISH RESIDENTIAL LONG-TERM CARE BENCHMARK")
    print(f"   register-study period: {FINNISH_LTC['period']}")
    print("   applies conditional on being alive at exact age 65")
    if birth_year is not None:
        age65_year = birth_year + FINNISH_LTC["starting_age"]
        print(f"   this cohort reaches age 65 in calendar year {age65_year}")
        if not (2014 <= age65_year <= 2018):
            print(
                "   WARNING: LTC benchmark is not cohort-matched to this birth year; "
                "treat it as contextual only"
            )
    print(f"   ever entering LTC: {stats['ever_enter_pct']:.1f}%")
    print(
        "   median first-entry age among eventual entrants: "
        f"{stats['median_first_entry_age']:.1f}"
    )
    print(
        "   mean time in LTC if entered: "
        f"{stats['years_in_ltc_if_entered']:.2f} years"
    )
    print(
        "   expected LTC time from age 65 across the whole cohort: "
        f"{stats['expected_ltc_years_at_65']:.2f} years"
    )
    print(
        "   note: study definition includes 90+ day residential LTC / "
        "administrative LTC decisions, not only traditional nursing homes"
    )
    print()


def print_batch_ltc_stats(
    selection: str,
    runs: int,
    batch_results: list[tuple[int, str]],
    birth_year: int | None = None,
) -> None:
    if ACTIVE_COUNTRY == "ca":
        return
    print()
    print("Finnish residential long-term-care benchmark")
    print("--------------------------------------------")
    print(
        f"source period: {FINNISH_LTC['period']} Finnish register multistate life table"
    )
    print("conditional benchmark begins at exact age 65")
    print("expected counts below are CALCULATED, not separately simulated care events")
    if birth_year is not None:
        age65_year = birth_year + FINNISH_LTC["starting_age"]
        print(f"this cohort reaches age 65 in calendar year {age65_year}")
        if not (2014 <= age65_year <= 2018):
            print(
                "cohort mismatch: the 2014–2018 LTC benchmark is shown for context "
                "but expected entrant counts are NOT applied to this cohort"
            )
            print()
            for sex in (
                ("male",)
                if selection == "m"
                else ("female",)
                if selection == "f"
                else ("male", "female")
            ):
                stats = ltc_stats(sex)
                print(
                    f"{sex}: ever enter after 65={stats['ever_enter_pct']:.1f}%, "
                    f"median first entry={stats['median_first_entry_age']:.1f}, "
                    f"mean LTC if entered={stats['years_in_ltc_if_entered']:.2f}y"
                )
            print()
            return
    print()

    sexes = (
        ("male",)
        if selection == "m"
        else ("female",)
        if selection == "f"
        else ("male", "female")
    )

    total_expected = 0.0

    for sex in sexes:
        stats = ltc_stats(sex)
        sex_results = [
            death_age
            for death_age, result_sex in batch_results
            if result_sex == sex
        ]
        sex_runs = len(sex_results)
        reached_65 = sum(death_age >= FINNISH_LTC["starting_age"] for death_age in sex_results)
        expected_entrants = reached_65 * stats["ever_enter_pct"] / 100.0
        total_expected += expected_entrants

        reach65_pct = (reached_65 / sex_runs * 100.0) if sex_runs else 0.0
        birth_cohort_pct = (expected_entrants / sex_runs * 100.0) if sex_runs else 0.0

        print(f"{sex}:")
        print(
            f"  reach age 65 in mortality simulation: "
            f"{reach65_pct:7.3f}%  ({reached_65:,}/{sex_runs:,})"
        )
        print(
            f"  study probability of ever entering LTC after 65: "
            f"{stats['ever_enter_pct']:.1f}%"
        )
        print(
            f"  expected LTC entrants among age-65 survivors: "
            f"~{expected_entrants:,.0f}"
        )
        print(
            f"  implied expected share of these simulated births: "
            f"~{birth_cohort_pct:.2f}%"
        )
        print(
            f"  median first-entry age among eventual entrants: "
            f"{stats['median_first_entry_age']:.1f}"
        )
        print(
            f"  mean years in LTC if entered: "
            f"{stats['years_in_ltc_if_entered']:.2f}"
        )
        print(
            f"  expected LTC years from age 65, whole age-65 cohort: "
            f"{stats['expected_ltc_years_at_65']:.2f}"
        )
        print()

    if selection == "r":
        print(
            f"combined expected LTC entrants in random-sex batch: "
            f"~{total_expected:,.0f}/{runs:,} "
            f"(~{total_expected / runs * 100.0:.2f}% of simulated births)"
        )
        print()


def record_cap_age(sex: str) -> int:
    """Whole-year hard cap based on the verified Finnish longevity record."""
    return FINNISH_RECORDS[sex]["years"]


def record_cap_triggered(age: int, sex: str, enabled: bool) -> bool:
    """Force death at the verified Finnish record ceiling when enabled."""
    if ACTIVE_COUNTRY == "ca":
        return False
    return enabled and age >= record_cap_age(sex)

def resolve_annual_mortality_q(
    *,
    age: int,
    sex: str,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> tuple[float, float, float, dict[str, object], str, bool, int | None]:
    """Resolve the exact annual qx used by roulette and deterministic printout.

    Returns (effective_q, baseline_q, alcohol_multiplier, alcohol_diag,
    mortality_source, tail_model, calendar_year). Keeping this lookup in one
    function prevents --printout from drifting away from the actual roller.
    """
    if birth_year is None:
        q, tail_model = q_for_age(age, sex)
        if tail_model:
            mortality_source = "tail model"
        elif ACTIVE_COUNTRY == "fi" and ACTIVE_MORTALITY_MODEL == "legacy":
            mortality_source = "original legacy Mortality Roulette"
        elif ACTIVE_PERIOD_SOURCE is not None and ACTIVE_MORTALITY_MODEL == "smoothed":
            mortality_source = f"{ACTIVE_PERIOD_SOURCE.name} — age-graduated"
        else:
            mortality_source = ACTIVE_PERIOD_SOURCE.name if ACTIVE_PERIOD_SOURCE is not None else "period table"
        calendar_year = None
    else:
        if cohort_source is None:
            raise CohortDataError("internal error: missing cohort source")
        calendar_year = birth_year + age
        q, mortality_source, tail_model = cohort_q_for_age(
            age=age,
            sex=sex,
            birth_year=birth_year,
            source=cohort_source,
        )

    baseline_q = q
    q, alcohol_multiplier, alcohol_diag = alcohol_adjust_q(
        q,
        age=age,
        sex=sex,
        cause_source=alcohol_cause_source,
    )
    return (
        q, baseline_q, alcohol_multiplier, alcohol_diag,
        mortality_source, tail_model, calendar_year,
    )


def default_printout_end_age(
    *,
    sex: str,
    birth_year: int | None,
    cohort_source: CohortMortalitySource | None,
) -> int:
    """Default last annual qx interval for deterministic printout mode.

    Finland mirrors the ordinary roulette's usable annual-roll range: show all
    qx intervals up to the year immediately before the observed longevity-record
    ceiling would force the run to end. Official qx ends at age 99, so age 100+
    rows are visibly marked as model tail. Canada has no project record ceiling,
    so its default remains the last official exact-age qx.
    """
    if ACTIVE_COUNTRY == "fi":
        return record_cap_age(sex) - 1
    if birth_year is not None:
        if cohort_source is None:
            raise CohortDataError("internal error: birth-year printout has no cohort source")
        return int(cohort_source.max_exact_age)
    if ACTIVE_PERIOD_SOURCE is not None:
        return int(ACTIVE_PERIOD_SOURCE.max_exact_age)
    raise CohortDataError("internal error: no active period mortality source")


def print_mortality_odds_table(
    *,
    sex: str,
    start_age: int,
    end_age: int,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> None:
    """Print qx rows without drawing RNG rolls or terminating on death."""
    print()
    print(f"=== MORTALITY ROULETTE v{VERSION} — PRINTOUT ===")
    print(country_display_label())
    print(f"sex: {sex}")
    print(f"age range: {start_age}–{end_age}")
    if birth_year is None:
        if ACTIVE_COUNTRY == "fi" and ACTIVE_MORTALITY_MODEL == "legacy":
            print("mortality mode: ORIGINAL LEGACY MORTALITY ROULETTE")
            print("mortality source: original baked schedule from early versions")
            print("status: retained for historical comparison and reproducibility")
        else:
            print(f"mortality mode: PRESENT-DAY {mortality_model_display_name()}")
            if ACTIVE_PERIOD_SOURCE is not None:
                print(f"mortality source: {ACTIVE_PERIOD_SOURCE.name} ({ACTIVE_PERIOD_SOURCE.max_year})")
                if ACTIVE_MORTALITY_MODEL == "smoothed":
                    print(
                        "graduation: 5-age triangular hazard smoother (1,2,3,2,1); "
                        f"nondecreasing PAVA from age {AGE_GRADUATION_MONOTONIC_FROM}"
                    )
                    print(f"official source support: exact-age qx 0–{ACTIVE_PERIOD_SOURCE.max_exact_age}")
                else:
                    print(f"official exact-age qx: 0–{ACTIVE_PERIOD_SOURCE.max_exact_age}")
                if end_age > ACTIVE_PERIOD_SOURCE.max_exact_age:
                    print(
                        f"modeled tail shown: {ACTIVE_PERIOD_SOURCE.max_exact_age + 1}–{end_age} "
                        "([tail model])"
                    )
    else:
        print(f"mortality mode: BIRTH COHORT / CALENDAR-YEAR | birth year: {birth_year}")
        if cohort_source is not None:
            print(f"mortality source: {cohort_source.name} ({cohort_source.min_year}–{cohort_source.max_year})")
    if ACTIVE_BOOZEHOUND:
        print(
            f"lifestyle modifier: {boozehound_preset_icon()} {boozehound_preset_label()} | "
            f"alcohol risk engine: {alcohol_model_label()}"
        )
    print("RNG: OFF — deterministic qx printout")
    print()

    saw_tail = False
    for age in range(start_age, end_age + 1):
        (
            q, baseline_q, alcohol_multiplier, _alcohol_diag,
            mortality_source, tail_model, calendar_year,
        ) = resolve_annual_mortality_q(
            age=age,
            sex=sex,
            birth_year=birth_year,
            cohort_source=cohort_source,
            alcohol_cause_source=alcohol_cause_source,
        )

        if birth_year is None:
            prefix = f"age {age:3d} -> {age + 1:3d}"
        else:
            prefix = f"age {age:3d} -> {age + 1:3d} | year {calendar_year}"

        booze_piece = ""
        if boozehound_active_for_age(age):
            exposure_years = boozehound_exposure_years(age)
            target_mult = boozehound_all_cause_target_rr(sex)
            booze_piece = (
                f" | {boozehound_preset_icon()} baseline {baseline_q * 100:.4f}% "
                f"×{alcohol_multiplier:.3f} (target ×{target_mult:.2f}; {exposure_years:.1f}y exposure)"
            )

        if tail_model:
            saw_tail = True
        source_suffix = ""
        if birth_year is not None:
            source_suffix = f" [{mortality_source}]"
        elif tail_model:
            source_suffix = " [tail model]"

        print(
            f"{prefix} | death prob. {q * 100:8.4f}% ({fmt_one_in(q):>12})"
            f"{booze_piece}{source_suffix}"
        )

    if saw_tail:
        print()
        tail_reference = (
            "last age-graduated qx" if ACTIVE_MORTALITY_MODEL == "smoothed"
            else "last official qx" if ACTIVE_MORTALITY_MODEL == "official"
            else "last legacy-table qx"
        )
        print(
            "note: rows marked [tail model] are explicit approximations, not exact observed-age qx; "
            f"the tail never decreases below the {tail_reference}."
        )


def simulate(
    sex: str,
    rng: random.Random,
    delay: float,
    log_path: Path | None,
    start_age: int = 0,
    use_record_cap: bool = True,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    cause_source: CauseOfDeathSource | None = None,
    cause_rng: random.Random | None = None,
    detail_resolver: CauseDetailResolver | None = None,
    detail_rng: random.Random | None = None,
    deep_detail_resolver: WhoDeepDetailResolver | None = None,
    deep_detail_rng: random.Random | None = None,
    cause_detail_mode: str = "broad",
    seasonal_source: SeasonalTimingSource | None = None,
    seasonal_rng: random.Random | None = None,
    alcohol_cause_source: object | None = None,
) -> int:
    writer = None
    fh = None

    if log_path:
        fh = log_path.open("w", newline="", encoding="utf-8")
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "age",
                "calendar_year",
                "sex",
                "mortality_source",
                "death_probability",
                "death_probability_percent",
                "baseline_death_probability",
                "boozehound_multiplier",
                "boozehound_multiplier_target",
                "boozehound_exposure_years",
                "boozehound_cumulative_ethanol_kg",
                "one_in_x",
                "roll",
                "roll_percent",
                "result",
                "tail_model",
                "cause_of_death",
                "cause_probability",
                "cause_data_year",
                "cause_age_group",
                "deep_cause_of_death",
                "deep_cause_probability",
                "deep_cause_source",
                "death_month",
                "death_month_probability",
                "seasonal_index",
                "seasonal_data_year",
            ],
        )
        writer.writeheader()

    try:
        print()
        print(f"=== MORTALITY ROULETTE v{VERSION} ===")
        print(country_display_label())
        print(f"sex: {sex}")
        print_record_banner(sex)
        print(f"starting age: {start_age}")
        if ACTIVE_BOOZEHOUND:
            icon = boozehound_preset_icon()
            label = boozehound_preset_label()
            print(f"lifestyle modifier: {icon} {label}")
            if ACTIVE_BOOZEHOUND_PRESET == "wino":
                print(
                    f"alcohol exposure: one {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottle/day of "
                    f"{BOOZEHOUND_WINO_ABV * 100:.0f}% ABV wine ≈ {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g pure ethanol/day"
                )
            else:
                print(f"alcohol exposure: {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g pure ethanol/day")
            for line in boozehound_schedule_lines():
                print(line)
            print(f"alcohol risk engine: {alcohol_model_label()}")
            if ACTIVE_ALCOHOL_MODEL == "legacy":
                print(
                    f"all-cause mortality RR target at this dose: male ×{boozehound_all_cause_target_rr('male'):.2f}, "
                    f"female ×{boozehound_all_cause_target_rr('female'):.2f}; duration-aware ramp over {BOOZEHOUND_ALL_CAUSE_RAMP_YEARS:g} years"
                )
                print("mortality math: RR applied on annual hazard; excess risk compounds through cumulative survival across years")
                print("cause model: alcohol-linked ICD causes reweighted with duration and dose; Canada uses complete-code aggregation, Finland broad StatFin proxies plus ICD detail weights")
            else:
                geography = "WHO complete-ICD" if ACTIVE_COUNTRY == "ca" else "StatFin broad-cause"
                print(f"prototype mortality math: {geography} hazards × duration/dose cause weights → recombined annual hazard")
                print(f"cause-hazard weight model: {cause_hazard_weight_model_label()}")
                if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v1":
                    print("evidence-v1 coverage: direct alcohol-related mortality uses raw Carr 2024 dose-response; remaining causes use proxy-v1")
                    print("prototype baseline note: population alcohol burden remains embedded in the observed mortality table")
                elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
                    print("evidence-v4 coverage: v3 direct-alcohol normalization + Dai 2026 cancer subhazards; remaining non-cancer mappings use proxy-v1")
                    for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                        print(line)
                elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v3-popdist":
                    print("evidence-v3 coverage: direct alcohol-related mortality uses Carr 2024 normalized by WHO-style Gamma population E[RR]; remaining causes use proxy-v1")
                    for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                        print(line)
                elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
                    anchor_g, source = alcohol_population_anchor(ACTIVE_COUNTRY, sex)
                    print(f"evidence-v2 population anchor: {anchor_g:.1f} g/day mean-dose equivalent | {source}")
                    print("population-normalization warning: first-order Carr(mean dose) normalization; not full exposure-distribution deconvolution")
                else:
                    print("prototype warning: cause weights are architecture-sensitivity proxies, not validated causal hazard RRs")
                    print("prototype baseline note: population alcohol burden is not deconvolved")
            print("exposure state: persistent duration + cumulative ethanol + cumulative survival/hazard accounting")
            if ACTIVE_BOOZEHOUND_PRESET == "wino":
                print("wino cause-dose scaling: excess RR scaled conservatively from the 60 g/day reference; explicit scenario assumption")
            print("calibration note: chronic-drinker RRs remain scenario targets; background drinking is not deconvolved; named comorbidity onset is not invented without incidence data")
        if birth_year is None:
            if ACTIVE_COUNTRY == "fi" and ACTIVE_MORTALITY_MODEL == "legacy":
                print("mortality mode: PRESENT-DAY ORIGINAL LEGACY MORTALITY ROULETTE")
                print("ages 0-100: original baked mortality probabilities")
                print("status: retained for historical comparison and reproducibility")
                print(">100: explicit legacy tail approximation, capped at 50% annual mortality")
            elif ACTIVE_PERIOD_SOURCE is not None:
                print(f"mortality mode: PRESENT-DAY {mortality_model_display_name()}")
                print(f"observed mortality source: {ACTIVE_PERIOD_SOURCE.name} ({ACTIVE_PERIOD_SOURCE.max_year})")
                if ACTIVE_COUNTRY == "ca" and ACTIVE_PERIOD_SOURCE.max_year >= 2023:
                    print("life-table status: preliminary Statistics Canada estimates")
                if ACTIVE_MORTALITY_MODEL == "smoothed":
                    print(
                        "graduation: 5-age triangular hazard smoother (1,2,3,2,1); "
                        f"nondecreasing PAVA from age {AGE_GRADUATION_MONOTONIC_FROM}"
                    )
                    print(f"ages 0-{ACTIVE_PERIOD_SOURCE.max_exact_age}: age-graduated from official exact-age qx")
                    tail_ref = "last age-graduated qx"
                else:
                    print(f"ages 0-{ACTIVE_PERIOD_SOURCE.max_exact_age}: observed exact-age qx")
                    tail_ref = "last official qx"
                print(
                    f">{ACTIVE_PERIOD_SOURCE.max_exact_age}: explicit tail approximation; "
                    f"50% is the nominal ceiling, never below the {tail_ref}"
                )
            else:
                raise CohortDataError("internal error: present-day source missing")
        else:
            if cohort_source is None:
                raise CohortDataError("internal error: birth-year mode has no cohort source")
            print("mortality mode: BIRTH COHORT / CALENDAR-YEAR")
            print(f"birth year: {birth_year}")
            print(
                f"observed mortality source: {cohort_source.name} "
                f"({cohort_source.min_year}–{cohort_source.max_year})"
            )
            print(
                f"future rule: hold {cohort_source.max_year} age-specific qx constant"
            )
            print(
                f"extreme ages >{cohort_source.max_exact_age}: explicit tail approximation"
            )
        if ACTIVE_COUNTRY == "ca":
            print("longevity mode: CANADA — no national longevity-record hard cap applied")
        elif use_record_cap:
            rec = FINNISH_RECORDS[sex]
            print(
                f"longevity mode: OBSERVED FINNISH RANGE — capped within "
                f"{rec['name']}'s final year ({rec['years']}y {rec['days']}d)"
            )
        else:
            print(
                "longevity mode: EXCEPTIONAL TAIL — hypothetical model-only "
                "survival beyond the verified Finnish record is allowed"
            )
        if cause_source is not None:
            print(
                f"cause-of-death roulette: ON — {cause_source.name} "
                f"({cause_source.min_year}–{cause_source.max_year})"
            )
            print(f"cause detail: {cause_detail_mode.upper()}")
            if USE_ICD_TITLES:
                print("ICD code titles: ON — WHO ICD-10 2019 + subsequent WHO emergency-use updates")
            else:
                print("ICD code titles: OFF — raw code display")
            if deep_detail_resolver is not None:
                print("deep ICD refinement: ON — WHO Mortality Database complete ICD codes")
        else:
            print("cause-of-death roulette: OFF")
        if seasonal_source is not None:
            if ACTIVE_COUNTRY == "ca":
                print(
                    f"seasonal death timing: ON — {seasonal_source.name} "
                    f"({seasonal_source.min_year}M01–{seasonal_source.max_year}M12; "
                    f"all-cause {getattr(seasonal_source, 'geography', 'Canada')} timing, no cause/sex/age conditioning)"
                )
            else:
                print(
                    f"seasonal death timing: ON — {seasonal_source.name} "
                    f"({seasonal_source.min_year}M01–{seasonal_source.max_year}M12; no age dimension)"
                )
        else:
            print("seasonal death timing: OFF")
        if log_path:
            print(f"log: {log_path}")
        print()

        age = start_age
        ltc_benchmark_printed = False

        if ACTIVE_COUNTRY != "ca" and age >= FINNISH_LTC["starting_age"]:
            print_ltc_benchmark(sex, birth_year=birth_year)
            ltc_benchmark_printed = True

        while True:
            if (
                ACTIVE_COUNTRY != "ca"
                and not ltc_benchmark_printed
                and age >= FINNISH_LTC["starting_age"]
            ):
                print_ltc_benchmark(sex, birth_year=birth_year)
                ltc_benchmark_printed = True

            maybe_print_record_milestone(age, sex)

            forced_by_record_cap = record_cap_triggered(age, sex, use_record_cap)

            (
                q, baseline_q, boozehound_mult, alcohol_diag,
                mortality_source, tail_model, calendar_year,
            ) = resolve_annual_mortality_q(
                age=age,
                sex=sex,
                birth_year=birth_year,
                cohort_source=cohort_source,
                alcohol_cause_source=alcohol_cause_source,
            )

            if forced_by_record_cap:
                roll = None
                died = True
                source_tag = " [observed-record ceiling]"
                result = "🏆 BIG WIN"
                year_piece = (
                    f" | year {birth_year + age}"
                    if birth_year is not None
                    else ""
                )
                print(
                    f"age {age:3d} -> {age + 1:3d}{year_piece} | "
                    f"death FORCED by observed-record ceiling | "
                    f"{result}{source_tag}",
                    flush=True,
                )
            else:
                roll = rng.random()
                died = roll < q
                source_tag = " [tail model]" if tail_model else ""
                result = "🏆 BIG WIN" if died else "survived"
                if birth_year is None:
                    prefix = f"age {age:3d} -> {age + 1:3d}"
                    source_suffix = source_tag
                else:
                    prefix = (
                        f"age {age:3d} -> {age + 1:3d} | "
                        f"year {calendar_year}"
                    )
                    source_suffix = f" [{mortality_source}]"

                booze_piece = ""
                if boozehound_active_for_age(age):
                    exposure_years = boozehound_exposure_years(age)
                    target_mult = boozehound_all_cause_target_rr(sex)
                    booze_piece = (
                        f" | {boozehound_preset_icon()} baseline {baseline_q * 100:.4f}% "
                        f"×{boozehound_mult:.3f} (target ×{target_mult:.2f}; {exposure_years:.1f}y exposure)"
                    )
                print(
                    f"{prefix} | "
                    f"death prob. {q * 100:8.4f}% ({fmt_one_in(q):>12})"
                    f"{booze_piece} | "
                    f"roll {roll * 100:8.4f}% | "
                    f"{result}{source_suffix}",
                    flush=True,
                )

            cause_outcome = None
            if died and cause_source is not None:
                if cause_rng is None:
                    raise CauseDataError("internal error: cause source has no RNG")
                cause_outcome = cause_source.roll(
                    sex=sex,
                    age=age,
                    calendar_year=(birth_year + age if birth_year is not None else None),
                    rng=cause_rng,
                )

            detail_outcome = None
            if (
                died
                and cause_outcome is not None
                and detail_resolver is not None
                and cause_detail_mode in {"specific", "tree"}
            ):
                if detail_rng is None:
                    raise CauseDataError("internal error: detail resolver has no RNG")
                detail_outcome = detail_resolver.roll_detail(
                    broad_outcome=cause_outcome,
                    sex=sex,
                    age=age,
                    calendar_year=(birth_year + age if birth_year is not None else None),
                    rng=detail_rng,
                )

            deep_detail_outcome = None
            if (
                died
                and detail_outcome is not None
                and detail_outcome.get("available")
                and deep_detail_resolver is not None
                and cause_detail_mode in {"specific", "tree"}
            ):
                if deep_detail_rng is None:
                    raise CauseDataError("internal error: WHO deep-detail resolver has no RNG")
                deep_detail_outcome = deep_detail_resolver.roll(
                    detail=detail_outcome,
                    sex=sex,
                    rng=deep_detail_rng,
                )

            seasonal_outcome = None
            if died and cause_outcome is not None and seasonal_source is not None:
                if seasonal_rng is None:
                    raise CauseDataError("internal error: seasonal source has no RNG")
                seasonal_outcome = seasonal_source.roll(
                    broad_outcome=cause_outcome,
                    sex=sex,
                    calendar_year=(birth_year + age if birth_year is not None else None),
                    rng=seasonal_rng,
                )

            if writer:
                writer.writerow(
                    {
                        "age": age,
                        "calendar_year": "" if birth_year is None else birth_year + age,
                        "sex": sex,
                        "mortality_source": mortality_source,
                        "death_probability": q,
                        "death_probability_percent": q * 100,
                        "baseline_death_probability": baseline_q,
                        "boozehound_multiplier": boozehound_mult,
                        "boozehound_multiplier_target": (
                            boozehound_all_cause_target_rr(sex)
                            if boozehound_active_for_age(age) and ACTIVE_ALCOHOL_MODEL == "legacy"
                            else ""
                        ),
                        "boozehound_exposure_years": (
                            boozehound_exposure_years(age) if boozehound_active_for_age(age) else 0.0
                        ),
                        "boozehound_cumulative_ethanol_kg": (
                            boozehound_cumulative_ethanol_kg(age) if boozehound_active_for_age(age) else 0.0
                        ),
                        "one_in_x": one_in_x(q),
                        "roll": "" if roll is None else roll,
                        "roll_percent": "" if roll is None else roll * 100,
                        "result": (
                            "death_record_cap"
                            if forced_by_record_cap
                            else ("death" if died else "survive")
                        ),
                        "tail_model": tail_model,
                        "cause_of_death": (
                            ""
                            if cause_outcome is None
                            else cause_key_for_batch(cause_outcome)
                        ),
                        "cause_probability": (
                            ""
                            if not cause_outcome or not cause_outcome.get("available")
                            else cause_outcome["conditional_probability"]
                        ),
                        "cause_data_year": (
                            ""
                            if not cause_outcome or not cause_outcome.get("available")
                            else cause_outcome["lookup_year"]
                        ),
                        "cause_age_group": (
                            ""
                            if not cause_outcome or not cause_outcome.get("available")
                            else cause_outcome["age_group"]
                        ),
                        "deep_cause_of_death": (
                            ""
                            if not deep_detail_outcome or not deep_detail_outcome.get("available")
                            else deep_detail_outcome["label"]
                        ),
                        "deep_cause_probability": (
                            ""
                            if not deep_detail_outcome or not deep_detail_outcome.get("available")
                            else deep_detail_outcome["conditional_probability"]
                        ),
                        "deep_cause_source": (
                            ""
                            if not deep_detail_outcome or not deep_detail_outcome.get("available")
                            else deep_detail_outcome["source"]
                        ),
                        "death_month": (
                            ""
                            if not seasonal_outcome or not seasonal_outcome.get("available")
                            else seasonal_outcome["month"]
                        ),
                        "death_month_probability": (
                            ""
                            if not seasonal_outcome or not seasonal_outcome.get("available")
                            else seasonal_outcome["conditional_probability"]
                        ),
                        "seasonal_index": (
                            ""
                            if not seasonal_outcome or not seasonal_outcome.get("available")
                            else seasonal_outcome["seasonal_index"]
                        ),
                        "seasonal_data_year": (
                            ""
                            if not seasonal_outcome or not seasonal_outcome.get("available")
                            else seasonal_outcome["lookup_year"]
                        ),
                    }
                )
                fh.flush()

            if died:
                if cause_outcome is not None:
                    print_cause_outcome(cause_outcome)
                    if detail_outcome is not None:
                        print_cause_detail(
                            cause_outcome,
                            detail_outcome,
                            tree=(cause_detail_mode == "tree"),
                            deep_detail=deep_detail_outcome,
                        )
                    if seasonal_outcome is not None:
                        print_seasonal_timing(seasonal_outcome)
                if ACTIVE_BOOZEHOUND:
                    print_boozehound_exposure_summary(
                        age,
                        sex,
                        start_age=start_age,
                        birth_year=birth_year,
                        cohort_source=cohort_source,
                        alcohol_cause_source=alcohol_cause_source,
                    )
                print()
                print(f"*** {country_flag()} BIG WIN at age {age} ***")
                return age

            age += 1

            if delay > 0:
                time.sleep(delay)

    finally:
        if fh:
            fh.close()



def build_death_age_cdf(
    sex: str,
    *,
    start_age: int = 0,
    use_record_cap: bool = True,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> tuple[list[int], list[float]]:
    """Exact inverse-CDF representation of the same age-by-age hazard process."""
    ages: list[int] = []
    cdf: list[float] = []
    survival = 1.0
    age = start_age

    while True:
        if record_cap_triggered(age, sex, use_record_cap):
            ages.append(age)
            cdf.append(1.0)
            break

        if birth_year is None:
            q, _ = q_for_age(age, sex)
        else:
            if cohort_source is None:
                raise CohortDataError("internal error: missing cohort source")
            q, _, _ = cohort_q_for_age(
                age=age,
                sex=sex,
                birth_year=birth_year,
                source=cohort_source,
            )

        q, _boozehound_mult, _alcohol_diag = alcohol_adjust_q(
            q,
            age=age,
            sex=sex,
            cause_source=alcohol_cause_source,
        )

        death_mass = survival * q
        survival -= death_mass
        ages.append(age)
        cdf.append(1.0 - survival)

        # In exceptional-tail mode the 50% cap makes the residual shrink rapidly.
        # Collapse only an utterly negligible floating tail to keep the CDF finite.
        if not use_record_cap and survival <= 1e-15:
            cdf[-1] = 1.0
            break

        age += 1
        if age > 1000:
            raise RuntimeError("failed to close mortality CDF by age 1000")

    return ages, cdf


def sample_death_age_cdf(
    rng: random.Random,
    ages: list[int],
    cdf: list[float],
) -> int:
    u = rng.random()
    idx = bisect.bisect_left(cdf, u)
    if idx >= len(ages):
        idx = len(ages) - 1
    return ages[idx]


def simulate_age_only(
    sex: str,
    rng: random.Random,
    start_age: int = 0,
    use_record_cap: bool = True,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    alcohol_cause_source: object | None = None,
) -> int:
    """Fast simulation for batch mode; returns the age interval in which death occurs."""
    age = start_age
    while True:
        if record_cap_triggered(age, sex, use_record_cap):
            return age

        if birth_year is None:
            q, _ = q_for_age(age, sex)
        else:
            if cohort_source is None:
                raise CohortDataError("internal error: missing cohort source")
            q, _, _ = cohort_q_for_age(
                age=age,
                sex=sex,
                birth_year=birth_year,
                source=cohort_source,
            )

        q, _boozehound_mult, _alcohol_diag = alcohol_adjust_q(
            q,
            age=age,
            sex=sex,
            cause_source=alcohol_cause_source,
        )

        if rng.random() < q:
            return age
        age += 1


def death_age_histogram_rows(ages: list[int]) -> list[tuple[str, int, float]]:
    """Return fixed, comparable death-age bands for batch presentation."""
    if not ages:
        return []

    bands: list[tuple[str, int | None, int | None]] = [
        ("<20", None, 19),
        ("20–29", 20, 29),
        ("30–39", 30, 39),
        ("40–49", 40, 49),
        ("50–59", 50, 59),
        ("60–69", 60, 69),
        ("70–79", 70, 79),
        ("80–89", 80, 89),
        ("90–99", 90, 99),
        ("100+", 100, None),
    ]
    total = len(ages)
    rows: list[tuple[str, int, float]] = []
    for label, lower, upper in bands:
        if lower is None:
            count = sum(age <= int(upper) for age in ages)
        elif upper is None:
            count = sum(age >= lower for age in ages)
        else:
            count = sum(lower <= age <= upper for age in ages)
        rows.append((label, count, count / total * 100.0))
    return rows


def print_death_age_histogram(ages: list[int]) -> None:
    """Print a terminal-width-aware death-age histogram for batch mode."""
    rows = death_age_histogram_rows(ages)
    if not rows:
        return

    terminal_columns = shutil.get_terminal_size(fallback=(120, 24)).columns
    # Fixed text columns consume ~31 cells. Keep enough room for a useful bar,
    # while avoiding enormous bars on ultra-wide terminals.
    bar_width = max(12, min(72, terminal_columns - 34))
    max_share = max(share for _label, _count, share in rows) or 1.0

    print("death-age distribution")
    print("──────────────────────")
    print(f"{'age':>6}  {'deaths':>12}  {'share':>8}  distribution")
    for label, count, share in rows:
        filled = 0 if count == 0 else max(1, round(share / max_share * bar_width))
        bar = "█" * filled
        print(f"{label:>6}  {count:12,d}  {share:7.3f}%  {bar}")



def _statfin_broad_batch_key_from_label(label: str) -> str:
    """Return the same broad batch label as cause_key_for_batch without an outcome dict."""
    if label.startswith("54 "):
        return "No death certificate"
    if label.startswith("40 "):
        return "Ill-defined / unknown cause"
    parts = label.split(" ", 1)
    return parts[1] if len(parts) == 2 else label


def _statfin_grouped_cause_distribution(
    *,
    source: "CauseOfDeathSource",
    sex: str,
    age: int,
    calendar_year: int | None,
) -> tuple[list[str], list[float], float] | None:
    """Resolve one broad StatFin cell into the exact weights used by CauseOfDeathSource.roll.

    This intentionally mirrors the reference sampler's boozehound cause shaping.
    Only the sampling strategy differs: the caller may draw many deaths from the
    compiled distribution at once.
    """
    cell = source.counts_for(sex=sex, age=age, calendar_year=calendar_year)
    if not cell.get("available"):
        return None
    counts = dict(cell["counts"])
    labels: list[str] = []
    cumulative: list[float] = []
    running = 0.0
    adjusted = boozehound_active_for_age(age)
    for label, raw_count in counts.items():
        count = int(raw_count)
        if count <= 0:
            continue
        weight = float(count)
        if adjusted:
            if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                mult, _target, _profile, _maturity, _basis = _boozehound_finland_broad_hazard_effective_rr(
                    label, age=age, sex=sex,
                    parent_count=count,
                    lookup_year=int(cell["lookup_year"]),
                    detail_resolver=getattr(source, "_alcohol_detail_resolver", None),
                )
            else:
                mult, _target, _profile, _maturity = boozehound_finland_broad_effective_rr(
                    label, age=age, sex=sex
                )
            weight *= mult
        if weight <= 0.0:
            continue
        running += weight
        labels.append(label)
        cumulative.append(running)
    if running <= 0.0 or not labels:
        return None
    return labels, cumulative, running


def sample_statfin_broad_causes_grouped(
    *,
    batch_results: list[tuple[int, str]],
    source: "CauseOfDeathSource",
    rng: random.Random,
    birth_year: int | None,
) -> Counter[str]:
    """Bulk-sample broad StatFin causes by sex/death-age cell.

    Mortality sampling is already complete before this function runs, and the
    cause RNG is an independent stream. Grouping therefore changes neither death
    ages nor their RNG stream; it only avoids rebuilding identical cause weights
    for every individual death.
    """
    grouped: Counter[tuple[str, int]] = Counter((sex, age) for age, sex in batch_results)
    totals: Counter[str] = Counter()
    for (sex, age), n in grouped.items():
        calendar_year = birth_year + age if birth_year is not None else None
        dist = _statfin_grouped_cause_distribution(
            source=source,
            sex=sex,
            age=age,
            calendar_year=calendar_year,
        )
        if dist is None:
            totals["CAUSE DATA UNAVAILABLE"] += n
            continue
        labels, cumulative, _total = dist
        # random.choices accepts cumulative weights directly and performs only
        # the cheap C-level bisect/random draw per death. The expensive StatFin
        # resolution and boozehound reweighting happen once per group above.
        draws = rng.choices(labels, cum_weights=cumulative, k=n)
        for label, count in Counter(draws).items():
            totals[_statfin_broad_batch_key_from_label(label)] += count
    return totals


def _resolve_cause_batch_sampler(
    *,
    requested: str,
    cause_source: object | None,
    cause_detail_mode: str,
    seasonal_source: object | None,
) -> tuple[str, str | None]:
    """Return (actual sampler, fallback reason)."""
    if requested == "reference-slow" or cause_source is None:
        return requested, None
    if not isinstance(cause_source, CauseOfDeathSource):
        return "reference-slow", "fast-grouped currently supports StatFin Finland broad causes only"
    if cause_detail_mode != "broad":
        return "reference-slow", f"cause detail mode {cause_detail_mode!r} requires individual outcome objects"
    if seasonal_source is not None:
        return "reference-slow", "seasonal death timing currently requires individual cause outcomes"
    return "fast-grouped", None


def run_batch(
    selection: str,
    runs: int,
    rng: random.Random,
    start_age: int = 0,
    show_progress: bool = True,
    use_record_cap: bool = True,
    birth_year: int | None = None,
    cohort_source: CohortMortalitySource | None = None,
    cause_source: CauseOfDeathSource | None = None,
    cause_rng: random.Random | None = None,
    top_causes: int = 16,
    batch_engine: str = "fast",
    cause_batch_sampler: str = DEFAULT_CAUSE_BATCH_SAMPLER,
    show_histogram: bool = True,
    detail_resolver: CauseDetailResolver | None = None,
    detail_rng: random.Random | None = None,
    deep_detail_resolver: WhoDeepDetailResolver | None = None,
    deep_detail_rng: random.Random | None = None,
    cause_detail_mode: str = "broad",
    seasonal_source: SeasonalTimingSource | None = None,
    seasonal_rng: random.Random | None = None,
    alcohol_cause_source: object | None = None,
) -> None:
    """Run many simulated lives and print aggregate sanity-check statistics."""
    ages: list[int] = []
    batch_results: list[tuple[int, str]] = []
    male_count = 0
    female_count = 0
    cause_counts: Counter[str] = Counter()
    seasonal_counts: Counter[int] = Counter()
    seasonal_available = 0
    seasonal_unavailable = 0

    spinner = "-\\|/"
    spinner_index = 0
    last_progress_update = 0.0
    batch_started = time.monotonic()

    cdf_by_sex: dict[str, tuple[list[int], list[float]]] = {}
    if batch_engine == "fast":
        needed_sexes = ("male", "female") if selection == "r" else (("male",) if selection == "m" else ("female",))
        for cdf_sex in needed_sexes:
            cdf_by_sex[cdf_sex] = build_death_age_cdf(
                cdf_sex,
                start_age=start_age,
                use_record_cap=use_record_cap,
                birth_year=birth_year,
                cohort_source=cohort_source,
                alcohol_cause_source=alcohol_cause_source,
            )

    actual_cause_batch_sampler, cause_sampler_fallback_reason = _resolve_cause_batch_sampler(
        requested=cause_batch_sampler,
        cause_source=cause_source,
        cause_detail_mode=cause_detail_mode,
        seasonal_source=seasonal_source,
    )

    if show_progress:
        print()
        print("Running simulations...", flush=True)

    for i in range(runs):
        sex = choose_sex(selection, rng)
        if sex == "male":
            male_count += 1
        else:
            female_count += 1

        if batch_engine == "fast":
            cdf_ages, cdf_values = cdf_by_sex[sex]
            death_age = sample_death_age_cdf(rng, cdf_ages, cdf_values)
        else:
            death_age = simulate_age_only(
                sex,
                rng,
                start_age=start_age,
                use_record_cap=use_record_cap,
                birth_year=birth_year,
                cohort_source=cohort_source,
                alcohol_cause_source=alcohol_cause_source,
            )
        ages.append(death_age)
        batch_results.append((death_age, sex))

        if cause_source is not None and actual_cause_batch_sampler == "reference-slow":
            if cause_rng is None:
                raise CauseDataError("internal error: cause source has no RNG")
            outcome = cause_source.roll(
                sex=sex,
                age=death_age,
                calendar_year=(
                    birth_year + death_age
                    if birth_year is not None
                    else None
                ),
                rng=cause_rng,
            )
            detail = None
            if detail_resolver is not None and cause_detail_mode in {"specific", "tree"}:
                if detail_rng is None:
                    raise CauseDataError("internal error: detail resolver has no RNG")
                detail = detail_resolver.roll_detail(
                    broad_outcome=outcome,
                    sex=sex,
                    age=death_age,
                    calendar_year=(birth_year + death_age if birth_year is not None else None),
                    rng=detail_rng,
                )
            deep = None
            if (
                detail is not None
                and detail.get("available")
                and deep_detail_resolver is not None
                and cause_detail_mode in {"specific", "tree"}
            ):
                if deep_detail_rng is None:
                    raise CauseDataError("internal error: WHO deep-detail resolver has no RNG")
                deep = deep_detail_resolver.roll(
                    detail=detail,
                    sex=sex,
                    rng=deep_detail_rng,
                )
            cause_counts[detail_key_for_batch(outcome, detail, deep)] += 1

            if seasonal_source is not None:
                if seasonal_rng is None:
                    raise CauseDataError("internal error: seasonal source has no RNG")
                seasonal = seasonal_source.roll(
                    broad_outcome=outcome,
                    sex=sex,
                    calendar_year=(birth_year + death_age if birth_year is not None else None),
                    rng=seasonal_rng,
                )
                if seasonal.get("available"):
                    seasonal_counts[int(seasonal["month"])] += 1
                    seasonal_available += 1
                else:
                    seasonal_unavailable += 1

        if show_progress:
            now = time.monotonic()
            # Update often enough to animate, but not on every simulation.
            if now - last_progress_update >= 0.08 or i + 1 == runs:
                done = i + 1
                pct = done / runs * 100.0
                elapsed = max(now - batch_started, 1e-9)
                rate = done / elapsed
                ch = spinner[spinner_index % len(spinner)]
                spinner_index += 1

                print(
                    f"\r{ch}  {done:,}/{runs:,}  "
                    f"({pct:6.2f}%)  "
                    f"{rate:,.0f} lives/s",
                    end="",
                    flush=True,
                )
                last_progress_update = now

    if cause_source is not None and actual_cause_batch_sampler == "fast-grouped":
        if cause_rng is None:
            raise CauseDataError("internal error: cause source has no RNG")
        cause_counts.update(
            sample_statfin_broad_causes_grouped(
                batch_results=batch_results,
                source=cause_source,
                rng=cause_rng,
                birth_year=birth_year,
            )
        )

    if show_progress:
        elapsed = time.monotonic() - batch_started
        # Clear the spinner line and replace it with a final status line.
        print(
            f"\r✓  {runs:,}/{runs:,}  (100.00%)  "
            f"completed in {elapsed:.2f}s"
            + " " * 12
        )

    print()
    print(f"=== MORTALITY ROULETTE v{VERSION}: BATCH MODE ===")
    print(country_display_label())
    if selection == "m":
        print("sex: male")
    elif selection == "f":
        print("sex: female")
    else:
        print(
            f"sex: random ({male_count:,} male / {female_count:,} female; "
            f"target male share={MALE_BIRTH_SHARE:.1%})"
        )
    print(f"runs: {runs:,}")
    print(f"starting age: {start_age}")
    if ACTIVE_BOOZEHOUND:
        icon = boozehound_preset_icon()
        label = boozehound_preset_label()
        print(f"lifestyle modifier: {icon} {label}")
        if ACTIVE_BOOZEHOUND_PRESET == "wino":
            print(
                f"alcohol exposure: one {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottle/day of "
                f"{BOOZEHOUND_WINO_ABV * 100:.0f}% ABV wine ≈ {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g pure ethanol/day"
            )
        else:
            print(f"alcohol exposure: {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g pure ethanol/day")
        for line in boozehound_schedule_lines():
            print(line)
        print(f"alcohol risk engine: {alcohol_model_label()}")
        if ACTIVE_ALCOHOL_MODEL == "legacy":
            print(
                f"all-cause mortality RR target at this dose: male ×{boozehound_all_cause_target_rr('male'):.2f}, "
                f"female ×{boozehound_all_cause_target_rr('female'):.2f}; duration-aware ramp over {BOOZEHOUND_ALL_CAUSE_RAMP_YEARS:g} years"
            )
            print("mortality math: hazard-scale RR with cumulative survival compounding")
            print("cause model: alcohol-linked causes reweighted with duration and dose")
        else:
            geography = "WHO complete-ICD" if ACTIVE_COUNTRY == "ca" else "StatFin broad-cause"
            print(f"prototype mortality math: {geography} hazards × duration/dose cause weights → recombined annual hazard")
            print(f"cause-hazard weight model: {cause_hazard_weight_model_label()}")
            if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v1":
                print("evidence-v1 coverage: direct alcohol-related mortality uses raw Carr 2024 dose-response; remaining causes use proxy-v1")
                print("prototype baseline note: population alcohol burden remains embedded in the observed mortality table")
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
                print("evidence-v4 coverage: v3 direct-alcohol normalization + Dai 2026 cancer subhazards; remaining non-cancer mappings use proxy-v1")
                for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                    print(line)
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v3-popdist":
                print("evidence-v3 coverage: direct alcohol-related mortality uses Carr 2024 normalized by WHO-style Gamma population E[RR]; remaining causes use proxy-v1")
                for line in alcohol_population_distribution_summary(ACTIVE_COUNTRY, sex):
                    print(line)
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
                anchor_g, source = alcohol_population_anchor(ACTIVE_COUNTRY, sex)
                print(f"evidence-v2 population anchor: {anchor_g:.1f} g/day mean-dose equivalent | {source}")
                print("population-normalization warning: first-order Carr(mean dose) normalization; not full exposure-distribution deconvolution")
            else:
                print("prototype warning: cause weights are architecture-sensitivity proxies; background alcohol not deconvolved")
        if ACTIVE_BOOZEHOUND_PRESET == "wino":
            print("wino cause-dose scaling: excess RR scaled from the 60 g/day reference (scenario assumption)")
    print(
        "batch engine: "
        + (
            "FAST CDF / inverse-transform sampling"
            if batch_engine == "fast"
            else "STEP / literal annual mortality rolls"
        )
    )
    if birth_year is None:
        if ACTIVE_COUNTRY == "fi" and ACTIVE_MORTALITY_MODEL == "legacy":
            print("mortality mode: PRESENT-DAY ORIGINAL LEGACY MORTALITY ROULETTE")
        elif ACTIVE_PERIOD_SOURCE is not None:
            print(
                f"mortality mode: PRESENT-DAY {mortality_model_display_name()} — "
                f"{ACTIVE_PERIOD_SOURCE.name} ({ACTIVE_PERIOD_SOURCE.max_year})"
            )
            if ACTIVE_MORTALITY_MODEL == "smoothed":
                print(
                    "graduation: 5-age triangular hazard smoother (1,2,3,2,1); "
                    f"nondecreasing PAVA from age {AGE_GRADUATION_MONOTONIC_FROM}"
                )
            if ACTIVE_COUNTRY == "ca" and ACTIVE_PERIOD_SOURCE.max_year >= 2023:
                print("life-table status: preliminary Statistics Canada estimates")
        else:
            raise CohortDataError("internal error: present-day source missing")
    else:
        if cohort_source is None:
            raise CohortDataError("internal error: birth-year batch has no cohort source")
        print("mortality mode: BIRTH COHORT / CALENDAR-YEAR")
        print(f"birth year: {birth_year}")
        print(
            f"observed source: {cohort_source.name} "
            f"({cohort_source.min_year}–{cohort_source.max_year})"
        )
        print(
            f"future rule: hold {cohort_source.max_year} age-specific qx constant"
        )
    if ACTIVE_COUNTRY == "ca":
        print("longevity mode: CANADA — no national record hard cap")
    elif use_record_cap:
        print("longevity mode: OBSERVED FINNISH RANGE")
    else:
        print("longevity mode: EXCEPTIONAL TAIL (model-only beyond records)")
    print(
        "cause-of-death roulette: "
        + (
            f"ON — {cause_source.name}"
            if cause_source is not None
            else "OFF"
        )
    )
    if cause_source is not None:
        if actual_cause_batch_sampler == "fast-grouped":
            print("batch cause sampler: FAST GROUPED / CACHED CELL DISTRIBUTIONS")
        else:
            print("batch cause sampler: REFERENCE SLOW / PER-DEATH ROLLS")
        if cause_sampler_fallback_reason is not None:
            print(f"cause sampler fallback: {cause_sampler_fallback_reason}")
        print(f"cause detail: {cause_detail_mode.upper()}")
        if USE_ICD_TITLES:
            print("ICD code titles: ON — WHO ICD-10 2019 + subsequent WHO emergency-use updates")
        else:
            print("ICD code titles: OFF — raw code display")
        if deep_detail_resolver is not None:
            print("deep ICD refinement: ON — WHO Mortality Database complete ICD codes")
    if seasonal_source is not None:
        if ACTIVE_COUNTRY == "ca":
            print(
                f"seasonal death timing: ON — {seasonal_source.name} "
                f"({seasonal_source.min_year}M01–{seasonal_source.max_year}M12; "
                f"all-cause {getattr(seasonal_source, 'geography', 'Canada')} timing, no cause/sex/age conditioning)"
            )
        else:
            print(
                f"seasonal death timing: ON — {seasonal_source.name} "
                f"({seasonal_source.min_year}M01–{seasonal_source.max_year}M12; no age dimension)"
            )
    else:
        print("seasonal death timing: OFF")
    print()
    print(f"mean age at death:   {statistics.fmean(ages):6.2f}")
    print(f"median age at death: {statistics.median(ages):6.1f}")
    print(f"youngest death:      {min(ages):6d}")
    print(f"oldest death:        {max(ages):6d}")
    print()

    if show_histogram:
        print_death_age_histogram(ages)
        print()

    checkpoints = [1, 18, 40, 60, 70, 80, 83, 84, 85, 90, 95, 100, 105, 110]
    print("survival checkpoints")
    print("--------------------")
    for target_age in checkpoints:
        survivors = sum(age >= target_age for age in ages)
        pct = survivors / runs * 100.0
        print(f"reach {target_age:3d}: {pct:7.3f}%  ({survivors:,}/{runs:,})")

    if cause_source is not None:
        print_batch_causes(
            counts=cause_counts,
            runs=runs,
            source=cause_source,
            birth_year=birth_year,
            top_n=top_causes,
        )

    if seasonal_source is not None:
        print_batch_seasonality(
            counts=seasonal_counts,
            available=seasonal_available,
            unavailable=seasonal_unavailable,
            source=seasonal_source,
        )

    print_batch_ltc_stats(
        selection=selection,
        runs=runs,
        batch_results=batch_results,
        birth_year=birth_year,
    )

    if ACTIVE_COUNTRY != "ca":
        print()
        print("Finnish longevity-record milestones")
        print("-----------------------------------")
        if use_record_cap:
            print("observed-record ceiling: ENABLED")
        else:
            print("observed-record ceiling: DISABLED (--exceptional-tail)")

        if selection in {"m", "f"}:
            sex = "male" if selection == "m" else "female"
            rec = FINNISH_RECORDS[sex]
            at_record_age = sum(age >= rec["years"] for age in ages)
            definitely_past = sum(age >= rec["years"] + 1 for age in ages)
            print(f"{sex} record holder: {record_label(sex)}")
            print(f"reach {rec['years']:3d}: {at_record_age / runs * 100:7.4f}%  ({at_record_age:,}/{runs:,})")
            print(f"reach {rec['years'] + 1:3d}: {definitely_past / runs * 100:7.4f}%  ({definitely_past:,}/{runs:,})  [guaranteed exact record exceeded]")
        else:
            for sex in ("male", "female"):
                rec = FINNISH_RECORDS[sex]
                sex_ages = [age for age, result_sex in batch_results if result_sex == sex]
                n = len(sex_ages)
                at_record_age = sum(age >= rec["years"] for age in sex_ages)
                definitely_past = sum(age >= rec["years"] + 1 for age in sex_ages)
                print(f"{sex} record holder: {record_label(sex)}")
                print(f"  reach {rec['years']:3d}: {(at_record_age / n * 100) if n else 0:7.4f}%  ({at_record_age:,}/{n:,})")
                print(f"  reach {rec['years'] + 1:3d}: {(definitely_past / n * 100) if n else 0:7.4f}%  ({definitely_past:,}/{n:,}) [guaranteed exact record exceeded]")

    ordered = sorted(ages)

    def percentile(p: float) -> int:
        idx = round((len(ordered) - 1) * p)
        return ordered[idx]

    print()
    print("death-age percentiles")
    print("---------------------")
    for p in (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"{int(p * 100):>2d}th percentile: {percentile(p):3d}")



def _activate_deathmatch_context(ctx: dict[str, object]) -> None:
    """Switch legacy country/region globals to one deathmatch contestant."""
    global ACTIVE_COUNTRY, ACTIVE_PERIOD_SOURCE, ACTIVE_CANADA_PROVINCE
    ACTIVE_COUNTRY = str(ctx["country"])
    ACTIVE_PERIOD_SOURCE = ctx.get("period_source")  # type: ignore[assignment]
    ACTIVE_CANADA_PROVINCE = (
        str(ctx["province"]) if ctx.get("province") is not None else None
    )


def _deathmatch_rng(
    seed: int | None,
    country: str,
    salt: int,
    *,
    contestant_index: int = 0,
) -> random.Random:
    """Independent reproducible RNG stream for one deathmatch contestant.

    The contestant index is deliberately part of the stream key.  This matters
    for same-country matches: Finland player 1 and Finland player 2 must not
    receive identical mortality/cause/detail/timing rolls merely because they
    use the same national data backend.
    """
    if seed is None:
        return random.Random()
    country_salt = {"fi": 0x46494E4C, "ca": 0x43414E41}[country]
    player_salt = ((contestant_index + 1) * 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
    return random.Random(
        (int(seed) ^ country_salt ^ player_salt ^ salt) & ((1 << 64) - 1)
    )


def _preflight_deathmatch_country(
    args: argparse.Namespace,
    country: str,
    *,
    province: str | None,
    cause_detail_mode: str,
    contestant_index: int,
) -> dict[str, object]:
    """Prepare one contestant's present-day mortality/cause/timing backends."""
    global ACTIVE_COUNTRY, ACTIVE_PERIOD_SOURCE, ACTIVE_CANADA_PROVINCE
    ACTIVE_COUNTRY = country
    ACTIVE_PERIOD_SOURCE = None
    ACTIVE_CANADA_PROVINCE = province if country == "ca" else None

    period_source = None
    cause_source = None
    detail_resolver = None
    deep_detail_resolver = None
    seasonal_source = None
    canada_raw = None

    if country == "ca":
        data_status("Canada deathmatch side: loading annual mortality probabilities...", level=1)
        if args.statcan_cache is not None or args.refresh_statcan:
            statcan_cache = args.statcan_cache or DEFAULT_STATCAN_CACHE
            statcan_province = province
        elif province == "bc" and BUNDLED_STATCAN_LIFE_TABLE_BC.exists():
            # fetch_statcan_life_table() applies the regional _bc suffix itself.
            # Pass the national/base path here or it would become *_bc_bc.json.
            statcan_cache = BUNDLED_STATCAN_LIFE_TABLE
            statcan_province = province
        elif province is None and BUNDLED_STATCAN_LIFE_TABLE.exists():
            statcan_cache = BUNDLED_STATCAN_LIFE_TABLE
            statcan_province = None
        else:
            statcan_cache = DEFAULT_STATCAN_CACHE
            statcan_province = province
        period_source = fetch_statcan_life_table(
            cache_path=statcan_cache,
            refresh=args.refresh_statcan,
            province=statcan_province,
        )
        ACTIVE_PERIOD_SOURCE = period_source
    elif ACTIVE_MORTALITY_MODEL != "legacy":
        data_status(
            "Finland deathmatch side: loading official annual mortality probabilities"
            + (" for age graduation..." if ACTIVE_MORTALITY_MODEL == "smoothed" else "..."),
            level=1,
        )
        statfin_cache = args.statfin_cache or (DEFAULT_STATFIN_CACHE if args.refresh_statfin else BUNDLED_STATFIN_LIFE_TABLE)
        period_source = fetch_statfin_life_table(
            cache_path=statfin_cache, refresh=args.refresh_statfin
        )
        ACTIVE_PERIOD_SOURCE = period_source
    else:
        data_status("Finland deathmatch side: using original legacy Mortality Roulette mortality schedule", level=1)

    need_cause_source = bool(args.causes or ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype")
    if need_cause_source:
        if country == "ca":
            data_status("Canada deathmatch side: resolving WHO cause-of-death data...", level=1)
            canada_raw = WhoCountryRawMortality(
                country_code=WHO_CANADA_COUNTRY_CODE,
                country_name="Canada",
                cache_dir=args.who_detail_cache_dir,
                refresh=args.refresh_who_detail,
            )
            cause_source = CanadaCauseOfDeathSource(canada_raw)
            cause_source.resolve_latest_year()
        else:
            data_status("Finland deathmatch side: loading StatFin cause-of-death data...", level=1)
            cause_source = fetch_statfin_causes(
                cache_path=(args.cause_cache or (DEFAULT_CAUSE_CACHE if args.refresh_causes else BUNDLED_STATFIN_CAUSES)),
                refresh=args.refresh_causes,
            )

    need_finland_v4_detail = (
        country == "fi"
        and ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype"
        and ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer"
    )
    if (args.causes and cause_detail_mode in {"specific", "tree"}) or need_finland_v4_detail:
        if country == "ca":
            if args.causes and cause_detail_mode in {"specific", "tree"}:
                if canada_raw is None:
                    raise CauseDataError("internal error: Canadian WHO raw source missing")
                detail_resolver = CanadaCauseDetailResolver(canada_raw)
        else:
            detail_resolver = CauseDetailResolver(
                cache_path=(args.detail_cache or (DEFAULT_DETAIL_CACHE if args.refresh_detail else BUNDLED_STATFIN_DETAIL)),
                refresh=args.refresh_detail,
            )
            if isinstance(cause_source, CauseOfDeathSource):
                setattr(cause_source, "_alcohol_detail_resolver", detail_resolver)
            if args.causes and cause_detail_mode in {"specific", "tree"} and not args.no_who_detail:
                deep_detail_resolver = WhoDeepDetailResolver(
                    cache_dir=args.who_detail_cache_dir,
                    refresh=args.refresh_who_detail,
                )
                if cause_source is not None:
                    preflight_year = int(cause_source.max_year)
                    data_status(
                        f"Finland deathmatch side: preflighting WHO deep ICD detail for {preflight_year}...",
                        level=1,
                    )
                    deep_detail_resolver.preflight_year(preflight_year)

    if args.seasonality:
        if country == "ca":
            data_status("Canada deathmatch side: loading monthly death distribution...", level=1)
            statcan_seasonal_refresh = args.refresh_statcan or args.refresh_seasonality
            if args.statcan_seasonal_cache is not None or statcan_seasonal_refresh:
                statcan_seasonal_cache = args.statcan_seasonal_cache or DEFAULT_STATCAN_MONTHLY_CACHE
                statcan_seasonal_province = province
            elif province == "bc" and BUNDLED_STATCAN_SEASONAL_BC.exists():
                # The monthly loader likewise appends the regional _bc suffix.
                statcan_seasonal_cache = BUNDLED_STATCAN_SEASONAL
                statcan_seasonal_province = province
            elif province is None and BUNDLED_STATCAN_SEASONAL.exists():
                statcan_seasonal_cache = BUNDLED_STATCAN_SEASONAL
                statcan_seasonal_province = None
            else:
                statcan_seasonal_cache = DEFAULT_STATCAN_MONTHLY_CACHE
                statcan_seasonal_province = province
            seasonal_source = fetch_statcan_seasonality(
                cache_path=statcan_seasonal_cache,
                refresh=statcan_seasonal_refresh,
                province=statcan_seasonal_province,
            )
        else:
            data_status("Finland deathmatch side: loading StatFin seasonal death timing...", level=1)
            seasonal_source = fetch_statfin_seasonality(
                cache_path=(args.seasonal_cache or (DEFAULT_SEASONAL_CACHE if args.refresh_seasonality else BUNDLED_STATFIN_SEASONAL)),
                refresh=args.refresh_seasonality,
            )

    ctx: dict[str, object] = {
        "country": country,
        "province": province if country == "ca" else None,
        "contestant_index": contestant_index,
        "period_source": period_source,
        "cause_source": cause_source,
        "detail_resolver": detail_resolver,
        "deep_detail_resolver": deep_detail_resolver,
        "seasonal_source": seasonal_source,
        "cause_rng": _deathmatch_rng(args.seed, country, 0x43415553, contestant_index=contestant_index),
        "detail_rng": _deathmatch_rng(args.seed, country, 0x44455441, contestant_index=contestant_index),
        "deep_rng": _deathmatch_rng(args.seed, country, 0x44454550, contestant_index=contestant_index),
        "seasonal_rng": _deathmatch_rng(args.seed, country, 0x53454153, contestant_index=contestant_index),
    }
    return ctx


def _deathmatch_roll_cause_stack(
    ctx: dict[str, object],
    *,
    sex: str,
    age: int,
    cause_detail_mode: str,
) -> dict[str, object]:
    """Roll cause/detail/month for a contestant after its mortality roll has lost."""
    _activate_deathmatch_context(ctx)
    cause_outcome = None
    detail_outcome = None
    deep_outcome = None
    seasonal_outcome = None

    cause_source = ctx.get("cause_source")
    if cause_source is not None:
        cause_outcome = cause_source.roll(
            sex=sex,
            age=age,
            calendar_year=None,
            rng=ctx["cause_rng"],
        )

    detail_resolver = ctx.get("detail_resolver")
    if (
        cause_outcome is not None
        and detail_resolver is not None
        and cause_detail_mode in {"specific", "tree"}
    ):
        detail_outcome = detail_resolver.roll_detail(
            broad_outcome=cause_outcome,
            sex=sex,
            age=age,
            calendar_year=None,
            rng=ctx["detail_rng"],
        )

    deep_resolver = ctx.get("deep_detail_resolver")
    if (
        detail_outcome is not None
        and detail_outcome.get("available")
        and deep_resolver is not None
        and cause_detail_mode in {"specific", "tree"}
    ):
        deep_outcome = deep_resolver.roll(
            detail=detail_outcome,
            sex=sex,
            rng=ctx["deep_rng"],
        )

    seasonal_source = ctx.get("seasonal_source")
    if cause_outcome is not None and seasonal_source is not None:
        seasonal_outcome = seasonal_source.roll(
            broad_outcome=cause_outcome,
            sex=sex,
            calendar_year=None,
            rng=ctx["seasonal_rng"],
        )

    return {
        "cause": cause_outcome,
        "detail": detail_outcome,
        "deep": deep_outcome,
        "seasonal": seasonal_outcome,
    }


def _deathmatch_cell(
    ctx: dict[str, object],
    state: dict[str, object],
    *,
    age: int,
    sex: str,
    exceptional_tail: bool,
    mortality_roll: float,
) -> str:
    country = str(ctx["country"])
    if state.get("dead"):
        return f"☠ dead at {int(state['death_age'])}"

    _activate_deathmatch_context(ctx)
    forced = record_cap_triggered(
        age,
        sex,
        enabled=(country == "fi" and not exceptional_tail),
    )

    q0, tail_model = q_for_age(age, sex)
    if ACTIVE_BOOZEHOUND:
        q, mult, alcohol_diag = alcohol_adjust_q(
            q0, age=age, sex=sex, cause_source=ctx.get("cause_source")
        )
    else:
        q, mult, alcohol_diag = q0, 1.0, {"engine": ACTIVE_ALCOHOL_MODEL, "effective_multiplier": 1.0}
    roll = None if forced else mortality_roll
    died = forced or (roll is not None and roll < q)

    if forced:
        body = "FORCED record ceiling | ☠"
    else:
        booze = ""
        if boozehound_active_for_age(age):
            booze = f" [{q0 * 100:.4f}×{mult:.3f}]"
        tail = " tail" if tail_model else ""
        status = "☠" if died else "✓"
        body = (
            f"q {q * 100:.4f}%{booze} | "
            f"roll {float(roll) * 100:.4f}% | {status}{tail}"
        )

    if died:
        state["dead"] = True
        state["death_age"] = age
        state["baseline_q"] = q0
        state["q"] = q
        state["mult"] = mult
        state["alcohol_diag"] = alcohol_diag
        state["roll"] = roll
        state["forced"] = forced

    return body


def _print_deathmatch_final_card(
    ctx: dict[str, object],
    state: dict[str, object],
    *,
    sex: str,
    start_age: int,
    cause_detail_mode: str,
) -> None:
    country = str(ctx["country"])
    province = str(ctx["province"]) if ctx.get("province") is not None else None
    age = int(state["death_age"])
    player_number = ctx.get("player_number")
    _activate_deathmatch_context(ctx)
    label = deathmatch_contestant_label(
        country,
        sex,
        province=province,
        player_number=(int(player_number) if player_number is not None else None),
    )
    print()
    heading = f"{label} FINAL CARD"
    print(heading)
    print("=" * _terminal_display_width(heading))

    stack = state.get("cause_stack") or {}
    cause_outcome = stack.get("cause")
    detail_outcome = stack.get("detail")
    deep_outcome = stack.get("deep")
    seasonal_outcome = stack.get("seasonal")

    if cause_outcome is not None:
        print_cause_outcome(cause_outcome)
        if detail_outcome is not None:
            print_cause_detail(
                cause_outcome,
                detail_outcome,
                tree=(cause_detail_mode == "tree"),
                deep_detail=deep_outcome,
            )
        if seasonal_outcome is not None:
            print_seasonal_timing(seasonal_outcome)
    if ACTIVE_BOOZEHOUND:
        print_boozehound_exposure_summary(
            age,
            sex,
            start_age=start_age,
            birth_year=None,
            cohort_source=None,
            alcohol_cause_source=ctx.get("cause_source"),
        )
    print()
    print(
        _terminal_emphasis(
            _deathmatch_tapout_banner(
                country,
                sex,
                age,
                province=province,
                player_number=(int(player_number) if player_number is not None else None),
            ),
            bold=True,
        )
    )


def _clean_broad_cause_label(outcome: dict[str, object] | None) -> str:
    if not outcome or not outcome.get("available"):
        return "unavailable"
    if outcome.get("no_death_certificate"):
        return "No death certificate"
    if outcome.get("ill_defined"):
        return "Ill-defined / unknown cause"
    label = str(outcome.get("label", "unknown"))
    parts = label.split(" ", 1)
    return parts[1] if len(parts) == 2 and parts[0][0:1].isdigit() else label


def _deathmatch_compact_stats(
    ctx: dict[str, object],
    state: dict[str, object],
    *,
    sex: str,
    start_age: int,
) -> list[tuple[str, str]]:
    """Build the compact sports-card rows printed under DEATHMATCH RESULT."""
    _activate_deathmatch_context(ctx)
    age = int(state["death_age"])
    stack = state.get("cause_stack") or {}
    cause = stack.get("cause") if isinstance(stack, dict) else None
    detail = stack.get("detail") if isinstance(stack, dict) else None
    deep = stack.get("deep") if isinstance(stack, dict) else None
    seasonal = stack.get("seasonal") if isinstance(stack, dict) else None

    rows: list[tuple[str, str]] = [("TAPPED OUT", f"age {age}")]
    q = state.get("q")
    q0 = state.get("baseline_q")
    mult = state.get("mult")
    if isinstance(q, (int, float)):
        if ACTIVE_BOOZEHOUND and isinstance(q0, (int, float)) and isinstance(mult, (int, float)):
            rows.append(("FATAL q", f"{float(q) * 100:.4f}% (baseline {float(q0) * 100:.4f}% ×{float(mult):.3f})"))
        else:
            rows.append(("FATAL q", f"{float(q) * 100:.4f}%"))
    roll = state.get("roll")
    if isinstance(roll, (int, float)):
        rows.append(("FATAL ROLL", f"{float(roll) * 100:.4f}%"))
    elif state.get("forced"):
        rows.append(("FATAL ROLL", "forced longevity-record ceiling"))

    rows.append(("CAUSE", _clean_broad_cause_label(cause if isinstance(cause, dict) else None)))
    detail_text = "specific detail unavailable"
    if isinstance(deep, dict) and deep.get("available"):
        detail_text = str(deep.get("label", deep.get("code", detail_text)))
    elif isinstance(detail, dict) and detail.get("available"):
        detail_text = str(detail.get("label", detail_text))
    rows.append(("DETAIL", detail_text))

    if isinstance(seasonal, dict) and seasonal.get("available"):
        rows.append(("MONTH", str(seasonal.get("month_name", "unknown"))))

    if ACTIVE_BOOZEHOUND and boozehound_exposure_has_started(age):
        years = boozehound_exposure_years(age)
        kg = boozehound_cumulative_ethanol_kg(age)
        eq = boozehound_beverage_equivalents(kg)
        metrics = boozehound_cumulative_survival_metrics(
            age, sex, start_age=start_age, birth_year=None, cohort_source=None,
            alcohol_cause_source=ctx.get("cause_source"),
        )
        rows.extend([
            ("EXPOSURE", f"{years:.1f} y @ {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g ethanol/day"),
            ("ETHANOL", f"≈{kg:,.0f} kg / ≈{eq['pure_ethanol_l']:,.0f} L pure ethanol"),
            ("🍷 WINE", f"≈{eq['wine_bottles']:,.0f} × {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL @ {BOOZEHOUND_WINO_ABV * 100:.0f}% ABV"),
            ("🥃 VODKA", f"≈{eq['vodka_bottles']:,.0f} × {BOOZEHOUND_EQ_VODKA_BOTTLE_ML:.0f} mL @ {BOOZEHOUND_EQ_VODKA_ABV * 100:.0f}% ABV"),
            ("SURVIVAL", f"{metrics['baseline_survival'] * 100:.2f}% baseline → {metrics['adjusted_survival'] * 100:.2f}% preset"),
        ])
    return rows


def _deathmatch_win_reason(win_mode: str) -> str:
    """Return the short human-readable reason shown beside the winner trophy."""
    if win_mode == "long":
        return "lived longer"
    if win_mode == "short":
        return "died sooner"
    raise ValueError(f"unknown deathmatch win mode: {win_mode!r}")


def _deathmatch_result_header_parts(
    label: str,
    *,
    width: int,
    winner: bool,
    win_mode: str,
) -> tuple[str, str]:
    """Return (country title, regular suffix) fitted to one result column."""
    if not winner:
        return _terminal_truncate(label, width), ""
    suffix = f" 🏆 ({_deathmatch_win_reason(win_mode)})"
    suffix_width = _terminal_display_width(suffix)
    if suffix_width >= width:
        return "", _terminal_truncate(suffix, width)
    base = _terminal_truncate(label, width - suffix_width)
    return base, suffix


def _deathmatch_result_header_label(
    label: str,
    *,
    width: int,
    winner: bool,
    win_mode: str,
) -> str:
    """Fit a contestant label into its result column, preserving winner status."""
    base, suffix = _deathmatch_result_header_parts(
        label, width=width, winner=winner, win_mode=win_mode
    )
    return f"{base}{suffix}"


def _deathmatch_result_header_render(
    label: str,
    *,
    width: int,
    winner: bool,
    win_mode: str,
) -> str:
    """Render a result header with only the country title in bold bright white."""
    base, suffix = _deathmatch_result_header_parts(
        label, width=width, winner=winner, win_mode=win_mode
    )
    plain = f"{base}{suffix}"
    padding = " " * max(0, width - _terminal_display_width(plain))
    styled_base = _terminal_emphasis(base, bold=True, bright_white=True) if base else ""
    return f"{styled_base}{suffix}{padding}"


def _deathmatch_result_cell_lines(
    key: str,
    value: str,
    *,
    column_width: int,
    label_width: int = 12,
) -> list[str]:
    """Format one final-result cell, preserving label indentation on wraps."""
    content_width = max(8, int(column_width) - int(label_width) - 3)
    wrapped = _terminal_wrap(str(value), content_width)
    first_prefix = f"{_terminal_pad(key, label_width)} : "
    continuation_prefix = " " * (label_width + 3)
    lines: list[str] = []
    for index, part in enumerate(wrapped):
        prefix = first_prefix if index == 0 else continuation_prefix
        lines.append(_terminal_pad(prefix + part, column_width))
    return lines



def _deathmatch_grid_rule(column_width: int, *, junction: str) -> str:
    """Build a two-column horizontal rule aligned with the Deathmatch divider."""
    if junction not in {"┬", "┼", "┴"}:
        raise ValueError(f"unsupported deathmatch-grid junction: {junction!r}")
    width = max(1, int(column_width))
    return f"{'─' * width}─{junction}─{'─' * width}"


def _deathmatch_result_grid_rule(column_width: int, *, junction: str) -> str:
    """Backward-compatible alias for the shared Deathmatch grid-rule helper."""
    return _deathmatch_grid_rule(column_width, junction=junction)

def _print_deathmatch_result_table(
    contexts: list[dict[str, object]],
    states: list[dict[str, object]],
    *,
    countries: list[str],
    provinces: list[str | None],
    player_numbers: list[int | None],
    sex: str,
    start_age: int,
    winner_idx: int | None,
    win_mode: str,
) -> None:
    """Print a compact two-column post-match comparison, sports-card style."""
    terminal_columns = max(80, shutil.get_terminal_size(fallback=(180, 24)).columns)
    column_width = max(36, min(100, (terminal_columns - 3) // 2))
    labels = [
        deathmatch_contestant_label(
            countries[i], sex, province=provinces[i], player_number=player_numbers[i]
        )
        for i in range(2)
    ]
    stats = [
        _deathmatch_compact_stats(contexts[i], states[i], sex=sex, start_age=start_age)
        for i in range(2)
    ]
    # Both cards intentionally use the same ordered row schema. If one side lacks
    # a conditional field (e.g. month), display an em dash rather than shifting rows.
    row_order: list[str] = []
    for card in stats:
        for key, _value in card:
            if key not in row_order:
                row_order.append(key)
    maps = [dict(card) for card in stats]

    header_labels = [
        _deathmatch_result_header_render(
            labels[i],
            width=column_width,
            winner=(winner_idx == i),
            win_mode=win_mode,
        )
        for i in range(2)
    ]
    print(_deathmatch_grid_rule(column_width, junction="┬"))
    print(f"{header_labels[0]} │ {header_labels[1]}")
    print(_deathmatch_grid_rule(column_width, junction="┼"))

    label_width = 12
    for key in row_order:
        left_lines = _deathmatch_result_cell_lines(
            key, maps[0].get(key, "—"), column_width=column_width, label_width=label_width
        )
        right_lines = _deathmatch_result_cell_lines(
            key, maps[1].get(key, "—"), column_width=column_width, label_width=label_width
        )
        line_count = max(len(left_lines), len(right_lines))
        blank_cell = " " * column_width
        for line_index in range(line_count):
            left_cell = left_lines[line_index] if line_index < len(left_lines) else blank_cell
            right_cell = right_lines[line_index] if line_index < len(right_lines) else blank_cell
            print(f"{left_cell} │ {right_cell}")

    # Close the final sports-card grid before the blank line and winner banner.
    print(_deathmatch_grid_rule(column_width, junction="┴"))


def _deathmatch_result(ages: list[int], win_mode: str) -> tuple[int | None, int]:
    """Return (winner index or None for draw, result age) for a completed match."""
    if len(ages) != 2:
        raise ValueError("deathmatch currently requires exactly two contestants")
    if ages[0] == ages[1]:
        return None, ages[0]
    if win_mode == "long":
        winner_idx = 0 if ages[0] > ages[1] else 1
    elif win_mode == "short":
        winner_idx = 0 if ages[0] < ages[1] else 1
    else:
        raise ValueError(f"unknown deathmatch win mode: {win_mode!r}")
    return winner_idx, ages[winner_idx]


def _canada_grouped_cause_distribution(
    *,
    source: "CanadaCauseOfDeathSource",
    sex: str,
    age: int,
    calendar_year: int | None,
) -> tuple[list[str], list[float], float] | None:
    """Compile one Canada WHO age/sex cell to broad chapter weights for batch use."""
    cell = source.counts_for(sex=sex, age=age, calendar_year=calendar_year)
    if not cell.get("available"):
        return None
    counts = dict(cell["counts"])
    chapter_weights: dict[str, float] = {}
    for raw_code, raw_count in counts.items():
        count = int(raw_count)
        if count <= 0:
            continue
        code = str(raw_code)
        chapter = _canada_icd_chapter(code)
        weight = float(count)
        if boozehound_active_for_age(age):
            if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
                mult, _target, _profile, _maturity, _basis = _boozehound_icd_hazard_effective_rr(
                    code, age=age, sex=sex, country="ca"
                )
            else:
                mult, _target, _profile, _maturity = boozehound_icd_effective_rr(
                    code, age=age, sex=sex
                )
            weight *= mult
        if weight > 0.0:
            chapter_weights[chapter] = chapter_weights.get(chapter, 0.0) + weight

    labels: list[str] = []
    cumulative: list[float] = []
    running = 0.0
    for chapter, weight in chapter_weights.items():
        if weight <= 0.0:
            continue
        running += weight
        labels.append(f"{chapter} {_CANADA_CHAPTER_LABEL.get(chapter, 'Other / unclassified ICD-10 causes')}")
        cumulative.append(running)
    if running <= 0.0 or not labels:
        return None
    return labels, cumulative, running


def _sample_deathmatch_broad_causes_grouped(
    *,
    grouped_results: Counter[tuple[str, int]],
    source: object,
    country: str,
    rng: random.Random,
) -> Counter[str]:
    """Bulk-sample broad causes for one Deathmatch side by sex/death-age cell."""
    totals: Counter[str] = Counter()
    for (sex, age), n in grouped_results.items():
        if isinstance(source, CauseOfDeathSource):
            dist = _statfin_grouped_cause_distribution(
                source=source, sex=sex, age=age, calendar_year=None
            )
            mapper = _statfin_broad_batch_key_from_label
        elif isinstance(source, CanadaCauseOfDeathSource):
            dist = _canada_grouped_cause_distribution(
                source=source, sex=sex, age=age, calendar_year=None
            )
            mapper = lambda label: label
        else:
            totals["CAUSE DATA UNAVAILABLE"] += n
            continue
        if dist is None:
            totals["CAUSE DATA UNAVAILABLE"] += n
            continue
        labels, cumulative, _total = dist
        draws = rng.choices(labels, cum_weights=cumulative, k=n)
        for label, count in Counter(draws).items():
            totals[mapper(label)] += count
    return totals


def _deathmatch_batch_percentile(sorted_ages: list[int], p: float) -> int:
    if not sorted_ages:
        raise ValueError("cannot compute percentile of empty Deathmatch batch")
    idx = min(len(sorted_ages) - 1, max(0, int(math.ceil(p * len(sorted_ages))) - 1))
    return sorted_ages[idx]


def _deathmatch_batch_percentile_counts(counts: Counter[int], p: float) -> int:
    """Nearest-rank percentile directly from a compact death-age frequency table."""
    total = sum(counts.values())
    if total <= 0:
        raise ValueError("cannot compute percentile of empty Deathmatch batch")
    rank = max(1, min(total, int(math.ceil(p * total))))
    cumulative = 0
    for value in sorted(counts):
        cumulative += counts[value]
        if cumulative >= rank:
            return int(value)
    return int(max(counts))


def _print_deathmatch_batch_causes(
    *,
    label: str,
    counts: Counter[str],
    runs: int,
    top_causes: int,
) -> None:
    print()
    print(f"{label} broad cause-of-death distribution")
    print("-" * _terminal_display_width(f"{label} broad cause-of-death distribution"))
    for rank, (cause, count) in enumerate(counts.most_common(top_causes), 1):
        print(f"{rank:2d}. {cause:<68} {count / runs * 100:7.3f}%  ({count:,})")


def run_deathmatch_batch(
    args: argparse.Namespace,
    *,
    selection: str,
    countries: list[str],
    provinces: list[str | None],
    player_numbers: list[int | None],
    contexts: list[dict[str, object]],
    match_seed: int,
    sex_rng: random.Random,
    mortality_rngs: list[random.Random],
) -> int:
    """Run many paired Deathmatches using exact precomputed age CDFs per side/sex."""
    runs = int(args.runs)
    if runs <= 0:
        print("--runs must be > 0", file=sys.stderr)
        return 2

    needed_sexes = ("male", "female") if selection == "r" else (("male",) if selection == "m" else ("female",))
    cdfs: list[dict[str, tuple[list[int], list[float]]]] = [{}, {}]
    for idx, ctx in enumerate(contexts):
        _activate_deathmatch_context(ctx)
        country = countries[idx]
        for sex in needed_sexes:
            cdfs[idx][sex] = build_death_age_cdf(
                sex,
                start_age=args.start_age,
                use_record_cap=(country != "ca" and not args.exceptional_tail),
                alcohol_cause_source=ctx.get("cause_source"),
            )

    age_counts_by_side: list[Counter[int]] = [Counter(), Counter()]
    cause_cells_by_side: list[Counter[tuple[str, int]]] = [Counter(), Counter()]
    wins = [0, 0]
    draws = 0
    sex_counts: Counter[str] = Counter()
    margin_counts: Counter[int] = Counter()
    left_10 = 0
    right_10 = 0
    within_2 = 0

    spinner = "-\\|/"
    spinner_index = 0
    last_update = 0.0
    started = time.monotonic()
    if not args.no_progress:
        print()
        print("Running batch Deathmatch simulations...", flush=True)

    for i in range(runs):
        sex = choose_sex(selection, sex_rng)
        sex_counts[sex] += 1
        pair: list[int] = []
        for idx in (0, 1):
            cdf_ages, cdf_values = cdfs[idx][sex]
            age = sample_death_age_cdf(mortality_rngs[idx], cdf_ages, cdf_values)
            age_counts_by_side[idx][age] += 1
            cause_cells_by_side[idx][(sex, age)] += 1
            pair.append(age)
        winner_idx, _result_age = _deathmatch_result(pair, args.deathmatch_win)
        if winner_idx is None:
            draws += 1
        else:
            wins[winner_idx] += 1
        diff = pair[0] - pair[1]
        margin_counts[abs(diff)] += 1
        if diff >= 10:
            left_10 += 1
        if diff <= -10:
            right_10 += 1
        if abs(diff) <= 2:
            within_2 += 1

        if not args.no_progress:
            now = time.monotonic()
            if now - last_update >= 0.08 or i + 1 == runs:
                done = i + 1
                elapsed = max(now - started, 1e-9)
                ch = spinner[spinner_index % len(spinner)]
                spinner_index += 1
                print(
                    f"\r{ch}  {done:,}/{runs:,} ({done / runs * 100:6.2f}%)  {done / elapsed:,.0f} matches/s",
                    end="", flush=True,
                )
                last_update = now

    if not args.no_progress:
        elapsed = time.monotonic() - started
        print(f"\r✓  {runs:,}/{runs:,} (100.00%)  completed in {elapsed:.2f}s" + " " * 20)

    cause_counts: list[Counter[str]] = [Counter(), Counter()]
    for idx, ctx in enumerate(contexts):
        source = ctx.get("cause_source")
        if source is None:
            continue
        _activate_deathmatch_context(ctx)
        cause_rng = ctx.get("cause_rng")
        if not isinstance(cause_rng, random.Random):
            raise CauseDataError("internal error: Deathmatch cause source has no RNG")
        cause_counts[idx] = _sample_deathmatch_broad_causes_grouped(
            grouped_results=cause_cells_by_side[idx], source=source, country=countries[idx], rng=cause_rng
        )

    labels = [
        deathmatch_contestant_label(countries[i], "male" if selection == "m" else "female" if selection == "f" else None,
                                    province=provinces[i], player_number=player_numbers[i])
        for i in (0, 1)
    ]
    # For random-sex batches, contestant labels should not imply one fixed sex.
    if selection == "r":
        labels = [country_display_label(countries[i], province=provinces[i]).upper() for i in (0, 1)]

    print()
    print(_terminal_rule())
    print(f"=== MORTALITY ROULETTE v{VERSION} — BATCH DEATHMATCH ===")
    print(_terminal_rule())
    print(f"{labels[0]}  ⚔  {labels[1]}")
    print(f"matches: {runs:,}")
    print(f"starting age: {args.start_age}")
    if selection == "r":
        print(f"sex: random but shared within each match | male {sex_counts['male'] / runs * 100:.2f}% | female {sex_counts['female'] / runs * 100:.2f}%")
    else:
        print(f"sex: {'male' if selection == 'm' else 'female'}")
    print(
        "win condition: LONGEVITY (long) — later death wins"
        if args.deathmatch_win == "long"
        else "win condition: BREVITY (short) — earlier death wins"
    )
    print(f"deathmatch RNG seed: {match_seed} (independent deterministic mortality streams per side)")
    if ACTIVE_MORTALITY_MODEL == "legacy" and any(country == "ca" for country in countries):
        print("mortality models: Finland original legacy Mortality Roulette | Canada official raw period table")
    else:
        print(f"shared mortality model: {mortality_model_display_name()}")
    if ACTIVE_BOOZEHOUND:
        print(f"lifestyle modifier: {boozehound_preset_icon()} {boozehound_preset_label()} | {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g ethanol/day")
        print(f"alcohol risk engine: {alcohol_model_label()}")
        if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
            print(f"cause-hazard weight model: {cause_hazard_weight_model_label()}")
            if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {"evidence-v3-popdist", "evidence-v4-cancer"}:
                if selection in {"m", "f"}:
                    batch_sex = "male" if selection == "m" else "female"
                    for idx, country in enumerate(countries):
                        side = country_display_label(country, province=provinces[idx])
                        for line in alcohol_population_distribution_summary(country, batch_sex):
                            print(f"{side} {line}")
                else:
                    print("population exposure model: WHO-style Gamma E[RR], resolved separately for each match sex")
                if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
                    print("evidence-v4 coverage: v3 direct-alcohol normalization + Dai 2026 cancer subhazards; remaining non-cancer mappings use proxy-v1")
                else:
                    print("population-normalization warning: distribution-based normalization currently replaces only the direct-alcohol bucket; remaining alcohol-sensitive causes still use proxy-v1 mappings")
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
                print("population-normalization warning: first-order mean-dose anchor only; not full exposure-distribution deconvolution")
    else:
        print("lifestyle modifier: none (population period-table baseline)")
    print("mortality sampling: exact inverse-CDF of the same annual hazard process used by single Deathmatch")
    print("cause sampling: grouped broad age/sex cells after mortality; independent cause RNG streams")

    print()
    print("match outcomes")
    print("--------------")
    print(f"{labels[0]} wins: {wins[0] / runs * 100:7.3f}%  ({wins[0]:,})")
    print(f"{labels[1]} wins: {wins[1] / runs * 100:7.3f}%  ({wins[1]:,})")
    print(f"draws: {draws / runs * 100:7.3f}%  ({draws:,})")

    print()
    print("death-age summary")
    print("-----------------")
    for idx in (0, 1):
        counts = age_counts_by_side[idx]
        mean_age = sum(age * count for age, count in counts.items()) / runs
        print(
            f"{labels[idx]}: mean {mean_age:.2f} | median {_deathmatch_batch_percentile_counts(counts, 0.50)} | "
            f"p10 {_deathmatch_batch_percentile_counts(counts, 0.10)} | p90 {_deathmatch_batch_percentile_counts(counts, 0.90)} | "
            f"min {min(counts)} | max {max(counts)}"
        )
    mean_margin = sum(gap * count for gap, count in margin_counts.items()) / runs
    print(
        f"absolute death-age gap: mean {mean_margin:.2f} y | "
        f"median {_deathmatch_batch_percentile_counts(margin_counts, 0.50)} y | "
        f"p90 {_deathmatch_batch_percentile_counts(margin_counts, 0.90)} y"
    )

    print()
    print("paired death-age difference")
    print("---------------------------")
    print(f"{labels[0]} dies ≥10 y later: {left_10 / runs * 100:7.3f}%  ({left_10:,})")
    print(f"within ±2 years:            {within_2 / runs * 100:7.3f}%  ({within_2:,})")
    print(f"{labels[1]} dies ≥10 y later: {right_10 / runs * 100:7.3f}%  ({right_10:,})")

    checkpoints = (60, 70, 80, 85, 90, 95)
    print()
    print("survival checkpoints")
    print("--------------------")
    for target in checkpoints:
        left = sum(count for age, count in age_counts_by_side[0].items() if age >= target)
        right = sum(count for age, count in age_counts_by_side[1].items() if age >= target)
        print(f"reach {target:3d}: {labels[0]} {left / runs * 100:7.3f}% | {labels[1]} {right / runs * 100:7.3f}%")

    if cause_counts[0] and cause_counts[1] and countries[0] != countries[1]:
        print()
        print("cause-taxonomy warning: country cause groupings are source-specific; cross-country broad-cause percentages")
        print("are descriptive and are not necessarily category-equivalent (e.g. StatFin custom groups vs WHO ICD chapters)")

    for idx in (0, 1):
        if cause_counts[idx]:
            _print_deathmatch_batch_causes(
                label=labels[idx], counts=cause_counts[idx], runs=runs, top_causes=args.top_causes
            )

    _activate_deathmatch_context(contexts[0])
    return 0


def run_deathmatch(args: argparse.Namespace, selection: str) -> int:
    """Run two countries side-by-side with independently rolled mortality."""
    global DATA_PREFLIGHT_COMPLETE, ACTIVE_COUNTRY, ACTIVE_PERIOD_SOURCE

    countries = list(args.deathmatch or [])
    if len(countries) != 2:
        print("internal deathmatch error: expected exactly two normalized contestants", file=sys.stderr)
        return 2
    provinces = list(getattr(args, "deathmatch_provinces", [None, None]))
    if len(provinces) != 2:
        provinces = [None, None]
    same_country = countries[0] == countries[1]
    player_numbers: list[int | None] = [1, 2] if same_country else [None, None]
    if args.log:
        print("--log is not supported with --deathmatch yet", file=sys.stderr)
        return 2
    if args.birth_year is not None:
        print("--birth-year is not supported with --deathmatch yet; use present-day period tables", file=sys.stderr)
        return 2

    batch_mode = args.runs is not None
    if batch_mode and int(args.runs) <= 0:
        print("--runs must be > 0", file=sys.stderr)
        return 2
    # Single Deathmatch is the showcase mode. Batch Deathmatch keeps broad causes
    # but skips tree/detail/seasonality work that cannot affect paired mortality.
    args.causes = True
    args.seasonality = not batch_mode
    cause_detail_mode = "broad" if batch_mode else ("tree" if args.cause_detail == "auto" else args.cause_detail)

    # Share only the contestant sex. Mortality rolls themselves MUST be
    # independent: each player gets a deterministic contestant-specific RNG
    # stream derived from the match seed. This remains true even when both
    # players use the same country's mortality table.
    match_seed = args.seed
    if match_seed is None:
        match_seed = random.SystemRandom().randrange(0, 2**63)
    sex_rng = random.Random(match_seed ^ 0x534558)
    sex = None if batch_mode else choose_sex(selection, sex_rng)
    mortality_rngs = [
        _deathmatch_rng(
            match_seed,
            country,
            0x4D4F5254,
            contestant_index=idx,
        )
        for idx, country in enumerate(countries)
    ]

    if args.causes and USE_ICD_TITLES:
        try:
            data_status("deathmatch: loading shared WHO ICD-10 terminology...", level=1)
            preflight_icd_titles()
        except (CauseDataError, OSError, json.JSONDecodeError) as exc:
            print(f"ICD-title warning: {exc}", file=sys.stderr)

    # Cause/detail/timing streams are also contestant-specific and independent.
    original_seed = args.seed
    args.seed = match_seed
    contexts: list[dict[str, object]] = []
    try:
        for idx, country in enumerate(countries):
            ctx = _preflight_deathmatch_country(
                args,
                country,
                province=provinces[idx],
                cause_detail_mode=cause_detail_mode,
                contestant_index=idx,
            )
            ctx["player_number"] = player_numbers[idx]
            contexts.append(ctx)
    except (CohortDataError, CauseDataError, OSError, urllib.error.URLError, zipfile.BadZipFile, json.JSONDecodeError, csv.Error) as exc:
        print(f"deathmatch data error: {exc}", file=sys.stderr)
        args.seed = original_seed
        return 2
    args.seed = original_seed

    data_status("deathmatch data preflight complete; starting mortality roulette", level=1)
    DATA_PREFLIGHT_COMPLETE = True

    if batch_mode:
        return run_deathmatch_batch(
            args,
            selection=selection,
            countries=countries,
            provinces=provinces,
            player_numbers=player_numbers,
            contexts=contexts,
            match_seed=match_seed,
            sex_rng=sex_rng,
            mortality_rngs=mortality_rngs,
        )

    assert sex is not None
    print()
    print(_terminal_rule())
    print(f"=== MORTALITY ROULETTE v{VERSION} — DEATHMATCH ===")
    print(_terminal_rule())
    print(
        f"{deathmatch_contestant_label(countries[0], sex, province=provinces[0], player_number=player_numbers[0])}"
        f"  ⚔  "
        f"{deathmatch_contestant_label(countries[1], sex, province=provinces[1], player_number=player_numbers[1])}"
    )
    if same_country:
        print(
            f"country: {country_display_label(countries[0])} "
            "(same-country match; independent players)"
        )
    else:
        print(
            f"countries: {country_display_label(countries[0], province=provinces[0])} vs "
            f"{country_display_label(countries[1], province=provinces[1])}"
        )
    print(f"sex: {sex}")
    if selection == "r":
        print(f"random sex selection shared by both contestants: {sex}")
    if args.deathmatch_win == "long":
        print("deathmatch win condition: LONGEVITY (long) — last contestant standing wins; same-age tap-outs = draw")
    else:
        print("deathmatch win condition: BREVITY (short) — first contestant to tap out wins; same-age tap-outs = draw")
    print(f"deathmatch RNG seed: {match_seed} (independent annual mortality rolls per player)")
    if ACTIVE_MORTALITY_MODEL == "legacy" and any(country == "ca" for country in countries):
        print("mortality models: Finland original legacy Mortality Roulette | Canada official raw period table")
    else:
        print(f"shared mortality model: {mortality_model_display_name()}")
    if ACTIVE_BOOZEHOUND:
        icon = boozehound_preset_icon()
        label = boozehound_preset_label()
        print(f"shared lifestyle modifier: {icon} {label}")
        if ACTIVE_BOOZEHOUND_PRESET == "wino":
            print(
                f"shared alcohol exposure: one {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottle/day of "
                f"{BOOZEHOUND_WINO_ABV * 100:.0f}% ABV wine ≈ {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g/day"
            )
        else:
            print(f"shared alcohol exposure: {ACTIVE_BOOZEHOUND_GRAMS_PER_DAY:.1f} g pure ethanol/day")
        for line in boozehound_schedule_lines():
            print(line)
        print(f"shared alcohol risk engine: {alcohol_model_label()}")
        if ACTIVE_ALCOHOL_MODEL == "legacy":
            print(
                f"sex-specific all-cause RR target at this dose: ×{boozehound_all_cause_target_rr(sex):.2f}"
            )
        else:
            print(f"shared cause-hazard weight model: {cause_hazard_weight_model_label()}")
            for idx, country in enumerate(countries):
                side = country_display_label(country, province=provinces[idx])
                if country == "fi":
                    print(f"{side} hazard input: Statistics Finland 11az broad causes by sex + age")
                else:
                    print(f"{side} hazard input: WHO Canada complete-ICD causes by sex + age (national cause geography)")
                if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL in {"evidence-v3-popdist", "evidence-v4-cancer"}:
                    for line in alcohol_population_distribution_summary(country, sex):
                        print(f"{side} {line}")
                elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
                    anchor_g, source = alcohol_population_anchor(country, sex)
                    print(
                        f"{side} population-normalization anchor: {anchor_g:.1f} g/day mean-dose equivalent | {source}"
                    )
            if ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer":
                print(
                    "evidence-v4 coverage: WHO-style population normalization applies to direct-alcohol and Dai 2026 cancer RRs; "
                    "other alcohol-sensitive causes still use proxy-v1 mappings"
                )
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v3-popdist":
                print(
                    "population-normalization warning: WHO-style Gamma E[RR] currently replaces only the direct-alcohol bucket; "
                    "other alcohol-sensitive causes still use proxy-v1 mappings"
                )
            elif ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v2-popnorm":
                print(
                    "population-normalization warning: first-order mean-dose anchor only; "
                    "not full exposure-distribution deconvolution"
                )
            print(
                "latency note: acute external-cause proxies apply immediately during active exposure; "
                "chronic disease profiles ramp with duration"
            )
    else:
        print("shared lifestyle modifier: none (population period-table baseline)")
    print("result detail defaults: causes + tree detail + seasonality")
    print()

    left_label = deathmatch_contestant_label(
        countries[0], sex, province=provinces[0], player_number=player_numbers[0]
    )
    right_label = deathmatch_contestant_label(
        countries[1], sex, province=provinces[1], player_number=player_numbers[1]
    )
    terminal_columns = shutil.get_terminal_size(fallback=(180, 24)).columns
    # 72 cells/side is enough for the compact annual row. Wider terminals get
    # more breathing room; very narrow terminals may wrap naturally rather than
    # requiring a curses/full-screen dependency.
    column_width = max(72, min(100, (terminal_columns - 3) // 2))
    print(_deathmatch_grid_rule(column_width, junction="┬"))
    print(f"{_terminal_pad(left_label, column_width)} │ {right_label}")
    print(_deathmatch_grid_rule(column_width, junction="┼"))

    states = [{"dead": False}, {"dead": False}]
    age = args.start_age

    while not all(bool(st.get("dead")) for st in states):
        cells: list[str] = []
        newly_dead: list[int] = []
        for idx, (ctx, state) in enumerate(zip(contexts, states)):
            mortality_roll = mortality_rngs[idx].random()
            was_dead = bool(state.get("dead"))
            cell = _deathmatch_cell(
                ctx,
                state,
                age=age,
                sex=sex,
                exceptional_tail=args.exceptional_tail,
                mortality_roll=mortality_roll,
            )
            cells.append(cell)
            if not was_dead and state.get("dead"):
                newly_dead.append(idx)

        age_prefix = f"age {age:3d}->{age + 1:3d} | "
        left = age_prefix + cells[0]
        right = age_prefix + cells[1]
        print(f"{_terminal_pad(left, column_width)} │ {right}", flush=True)

        # Live arena announcement stays in the contestant's own column.
        # Fatal rolls are neutral tap-outs; the one trophy is awarded only
        # after the configured long/short win condition is evaluated.
        if newly_dead:
            print(
                _deathmatch_live_tapout_row(
                    newly_dead,
                    countries=countries,
                    provinces=provinces,
                    player_numbers=player_numbers,
                    states=states,
                    sex=sex,
                    column_width=column_width,
                    blink=True,
                ),
                flush=True,
            )

        for idx in newly_dead:
            states[idx]["cause_stack"] = _deathmatch_roll_cause_stack(
                contexts[idx],
                sex=sex,
                age=int(states[idx]["death_age"]),
                cause_detail_mode=cause_detail_mode,
            )

        age += 1
        if args.delay > 0 and not all(bool(st.get("dead")) for st in states):
            time.sleep(args.delay)

    # Both eventual death cards are printed regardless of win mode. This
    # preserves the full underlying mechanics and gives both players complete
    # comparable outcomes.
    for ctx, state in zip(contexts, states):
        _print_deathmatch_final_card(
            ctx,
            state,
            sex=sex,
            start_age=args.start_age,
            cause_detail_mode=cause_detail_mode,
        )

    ages = [int(st["death_age"]) for st in states]
    winner_idx, result_age = _deathmatch_result(ages, args.deathmatch_win)
    print()
    result_heading = "DEATHMATCH RESULT"
    print(result_heading)
    print("=" * _terminal_display_width(result_heading))
    _print_deathmatch_result_table(
        contexts, states, countries=countries, provinces=provinces,
        player_numbers=player_numbers, sex=sex, start_age=args.start_age,
        winner_idx=winner_idx, win_mode=args.deathmatch_win,
    )

    print()
    if winner_idx is None:
        result_banner = f"*** 🤝 DEATHMATCH DRAW AT AGE {result_age} ***"
    else:
        winner_country = countries[winner_idx]
        winner_label = deathmatch_contestant_label(
            winner_country,
            sex,
            province=provinces[winner_idx],
            player_number=player_numbers[winner_idx],
        )
        if args.deathmatch_win == "long":
            result_banner = (
                f"*** {winner_label} WINS DEATHMATCH — OUTLIVED OPPONENT; "
                f"TAPPED OUT AT AGE {result_age} ***"
            )
        else:
            result_banner = (
                f"*** {winner_label} WINS DEATHMATCH — TAPPED OUT FIRST "
                f"AT AGE {result_age} ***"
            )
    print(_terminal_emphasis(result_banner, bold=True))

    _activate_deathmatch_context(contexts[0])
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Roll annual mortality probabilities year by year.",
        epilog=(
            "⚠ Educational/entertainment statistical simulation provided AS IS. "
            "Population-level output is not medical advice, diagnosis, prognosis, "
            "treatment guidance, or a basis for healthcare decisions."
        ),
    )
    p.add_argument(
        "-v", "--version",
        action="version",
        version=f"Mortality Roulette v{VERSION}",
        help="show program version and exit",
    )
    country = p.add_mutually_exclusive_group()
    country.add_argument(
        "--country", choices=("fi", "ca"),
        help="country data mode: fi=Finland (default), ca=Canada",
    )
    country.add_argument(
        "--canada", action="store_true",
        help="shorthand for --country ca",
    )
    country.add_argument(
        "--deathmatch", nargs="+", metavar="COUNTRY", choices=("fi", "ca"),
        help=(
            "deathmatch mode with one or two country codes, e.g. --deathmatch fi ca or --deathmatch fi; "
            "one code creates two independent players from that country; the mode defaults to full cause/timing detail and no alcohol exposure"
        ),
    )
    p.add_argument(
        "--ca-province",
        nargs="+",
        metavar="PROVINCE",
        help=(
            "Canadian province selector for --country ca / --canada / --deathmatch; "
            "use postal codes such as bc, on, ab, qc (or quoted full names). In Canada-vs-Canada deathmatch, "
            "one value applies to both players and two values map left-to-right. Use 'national' for Canada-wide data."
        ),
    )
    p.add_argument(
        "--deathmatch-win",
        choices=("long", "short"),
        default="long",
        help=(
            "deathmatch win condition: long=longevity/last contestant standing (default); "
            "short=brevity/first contestant to tap out"
        ),
    )
    p.add_argument(
        "--sex", "--gender",
        dest="sex",
        choices=("m", "f", "r"),
        help="m=male, f=female, r=random; --gender is an alias for --sex; if omitted, ask interactively",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="seconds between years (default: 0.15; use 0 for instant)",
    )
    p.add_argument(
        "--seed",
        type=int,
        help="PRNG seed for reproducible runs",
    )
    p.add_argument(
        "--log",
        type=Path,
        help="write every roll to CSV",
    )
    p.add_argument(
        "--start-age",
        type=int,
        default=0,
        help="starting age (default: 0)",
    )
    p.add_argument(
        "--printout", "--odds-table",
        action="store_true",
        help=(
            "deterministic mortality-odds table: print each age interval's death probability "
            "and 1-in-X odds without RNG rolls or simulated death; --odds-table is an alias"
        ),
    )
    p.add_argument(
        "--end-age",
        type=int,
        help=(
            "last age interval to print with --printout (inclusive); Finland defaults to the "
            "last annual odds interval used before its observed-record ceiling (tail rows labelled), "
            "while Canada defaults to the last official exact-age qx"
        ),
    )
    p.add_argument(
        "--birth-year",
        type=int,
        help=(
            "simulate a birth cohort using calendar-year mortality at each age; "
            "omit for the original present-day synthetic mode"
        ),
    )
    p.add_argument(
        "--hmd-dir",
        type=Path,
        help=(
            "directory containing HMD Finland mltper_1x1.txt / fltper_1x1.txt; "
            "needed for cohort years before 1986"
        ),
    )
    p.add_argument(
        "--statfin-cache",
        type=Path,
        default=None,
        help=("explicit Statistics Finland qx cache path; if omitted, bundled official data are used "
              f"(network/cache refresh target: {DEFAULT_STATFIN_CACHE})"),
    )
    p.add_argument(
        "--refresh-statfin",
        action="store_true",
        help="redownload the Statistics Finland 12ap qx cache",
    )
    p.add_argument(
        "--statcan-cache", type=Path, default=None,
        help=("explicit Statistics Canada 13-10-0837 qx cache; if omitted, bundled Canada/BC data "
              f"are preferred (network/cache refresh target: {DEFAULT_STATCAN_CACHE})"),
    )
    p.add_argument(
        "--refresh-statcan", action="store_true",
        help="redownload/reparse the Statistics Canada complete life table",
    )
    mortality_model_group = p.add_mutually_exclusive_group()
    mortality_model_group.add_argument(
        "--mortality-model",
        choices=MORTALITY_MODELS,
        default=None,
        help=(
            "present-day mortality model: smoothed=age-graduated official qx (recommended simulation baseline); "
            "official=literal published single-age qx; legacy=original Mortality Roulette baked schedule (Finland only)"
        ),
    )
    mortality_model_group.add_argument(
        "--legacy-mortality",
        action="store_true",
        help=(
            "backward-compatible alias for --mortality-model legacy; Finland's original baked mortality schedule, "
            "retained for historical comparison and reproducibility"
        ),
    )
    causes_group = p.add_mutually_exclusive_group()
    causes_group.add_argument(
        "--causes",
        dest="causes",
        action="store_true",
        default=None,
        help=(
            "roll underlying cause after death (default: ON for normal single-run roulette; "
            "OFF for batch/printout unless explicitly requested)"
        ),
    )
    causes_group.add_argument(
        "--no-causes",
        dest="causes",
        action="store_false",
        help="disable cause-of-death roulette in single-run mode",
    )
    p.add_argument(
        "--cause-cache",
        type=Path,
        default=None,
        help=("explicit Statistics Finland cause cache; bundled 11az snapshot is the default "
              f"(network/cache refresh target: {DEFAULT_CAUSE_CACHE})"),
    )
    p.add_argument(
        "--refresh-causes",
        action="store_true",
        help="redownload the Statistics Finland 11az cause-of-death cache",
    )
    p.add_argument(
        "--top-causes",
        type=int,
        default=16,
        help="number of cause groups to show in batch mode (default: 16)",
    )
    p.add_argument(
        "--cause-detail",
        choices=("auto", "broad", "specific", "tree"),
        default="auto",
        help=(
            "cause drill-down: auto=tree for single runs, broad for batches; "
            "specific/tree use the active country's detailed cause backend"
        ),
    )
    p.add_argument(
        "--detail-cache",
        type=Path,
        default=None,
        help=("explicit Statistics Finland detailed-cause cache; bundled snapshot is the default "
              f"(network/cache refresh target: {DEFAULT_DETAIL_CACHE})"),
    )
    p.add_argument(
        "--refresh-detail",
        action="store_true",
        help="ignore cached detailed-cause distributions and refresh them on demand",
    )
    p.add_argument(
        "--no-who-detail",
        action="store_true",
        help=(
            "Finland mode: disable automatic WHO complete-ICD refinement below "
            "StatFin's 3-character cause detail; Canada already uses WHO complete ICD codes"
        ),
    )
    p.add_argument(
        "--who-detail-cache-dir",
        type=Path,
        default=DEFAULT_WHO_DETAIL_CACHE_DIR,
        help=(
            "WHO Mortality Database raw/detail cache directory "
            f"(default: {DEFAULT_WHO_DETAIL_CACHE_DIR})"
        ),
    )
    p.add_argument(
        "--refresh-who-detail",
        action="store_true",
        help="redownload/reparse WHO raw ICD mortality detail when needed",
    )
    seasonality_group = p.add_mutually_exclusive_group()
    seasonality_group.add_argument(
        "--seasonality",
        "--death-month",
        dest="seasonality",
        action="store_true",
        default=None,
        help=(
            "roll a death month after death/cause selection (default: ON for normal single-run "
            "roulette; OFF for batch/printout unless explicitly requested)"
        ),
    )
    seasonality_group.add_argument(
        "--no-seasonality",
        dest="seasonality",
        action="store_false",
        help="disable seasonal/month-of-death timing in single-run mode",
    )
    p.add_argument(
        "--seasonal-cache",
        type=Path,
        default=None,
        help=(
            "explicit Statistics Finland 11bf seasonal cache; bundled snapshot is the default "
            f"(network/cache refresh target: {DEFAULT_SEASONAL_CACHE})"
        ),
    )
    p.add_argument(
        "--refresh-seasonality",
        action="store_true",
        help="redownload the Statistics Finland 11bf monthly cause-of-death cache",
    )
    p.add_argument(
        "--statcan-seasonal-cache", type=Path, default=None,
        help=("explicit Statistics Canada monthly-deaths cache; bundled Canada/BC snapshot is the default "
              f"(network/cache refresh target: {DEFAULT_STATCAN_MONTHLY_CACHE})"),
    )
    p.add_argument(
        "--batch-engine",
        choices=("fast", "step"),
        default="fast",
        help="batch mortality engine: fast=CDF sampler (default), step=literal annual rolls",
    )
    p.add_argument(
        "--cause-batch-sampler",
        choices=CAUSE_BATCH_SAMPLERS,
        default=DEFAULT_CAUSE_BATCH_SAMPLER,
        help=(
            "batch broad-cause assignment engine: "
            f"{DEFAULT_CAUSE_BATCH_SAMPLER}=group deaths by resolved age/sex cause cell and sample cached weights (default); "
            "reference-slow=original one-death-at-a-time cause rolls for A/B validation"
        ),
    )
    booze_group = p.add_mutually_exclusive_group()
    booze_group.add_argument(
        "--boozehound",
        action="store_true",
        help=(
            f"heavy-drinking scenario: {BOOZEHOUND_GRAMS_PER_DAY:g} g pure ethanol/day; "
            f"default start age {BOOZEHOUND_START_AGE}; hazard-scale mortality RR plus duration/dose-aware cause weighting"
        ),
    )
    booze_group.add_argument(
        "--boozehound-wino",
        action="store_true",
        help=(
            f"wine-heavy scenario: one {BOOZEHOUND_WINO_BOTTLE_ML:.0f} mL bottle/day at "
            f"{BOOZEHOUND_WINO_ABV * 100:.0f}%% ABV ≈ {BOOZEHOUND_WINO_GRAMS_PER_DAY:.1f} g ethanol/day; default start age {BOOZEHOUND_START_AGE}"
        ),
    )
    p.add_argument(
        "--alcohol-model",
        choices=ALCOHOL_MODELS,
        default=DEFAULT_ALCOHOL_MODEL,
        help=(
            "alcohol mortality engine for boozehound modes: "
            f"{DEFAULT_ALCOHOL_MODEL}=legacy behavior (default); "
            "cause-hazard-prototype=experimental country-specific cause-hazard reconstruction (Finland StatFin; Canada WHO ICD)"
        ),
    )
    p.add_argument(
        "--cause-hazard-weight-model",
        choices=CAUSE_HAZARD_WEIGHT_MODELS,
        default=DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL,
        help=(
            "broad cause-hazard weights for --alcohol-model cause-hazard-prototype: "
            f"{DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL}=original prototype proxies (default); "
            "evidence-v1=raw Carr 2024 direct-alcohol mortality plus proxy fallback; "
            "evidence-v2-popnorm=Carr direct-alcohol hazard normalized to a provisional country population APC anchor; "
            "evidence-v3-popdist=Carr direct-alcohol hazard normalized by WHO-style sex-specific Gamma population E[RR]; "
            "evidence-v4-cancer=v3 direct-alcohol normalization plus Dai et al. Nature Health 2026 cancer subhazards"
        ),
    )
    p.add_argument(
        "--alcohol-start-age",
        type=int,
        default=BOOZEHOUND_START_AGE,
        metavar="AGE",
        help=f"age when boozehound alcohol exposure begins (default: {BOOZEHOUND_START_AGE})",
    )
    p.add_argument(
        "--alcohol-end-age",
        type=int,
        metavar="AGE",
        help="optional age when boozehound alcohol exposure stops; stop age itself is alcohol-free",
    )
    p.add_argument(
        "--runs",
        type=int,
        help="batch mode: simulate N lives, or N paired matches with --deathmatch, and print aggregate statistics",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="disable the animated batch progress spinner",
    )
    p.add_argument(
        "--no-histogram",
        action="store_true",
        help="batch mode: suppress the default death-age distribution histogram",
    )
    p.add_argument(
        "--exceptional-tail",
        action="store_true",
        help=(
            "Finland only: allow hypothetical model-only survival beyond the verified "
            "Finnish longevity record; Canada has no hard record cap in this model"
        ),
    )
    return p.parse_args()


def main() -> int:
    global ACTIVE_COUNTRY, ACTIVE_PERIOD_SOURCE, ACTIVE_CANADA_PROVINCE, ACTIVE_LEGACY_MORTALITY, ACTIVE_MORTALITY_MODEL, DATA_PREFLIGHT_COMPLETE
    global ACTIVE_BOOZEHOUND, ACTIVE_BOOZEHOUND_PRESET, ACTIVE_BOOZEHOUND_GRAMS_PER_DAY
    global ACTIVE_BOOZEHOUND_START_AGE, ACTIVE_BOOZEHOUND_END_AGE, ACTIVE_ALCOHOL_MODEL
    global ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL
    DATA_PREFLIGHT_COMPLETE = False
    args = parse_args()
    _print_startup_banner()

    # --deathmatch accepts either one country (same-country two-player shorthand)
    # or two countries.  Normalize to exactly two contestants before any backend
    # initialization so the rest of the engine has one simple invariant.
    deathmatch_single_country = False
    if args.deathmatch:
        raw_deathmatch = list(args.deathmatch)
        if len(raw_deathmatch) == 1:
            deathmatch_single_country = True
            args.deathmatch = [raw_deathmatch[0], raw_deathmatch[0]]
        elif len(raw_deathmatch) == 2:
            args.deathmatch = raw_deathmatch
        else:
            print("--deathmatch accepts one or two country codes", file=sys.stderr)
            return 2

    ACTIVE_COUNTRY = (args.deathmatch[0] if args.deathmatch else ("ca" if args.canada else (args.country or "fi")))
    ACTIVE_MORTALITY_MODEL = DEFAULT_MORTALITY_MODEL
    ACTIVE_LEGACY_MORTALITY = False

    # Resolve Canadian province selection after --deathmatch shorthand has been
    # normalized to exactly two contestants.  Store a parallel province list so
    # Canada-vs-Canada can use different provincial mortality/seasonality data.
    try:
        if args.deathmatch:
            _single_province, deathmatch_provinces = resolve_canada_province_assignments(
                list(args.deathmatch), args.ca_province
            )
            args.deathmatch_provinces = deathmatch_provinces
            ACTIVE_CANADA_PROVINCE = (
                deathmatch_provinces[0] if ACTIVE_COUNTRY == "ca" else None
            )
            args.ca_province_active = None
        else:
            if args.ca_province and ACTIVE_COUNTRY != "ca":
                raise ValueError("--ca-province requires --country ca / --canada or a Canadian deathmatch contestant")
            single_province, _unused = resolve_canada_province_assignments(None, args.ca_province)
            args.ca_province_active = single_province if ACTIVE_COUNTRY == "ca" else None
            args.deathmatch_provinces = []
            ACTIVE_CANADA_PROVINCE = args.ca_province_active
    except ValueError as exc:
        print(f"argument error: {exc}", file=sys.stderr)
        return 2

    selection = args.sex
    if selection is None:
        while True:
            selection = input("Choose sex: (m)ale, (f)emale, (r)andom: ").strip().lower()
            if selection in {"m", "f", "r"}:
                break
            print("Please enter m, f, or r.")

    ACTIVE_MORTALITY_MODEL = resolve_requested_mortality_model(args)
    ACTIVE_LEGACY_MORTALITY = ACTIVE_MORTALITY_MODEL == "legacy"

    if args.birth_year is not None and ACTIVE_MORTALITY_MODEL != "official":
        print(
            "argument error: --birth-year uses literal calendar-year mortality and supports only --mortality-model official",
            file=sys.stderr,
        )
        return 2

    selected_countries = list(args.deathmatch or [ACTIVE_COUNTRY])
    if ACTIVE_MORTALITY_MODEL == "legacy" and "fi" not in selected_countries:
        print(
            "argument error: original legacy Mortality Roulette mortality applies only to Finland",
            file=sys.stderr,
        )
        return 2

    if args.alcohol_start_age < 0:
        print("argument error: --alcohol-start-age must be >= 0", file=sys.stderr)
        return 2
    if args.alcohol_end_age is not None and args.alcohol_end_age < 0:
        print("argument error: --alcohol-end-age must be >= 0", file=sys.stderr)
        return 2
    if args.alcohol_end_age is not None and args.alcohol_end_age <= args.alcohol_start_age:
        print("argument error: --alcohol-end-age must be greater than --alcohol-start-age", file=sys.stderr)
        return 2

    ACTIVE_BOOZEHOUND_START_AGE = int(args.alcohol_start_age)
    ACTIVE_BOOZEHOUND_END_AGE = int(args.alcohol_end_age) if args.alcohol_end_age is not None else None
    ACTIVE_ALCOHOL_MODEL = str(args.alcohol_model)
    ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL = str(args.cause_hazard_weight_model)

    if args.boozehound_wino:
        ACTIVE_BOOZEHOUND = True
        ACTIVE_BOOZEHOUND_PRESET = "wino"
        ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = float(BOOZEHOUND_WINO_GRAMS_PER_DAY)
    elif args.boozehound:
        ACTIVE_BOOZEHOUND = True
        ACTIVE_BOOZEHOUND_PRESET = "standard"
        ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = float(BOOZEHOUND_GRAMS_PER_DAY)
    else:
        ACTIVE_BOOZEHOUND = False
        ACTIVE_BOOZEHOUND_PRESET = None
        ACTIVE_BOOZEHOUND_GRAMS_PER_DAY = 0.0
    if not ACTIVE_BOOZEHOUND and (args.alcohol_start_age != BOOZEHOUND_START_AGE or args.alcohol_end_age is not None):
        print("argument error: alcohol start/end ages require --boozehound or --boozehound-wino", file=sys.stderr)
        return 2
    if not ACTIVE_BOOZEHOUND and ACTIVE_ALCOHOL_MODEL != DEFAULT_ALCOHOL_MODEL:
        print("argument error: non-default --alcohol-model requires --boozehound or --boozehound-wino", file=sys.stderr)
        return 2
    if ACTIVE_ALCOHOL_MODEL != "cause-hazard-prototype" and ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL != DEFAULT_CAUSE_HAZARD_WEIGHT_MODEL:
        print("argument error: non-default --cause-hazard-weight-model requires --alcohol-model cause-hazard-prototype", file=sys.stderr)
        return 2
    if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
        if args.birth_year is not None:
            print("argument error: cause-hazard-prototype currently supports present-day period mode only (no --birth-year)", file=sys.stderr)
            return 2
        if ACTIVE_COUNTRY not in {"fi", "ca"}:
            print("argument error: cause-hazard-prototype currently supports Finland and Canada only", file=sys.stderr)
            return 2
    if args.deathmatch:
        dm_provinces = list(args.deathmatch_provinces)
        base_labels = [
            deathmatch_contestant_label(args.deathmatch[i], "m", province=dm_provinces[i])
            for i in range(2)
        ]
        duplicate_labels = base_labels[0] == base_labels[1]
        notice_players = [1, 2] if duplicate_labels else [None, None]
        if deathmatch_single_country:
            print(
                "[ATTN] Only one country selected; starting a same-country deathmatch: "
                f"{deathmatch_contestant_label(args.deathmatch[0], 'm', province=dm_provinces[0], player_number=notice_players[0])} "
                f"vs {deathmatch_contestant_label(args.deathmatch[1], 'm', province=dm_provinces[1], player_number=notice_players[1])}."
            )
        data_status(
            "deathmatch "
            f"{country_display_label(args.deathmatch[0], province=dm_provinces[0])} vs "
            f"{country_display_label(args.deathmatch[1], province=dm_provinces[1])}: initializing data backends...",
            level=1,
        )
    else:
        data_status(f"{country_display_label()}: initializing data backends...", level=1)

    # Resolve showcase defaults after mode selection. Normal single-run roulette
    # should demonstrate the full cause/detail/month stack without requiring
    # three extra switches. Batch and deterministic printout remain lean unless
    # those layers are explicitly requested. Explicit opt-outs always win.
    if not args.deathmatch:
        explicit_causes = args.causes
        explicit_seasonality = args.seasonality
        if args.printout:
            if explicit_causes is True or explicit_seasonality is True:
                print("--printout only emits mortality odds; --causes/--seasonality are not applicable", file=sys.stderr)
                return 2
            args.causes = False
            args.seasonality = False
        else:
            if explicit_causes is False and explicit_seasonality is True:
                print("argument error: --no-causes conflicts with --seasonality/--death-month", file=sys.stderr)
                return 2
            if explicit_seasonality is True and explicit_causes is None:
                explicit_causes = True
            if args.runs is not None:
                args.causes = False if explicit_causes is None else bool(explicit_causes)
                args.seasonality = False if explicit_seasonality is None else bool(explicit_seasonality)
            else:
                args.causes = True if explicit_causes is None else bool(explicit_causes)
                # Month timing depends on a cause cell in Finland. If causes were
                # explicitly disabled, do not silently re-enable them via the
                # single-run showcase default.
                args.seasonality = (
                    bool(args.causes) if explicit_seasonality is None
                    else bool(explicit_seasonality)
                )
            if args.seasonality:
                args.causes = True

    if args.delay < 0:
        print("--delay must be >= 0", file=sys.stderr)
        return 2
    if args.start_age < 0:
        print("--start-age must be >= 0", file=sys.stderr)
        return 2
    if args.end_age is not None and args.end_age < 0:
        print("--end-age must be >= 0", file=sys.stderr)
        return 2
    if args.end_age is not None and not args.printout:
        print("--end-age requires --printout", file=sys.stderr)
        return 2
    if args.printout and args.end_age is not None and args.end_age < args.start_age:
        print("--end-age must be >= --start-age", file=sys.stderr)
        return 2
    if args.printout and args.deathmatch:
        print("--printout is not supported with --deathmatch", file=sys.stderr)
        return 2
    if args.printout and args.runs is not None:
        print("--printout is not supported with --runs", file=sys.stderr)
        return 2
    if args.printout and args.log is not None:
        print("--printout is not supported with --log", file=sys.stderr)
        return 2
    if args.birth_year is not None:
        minimum = STATCAN_LIFE_TABLE_FIRST_YEAR if ACTIVE_COUNTRY == "ca" else HMD_FINLAND_FIRST_YEAR
        if args.birth_year < minimum:
            print(f"--birth-year must be >= {minimum} for {'Canadian' if ACTIVE_COUNTRY == 'ca' else 'Finnish'} cohort mode", file=sys.stderr)
            return 2
    if args.top_causes <= 0:
        print("--top-causes must be > 0", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    cause_rng = random.Random(
        None if args.seed is None else (args.seed ^ 0xC0DDEAD)
    )
    detail_rng = random.Random(
        None if args.seed is None else (args.seed ^ 0xD37A11ED)
    )
    # Separate stream: WHO subtype refinement must not perturb the StatFin
    # mortality, broad-cause or 3-character detail rolls.
    deep_detail_rng = random.Random(
        None if args.seed is None else (args.seed ^ 0x4D494344)
    )
    # Separate stream: enabling month timing must not perturb mortality/cause rolls.
    seasonal_rng = random.Random(
        None if args.seed is None else (args.seed ^ 0x5EA50A11)
    )

    if args.deathmatch:
        return run_deathmatch(args, selection)

    cohort_source = None
    if ACTIVE_COUNTRY == "ca":
        data_status("Canada mode: loading annual mortality probabilities...", level=1)
        try:
            if args.statcan_cache is not None or args.refresh_statcan:
                statcan_cache = args.statcan_cache or DEFAULT_STATCAN_CACHE
            elif args.ca_province_active == "bc" and BUNDLED_STATCAN_LIFE_TABLE_BC.exists():
                # The loader appends the regional _bc suffix to this base path.
                statcan_cache = BUNDLED_STATCAN_LIFE_TABLE
            elif args.ca_province_active is None and BUNDLED_STATCAN_LIFE_TABLE.exists():
                statcan_cache = BUNDLED_STATCAN_LIFE_TABLE
            else:
                statcan_cache = DEFAULT_STATCAN_CACHE
            ACTIVE_PERIOD_SOURCE = fetch_statcan_life_table(
                cache_path=statcan_cache, refresh=args.refresh_statcan,
                province=args.ca_province_active,
            )
        except (CohortDataError, OSError, urllib.error.URLError, zipfile.BadZipFile, json.JSONDecodeError, csv.Error) as exc:
            print(f"Canadian life-table data error: {exc}", file=sys.stderr)
            return 2
        if args.birth_year is not None:
            cohort_source = ACTIVE_PERIOD_SOURCE
            first_year = args.birth_year + args.start_age
            if first_year < cohort_source.min_year:
                print(f"cohort-data error: Canadian life-table data begin in {cohort_source.min_year}; simulation begins in {first_year}", file=sys.stderr)
                return 2
    elif args.birth_year is not None:
        data_status("Finland cohort mode: loading age/year mortality probabilities...", level=1)
        try:
            statfin_cache = args.statfin_cache or (DEFAULT_STATFIN_CACHE if args.refresh_statfin else BUNDLED_STATFIN_LIFE_TABLE)
            cohort_source = prepare_cohort_source(
                birth_year=args.birth_year, start_age=args.start_age, selection=selection,
                hmd_dir=args.hmd_dir, statfin_cache=statfin_cache, refresh_statfin=args.refresh_statfin,
            )
        except CohortDataError as exc:
            print(f"cohort-data error: {exc}", file=sys.stderr)
            return 2
    elif ACTIVE_MORTALITY_MODEL != "legacy":
        data_status(
            "Finland mode: loading official annual mortality probabilities"
            + (" for age graduation..." if ACTIVE_MORTALITY_MODEL == "smoothed" else "..."),
            level=1,
        )
        try:
            statfin_cache = args.statfin_cache or (DEFAULT_STATFIN_CACHE if args.refresh_statfin else BUNDLED_STATFIN_LIFE_TABLE)
            ACTIVE_PERIOD_SOURCE = fetch_statfin_life_table(
                cache_path=statfin_cache, refresh=args.refresh_statfin
            )
        except CohortDataError as exc:
            print(f"Finnish life-table data error: {exc}", file=sys.stderr)
            return 2
    else:
        data_status("Finland mode: using original legacy Mortality Roulette mortality schedule", level=1)
        ACTIVE_PERIOD_SOURCE = None

    if args.seasonality:
        # Seasonal timing is conditional on the already-selected broad cause.
        args.causes = True

    cause_source = None
    canada_raw = None
    if args.causes and USE_ICD_TITLES:
        try:
            data_status("loading shared WHO ICD-10 terminology...", level=1)
            preflight_icd_titles()
        except (CauseDataError, OSError, json.JSONDecodeError) as exc:
            # Terminology is presentation metadata, not mortality probability data.
            # Keep the simulation usable but make the missing labels explicit.
            print(f"ICD-title warning: {exc}", file=sys.stderr)

    if args.causes:
        try:
            if ACTIVE_COUNTRY == "ca":
                data_status("Canada mode: resolving WHO cause-of-death data...", level=1)
                canada_raw = WhoCountryRawMortality(
                    country_code=WHO_CANADA_COUNTRY_CODE, country_name="Canada",
                    cache_dir=args.who_detail_cache_dir, refresh=args.refresh_who_detail,
                )
                cause_source = CanadaCauseOfDeathSource(canada_raw)
                cause_source.resolve_latest_year()
            else:
                data_status("Finland mode: loading StatFin cause-of-death data...", level=1)
                cause_source = fetch_statfin_causes(cache_path=(args.cause_cache or (DEFAULT_CAUSE_CACHE if args.refresh_causes else BUNDLED_STATFIN_CAUSES)), refresh=args.refresh_causes)
        except CauseDataError as exc:
            print(f"cause-data error: {exc}", file=sys.stderr)
            return 2

    # The experimental alcohol engine needs country cause cells to build annual
    # mortality hazards even when the user did not request a visible cause roll.
    # Keep that internal dependency separate so terminal output can still
    # truthfully say "cause-of-death roulette: OFF".
    alcohol_cause_source: object | None = None
    if ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype":
        if cause_source is not None:
            alcohol_cause_source = cause_source
        else:
            try:
                if ACTIVE_COUNTRY == "ca":
                    data_status("Canada alcohol prototype: loading WHO complete-ICD hazard inputs...", level=1)
                    canada_raw = WhoCountryRawMortality(
                        country_code=WHO_CANADA_COUNTRY_CODE, country_name="Canada",
                        cache_dir=args.who_detail_cache_dir, refresh=args.refresh_who_detail,
                    )
                    alcohol_cause_source = CanadaCauseOfDeathSource(canada_raw)
                    alcohol_cause_source.resolve_latest_year()
                else:
                    data_status("Finland alcohol prototype: loading StatFin broad-cause hazard inputs...", level=1)
                    alcohol_cause_source = fetch_statfin_causes(
                        cache_path=(args.cause_cache or (DEFAULT_CAUSE_CACHE if args.refresh_causes else BUNDLED_STATFIN_CAUSES)),
                        refresh=args.refresh_causes,
                    )
            except CauseDataError as exc:
                print(f"cause-data error: {exc}", file=sys.stderr)
                return 2

    cause_detail_mode = args.cause_detail
    if cause_detail_mode == "auto":
        cause_detail_mode = "broad" if args.runs is not None else "tree"

    detail_resolver = None
    if args.causes and cause_detail_mode in {"specific", "tree"}:
        if ACTIVE_COUNTRY == "ca":
            if canada_raw is None:
                raise CauseDataError("internal error: Canadian WHO raw source missing")
            detail_resolver = CanadaCauseDetailResolver(canada_raw)
        else:
            detail_resolver = CauseDetailResolver(cache_path=(args.detail_cache or (DEFAULT_DETAIL_CACHE if args.refresh_detail else BUNDLED_STATFIN_DETAIL)), refresh=args.refresh_detail)

    # DEV9 v4 needs the StatFin 11be neoplasm partition even when cause-detail
    # output is broad/off, because the same children now build the annual
    # neoplasm subhazard. Reuse the visible resolver when one already exists.
    if (
        ACTIVE_COUNTRY == "fi"
        and ACTIVE_ALCOHOL_MODEL == "cause-hazard-prototype"
        and ACTIVE_CAUSE_HAZARD_WEIGHT_MODEL == "evidence-v4-cancer"
    ):
        if detail_resolver is None:
            detail_resolver = CauseDetailResolver(
                cache_path=(args.detail_cache or (DEFAULT_DETAIL_CACHE if args.refresh_detail else BUNDLED_STATFIN_DETAIL)), refresh=args.refresh_detail
            )
        if isinstance(cause_source, CauseOfDeathSource):
            setattr(cause_source, "_alcohol_detail_resolver", detail_resolver)
        if isinstance(alcohol_cause_source, CauseOfDeathSource):
            setattr(alcohol_cause_source, "_alcohol_detail_resolver", detail_resolver)

    deep_detail_resolver = None
    if (
        ACTIVE_COUNTRY != "ca" and args.causes
        and cause_detail_mode in {"specific", "tree"}
        and not args.no_who_detail
    ):
        deep_detail_resolver = WhoDeepDetailResolver(cache_dir=args.who_detail_cache_dir, refresh=args.refresh_who_detail)

        # Present-day Finland always rolls causes from the newest StatFin year,
        # so load the matching WHO complete-ICD year NOW. This prevents a
        # surprise archive/cache burst after the age roll has already ended.
        # Cohort mode can request many historical cause years; preloading every
        # possible year would mean scanning several large WHO archives. Keep
        # those lazy, but DATA_VERBOSITY still controls any later status lines.
        if args.birth_year is None and cause_source is not None:
            preflight_year = int(cause_source.max_year)
            data_status(
                f"Finland mode: preflighting WHO deep ICD detail for {preflight_year}...",
                level=1,
            )
            deep_detail_resolver.preflight_year(preflight_year)

    seasonal_source = None
    if args.seasonality:
        try:
            if ACTIVE_COUNTRY == "ca":
                data_status("Canada mode: loading monthly death distribution...", level=1)
                statcan_seasonal_refresh = args.refresh_statcan or args.refresh_seasonality
                if args.statcan_seasonal_cache is not None or statcan_seasonal_refresh:
                    statcan_seasonal_cache = args.statcan_seasonal_cache or DEFAULT_STATCAN_MONTHLY_CACHE
                    statcan_seasonal_province = args.ca_province_active
                elif args.ca_province_active == "bc" and BUNDLED_STATCAN_SEASONAL_BC.exists():
                    # The monthly loader appends the regional _bc suffix.
                    statcan_seasonal_cache = BUNDLED_STATCAN_SEASONAL
                    statcan_seasonal_province = args.ca_province_active
                elif args.ca_province_active is None and BUNDLED_STATCAN_SEASONAL.exists():
                    statcan_seasonal_cache = BUNDLED_STATCAN_SEASONAL
                    statcan_seasonal_province = None
                else:
                    statcan_seasonal_cache = DEFAULT_STATCAN_MONTHLY_CACHE
                    statcan_seasonal_province = args.ca_province_active
                seasonal_source = fetch_statcan_seasonality(
                    cache_path=statcan_seasonal_cache, refresh=statcan_seasonal_refresh,
                    province=statcan_seasonal_province,
                )
            else:
                data_status("Finland mode: loading StatFin seasonal death timing...", level=1)
                seasonal_source = fetch_statfin_seasonality(cache_path=(args.seasonal_cache or (DEFAULT_SEASONAL_CACHE if args.refresh_seasonality else BUNDLED_STATFIN_SEASONAL)), refresh=args.refresh_seasonality)
        except CauseDataError as exc:
            print(f"seasonal-data error: {exc}", file=sys.stderr)
            return 2

    data_status(
        "data preflight complete; printing mortality odds" if args.printout
        else "data preflight complete; starting mortality roulette",
        level=1,
    )
    DATA_PREFLIGHT_COMPLETE = True

    if args.printout:
        sex = choose_sex(selection, rng)
        if selection == "r":
            print(
                f"random selection: {sex} "
                f"(male share={MALE_BIRTH_SHARE:.1%}, female share={1-MALE_BIRTH_SHARE:.1%})"
            )
        end_age = (
            args.end_age
            if args.end_age is not None
            else default_printout_end_age(
                sex=sex,
                birth_year=args.birth_year,
                cohort_source=cohort_source,
            )
        )
        if end_age < args.start_age:
            print(
                f"--start-age {args.start_age} is beyond the default printout ceiling {end_age}; "
                "supply --end-age explicitly to extend the odds table",
                file=sys.stderr,
            )
            return 2
        print_mortality_odds_table(
            sex=sex,
            start_age=args.start_age,
            end_age=end_age,
            birth_year=args.birth_year,
            cohort_source=cohort_source,
            alcohol_cause_source=alcohol_cause_source,
        )
        return 0

    if args.runs is not None:
        if args.runs <= 0:
            print("--runs must be > 0", file=sys.stderr)
            return 2
        if args.log:
            print("--log is only supported in single-run mode", file=sys.stderr)
            return 2
        run_batch(
            selection=selection,
            runs=args.runs,
            rng=rng,
            start_age=args.start_age,
            show_progress=not args.no_progress,
            use_record_cap=(ACTIVE_COUNTRY != "ca" and not args.exceptional_tail),
            birth_year=args.birth_year,
            cohort_source=cohort_source,
            cause_source=cause_source,
            cause_rng=cause_rng,
            top_causes=args.top_causes,
            batch_engine=args.batch_engine,
            cause_batch_sampler=args.cause_batch_sampler,
            show_histogram=not args.no_histogram,
            detail_resolver=detail_resolver,
            detail_rng=detail_rng,
            deep_detail_resolver=deep_detail_resolver,
            deep_detail_rng=deep_detail_rng,
            cause_detail_mode=cause_detail_mode,
            seasonal_source=seasonal_source,
            seasonal_rng=seasonal_rng,
            alcohol_cause_source=alcohol_cause_source,
        )
        return 0

    sex = choose_sex(selection, rng)

    if selection == "r":
        print(
            f"random selection: {sex} "
            f"(male share={MALE_BIRTH_SHARE:.1%}, female share={1-MALE_BIRTH_SHARE:.1%})"
        )

    simulate(
        sex=sex,
        rng=rng,
        delay=args.delay,
        log_path=args.log,
        start_age=args.start_age,
        use_record_cap=(ACTIVE_COUNTRY != "ca" and not args.exceptional_tail),
        birth_year=args.birth_year,
        cohort_source=cohort_source,
        cause_source=cause_source,
        cause_rng=cause_rng,
        detail_resolver=detail_resolver,
        detail_rng=detail_rng,
        deep_detail_resolver=deep_detail_resolver,
        deep_detail_rng=deep_detail_rng,
        cause_detail_mode=cause_detail_mode,
        seasonal_source=seasonal_source,
        seasonal_rng=seasonal_rng,
        alcohol_cause_source=alcohol_cause_source,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
