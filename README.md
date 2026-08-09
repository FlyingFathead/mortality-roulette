# Mortality Roulette

**Mortality Roulette** (Finnish: *Kuolleisuusruletti*) is an educational and entertainment statistical simulation of human mortality, built around real population-level life-table and cause-of-death data.

It rolls a simulated life year by year using age-, sex-, country- and model-specific mortality probabilities and, when death occurs, can continue into cause of death, detailed cause trees and seasonal timing.

⚠ **This is a statistical concept project, not an individualized medical prognosis or healthcare decision tool.**

## ⚠ Disclaimer

**Mortality Roulette is an educational and entertainment statistical simulation and concept project.** It works with population-level mortality data; it is not a medical risk calculator or an individualized prognosis tool.

The software and bundled datasets are provided **AS IS**. Output is not medical advice, diagnosis, prognosis, treatment guidance, or a basis for healthcare decisions. Do not use it as a substitute for professional medical assessment.

Just because you can fly an airliner in Microsoft Flight Simulator does not make you a pilot. Likewise, running Mortality Roulette does not make you a physician, epidemiologist, actuary, or fortune-teller.

---

## Quick start

Requirements:

- Python 3.10+
- no third-party Python packages are required for the main program
- internet access is optional for bundled default datasets; refresh/download paths and non-bundled data can still use the network

Clone the repository:

```bash
git clone https://github.com/FlyingFathead/mortality-roulette.git
cd mortality-roulette
```

### Quickest run

Just run it:

```bash
python mortality_roulette.py
```

In an interactive terminal, Mortality Roulette asks for the basic choices that were not supplied on the command line, including sex and the present-day mortality model.

```text
Choose sex: (m)ale, (f)emale, (r)andom:

Choose mortality model:
  (s) age-graduated official baseline  [recommended for simulation]
  (o) official raw period table        [literal published single-age qx]
  (l) original legacy Mortality Roulette

Selection [s]:
```

The default/recommended `smoothed` model is still derived from the bundled official period table. It uses a transparent age-domain graduation to reduce single-calendar-year sawtooth noise; it does **not** rewrite or replace the raw official dataset.

### Fun run: Boozehound Deathmatch 🍷⚔️

For added morbid education about how sustained lifestyle hazards can modify an already-unfriendly mortality baseline, load up Finland and Canada with the Boozehound/Wino scenario and let the cause-hazard model do its thing:

```bash
python mortality_roulette.py \
  --deathmatch fi ca \
  --sex m \
  --boozehound-wino \
  --alcohol-model cause-hazard-prototype \
  --cause-hazard-weight-model evidence-v4-cancer
```

Or, less academically: **load up the contestants with booze and see what the statistics do to them.**

A plain baseline Deathmatch, with no alcohol exposure, is simply:

```bash
python mortality_roulette.py --deathmatch fi ca --sex m
```

Print annual mortality odds without rolling a life:

```bash
python mortality_roulette.py --printout --gender m
```

Choose a mortality model explicitly:

```bash
python mortality_roulette.py --mortality-model smoothed
python mortality_roulette.py --mortality-model official
python mortality_roulette.py --mortality-model legacy
```

`--legacy-mortality` remains available as a backward-compatible alias for `--mortality-model legacy`.

For all options:

```bash
python mortality_roulette.py --help
```

### Present-day mortality models

**`smoothed` — age-graduated official baseline (recommended for simulation)**

- starts from the bundled official single-age period-table `qx`
- converts `qx` to annual hazards
- leaves age 0 untouched
- applies a centered five-age triangular smoother with weights `1,2,3,2,1`
- from exact age 30 onward, applies nondecreasing isotonic graduation (PAVA)
- keeps the official source data untouched and separately selectable

This is intended to expose the underlying age-loading of the mortality die without letting random single-calendar-year bumps dominate adjacent ages.

**`official` — raw published period table**

Uses the literal published single-age `qx` values. Annual sampling noise is preserved, so adjacent ages can occasionally move downward even though the overall age trend rises strongly.

For Finland the bundled official 2024 StatFin table supplies one-year `qx` through exact age 99. The age-100 row is terminal/open-ended and has no published `100→101` qx; the program therefore labels age 100+ as an explicit tail model. StatFin reports remaining life expectancy at age 100 separately (1.85 years for males and 1.80 for females).

For Canada the bundled 2024 Statistics Canada complete life table supplies exact-age `qx` through age 109. Any modeled tail starts only after the last available exact-age value.

**`legacy` — original legacy Mortality Roulette**

The original baked mortality schedule from early versions is retained in the code for historical comparison and exact reproducibility. It is not represented as the current official StatFin table and is not silently substituted for the new age-graduated model.

Present-day model selection does not remove any existing data plumbing: bundled datasets are preferred for normal offline use, while explicit cache paths and `--refresh-statfin`, `--refresh-statcan` and the other refresh/download options remain available.

Deathmatch is population-baseline/no-alcohol by default. Add `--boozehound` or `--boozehound-wino` explicitly to apply alcohol exposure.

---

## Key commands and modes

### Country selection

```bash
--country fi
--country ca
--canada                     # shorthand for --country ca
```

### Canadian provinces

Use `--ca-province` to select a Canadian province for mortality and monthly timing data:

```bash
python mortality_roulette.py --country ca --ca-province bc --sex m
python mortality_roulette.py --country ca --ca-province ontario --sex f
```

