# Bundled datasets

This directory contains versioned statistical/reference snapshots used by Mortality Roulette so the default simulation does not need to hit external services at runtime. Refresh/download code remains available in the main program.

## Runtime policy

Bundled vetted snapshots are preferred when they cover the requested default geography. Explicit cache-path arguments override them. `--refresh-*` keeps the existing network/download/parser path and writes to the normal external cache unless a custom cache path is supplied.

## Sources and licensing

### Statistics Finland

- Life table: StatFin **12ap — Life table by age and sex, 1986–2024**
  - https://pxdata.stat.fi/PXWeb/pxweb/en/StatFin/StatFin__kuol/12ap.px
  - Bundled 2024 qx values are verified against the official downloadable table output. Exact one-year qx ends at age 99; the age-100 row is terminal/open and has no q100. The source reports age-100 remaining life expectancy separately (male 1.85 y, female 1.80 y).
- Broad causes: StatFin **11az — Causes of death**
  - https://pxdata.stat.fi/PXWeb/pxweb/en/StatFin/StatFin__ksyyt/11az.px
- Monthly cause timing: StatFin **11bf**
  - https://pxdata.stat.fi/PXWeb/pxweb/en/StatFin/StatFin__ksyyt/11bf.px
- Detailed cause caches are derived from the project's existing StatFin 11be / 11b2 / 11bx download paths.
- The bundled `statfin_cause_detail_2024.json` is a read-only release snapshot. Runtime/lazy StatFin detail fetches overlay it from `~/.cache/mortality_roulette/statfin_finland_cause_detail.json` (or an explicit `--detail-cache`) and must never rewrite the vendored dataset. The v0.13.6 manifest intentionally records the 374,077-byte snapshot that includes the legitimate male age-70–74 dementia/nervous-system detail cells added during v0.13.5 development.

Statistics Finland open statistical data are redistributed with source attribution under **CC BY 4.0**.

### Statistics Canada

- Complete life table: **13-10-0837-01**
  - https://www150.statcan.gc.ca/n1/en/catalogue/1310083701
- Monthly deaths: **13-10-0708-01**
  - https://www150.statcan.gc.ca/n1/en/catalogue/1310070801

Statistics Canada snapshots are redistributed with source attribution under the **Statistics Canada Open Licence**. The existing CSV download/parser path remains available for refreshes and for supported provinces not bundled here.

### Human Mortality Database (optional local historical source)

Mortality Roulette supports locally supplied **Human Mortality Database (HMD)** country archives for long-run national historical mortality. These files are optional and are **not bundled datasets**: standard present-day Mortality Roulette works without them.

Default local layout:

```text
local-data/hmd/FIN.zip
local-data/hmd/CAN.zip
local-data/hmd/USA.zip
```

`local-data/` is Git-ignored and excluded from release packages. The HMD reader opens country ZIPs directly and reads only the HMD-created sex-specific 1x1 **period life tables** under `STATS/` (`mltper_1x1.txt` / `fltper_1x1.txt`). It intentionally ignores `InputDB/` and other archive members. Extracted HMD country trees remain supported for backward compatibility.

Historical birth-cohort mortality is obtained by walking the diagonal through period tables: calendar year = birth year + exact age. HMD cohort-table files are therefore not required, and the same method can be applied consistently to countries whose HMD download does not publish a completed cohort life table. For national historical runs, local HMD period tables are preferred when present for their long historical coverage; Statistics Canada’s bundled national history and Statistics Finland’s open cached/downloaded 12ap history are fallbacks when HMD is absent. If a bundled canonical national table contains observed years newer than the installed HMD archive, those newer years may extend the HMD-backed trajectory and are labelled in the source description rather than being discarded. Province-specific Canadian mortality remains Statistics Canada-based because HMD Canada is a national series. Years after the newest observed table still retain the existing explicitly labelled future-hold behavior; no future improvement trend is invented.

