# Changelog

## v0.13.7

- Normalized Deathmatch contestant labels to put player identity first: `PLAYER 1: 🇨🇦 CANADA (ONTARIO)` instead of `🇨🇦 CANADA (ONTARIO) (PLAYER 1)`.
- Legacy `--deathmatch` and the newer repeatable `--player` interface now both identify the two sides consistently as `PLAYER 1` and `PLAYER 2`, including mixed-country and batch output.
- Refined the two-column Deathmatch result card with a `🍸 ALCOHOL` subsection divider and explicit `🍷 WINE EQUIV.` / `🥃 VODKA EQUIV.` labels so beverage quantities cannot be mistaken for additional consumption.
- Generalized poisoning detail into a dedicated `💊 SUBSTANCES` section above ALCOHOL. Existing `X41` class rolls retain their RNG stream; `X40`, `X42`, and `X43` expose their ICD-resolved broad agent category, while `X44` now receives conservative multidrug/unspecified context instead of silently omitting substance information.
- Added a separate downstream X44 RNG stream. Canada uses PHAC's published accidental acute-toxicity substance-count distribution as an explicitly labelled reference (29% one causal substance, 7% unknown count, 64% two-or-more at published whole-percent resolution); unsupported countries fall back only to WHO ICD-10 X44 semantics, with no invented exact drug combination.
- Added regression coverage for Ontario/Finland identity-first labels and legacy mixed-country Deathmatch presentation.
- Fixed poisoning/substance ICD detection so endpoints mentioned only inside broad cause ranges (for example `V01-X44`) cannot masquerade as a realized `X44` poisoning death; added the observed Finnish motorcycle-crash case as a regression.
- Added a separate downstream `🚗 CRASH CONTEXT` section for resolved road-traffic deaths. Finland uses OTI 2015–2024 investigation-board data: decedent-specific intoxication distributions for pedestrians/cyclists and a separately labelled crash-level at-fault-driver impairment distribution for motor-vehicle deaths, retaining unknown-status cases. Canada uses Transport Canada's 2022 `Impaired / Under the Influence` fatal-collision contributing-factor share as an explicitly labelled crash-level/subset-estimated reference.
- Added an independent traffic-context RNG stream (`0x54524649`) plus CSV provenance fields. Traffic context cannot perturb mortality, cause, detail, substance, PLACE or seasonality rolls. Broad transport ranges alone do not trigger the model; a resolved road-user detail is required. OTI age/sex marginals among impaired drivers are documented but deliberately not converted into unsupported `P(impaired | age, sex)` cells; Statistics Finland 11b2 is documented as the future exact age/sex/year cross-tab route.

## v0.13.6

- Added repeatable compact `--player COUNTRY[:PROVINCE]:SEX` Deathmatch contestant specs, e.g. `--player ca:on:m --player fi:f`. Players can now independently select sex and geography; Canadian province is embedded in the relevant player spec.
- Added independent seeded sex RNG streams for `--player ...:r`, including batch mode. Legacy `--deathmatch ... --sex ...` remains backward-compatible and preserves its historical shared-sex behavior.
- Retained the legitimate three additional StatFin male age-70–74 detailed-cause distributions already present in the v0.13.5 bundled JSON and refreshed its manifest size/SHA-256 metadata instead of deleting data.
- Fixed the StatFin detailed-cause cache architecture: the bundled dataset is now an immutable read-only seed and newly fetched detail cells are written only to the user/runtime cache. Added a hard guard against writing a runtime cache directly over the bundled seed.
- Added player-spec, independent-random-sex, cache-isolation, CLI, manifest and regression coverage.

## v0.13.5

- Expanded the evidence-backed **PLACE** layer with fatal drug/substance-poisoning settings. Finland uses THL forensic death-investigation counts for ages 15–29 and does not extrapolate them to older ages; the Finnish source pools manner of death and is labelled accordingly. Canada uses PHAC national coroner/medical-examiner accidental acute-toxicity distributions by sex and life stage.
- Added fire-death PLACE models. Finnish `X00`/`X01` building/structure-fire deaths use pooled 2007–2010 Pelastusopisto building-type counts; other Finnish fire codes remain blank rather than being forced into a building model. Canadian `X00–X09` unintentional fire deaths use the national 2011–2020 CCMED residence/property share with an explicit residual other setting.
- Extended PLACE model resolution to age-conditioned profiles without changing existing context distributions or RNG streams. Published gaps remain gaps: Canadian female accidental acute-toxicity deaths at age 60+ are intentionally not modeled because one event-place category is suppressed in the source table.
- Grouped compact context presentation with `💊 DRUG CLASS` / indented drug metadata and `📍 PLACE` / indented place probability, roll and model metadata. Full result cards use the same semantic emoji headings and print drug class before PLACE when both exist.
- Preserved existing X80 suicide-location probabilities/RNG, drowning constraints, homicide, road, cancer and neurodegenerative PLACE behavior; added regression coverage for age boundaries, intent boundaries, fire building constraints and the grouped rendering.