Supported single-year complete-life-table provinces:

```text
nl  Newfoundland and Labrador
ns  Nova Scotia
nb  New Brunswick
qc  Quebec
on  Ontario
mb  Manitoba
sk  Saskatchewan
ab  Alberta
bc  British Columbia
```

Prince Edward Island is deliberately rejected for now because Statistics Canada does not publish it in the same single-year complete life-table series used by the exact-age engine. The territories likewise use a different abridged life-table product.

Canadian provincial mode currently uses:

- province-specific annual `qx` from Statistics Canada 13-10-0837-01
- province-specific monthly timing from Statistics Canada 13-10-0708-01
- national Canadian WHO cause-of-death distributions, clearly labelled as national when a province is active

### Deathmatch

Two countries:

```bash
python mortality_roulette.py --deathmatch fi ca --sex m
```

Same country, two independent players:

```bash
python mortality_roulette.py --deathmatch fi --sex m
```

Canadian provincial Deathmatch:

```bash
python mortality_roulette.py --deathmatch ca ca --ca-province bc on --sex m
```

Win condition:

```bash
--deathmatch-win long        # longevity; last contestant standing wins (default)
--deathmatch-win short       # brevity; first contestant to tap out wins
```

Deathmatch players always receive independent mortality, cause, detail and timing RNG streams. `--seed N` still makes the entire match reproducible.

### Cause and timing detail

Normal single-run roulette defaults to the full presentation stack:

```text
cause-of-death roulette: ON
cause detail: TREE
seasonal death timing: ON
```

Controls remain available:

```bash
--causes / --no-causes
--cause-detail broad
--cause-detail specific
--cause-detail tree
--seasonality / --death-month
--no-seasonality
--no-who-detail
```

Batch mode remains lean by default (broad/optional cause work and no monthly timing unless explicitly requested), and `--printout` remains qx-only. Finland uses Statistics Finland cause data and Canadian cause selection uses Canada's WHO Mortality Database submission. Seasonal timing is rolled only after death and does not alter annual mortality or cause selection.

### Alcohol scenarios

```bash
--boozehound
--boozehound-wino
--alcohol-start-age AGE        # default: 18
--alcohol-end-age AGE          # optional; stop age itself is alcohol-free
--alcohol-model legacy|cause-hazard-prototype
--cause-hazard-weight-model proxy-v1|evidence-v1|evidence-v2-popnorm|evidence-v3-popdist|evidence-v4-cancer
```

`--boozehound-wino` models one 750 mL bottle of 12% ABV wine per day, including hazard-based all-cause mortality adjustment, duration-aware cause weighting, cumulative survival accounting and descriptive ethanol/wine/vodka equivalents. Exposure starts at age 18 by default; `--alcohol-start-age` changes the start age and `--alcohol-end-age` optionally ends modeled intake. Start/stop ages are printed in run headers and exposure summaries.

The current cessation implementation preserves alcohol exposure accumulated before the stop age and its already-compounded survival effect, but returns the *current* alcohol hazard multiplier and alcohol cause reweighting to baseline after cessation. A disease-specific post-cessation residual-risk decay curve is not yet calibrated, so the program states this limitation explicitly when relevant.

`v0.13.0-dev1` added an opt-in `--alcohol-model cause-hazard-prototype` engine for present-day Finland. It splits each annual all-cause hazard using StatFin broad cause shares, applies the existing duration/dose-aware broad alcohol cause weights as provisional hazard multipliers, recombines them, and derives the annual death probability from that total. **This is an architecture sensitivity prototype, not a validated gameplay model.** The existing broad cause weights were originally conditional cause-shape proxies, and Finnish population background alcohol exposure is not yet deconvolved. `legacy` remains the default through the single top-level `DEFAULT_ALCOHOL_MODEL` constant.

The selected alcohol engine is printed in single-run, batch and Deathmatch headers whenever a boozehound preset is active. The prototype loads the active country's cause data internally even when visible cause reporting is off: StatFin 11az broad causes for Finland and WHO complete-ICD cause cells for Canada. This does not by itself enable visible cause-of-death roulette. Birth-cohort mode remains unsupported for the prototype.

`v0.13.0-dev2` adds an A/B-selectable broad-cause batch sampler. `--cause-batch-sampler fast-grouped` is the default: it resolves each StatFin sex/age/year cause cell once and performs grouped draws, avoiding the previous per-death distribution rebuild. `--cause-batch-sampler reference-slow` preserves the original one-death-at-a-time implementation for validation. Fast grouped sampling currently applies only to broad causes without seasonality; specific/tree detail or seasonal timing falls back explicitly to the reference sampler. The top-level `DEFAULT_CAUSE_BATCH_SAMPLER` controls the default.

`v0.13.0-dev3` introduced A/B cause-hazard weights. `proxy-v1` exactly preserves the original prototype and `evidence-v1` replaces only the directly alcohol-coded hazard with the Carr et al. 2024 AUD-mortality dose-response. `v0.13.0-dev4` added `evidence-v2-popnorm`, which divides that direct-alcohol RR by a provisional population mean-dose RR because the observed period-table hazard already embeds background drinking. `v0.13.0-dev8` adds `evidence-v3-popdist`: instead of pretending the population mean dose is a representative person, it estimates population `E[RR(D)]` with the WHO/Rehm/Kehoe Gamma exposure model for current drinkers plus an abstainer point mass. All heterogeneous non-direct-alcohol broad groups remain explicit proxy fallbacks. None of the evidence models is the global default yet.