Deathmatch can assign a separate birth year to each contestant. When both are known, the default shared-calendar timeline starts with the earlier cohort and holds the later cohort at `WAITING TO BE BORN...` until its birth year; `--deathmatch-timeline independent` instead compares the same attained ages on each cohort's own calendar. Mortality, cause, detail and seasonality layers are resolved against each contestant's actual calendar year. A layer with no historical coverage for the realized death year is reported unavailable rather than backfilled from a later table; future years may use only the explicitly labelled latest-year hold already defined for that layer.

HMD licensing/provenance boundary (checked 2026-08-11):

- HMD states that data constructed by the HMD team, including exposure estimates, death rates and life tables, are published under **CC BY 4.0**.
- Input data supplied to HMD remain under each original provider's distribution licence.
- HMD asks users to acknowledge HMD as source/intermediary, note the download/access date, and preferably direct other users to HMD for their own current copy rather than passing around archive copies. Users publishing results should record the date on which their local HMD archive was downloaded/accessed.
- Mortality Roulette therefore does not redistribute complete HMD country archives. Any Mortality Roulette model or result derived from HMD statistical estimates must identify HMD as a source; this policy does not imply that the HMD-created CC BY 4.0 estimates themselves are proprietary.

HMD citation guidance requests the full database name, institutional sponsors, mortality.org, and access/download date. A practical citation form is: **Human Mortality Database (HMD), Max Planck Institute for Demographic Research, University of California, Berkeley, and French Institute for Demographic Studies; mortality.org; data accessed/downloaded [date].** Country-specific source metadata should also be consulted when deriving or publishing results.

Links:

- HMD: https://www.mortality.org/
- User Agreement: https://www.mortality.org/Data/UserAgreement
- Citation Guidelines: https://www.mortality.org/Research/CitationGuidelines
- Finland: https://www.mortality.org/Country/Country?cntr=FIN
- Canada: https://www.mortality.org/Country/Country?cntr=CAN
- United States: https://www.mortality.org/Country/Country?cntr=USA

### WHO ICD-10 terminology

- WHO ICD-10, Sixth Edition, 2019
  - https://icd.who.int/browse10/2019/en

WHO remains the copyright holder. The 2019 ICD-10 publication is distributed under **CC BY-ND 3.0 IGO**. The bundled file is terminology/reference material; codes and titles must not be represented as modified WHO terminology.

## Machine-readable provenance

`manifest.json` records the repository path, source agency/table, reference year/range, source URL, licence/attribution note, byte size, and SHA-256 for each bundled file.

### Suicide statistical-reason context model

- `datasets/suicide/suicide_reason_model_v1.json`
- Purpose: after the existing cause stack has already resolved a suicide (`X60-X84` / `Y87.0`), draw one additional age/sex-conditioned **statistical reason / precipitating context**.
- Finland uses the nationwide Finnish psychological-autopsy literature (Heikkinen and colleagues) as its country evidence base.
- Canada uses Canadian coroner/medical-examiner evidence, especially Quan & Arboleda-Flórez's Alberta age-55+ study and Houle et al.'s Montréal coroner profile.
- The Finnish and some younger Canadian source variables are overlapping circumstances rather than mutually exclusive motives. Those cells are therefore converted to relative evidence weights and normalized for one display roll. The JSON records the provenance and modelling status of each cell.
- Finland-specific residual semantics: Heikkinen et al. reported a recent life event in 80% of the nationwide suicide sample. The model therefore retains 20% as a national **no specific recent life event reported** residual. That residual is repeated across Finnish age/sex profiles because the source does not provide an age/sex-specific complement; it is not evidence that 20% of each subgroup had "no reason" for suicide.
- `FI_CA_REFERENCE` is an equal 50/50 average of the already-normalized Finnish and Canadian sex/age cells. It is a transparent fallback for future countries without native context data, not a claim that Finnish/Canadian circumstances describe that country.

Key references:

- Heikkinen M, Aro H, Lönnqvist J. *Recent life events, social support and suicide*. Acta Psychiatr Scand Suppl. 1994;377:65-72. https://doi.org/10.1111/j.1600-0447.1994.tb05805.x
- Heikkinen ME, Isometsä ET, Aro HM, Sarna SJ, Lönnqvist JK. *Age-related variation in recent life events preceding suicide*. J Nerv Ment Dis. 1995;183(5):325-331. https://pubmed.ncbi.nlm.nih.gov/7745388/
- Heikkinen ME, Lönnqvist JK. *Recent Life Events in Elderly Suicide: A Nationwide Study in Finland*. Int Psychogeriatr. 1995. https://pubmed.ncbi.nlm.nih.gov/8829434/
- Quan H, Arboleda-Flórez J. *Elderly Suicide in Alberta: Difference by Gender*. Can J Psychiatry. 1999;44:762-768. https://doi.org/10.1177/070674379904400801
- Houle J et al. *Coroners' records on suicide mortality in Montréal: limitations and implications in suicide prevention strategies*. Chronic Diseases and Injuries in Canada. 2014;34(1). https://www.canada.ca/en/public-health/services/reports-publications/health-promotion-chronic-disease-prevention-canada-research-policy-practice/vol-34-no-1-2014/coroners-records-suicide-mortality-montreal-limitations-implications-suicide-prevention-strategies.html

### Conditional external-cause context model

- `datasets/external_causes/conditional_context_model_v1.json`
- Purpose: add one further broad conditional category only after an already-resolved matching ICD outcome. It never changes mortality or cause selection.
- `X80` location type: Canada uses Toronto coroner evidence for the building-versus-bridge split; building subtypes use Chen, Gunnell & Lu's Taipei site study. Finland currently uses an explicitly labelled international reference because no comparable Finland-native X80 site-type table was found. No height, named hotspot or access information is included.
- `X41` drug class: Finland uses primary-agent counts from a Northern Finland cause-of-death study (antidepressants, neuroleptics, benzodiazepines and antiepileptics), with Statistics Finland national reports as qualitative validation. Canada uses sex-specific class counts from the Public Health Agency of Canada's national coroner/medical-examiner chart review. These are normalized class weights, not dose or molecule-specific lethality estimates.
- `X44` substance context: WHO ICD-10 mortality-coding guidance explicitly uses X44 for multidrug poisonings when drugs from different external-cause categories are reported and none is identified as the most important; X44 also covers other/unspecified drugs, so the code alone does not prove a particular combination. For Canada only, v0.13.7 adds an explicitly labelled PHAC accidental-acute-toxicity reference roll for **number of causal substance types**: 29% one, 7% unknown, and 64% two-or-more at the source's published whole-percent resolution. This is not an X44-specific cross-tab and therefore never invents exact molecules or a joint drug combination. Finland/unsupported countries expose only conservative ICD semantic context for X44.
- Compact/full rendering normalizes X40-X44 poisoning information under `💊 SUBSTANCES`. X40/X42/X43 use their directly encoded broad ICD agent class, X41 preserves the previous independent class roll, and X44 uses the separate downstream context described above. The new X44 stream is independent, so adding this context cannot change mortality, cause, detail, X41, PLACE, or seasonality outcomes.
- `🚗 CRASH CONTEXT` traffic impairment/intoxication: this is a separate downstream context layer and never changes whether a transport death occurs. It requires a resolved road-user detail (`001`/`V01-V09` pedestrian, `002`/`V10-V19` cyclist, `003`/`V20-V39` motorcyclist, or `004`/`V40-V79` motor-vehicle occupant); a broad parent range alone cannot trigger it.
- Finland, pedestrians/cyclists: OTI's national investigation-board review for 2015–2024 gives decedent-specific intoxication status. Cyclists: 160 deaths, 35 intoxicated, 30 with alcohol involved, 108 clear, 17 unknown. Pedestrians: 216 deaths, 48 intoxicated, 39 with alcohol involved, 140 clear, 28 unknown. The residual intoxicated-without-alcohol cells are retained as `other intoxicant(s)`; OTI defines these as illicit drugs and/or medicines that may impair driving.
- Finland, motor vehicles: OTI reports 1,474 fatal motor-vehicle crashes in 2015–2024. The figure records 526 crashes caused by impaired drivers, 890 by clear drivers and 58 with impairment information unavailable. Among the 526 impaired at-fault drivers, 263 had alcohol only, 118 alcohol plus another intoxicant, 139 another intoxicant without alcohol, and 6 could not be classified because of incomplete information. The model keeps all six categories over the full 1,474 denominator; consequently the commonly reported `37%` is the known-status percentage, not a forced all-case probability. This is crash-level context and does not prove the simulated decedent was the impaired driver.
- Statistics Finland table `11b2` independently provides deaths by external cause, age, sex and year with alcohol/drug intoxication recorded as contributing causes on the death certificate. That table establishes a path to finer age/sex/year traffic cells, but v0.13.7 does not fabricate those joint probabilities from OTI's marginal age/sex distribution among impaired drivers.
- Canada: Transport Canada's 2022 collision statistics report `Impaired / Under the Influence` as a contributing factor in 23.0% of fatal collisions. Contributing factors overlap and the published estimate uses a subset of provinces/territories, so the model is explicitly crash-level and subset-estimated. A negative roll is phrased as the factor not being selected in the reference roll, not as proof that every involved person was sober.
- Traffic context uses its own downstream RNG stream (`0x54524649`), preserving existing mortality/cause/detail, X41, X44, PLACE and seasonality streams.
- Future countries/cells fall back only where explicitly declared in the JSON, with provenance retained in output.

