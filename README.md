# Mortality Roulette

**Mortality Roulette** (Finnish: *Kuolleisuusruletti*) is an educational and entertainment statistical simulation of human mortality, built around real population-level life-table and cause-of-death data.

It rolls a simulated life year by year using age-, sex-, country- and model-specific mortality probabilities and, when death occurs, can continue into cause of death, detailed cause trees and seasonal timing.

⚠ **This is a statistical concept project, not an individualized medical prognosis or healthcare decision tool. This project presents mortality probabilities and causes of death directly and may be unsettling to some readers.**

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

For added morbid education about how sustained lifestyle hazards can modify an already-unfriendly mortality baseline, load up Finland and Canada with the Boozehound/Wino scenario and let the cause-hazard model do its thing.

Quick fun run example:

```bash
python mortality_roulette.py \
  --deathmatch fi ca \
  --sex m \
  --mortality-model official \
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

If the resolved underlying cause is suicide (`X60-X84` / `Y87.0`), the simulator adds one further **STATISTICAL REASON** roll. Finland and Canada use separate sex/age evidence models; unsupported future countries fall back to an explicitly labelled Finnish-Canadian reference distribution. This is a probabilistic context model, not an assertion of an individual's proven motive.

`v0.13.2` also adds two narrow conditional detail rolls where published evidence supports them: `X80` (intentional self-harm by jumping from a high place) can receive a broad **LOCATION TYPE**, and `X41` accidental psychotropic/antiepileptic poisoning can receive a broad **DRUG CLASS**. These are source-weighted category rolls only: no heights, named hotspots, doses or molecule-level lethality ranking are modeled. See `datasets/README.md` for methodology and provenance.

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

Release history is maintained in **[CHANGELOG.md](CHANGELOG.md)**.

## Roadmap

### Smoking and combined exposure

Smoking is planned as an independent first-class lifestyle exposure using the `🚬` indicator, given its substantial impact on long-term morbidity and mortality trajectories. Contestants should eventually support at least these states independently per player:

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
- Suicide statistical-reason evidence: Finnish nationwide psychological-autopsy studies (Heikkinen and colleagues) plus Canadian coroner/medical-examiner studies from Alberta and Montréal; exact references and model provenance are in `datasets/README.md`.
- Conditional external-cause context evidence: Toronto/Swiss/Taipei jumping-site studies for `X80`, and Finnish poisoning studies plus Public Health Agency of Canada coroner/medical-examiner toxicology data for `X41`; exact references and modeling limitations are in `datasets/README.md`.

See `datasets/README.md` and `datasets/manifest.json` for the bundled-file provenance map.

Alcohol-risk calibration and disease-specific scenario references are documented next to the relevant constants/functions in `mortality_roulette.py`.

---

## License

No software license has been granted for Mortality Roulette at this time. If you are interested in the project, collaboration, or licensing, please contact **[FlyingFathead](https://github.com/FlyingFathead)**.

Third-party datasets remain subject to their respective source licences and terms. See `datasets/README.md` and `datasets/manifest.json` for details.

---

## Credits

Project / code / design: **[FlyingFathead](https://github.com/FlyingFathead)**
With special thanks to **ChaosWhisperer** for development and research assistance.

Mortality Roulette was inspired in part by the work of Sheldon Solomon and colleagues on [terror management theory](https://en.wikipedia.org/wiki/Terror_management_theory): the curious predicament of an animal intelligent enough to understand that it is going to die, and inventive enough to spend much of its life trying not to think about that.

_Memento mori_