`v0.13.0-dev9` adds `evidence-v4-cancer`. It preserves v3's population-normalized Carr direct-alcohol hazard and adds disease-specific cancer subhazards from Dai et al., *Nature Health* (2026), Table 3. The mapped ICD-10 partitions are C00-C08 (lip/oral cavity), C09-C10 and C12-C14 (other pharynx; C11 nasopharynx excluded), C15 (oesophagus), C16 (stomach), C18-C21 (colorectal), C22 (liver), C25 (pancreas), C32 (larynx), C50 (female breast) and C61 (prostate). The published mean-RR table is used at 10 g/day intervals through 100 g/day and held flat above 100 g/day rather than extrapolated beyond published support. Each site RR is normalized by the same country/sex WHO-style Gamma `E[RR(D)]` exposure distribution used by v3.

For Finland, DEV9 also removes the old flat neoplasm broad-hazard shortcut when v4 is active. The annual StatFin 04-22 neoplasm hazard is rebuilt from the exact same 11be C00-D48 child distribution used by specific cause roulette. Suppressed/missing child mass is preserved as an explicit unresolved residual at multiplier 1.0, and an over-inclusive child partition is rejected. This is a hard consistency invariant: the broad annual cancer hazard and the visible detailed cancer roulette cannot silently use different cancer mass. Non-cancer/non-direct alcohol-sensitive mappings remain explicit `proxy-v1` fallbacks.

For `evidence-v3-popdist`, the current-drinker distribution is Gamma with sex-specific `SD/mean` ratios (1.171 men, 1.258 women), uses 80% of APC in accordance with WHO burden-of-disease exposure methodology, and is normalized on 0–150 g/day. Carr reports the AUD-mortality curve through 100 g/day; inside the **population denominator only**, dev8 holds the Carr RR flat above 100 g/day rather than inventing an exponential continuation through the 100–150 g/day tail. Finland uses OECD 2025 sex-specific APC plus THL 2023 abstainer shares (20–69: men 10%, women 12%). Canada currently uses a WHO GISAH 2020 sex-neutral APC fallback plus Statistics Canada CCHS 2023 past-year nondrinker prevalence as an explicitly labeled sex-neutral fallback. These source/age/year mismatches are printed in diagnostics rather than hidden.

The alcohol calibration harness also reports an **unfitted** cause-hazard Wood check when an existing StatFin 11az cache is available. This is deliberately different from the Wood-smooth curve: the cause-hazard prototype is not fitted to Wood, so its lifespan-loss row is an out-of-sample architecture diagnostic.

### Batch and cohort modes

```bash
--runs 100000
--batch-engine fast
--batch-engine step
--birth-year 1980
```

Batch summaries include a fixed-bucket terminal death-age histogram by default, with counts and shares. Use `--no-histogram` to suppress it. The histogram is presentation-only and uses the already simulated death ages; all pre-existing batch summary figures and sections remain unchanged.

Other useful options:

```bash
-v, --version              # print the central VERSION value and exit
--sex m|f|r, --gender m|f|r  # aliases; same parser destination
--printout, --odds-table      # deterministic qx/1-in-X table, no RNG
--end-age N                   # inclusive final interval for --printout
--seed N
--delay 0
--start-age N
--exceptional-tail           # Finland: allow model-only survival beyond observed record ceiling
```

Run `python mortality_roulette.py --help` for the full argument list.

---

## Alcohol calibration harness

`v0.12.10` added a standalone validation utility without changing roulette mortality semantics.
`v0.12.11` extended that same calibration-only harness with a smooth Wood-calibrated
candidate curve. `v0.12.12` adds an independent high-dose holdout panel; the main
roulette still uses the unchanged legacy alcohol model:

```bash
python tools/alcohol_calibration.py
```

The harness analytically integrates the existing Finnish period table and current legacy
alcohol hazard model, then compares its age-40 life-expectancy differences with the
Wood et al. (2018) current-drinker benchmark. It also prints a diagnostic single-RR
value required to reproduce 4.0, 4.5 and 5.0 years of life-expectancy loss under the
existing simplistic architecture. Those diagnostic values are explicitly not proposed
alcohol relative risks.

The v0.12.11 candidate solves architecture-specific RR knots that reproduce the midpoint
of Wood's reported lifespan-loss bands at the reported group mean intakes, then connects
them with a dependency-free monotone cubic interpolation in log(RR). Above Wood's
highest observed group mean (~52.4 g/day), the tool uses conservative log-linear
extrapolation and labels those outputs LOW CONFIDENCE. The 71 g/day BOOZEHOUND-WINO
comparison is therefore a sensitivity analysis, not a proposed epidemiological estimate.

v0.12.12 adds an independent holdout rather than another fit: published male all-cause
RR points from Wang et al. (2014) at 50/75/90/100 g/day are printed beside the
Wood-effective multiplier. Their reference populations are different, so the comparison
is explicitly diagnostic rather than an apples-to-apples pass/fail test. Cirrhosis
mortality dose-response estimates and hospitalized Nordic AUD mortality/life-expectancy
ranges are shown only as severity/context bounds. None of these values change gameplay.