Key references:

- Sinyor M et al. *Effect of a barrier at Bloor Street Viaduct on suicide rates in Toronto: natural experiment*. BMJ. 2010. https://pubmed.ncbi.nlm.nih.gov/20605890/
- Reisch T, Schuster U, Michel K. *Suicide by Jumping and Accessibility of Bridges: Results from a National Survey in Switzerland*. Suicide Life Threat Behav. 2007. https://doi.org/10.1521/suli.2007.37.6.681
- Chen YY, Gunnell D, Lu TH. *Descriptive epidemiological study of sites of suicide jumps in Taipei, Taiwan*. Inj Prev. 2009. https://pubmed.ncbi.nlm.nih.gov/19190275/
- Koskela L et al. *Fatal poisonings in Northern Finland: causes, incidence, and rural-urban differences*. Scand J Trauma Resusc Emerg Med. 2017. https://doi.org/10.1186/s13049-017-0431-8
- Statistics Finland. *Causes of death 2020: Accident mortality decreased for women* (accidental poisoning discussion). https://stat.fi/til/ksyyt/2020/ksyyt_2020_2021-12-10_kat_005_en.html
- Public Health Agency of Canada. *Substance-related acute toxicity deaths in Canada from 2016 to 2017: A review of coroner and medical examiner files*. https://www.canada.ca/en/health-canada/services/opioids/data-surveillance-research/substance-related-acute-toxicity-deaths-canada-2016-2017-review-coroner-medical-examiner-files.html
- Onnettomuustietoinstituutti (OTI). *Päihdeonnettomuudet vuosina 2015–2024*. Onnettomuustietoa tiiviisti 3/2026. https://www.lvk.fi/api/v2/document/628668/B20695E1B6A739A4910A9899E901F70CF5044D7D6E20E36ED5EAF4BB5570AE52
- Statistics Finland. *11b2 -- Accidental and violent deaths by underlying cause of death (short list of external causes), age and sex, intoxicated separately, 1998-2024*. https://pxdata.stat.fi/PXWeb/pxweb/en/StatFin/StatFin__ksyyt/11b2.px
- Transport Canada. *Canadian Motor Vehicle Traffic Collision Statistics: 2022*. https://tc.canada.ca/en/road-transportation/statistics-data/canadian-motor-vehicle-traffic-collision-statistics/2022/canadian-motor-vehicle-traffic-collision-statistics-2022

### Cause-conditional PLACE model

