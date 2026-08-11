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

### Historical birth cohorts (optional HMD)

`--birth-year YEAR` can follow the mortality conditions that applied as a simulated person aged through calendar time rather than applying one modern period table to the whole life. For a person born in 1947, age 0 uses 1947 qx, age 1 uses 1948 qx, and so on.

Mortality Roulette can read **Human Mortality Database (HMD)** 1x1 period life tables directly from locally downloaded country ZIPs. HMD is optional: the normal present-day game does not need it. For **national historical birth-cohort runs**, an installed HMD archive is preferred automatically for its long historical coverage. If a bundled canonical national source contains a newer observed year than the installed HMD archive, Mortality Roulette appends that newer observed year rather than discarding it or silently treating an older HMD year as current. If HMD is not installed, Canada falls back to its bundled Statistics Canada history and Finland can use the open Statistics Finland 12ap history (cached/downloaded on demand for pre-2024 cohort years). Province-specific Canadian runs continue to use province-specific Statistics Canada mortality rather than substituting national HMD data.

After registering/logging in at the [Human Mortality Database](https://www.mortality.org/), download the desired country archive from the relevant HMD country page:

- [Finland (FIN)](https://www.mortality.org/Country/Country?cntr=FIN)
- [Canada (CAN)](https://www.mortality.org/Country/Country?cntr=CAN)
- [United States (USA)](https://www.mortality.org/Country/Country?cntr=USA)

Place the downloaded archive under the Git-ignored local data directory:

```text
local-data/hmd/FIN.zip
local-data/hmd/CAN.zip
local-data/hmd/USA.zip   # parser-ready for future U.S. geography support
```

The program reads only the HMD-created `STATS/*ltper_1x1.txt` period life tables required for qx. It does **not** consume HMD `InputDB` material. Complete HMD country downloads are deliberately not bundled in Mortality Roulette releases; users obtain their own current copy from HMD. `local-data/` is optional and is not created merely by launching the base program. When HMD is actually used, the historical run/printout identifies the HMD country source page; there is no HMD nag in ordinary present-day startup.

`--hmd-dir PATH` can override the default location and accepts a directory containing country ZIPs, an extracted HMD country tree, or a direct country ZIP path for a single-country run.

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

The preferred scalable contestant syntax is repeatable `--player`. Each player carries its own country, optional Canadian province, sex, and optional birth year:

```bash
python mortality_roulette.py --player ca:on:m --player fi:f
```

Compact player format:

```text
fi:m          Finland, male
fi:f          Finland, female
fi:r          Finland, random sex
fi:m:1947     Finland, male, born 1947
ca:m          national Canada, male
ca:m:1980     national Canada, male, born 1980
ca:on:m       Ontario, male
ca:on:f:1962  Ontario, female, born 1962
ca:bc:f       British Columbia, female
```

`--player` must currently be supplied exactly twice. `:r` is resolved independently for each player using its own deterministic RNG stream when `--seed` is supplied. Province and sex are part of the player spec, so `--ca-province` and `--sex/--gender` are intentionally rejected when `--player` is used. This compact contestant object is the foundation for adding further per-player exposures later without proliferating parallel `--foo-1` / `--foo-2` switches.

Birth years can be embedded per player or supplied as a match-level convenience override:

```bash
# Per-player years
python mortality_roulette.py --player fi:m:1979 --player fi:f:1985 --mortality-model official

# Override both embedded/player years left-to-right
python mortality_roulette.py --player fi:m --player fi:f --birth-years 1979 1985 --mortality-model official

# One value applies to both contestants
python mortality_roulette.py --deathmatch fi ca --sex m --birth-years 1947 --mortality-model official
```

When **both** birth years are known, Deathmatch defaults to a shared **calendar timeline**. The earlier-born contestant starts first; the later-born column displays `WAITING TO BE BORN...` until its birth year arrives, after which both lives advance through the same calendar years. In this mode the `long` winner is the contestant who dies in the later calendar year (the last one alive), not necessarily the contestant with the greater lifespan in years.

Use `--deathmatch-timeline independent` for the alternative age-for-age comparison. Both players then start at age 0 immediately, but each column advances through its own calendar years (for example age 40 may mean 2019 for a 1979-born player and 2025 for a 1985-born player). `--deathmatch-timeline calendar` forces the shared-world form and requires birth years for both contestants. With no birth years, Deathmatch behaves exactly as the ordinary present-day mode always has.

Historical layers are calendar-gated independently. Annual mortality uses the player's year-specific cohort source. Cause/detail/seasonality data are used only when the death calendar year falls within that source's historical coverage; pre-coverage deaths remain explicitly `N/A`/unavailable rather than borrowing later distributions. Years after the newest observation retain the existing explicitly labelled future-hold behavior. This prevents anachronisms such as assigning a modern cause distribution to a death that occurred before that cause/data classification existed.

Deathmatch presentation identifies the two sides consistently before their geography, for example `PLAYER 1: 🇨🇦 CANADA (ONTARIO)` and `PLAYER 2: 🇫🇮 FINLAND`. The final two-column card now uses explicit semantic subsections when applicable: `🚗 CRASH CONTEXT` for downstream traffic impairment/intoxication context, `💊 SUBSTANCES` for poisoning-agent context, and `🍸 ALCOHOL` for the configured lifetime exposure. Cumulative beverage conversions are labeled `🍷 WINE EQUIV.` and `🥃 VODKA EQUIV.` to make clear that they are descriptive equivalents of the same ethanol total, not additional consumption.

The older `--deathmatch` interface remains backward-compatible and keeps its historical shared-sex semantics while using the same `PLAYER 1` / `PLAYER 2` presentation.

Two countries with the legacy interface:

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

Finnish detailed-cause data use the vendored `datasets/finland/causes/statfin_cause_detail_2024.json` as an immutable read-only seed. If a legitimate StatFin detail cell is missing and must be fetched lazily, the new cell is written to `~/.cache/mortality_roulette/statfin_finland_cause_detail.json` (or an explicit `--detail-cache`) rather than modifying the tracked bundled dataset.

`v0.13.8` adds a sparse **CAUSE NOTE** annotation layer backed by `datasets/cause_notes/cause_note_model_v1.json`. Notes are deterministic explanatory metadata applied only after an underlying cause has already been resolved; they do not consume RNG or alter mortality, cause, detail, PLACE, seasonality, substance or crash-context probabilities. The initial rule covers Finnish `M17` gonarthrosis from StatFin 11be, where the public table records the underlying cause but not the complete death-certificate chain of immediate/intervening causes. The table is intentionally extensible so similarly non-obvious underlying-cause results can receive precise notes later without hard-coding prose into the roulette engine.

If the resolved underlying cause is suicide (`X60-X84` / `Y87.0`), the simulator adds one further **STATISTICAL REASON** roll. Finland and Canada use separate sex/age evidence models; unsupported future countries fall back to an explicitly labelled Finnish-Canadian reference distribution. This is a probabilistic context model, not an assertion of an individual's proven motive.

`v0.13.2` added two narrow conditional detail rolls where published evidence supports them: `X80` (intentional self-harm by jumping from a high place) receives a broad statistically weighted site type, and `X41` accidental psychotropic/antiepileptic poisoning can receive a broad evidence-weighted drug class. In v0.13.7 poisoning output is normalized under a dedicated **💊 SUBSTANCES** section: `X40`, `X42`, and `X43` expose the broad agent category already encoded by ICD; `X41` retains its existing evidence-weighted class roll; and `X44` explicitly represents other/unspecified or multidrug poisoning context instead of leaving the agent field blank. No doses or molecule-level lethality ranking are modeled.

`v0.13.7` also adds an independent **🚗 CRASH CONTEXT** roll after a resolved road-traffic death. The model deliberately distinguishes *who the statistic describes*. For Finland, OTI 2015–2024 investigation-board data provide deceased-person intoxication distributions for pedestrians and cyclists; motorcyclist and other motor-vehicle deaths use a crash-level at-fault-driver impairment reference and explicitly state that this does **not** establish that the simulated decedent was the impaired driver. For Canada, Transport Canada's 2022 fatal-collision contributing-factor statistic is used as a broad crash-level reference and likewise does not assign impairment to the decedent. Unknown/unavailable Finnish statuses are retained as explicit outcomes rather than silently treated as sober. Statistics Finland table 11b2 confirms that death-certificate alcohol/drug intoxication is available by external cause, age, sex and year; those exact cross-tabs are a future refinement and are not reverse-engineered from marginal age/sex percentages here. The traffic roll has its own RNG stream and cannot change mortality, cause, detail, SUBSTANCES, PLACE, or seasonal outcomes.

`v0.13.8` tightens that boundary for railway and explicitly nontraffic transport deaths. A realized railway-train/vehicle detail is no longer fed into the generic road-setting distribution: ICD wording resolves `Railway tracks / premises` for nontraffic events, `Railway crossing / public road` for traffic events, and `Railway tracks / crossing` when traffic status is unspecified. Railway collisions and exact nontraffic V-codes also skip the generic road/fatal-motor-vehicle impairment roll because the bundled impairment sources do not provide a defensible rail-event denominator.

`v0.13.3` generalizes the existing X80 location machinery into a public **PLACE** layer without replacing the older evidence. PLACE is a separate downstream RNG stream and is emitted only when a matching country/cause model exists. Bundled coverage now includes Finnish and Canadian drowning settings, Finnish sex-specific homicide scenes, Finnish and Canadian fatal-road settings, Finnish and Canadian cancer place of death, and Finnish neurodegenerative place of death. Explicit ICD environment information constrains the roll first: for example, bathtub/pool drowning codes resolve that setting directly, while natural-water codes restrict the subsequent statistical PLACE roll to compatible water categories. Existing X80 probabilities and its independent RNG stream are preserved exactly and now render through the same PLACE presentation. Unsupported cause/country combinations remain blank rather than receiving invented scenery. See `datasets/README.md` for exact source populations, derived residuals, caveats and provenance.

`v0.13.5` extends PLACE to selected fatal poisoning and fire contexts. Finnish drug-poisoning PLACE is age-limited to 15–29 because the bundled THL forensic study covers under-30 deaths; Canada uses sex/life-stage national accidental acute-toxicity event-place data. Fire PLACE is likewise source-specific: Finnish building-fire detail is used only when ICD has already resolved a building/structure fire (`X00`/`X01`), while Canada has a broader national unintentional-fire residence/property distribution. No missing or suppressed category is silently reconstructed. In v0.13.7 compact output separates `🚗 CRASH CONTEXT`, `💊 SUBSTANCES`, `📍 PLACE`, and `🍸 ALCOHOL` into distinct semantic blocks.

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

`v0.13.4` clarifies that the printed g/day exposure is an **ongoing modeled / annualized habitual exposure**, not a literal day-by-day drinking schedule. It also fixes explanatory ICD context for Finnish StatFin alcohol rows such as `F10`: public StatFin mortality tables publish the underlying cause at 3-character level, so the simulator does not invent an `F10.x` probability roll, but it can display the legitimate WHO clinical-state children and Finnish ICD-10 withdrawal/delirium refinements (including seizure-status subcodes) as non-probabilistic taxonomy. Statistics Finland documents that its source register is coded at the most accurate ICD-10 level even though public underlying-cause statistics are published at 3 characters; exact `F10.x` mortality weights therefore remain a data-access task rather than a classification gap.

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
--birth-year 1980           # single run; in Deathmatch one shared year for both
--birth-years 1979 1985     # Deathmatch per-player override; one value = both
--deathmatch-timeline auto|calendar|independent
--hmd-dir PATH              # optional local HMD ZIP directory/tree/archive
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
- [Human Mortality Database (HMD)](https://www.mortality.org/) — optional local historical 1x1 period-life-table input for national birth-cohort simulation. Mortality Roulette supports HMD country ZIP imports without bundling complete HMD downloads. Current country pages: [Finland](https://www.mortality.org/Country/Country?cntr=FIN), [Canada](https://www.mortality.org/Country/Country?cntr=CAN), and parser-ready [United States](https://www.mortality.org/Country/Country?cntr=USA). HMD-created estimates are CC BY 4.0; separately supplied input data retain their providers' distribution licences.
- Suicide statistical-reason evidence: Finnish nationwide psychological-autopsy studies (Heikkinen and colleagues) plus Canadian coroner/medical-examiner studies from Alberta and Montréal; exact references and model provenance are in `datasets/README.md`.
- Conditional external-cause context evidence: Toronto/Swiss/Taipei jumping-site studies for `X80`; Finnish poisoning studies plus Public Health Agency of Canada coroner/medical-examiner toxicology data for `X41`; WHO ICD-10 multidrug-poisoning coding semantics plus PHAC accidental acute-toxicity substance-count data for the explicitly labelled Canadian `X44` context reference; OTI fatal-road investigation data for Finnish traffic intoxication/impairment context; and Transport Canada fatal-collision contributing-factor data for the Canadian traffic reference. Exact references and modeling limitations are in `datasets/README.md`.

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