The tool is intentionally calibration-only: it does not alter the main CLI, mortality
probabilities, alcohol presets, cause selection, RNG streams or batch simulation.

---

## Development / regression tests

The 0.12.x series begins a gradual modularization of the original single-file prototype.
The public entry point remains `mortality_roulette.py`; low-risk support code can move into
`mortality_roulette_core/` without changing CLI usage.

Run the bundled dependency-free regression suite with:

```bash
python -m unittest discover -s tests -v
```

The first tests pin CLI version reporting, terminal rendering primitives, Canadian province
assignment, hazard-space alcohol mortality adjustment, and reproducible/independent Deathmatch RNG streams.

---

## Changelog

### v0.13.0-dev16

- Fixed interactive mortality-model detection so prompts appear only when both stdin and stdout are attached to a terminal. Captured/subprocess test runs no longer block on `Selection [s]:` merely because they inherit a terminal stdin.
- Added regression coverage for both captured-output noninteractive execution and genuine full-TTY interactive execution; subprocess CLI tests now use `stdin=DEVNULL` so accidental prompts fail instead of waiting for keyboard input.
- Added a minimal repository `.gitignore` for Python bytecode, test/type/lint caches, virtual environments and local `.env` files; bundled statistical datasets remain tracked.
- No mortality data, smoothing calculations, cause models, RNG behavior, or dataset semantics changed from dev15.

### v0.13.0-dev15

- Documentation-only credits update: added an acknowledgement of Sheldon Solomon and colleagues and the influence of terror management theory, with a reference link.
- No mortality data, simulation semantics, RNG behavior, CLI behavior, or model calculations changed from dev14.

### v0.13.0-dev14

- Added present-day mortality-model selection: `smoothed`, `official`, and `legacy`. Interactive terminal runs use the intentionally memorable S/O/L selector when no model is supplied; noninteractive/scripted present-day runs use the documented `smoothed` default.
- Added a dependency-free age-graduated mortality model derived from the active official period table: annual `qx` is converted to hazard, age 0 is preserved exactly, ages 1+ use a centered five-age triangular smoother (`1,2,3,2,1`), and ages 30+ receive a nondecreasing PAVA graduation. The raw official dataset is never overwritten.
- Preserved the literal official-period mode and the original baked Mortality Roulette schedule as distinct selectable models. `--legacy-mortality` remains a compatibility alias for `--mortality-model legacy`.
- Pinned the alcohol calibration harness to `official` mortality so changing the gameplay default cannot silently move historical calibration diagnostics.
- Expanded README onboarding with the *Kuolleisuusruletti* introduction, short warning plus the original full Flight Simulator disclaimer, clone/run instructions, a one-command quick run, and the Boozehound/Wino Deathmatch example.
- Clarified StatCan BC bundled-path handling and added regressions proving the `_bc` regional cache resolution works offline without changing the existing downloader/cache architecture.

### v0.13.0-dev13

- Corrected the bundled Statistics Finland 12ap 2024 qx snapshot against the official downloadable table output. Regression anchors now pin published values including male age 80 = 52.39 per mille, age 98 = 339.53 per mille and age 99 = 392.67 per mille; age 100 remains an open/terminal row with no one-year q100 and published remaining life expectancy 1.85 years (male) / 1.80 years (female).
- Fixed Finnish `--printout` so the deterministic odds ladder does not stop merely because observed qx ends at age 99. It now continues through the annual tail-model intervals used by normal roulette before the sex-specific Finnish observed-record ceiling, with every modeled row explicitly labelled `[tail model]`.
- Changed normal single-run roulette defaults to cause-of-death ON, TREE detail and seasonal timing ON. Added `--no-causes` and `--no-seasonality` opt-outs; batch and `--printout` defaults remain lean.
- Fixed `--seasonal-cache` source priority so the bundled StatFin 11bf snapshot is actually used offline by default instead of an argparse default path forcing an unnecessary network lookup. Existing explicit cache and `--refresh-seasonality` behavior remains intact.
- Added regression tests for the official StatFin anchor rows, Finnish default tail printout, full single-run cause/tree/month stack, and opt-out behavior.

### v0.13.0-dev12

- Release-candidate cleanup pass over the dev11 dataset/source migration; mortality probabilities and simulation semantics are unchanged.
- Added regression coverage for the bundled dataset manifest: every vendored dataset must exist and match its recorded byte size and SHA-256 before release packaging.
- Revalidated the official/default versus modeled-tail versus original-legacy source boundaries and retained all existing cache/download/refresh paths.

### v0.13.0-dev11

- Replaced the default Finnish baked present-day qx schedule with a bundled official Statistics Finland 12ap 2024 snapshot, sex-specific through exact age 99. Age 100+ remains an explicitly labelled model tail because the source's terminal 100+ interval is not a one-year q100.
- Bundled the existing official Statistics Canada 13-10-0837 life-table caches for national Canada and British Columbia; those paths now work offline by default. Other supported provinces retain the existing download/cache fallback.
- Preserved the original Finnish baked qx arrays in code behind `--legacy-mortality`, retained as the original legacy model for historical comparison and reproducibility.
- Added `datasets/` as the repository home for vendored statistical/reference data and moved `who_icd10_titles_2019.json` under `datasets/who/icd10/`.
- Bundled existing Finland cause/detail/seasonality and Canada monthly snapshots where available; explicit cache paths and all `--refresh-*` downloader paths remain supported.
- Fixed old-age tail provenance/monotonicity: Finland 100+ is explicitly modeled from sex-specific centenarian anchors rather than pretending StatFin publishes q100; an extrapolated tail can never step downward when the last official qx already exceeds the historical nominal 50% ceiling.
- Added dataset provenance/licensing documentation and an `⚠` AS-IS educational/entertainment disclaimer.