- `datasets/places/cause_place_model_v1.json`
- Purpose: extend the existing statistically weighted X80 location feature into one reusable downstream **PLACE** layer. The mortality roll, broad cause, cause detail, suicide context, X80 site roll, X41 drug-class roll and seasonality remain separate and unchanged.
- RNG semantics: generalized PLACE uses its own stream. Existing X80 retains its original `0x5838304C` stream and distribution; X80 is merely rendered through the unified PLACE field. The generalized place stream therefore cannot reshuffle a pre-existing seeded X80 result.
- ICD constraint rule: specific environment information already resolved by ICD wins before statistical refinement. W65/W66 resolve to bathtub and W67/W68 to swimming pool. W69/W70 and watercraft-drowning codes V90/V92 restrict the country model to explicitly compatible natural/open-water categories and renormalize only those categories. Mixed/unspecified residuals are excluded rather than guessed. W73/W74 can use the broader drowning distribution because the code does not already fix a narrower setting.
- Drowning, Finland: Safety Investigation Authority S1/2010Y investigated 228 accidental water-related deaths during 1 Apr 2010–31 Mar 2011: lake 110, sea 51, river 22, pond 14, indoor pool 5, and 26 in smaller water settings/bathtubs. Raw counts are normalized for the broad roll. Natural-water-constrained rolls use only the explicitly compatible lake/sea/river/pond counts.
- Drowning, Canada: the 2024 Canadian Detailed Drowning Report gives the national 2015–2019 distribution lake/pond 35%, river 26%, bathtub 13%, pool 9%, ocean 6%, other 11%. Natural/open-water-constrained rolls use lake/pond, river and ocean only.
- Drug poisoning, Finland (ages 15–29 only): THL's forensic review of 300 under-30 drug-poisoning deaths in 2019–2021 reports event/death settings directly: own residence 124 (41.3%), friend/new acquaintance residence 117 (39.0%), parent/relative residence 17 (5.7%), supported housing/hostel 14 (4.7%), hospital 9 (3.0%), outdoors 5 (1.7%), hotel room 5 (1.7%), other 9 (3.0%). The source pools manner of death (86.7% accidental, 5.0% suicide, 8.3% undetermined), so the model is labelled as a pooled-manner Finnish youth/young-adult distribution and is not extrapolated beyond age 29. The youngest observed decedent was 15.
- Accidental acute toxicity, Canada: PHAC's national 2016–2017 coroner/medical-examiner chart review publishes the place of the fatal acute-toxicity event by sex and life stage (12–24, 25–59, 60+). Those published percentages are used as age/sex PLACE profiles for accidental substance poisoning (`X40–X44`, `X46–X49`, excluding alcohol-only poisoning). Female age 60+ is deliberately left unsupported because the `home of another person` category is suppressed, so a complete mutually exclusive distribution cannot be reconstructed without guessing. The source also publishes terminal place (same location / hospital / other), but v0.13.5 does not add a second marginal terminal-place roll because the joint event-place→terminal-place distribution is not published.
- Fire, Finland: for ICD-resolved building/structure fires (`X00`/`X01`), Pelastusopisto 2007–2010 investigation data provide 343 fatal building-fire settings by building type: detached house 191, block of flats 82, row house 30, leisure-time house 19, rental cottage 3, storage/outbuilding 8, other building 10. The source pools fire intent, which is stated in model status; other Finnish fire codes remain unsupported rather than being forced into a building-type distribution.
- Fire, Canada: Statistics Canada's Canadian Coroner and Medical Examiner Database analysis for 2011–2020 reports that 92% of unintentional fire-related deaths occurred in someone's residence or on their property (including a vehicle parked in a driveway/garage). The remaining 8% is retained as an explicit `other setting` residual for `X00–X09`.
- Homicide, Finland: European Homicide Monitor 2003–2006 tables provide sex-specific known-event-location counts (350 male victims, 136 female victims). Unknown location is excluded from the conditional known-place roll. No Canada homicide PLACE fallback is bundled yet; Canadian homicide therefore prints no PLACE rather than borrowing Finnish scene patterns.
- Road traffic, Finland: European Commission/CARE 2020 fatality setting weights are rural road 68%, urban road 28%, motorway 4%. A broad `V01–V99` transport parent is intentionally insufficient to trigger this model; a resolved road/land-transport detail is required so water/air transport cannot acquire a fake road setting.
- Road traffic, Canada: Transport Canada 2023 fatal-collision counts are urban 799, rural 932, not stated 37 (1,768 total), normalized directly.
- Railway/nontraffic transport coherence (v0.13.8): when an exact ICD transport detail identifies a collision with a railway train/vehicle, PLACE is resolved from the ICD traffic-status wording rather than from the generic road-setting distribution: nontraffic → `Railway tracks / premises`; traffic → `Railway crossing / public road`; unspecified → `Railway tracks / crossing`. Exact nontraffic transport details with no defensible specific setting are not forced into rural/urban/motorway categories. Railway collisions and explicit nontraffic V-codes do not receive the generic road impairment context because the bundled OTI/Transport Canada impairment models use road/fatal-motor-vehicle denominators, not rail-occurrence denominators.
- Cancer terminal place, Finland: Ahtiluoto et al.'s nationwide 2019 register cohort reports hospital 82.1%, home 11.0%, long-term-care facility 6.8%; rounding is normalized within the model.
- Cancer terminal place, Canada: CIHI/Canadian Partnership Against Cancer reporting for Statistics Canada 2005–2009 gives approximately 70% hospital and 11% home. The remaining 19% is retained explicitly as `other / unspecified`; it is a derived residual, not an observed subcategory split.
- Neurodegenerative terminal place, Finland: the same nationwide register framework gives hospital 43.2%, home 7.0%, long-term care 49.7% for the documented neurodegenerative grouping. No Canadian fallback is used.
- Semantic distinction: `event_setting` (for example lake, homicide scene, rural road) and `terminal_place` (for example hospital/home/LTC) remain distinct in model metadata even though the CLI deliberately presents both under the compact **PLACE** label.
- Absence is meaningful: if neither ICD nor the bundled evidence supports a defensible place distribution for that cause/country, PLACE is omitted.