## v0.13.4

- Fixed the explanatory ICD subtype context so StatFin 11bx labels that place the code at the end, such as `Mental and behavioural disorders due to use of alcohol (F10)`, are recognized. Broad ICD ranges remain rejected as resolved leaf codes.
- For unresolved Finnish `F10` deaths, the final card now exposes the legitimate WHO fourth-character clinical-state taxonomy and selected Finnish fifth-character withdrawal/delirium refinements (including seizure status) as **classification context only**. No subtype is randomly selected because public StatFin mortality tables publish underlying causes only at the 3-character level.
- Clarified the boozehound exposure summary from `continuous exposure` to `ongoing modeled exposure`, reflecting that the configured g/day value is an annualized/habitual exposure intensity rather than a day-by-day consumption schedule.
- Added regression tests for parenthetical `F10`, range rejection, Finnish withdrawal taxonomy output, and version reporting.

## v0.13.3

- Generalized the existing X80 location feature into a reusable downstream **PLACE** layer while preserving all existing X80 source weights, fallbacks and RNG behavior. Deathmatch now presents X80 through `PLACE` / `PLACE MODEL`.
- Added independent country/cause-conditioned PLACE rolls for Finnish/Canadian drowning, Finnish homicide, Finnish/Canadian road traffic, Finnish/Canadian cancer terminal setting, and Finnish neurodegenerative terminal setting. Unsupported country/cause combinations remain blank instead of receiving a borrowed generic location.
- Added ICD-aware drowning constraints: bathtub/pool codes resolve directly, while natural/open-water codes restrict and renormalize the national water-setting distribution to compatible categories. Broad transport parents cannot masquerade as road traffic.
- Fixed PLACE trigger matching so ICD range endpoints embedded in broad parent labels (for example `V01-Y89`) are never treated as resolved event codes; this prevents non-traffic external causes such as `X70` suicide from spuriously receiving a road-collision PLACE.
- Added a separate generalized PLACE RNG stream plus regular-run CSV fields (`place`, probability, roll, model, semantic and context id). Existing X80 keeps its original independent RNG stream, so old seeded X80 outcomes do not move.
- Renamed the Finnish suicide 20% residual from `No specific precipitating context resolved` to `No specific recent life event reported` and documented that it is a national residual from ~80% reported recent-life-event coverage, not an age/sex-specific observation and not a claim of “no reason.”
- Added bundled PLACE evidence/provenance data, regression coverage, README/dataset methodology documentation and refreshed manifest metadata.

## v0.13.2

- Added an `X80` conditional **LOCATION TYPE** roll using broad, non-actionable site categories. Canada uses a Toronto-derived building/bridge split with peer-reviewed building-subtype evidence; Finland and unsupported countries use an explicitly labelled international reference where native site data are unavailable.
- Added an `X41` conditional **DRUG CLASS** roll. Finland uses Finnish fatal-poisoning primary-agent evidence; Canada uses sex-specific national coroner/medical-examiner substance-class evidence. The model does not include doses or molecule-level lethality rankings.
- Added independent RNG streams for both context rolls so they do not perturb mortality, cause, detail, suicide-reason or seasonal timing rolls.
- Added regular-run CSV fields and Deathmatch `LOCATION` / `LOCATION MODEL` and `DRUG CLASS` / `DRUG MODEL` rows.
- Added source/provenance documentation in the README and bundled dataset documentation, plus regression coverage and manifest integrity for the new model file.

## v0.13.1

- Refreshed stale size/checksum metadata for the already-bundled Finnish detailed-cause dataset; dataset content itself is unchanged by this release.

- Added a conditional **STATISTICAL REASON** roll after a resolved suicide cause (`X60-X84` / `Y87.0`). It is a separate RNG stream and does not alter mortality, cause, detail or seasonality rolls.
- Added bundled Finland and Canada sex-by-age evidence models plus an explicit equal-weight **Finnish-Canadian reference** fallback for future unsupported countries/cells.
- Added regular-run CSV fields and Deathmatch `REASON` / `REASON MODEL` rows with model provenance.
- Added `datasets/suicide/suicide_reason_model_v1.json`, model/trigger regression tests, and dataset provenance documentation.
- Moved release history out of the README into this file.

### v0.13.0

- First stable public release of Mortality Roulette.
- Promotes the tested `v0.13.0-dev16` codebase to stable release status.

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