### v0.13.0-dev10

- Added deterministic `--printout` mode (`--odds-table` alias): prints the same annual qx and `1 in X` odds used by the roulette engine, but does not draw RNG rolls, emit `survived`/death results, or terminate on a simulated death.
- Added `--end-age N` for printout mode. Without it, printout stops at the last exact age available in the active mortality table; explicit higher values are allowed and tail-model rows remain labelled.
- Added `--gender m|f|r` as a true argparse alias for `--sex m|f|r`; both populate the same `args.sex` value and existing scripts remain compatible.
- Refactored single-run roulette and printout through one shared annual-qx resolver so deterministic output cannot silently diverge from the actual mortality roll path, including cohort and alcohol-adjusted qx.

### v0.13.0-dev9

- Added opt-in `evidence-v4-cancer`; defaults remain unchanged (`legacy` alcohol engine and `proxy-v1` weight model).
- Preserves v3's Carr 2024 direct-alcohol hazard normalized by the WHO-style country/sex Gamma population `E[RR(D)]`.
- Added Dai et al. 2026 *Nature Health* Table 3 mean-RR curves for breast, colorectal, oesophageal, laryngeal, liver, lip/oral, other pharyngeal, pancreatic, prostate and stomach cancer.
- Added explicit ICD-10 cancer partitions: C00-C08, C09-C10/C12-C14, C15, C16, C18-C21, C22, C25, C32, C50 (female) and C61 (male); C11 nasopharynx is deliberately excluded from the "other pharyngeal" mapping.
- Cancer site RRs are population-normalized with the same v3 Gamma exposure model; at the 71 g/day wino preset, Finnish male target multipliers are approximately oesophagus x2.02, other pharynx x2.07, larynx x1.78, lip/oral x1.75, liver x1.59, colorectal x1.23, pancreas x1.10, prostate x1.09 and stomach x1.11.
- Finland v4 broad neoplasm hazards now use reconciled StatFin 11be C00-D48 children rather than a flat broad neoplasm proxy. Suppressed/unresolved detail mass is retained explicitly at x1.0.
- The same reconciled 11be partition and ICD-level weighting function are used by annual hazard reconstruction and specific cause-detail roulette; child totals exceeding the 11az parent are rejected.
- Added six DEV9 cancer/invariant regressions; full dependency-free suite is 84 tests.
- Source: Dai X et al. *Nature Health* (2026), "Health effects associated with alcohol consumption: a Burden of Proof study", doi:10.1038/s44360-026-00139-5.

### v0.13.0-dev8

- Added opt-in `evidence-v3-popdist` to the cause-hazard prototype; defaults remain unchanged (`legacy` alcohol engine and `proxy-v1` weight model).
- Replaced v2's `RR(mean population dose)` denominator with a WHO/Rehm/Kehoe-style population `E[RR(D)]`: abstainers are represented separately and current drinkers follow a sex-specific Gamma distribution.
- WHO exposure construction uses 80% of APC and a 0–150 g/day normalized drinker distribution; the Gamma SD is inferred from the mean using 1.171× for men and 1.258× for women.
- Finland inputs: OECD 2025 sex-specific APC plus THL Drinking Habits Survey 2023 abstainer shares (20–69: men 10%, women 12%).
- Canada inputs remain explicit fallbacks pending matched sex-specific data: WHO GISAH 2020 total APC plus Statistics Canada CCHS 2023 past-year nondrinker prevalence.
- Carr's direct-alcohol RR is held flat above 100 g/day **inside the population E[RR] integral only**, because the published AUD-mortality table ends at 100 g/day; individual doses within published support are unchanged.
- Gamma integration uses a transformed variable that removes the integrable density singularity at zero for shape < 1; regression tests pin retained mass and truncated mean against independent numerical integration.
- Calibration, single/batch mode and Deathmatch print the v3 exposure-distribution assumptions and source fallbacks explicitly.
- Added regression coverage for v3 normalization, Finland THL female abstainer input, Canada fallback labeling, and Gamma quadrature accuracy.

### v0.13.0-dev7

- **Deathmatch is now baseline-neutral by default.** `--deathmatch ...` no longer silently enables the BOOZEHOUND-WINO preset; alcohol exposure requires explicit `--boozehound` or `--boozehound-wino`.
- Non-default alcohol engines in Deathmatch therefore also require an explicit alcohol preset, matching single-country CLI semantics.
- Single and batch Deathmatch headers print `lifestyle modifier: none (population period-table baseline)` when no exposure is active.
- Batch Deathmatch prints a warning before cross-country cause tables that source-specific broad cause taxonomies (for example StatFin custom groups vs WHO ICD chapters) are not necessarily category-equivalent.
- Added regression coverage preventing the old implicit-wino Deathmatch default from returning.

### v0.13.0-dev6