Key references:

- Safety Investigation Authority Finland. *S1/2010Y Deaths by Drowning in Finland 1.4.2010–31.3.2011*. https://www.turvallisuustutkinta.fi/en/investigations/investigation-reports/s1-2010y-deaths-by-drowning-in-finland-1-4-2010-31-3-2011/
- Lifesaving Society / Drowning Prevention Research Centre Canada. *2024 Canadian Detailed Drowning Report*. https://www.lifesavingsociety.sk.ca/fileadmin/lifesavingsociety/storage/2024/Drowning_Reports/LS-Canadian-Drowning-Report-2024-Web.pdf
- Finnish Institute for Health and Welfare (THL). Rönkä S, Konttinen H, Häkkinen M, Karjalainen K. *Nuorten huumemyrkytyskuolemien olosuhteet – Näkökulmia ehkäisyyn*. Tutkimuksesta tiiviisti 24/2024. https://www.julkari.fi/bitstreams/799c2104-b74f-44b5-8c63-8f8472f8f130/download
- Public Health Agency of Canada. Chang et al. *A comparison of the characteristics of accidental substance-related acute toxicity deaths in Canada across life stages (2016 to 2017).* 2024. https://www.canada.ca/en/public-health/services/reports-publications/health-promotion-chronic-disease-prevention-canada-research-policy-practice/vol-44-no-7-8-2024/comparison-characteristics-accidental-substance-related-acute-toxicity-deaths-canada-2016-2017.html
- Kokki E. *Palokuolemat ja ihmisen pelastamiset tulipaloissa 2007–2010.* Pelastusopisto, 2011. https://www.pelastusopisto.fi/wp-content/uploads/2016/12/B3_2011.pdf
- Statistics Canada. *Unintentional fire-related deaths in Canada, 2011 to 2020.* 2022. https://www150.statcan.gc.ca/n1/pub/11-627-m/11-627-m2022035-eng.htm
- Granath et al. *Homicide in Finland, the Netherlands and Sweden: A First Study on the European Homicide Monitor Data*. 2011. https://irep.ntu.ac.uk/id/eprint/28206/1/5724_Ganpat.pdf
- European Commission / CARE. *National Road Safety Profile – Finland*. https://road-safety.transport.ec.europa.eu/system/files/2023-02/erso-country-overview-2023-finland_0.pdf
- Transport Canada. *Canadian Motor Vehicle Traffic Collision Statistics: 2023*. https://tc.canada.ca/en/road-transportation/statistics-data/canadian-motor-vehicle-traffic-collision-statistics/2023/canadian-motor-vehicle-traffic-collision-statistics-2023
- Ahtiluoto et al. *Impact of specialist palliative care on utilization of healthcare and social services at the end-of-life: a nationwide register-based cohort study*. Eur J Public Health. 2025. https://doi.org/10.1093/eurpub/ckaf044
- Canadian Institute for Health Information. *End-of-Life Hospital Care for Cancer Patients*. 2013. https://publications.gc.ca/collections/collection_2013/icis-cihi/H117-5-22-2013-eng.pdf

### Finnish F10 subtype classification context

- Public Statistics Finland cause-of-death table **11be** publishes underlying causes at the ICD-10 **3-character level**, so an underlying-cause result such as `F10` cannot be assigned an empirical `F10.x` probability distribution from that table.
- Statistics Finland's methodological documentation states that the source cause-of-death data are classified at the **most accurate ICD-10 level**, while underlying causes are published at 3-character level. This means finer coding is a public-access/resolution limitation rather than an absence from the underlying register.
- `v0.13.4` therefore treats lower `F10` codes as **taxonomy/context only** unless an empirical complete-code mortality backend supplies a resolved subtype. It never normalizes clinical or registry-association counts into mortality probabilities.
- WHO ICD-10 supplies the fourth-character clinical-state scheme (`F10.0` intoxication, `.1` harmful use, `.2` dependence, `.3` withdrawal, `.4` withdrawal with delirium, etc.). Finland's national ICD-10 documentation maintained through THL/Kanta further refines withdrawal and withdrawal-delirium categories by seizure/convulsion status (for example `F10.31` and `F10.41`).

Primary references:

- Statistics Finland. *Causes of death: documentation of statistics*. https://stat.fi/en/documentation/documentation-of-statistics/ksyyt
- Statistics Finland. StatFin **11be — Deaths by underlying cause of death (ICD-10, 3-character level), age and sex**. https://pxdata.stat.fi/PXWeb/pxweb/en/StatFin/StatFin__ksyyt/11be.px
- Kanta Code Service / Finnish ICD-10 (THL-maintained classification), F10-F19 substance-use disorders and Finnish fifth-character refinements. https://koodistopalvelu.kanta.fi/codeserver/
- WHO ICD-10 browser, 2019. https://icd.who.int/browse10/2019/en
### Cause-note annotation model

- `datasets/cause_notes/cause_note_model_v1.json` is a sparse deterministic annotation table, not a probability model. Rules can match exact ICD codes or ranges and may be restricted by country/source. A matching note is added only after cause/detail resolution and consumes no RNG.
- The initial `M17` rule applies to Finnish StatFin 11be gonarthrosis detail. Statistics Finland 11be reports the **underlying cause of death** at ICD-10 3-character level; it does not expose the individual medical certificate's complete immediate/intervening cause sequence. The note therefore states that the immediate fatal mechanism or intervening complication is unavailable rather than inventing a pulmonary embolism, infection, operation complication, fall, or other plausible pathway.
- Design rule: unusual source data are retained. Notes explain what the published field means; they must not replace, suppress, reinterpret, or increase the certainty of the recorded cause. Additional rules can be added to this table as similarly non-obvious underlying-cause codes are encountered and verified.

Key references:

- Statistics Finland. *11be -- Deaths by underlying cause of death (ICD-10, 3-character level), age and sex, 1998-2024.* https://statfin.stat.fi/PxWeb/pxweb/en/StatFin/StatFin__ksyyt/statfin_ksyyt_pxt_11be.px/
- World Health Organization. *Cause of death* — underlying cause is the disease/injury initiating the train of morbid events leading directly to death. https://www.who.int/standards/classifications/classification-of-diseases/cause-of-death