- Added high-throughput batch Deathmatch with `--deathmatch ... --runs N`.
- Batch matches sample each side from precomputed inverse-CDF mortality distributions using independent deterministic RNG streams.
- Reports win/draw rates under the configured `--deathmatch-win long|short` rule, death-age summaries, paired gaps, survival checkpoints and grouped broad cause distributions.
- Finland batch causes use grouped StatFin cells; Canada uses grouped WHO complete-ICD chapter cells.
- Alcohol-calibration `UNDER` / `OVER` labels are explicitly documented as rough numeric comparators, not significance tests or confidence-interval verdicts.
- Added tested, non-operative `E[RR(D)]` population-distribution normalization helpers as scaffolding for a future evidence-v3 model; no v2 gameplay outputs are changed and no unsourced exposure distribution is bundled.

### v0.13.0-dev5

Deathmatch presentation/semantics hardening:

- fatal annual rolls now use a neutral `☠` marker; `🏆` is reserved for the single final winner
- live tap-out announcements render inside the contestant's own left/right arena column
- final winner selection is explicitly governed by `--deathmatch-win`: `long` awards the later death, `short` awards the earlier death; same-age deaths are trophy-free draws
- final winner banner states whether the winner outlived the opponent or tapped out first
- Canada cause-hazard exposure summaries now describe WHO Canada complete-ICD hazards instead of incorrectly saying StatFin
- Deathmatch cause-hazard header clarifies that acute external-cause proxies apply immediately while chronic profiles ramp with duration

### v0.13.0-dev4

- Added `evidence-v2-popnorm` alongside `proxy-v1` and raw `evidence-v1`; defaults remain unchanged for reproducibility.
- `evidence-v2-popnorm` population-normalizes the Carr direct-alcohol mortality multiplier against a provisional country mean-dose APC anchor instead of treating the observed population hazard as an unexposed baseline.
- Finland uses sex-specific OECD 2025 APC anchors; Canada uses WHO GISAH 2020 total APC as a clearly labeled sex-neutral fallback pending a bundled sex-specific source.
- Enabled `cause-hazard-prototype` in present-day Deathmatch for Finland and Canada. Finland reconstructs hazards from StatFin broad causes; Canada reconstructs hazards from WHO complete-ICD age/sex cells.
- Deathmatch now prints the selected alcohol risk engine, cause-hazard weight model, country-specific hazard backend and population-normalization anchor when applicable.
- Removed the stale hard-coded “not available in deathmatch mode in dev1” restriction/error path. Birth-cohort mode remains unsupported for cause-hazard prototype.

### v0.13.0-dev3

- Added `--cause-hazard-weight-model proxy-v1|evidence-v1`; default remains `proxy-v1` for exact dev2 reproducibility.
- Added a Carr et al. 2024 dose-response kernel for mortality due to AUD/alcohol poisoning (20/40/60/80/100 g/day RR points).
- `evidence-v1` applies that source-backed curve only to StatFin broad group 41; all other broad cause weights remain explicitly labeled proxy fallbacks.
- Cause assignment and mortality recombination use the same selected cause-hazard weights, preserving internal consistency.
- Alcohol calibration now prints unfitted Wood panels for both `proxy-v1` and `evidence-v1`.
- Legacy alcohol behavior and the dev2 fast-grouped/reference-slow cause sampler A/B paths remain available.

### v0.13.0-dev2

- Added `--cause-batch-sampler fast-grouped|reference-slow`; default is centralized in `DEFAULT_CAUSE_BATCH_SAMPLER`.
- `fast-grouped` caches broad StatFin cause distributions by death cell and samples grouped deaths instead of rebuilding the same distribution per death.
- Specific/tree cause detail and seasonal timing explicitly fall back to the reference sampler in dev2.
- Added the unfitted cause-hazard prototype to `tools/alcohol_calibration.py` when a StatFin cause cache is available.
- Legacy alcohol remains the default risk engine; dev2 does not promote the experimental cause-hazard prototype to production.

### v0.13.0-dev1

- Added opt-in `--alcohol-model cause-hazard-prototype` for present-day Finland; `legacy` remains the default.
- Added the top-level `DEFAULT_ALCOHOL_MODEL = "legacy"` switch as the single CLI default source.
- The prototype decomposes all-cause integrated hazard by StatFin broad cause shares, applies existing duration/dose-aware cause weights as provisional hazard multipliers, and recombines them into annual `qx`.
- FAST CDF batch, STEP batch, single-run mortality and cumulative exposure summaries all use the selected alcohol engine consistently.
- Prototype StatFin hazard inputs are loaded independently of visible `--causes`; the run header still reports cause roulette OFF unless requested.
- Terminal output prints the active alcohol risk engine whenever boozehound mode is active.
- Prototype is explicitly experimental: broad cause weights are not yet validated causal hazard RRs and background Finnish alcohol exposure is not deconvolved.
- Canadian, cohort and Deathmatch prototype use is rejected in dev1 rather than silently falling back.

### v0.12.12

- Extended `tools/alcohol_calibration.py` with an independent high-dose holdout panel; no roulette mortality behavior changed.
- Added Wang et al. (2014) male all-cause mortality RR points at 50, 75, 90 and 100 g/day versus nondrinkers, displayed beside the Wood-effective candidate multiplier without using them to refit the curve.
- The report explicitly flags the incompatible reference populations and treats the comparison as a warning/diagnostic, not a formal validation test.
- Added cirrhosis-mortality dose-response context (25/50/100 g/day) and hospitalized Nordic AUD mortality/life-expectancy severity bounds; these are not dose-equivalent boozehound parameters.
- Reinforced the design conclusion that a single universal high-dose multiplier is inadequate and that cause-specific hazard reconstruction is the likely v0.13 direction.
- Main CLI, RNG, life table, alcohol preset behavior, cause selection and batch simulation remain unchanged.

### v0.12.11

- Extended `tools/alcohol_calibration.py` with a calibration-only Wood-smooth candidate all-cause hazard curve.
- Candidate knots are solved against the Finnish period table to reproduce the midpoint of Wood's ~0.5, ~1-2 and ~4-5 year age-40 lifespan-loss bands at mean intakes 123, 208 and 367 g/week.
- Added dependency-free monotone cubic interpolation in log(RR) between those knots.
- High-dose values above Wood's highest observed mean (~52.4 g/day) are conservative log-linear extrapolations and are explicitly labeled LOW CONFIDENCE.
- Added a 71 g/day sensitivity table comparing legacy versus candidate remaining life expectancy and survival to ages 60/70/80/85/90/95/100.
- The main roulette alcohol model is unchanged; this release adds calibration experiments only.

### v0.12.10

- Added `tools/alcohol_calibration.py`, a deterministic no-Monte-Carlo validation harness for the current legacy all-cause alcohol hazard model.
- Added the Wood et al. (2018) age-40 life-expectancy benchmark using the reported mean usual intakes of 56, 123, 208 and 367 g/week.
- The harness exposes a structural weakness in the legacy model: below 45 g/day the all-cause target is flat at RR=1.0, and the 367 g/week Wood group produces only about 1.25 modeled years lost versus the reported ~4-5 years.
- Added diagnostic single-RR solving for 4.0/4.5/5.0-year lifespan-loss targets; these are explicitly diagnostics, not proposed epidemiological RRs.
- No mortality probabilities, alcohol-risk logic, cause data, RNG behavior, batch behavior or main CLI semantics changed.

### v0.12.9

- Kept the batch histogram as a pure additive presentation section: existing mean/median, survival checkpoints, LTC benchmark, longevity milestones, and death-age percentiles are unchanged.
- Histogram remains enabled by default in batch mode and can be suppressed with `--no-histogram`.
- Removed the extra modal-age-band and IQR lines so the histogram adds no redundant summary figures.
- No mortality probabilities, alcohol-risk logic, cause data, RNG behavior, or sampling logic changed.

### v0.12.8

- Batch-mode death-age histogram is now shown by default.
- Added `--no-histogram` to suppress the histogram while retaining the rest of the batch summary.
- Statistical and mortality logic are unchanged.

### v0.12.7

- Added a width-aware terminal **death-age distribution** histogram to batch-mode output.
- Histogram buckets are fixed across runs: `<20`, `20–29`, ..., `90–99`, `100+`, with counts and percentages printed beside each bar.
- Added `modal age band` and batch IQR (`25th–75th percentile`) below the histogram.
- Histogram/reporting is derived from the already-simulated batch death ages; mortality probabilities, boozehound hazard math, cause selection, datasets and RNG behavior are unchanged.

### v0.12.6

- Added `--alcohol-start-age AGE` with the existing age 18 behavior retained as the default.
- Added optional `--alcohol-end-age AGE`; the stop age itself is treated as alcohol-free.
- Added explicit `drinking starts at age:` / `drinking stops at age:` lines to boozehound headers, including Deathmatch.
- Cumulative ethanol exposure now caps at the configured stop age, while cumulative survival accounting retains the mortality penalty accumulated during prior exposed years.
- Former-boozehound final cards retain the exposure history after cessation and explicitly state that post-cessation residual-risk decay is not yet calibrated.
- No mortality datasets, cause datasets, RNG streams or non-alcohol simulation logic changed.

### v0.12.5

- Closed the final **DEATHMATCH RESULT** two-column sports-card grid with a Unicode `┴` bottom junction.
- Preserved one blank line between the closed grid and the existing winner/draw banner.
- Reused the existing shared Deathmatch grid-rule helper; no mortality, cause, RNG or data-model changes.

### v0.12.4

- Framed the live Deathmatch contestant header with the same connected two-column grid used by the final result.
- Added a `┬` top junction above the center `│`; the existing lower divider remains `┼`.
- Reused a shared Deathmatch grid-rule helper for both live and final tables.
- No mortality, cause, RNG or data-model changes.

### v0.12.3

- Framed the Deathmatch final-result country header with a top horizontal rule.
- Uses a Unicode `┬` junction above the center `│`, while the existing row divider uses `┼`, keeping the two-column grid visually connected.
- No mortality, cause, RNG or data-model changes.

### v0.12.2

- Rendered Deathmatch result country titles in bold bright white on interactive ANSI terminals while keeping the trophy and win-condition suffix in regular text.
- Hardened the final two-column summary wrapping so each cell wraps independently and continuation lines preserve the row-label indentation.
- Added regression coverage for ANSI title emphasis and long wrapped cause rows.

### v0.12.1

- Added the UTF-8 trophy directly to the winning contestant's column in the final **DEATHMATCH RESULT** table.
- Added the resolved win condition beside the trophy: `🏆 (lived longer)` for longevity mode and `🏆 (died sooner)` for brevity mode.
- Kept draws trophy-free and preserved the existing final winner/draw banner.

### v0.12.0

- Began the 0.12.x architecture/test hardening series without changing mortality datasets or simulation semantics.
- Kept `VERSION` as the central version constant near the top of `mortality_roulette.py` and added conventional `__version__` aliasing.
- Added `-v` / `--version`; both print `Mortality Roulette v0.12.0` and exit before startup/data preflight.
- Extracted dependency-free terminal formatting primitives into `mortality_roulette_core/terminal.py` while preserving the existing public CLI and output behavior.
- Added a bundled `unittest` regression suite covering version reporting, terminal formatting, Canadian province assignment, hazard-space boozehound mortality math, and Deathmatch RNG reproducibility/independence.

### v0.11.31

- Standardized the canonical terminal separator on a terminal-width solid `─` rule.
- Added the solid rule above and below the live Deathmatch mode header so preflight output and roulette output have a clear boundary.
- Updated the startup banner to use the same solid rule instead of ASCII hyphens.

### v0.11.30

- Added Canadian province selection with `--ca-province`.
- Added province-specific Statistics Canada annual mortality and monthly timing backends where the existing exact-age table supports them.
- Kept Canadian cause-of-death roulette national rather than pretending WHO cause data are province-conditioned.
- Added a post-match side-by-side **DEATHMATCH RESULT** sports-card summary with fatal age, fatal `qx`, roll, broad/detailed cause, death month, alcohol exposure, pure ethanol, wine/vodka bottle equivalents and modeled survival.
- Replaced the Deathmatch `-+-` divider with UTF-8 box drawing (`─`, `│`, `┼`).
- Added a terminal-width startup banner driven by the central `VERSION` constant.
- Git-ready bundles now ship the main program as `mortality_roulette.py` plus this README and the ICD title data file.

### v0.11.29

- Added same-country Deathmatch and automatic two-player expansion when only one country is supplied.

### v0.11.28

- Added `--deathmatch-win long|short`; longevity is the default.

### v0.11.27

- Changed Deathmatch mortality rolls to independent per-player RNG streams instead of a shared annual roll.

### v0.11.26

- Added bold/blinking live `TAPPED OUT` announcements and bold final match results on supported terminals.

### v0.11.24-v0.11.25

- Added two-column Deathmatch mode and universal flag + uppercase country labels.

### v0.11.21-v0.11.23

- Added hazard-scale alcohol RR math, cumulative survival accounting, BOOZEHOUND-WINO, beverage-equivalent reporting, country flags, network retry handling and corrected bundled WHO ICD terminology.

### Earlier v0.11.x

- Added Canadian Statistics Canada/WHO support, detailed Finnish cause trees, WHO deep ICD refinement, monthly seasonality, cohort mode and batch simulation.

---

## Roadmap

### Smoking and combined exposure

Smoking is planned as an independent first-class lifestyle exposure using the `🚬` indicator. Contestants should eventually support at least these states independently per player:

- neither exposure
- `🍷` alcohol only
- `🚬` smoking only
- `🍷 + 🚬` alcohol + smoking
- former smoker, with explicit start/stop ages and time since cessation

The smoking model should track intensity and accumulated exposure (for example cigarettes/day and pack-years), plus cessation-related risk decay where evidence supports it. Combined alcohol + smoking must use cause-specific interaction terms where epidemiological evidence supports synergy, especially upper aerodigestive cancers; the simulator must not blindly multiply one global alcohol RR by one global smoking RR. Single-exposure modes remain available for clean A/B comparisons.

---

## Sources

Primary statistical/data sources:

- [Statistics Finland](https://stat.fi/) — Finnish life tables, causes of death and seasonal timing. Bundled StatFin open-data snapshots are attributed to Statistics Finland and distributed under CC BY 4.0.
- [Statistics Canada 13-10-0837-01](https://www150.statcan.gc.ca/n1/en/catalogue/1310083701) — complete single-year life tables for Canada and supported provinces.
- [Statistics Canada 13-10-0708-01](https://www150.statcan.gc.ca/n1/en/catalogue/1310070801) — deaths by month and place of residence. Bundled Statistics Canada snapshots are redistributed under the Statistics Canada Open Licence with source attribution.
- [WHO Mortality Database](https://www.who.int/data/data-collection-tools/who-mortality-database) — Canadian civil-registration cause-of-death data and Finnish deep-detail support where available.
- WHO ICD-10 2019 terminology — code-title presentation metadata. WHO retains copyright/licensing control over ICD-10; this material is not represented as Statistics Finland/Statistics Canada open data.
- [Human Mortality Database](https://www.mortality.org/) — optional Finnish historical cohort life-table input.

See `datasets/README.md` and `datasets/manifest.json` for the bundled-file provenance map.

Alcohol-risk calibration and disease-specific scenario references are documented next to the relevant constants/functions in `mortality_roulette.py`.

---

## Credits

Project / code / design: **[FlyingFathead](https://github.com/FlyingFathead)**
With special thanks to **ChaosWhisperer** for development and research assistance.

Mortality Roulette was inspired in part by the work of Sheldon Solomon and colleagues on [terror management theory](https://en.wikipedia.org/wiki/Terror_management_theory): the curious predicament of an animal intelligent enough to understand that it is going to die, and inventive enough to spend much of its life trying not to think about that.

_Memento mori_