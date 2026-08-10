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

Statistics Finland open statistical data are redistributed with source attribution under **CC BY 4.0**.

### Statistics Canada

- Complete life table: **13-10-0837-01**
  - https://www150.statcan.gc.ca/n1/en/catalogue/1310083701
- Monthly deaths: **13-10-0708-01**
  - https://www150.statcan.gc.ca/n1/en/catalogue/1310070801

Statistics Canada snapshots are redistributed with source attribution under the **Statistics Canada Open Licence**. The existing CSV download/parser path remains available for refreshes and for supported provinces not bundled here.

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
- Future countries/cells fall back only where explicitly declared in the JSON, with provenance retained in output.

Key references:

- Sinyor M et al. *Effect of a barrier at Bloor Street Viaduct on suicide rates in Toronto: natural experiment*. BMJ. 2010. https://pubmed.ncbi.nlm.nih.gov/20605890/
- Reisch T, Schuster U, Michel K. *Suicide by Jumping and Accessibility of Bridges: Results from a National Survey in Switzerland*. Suicide Life Threat Behav. 2007. https://doi.org/10.1521/suli.2007.37.6.681
- Chen YY, Gunnell D, Lu TH. *Descriptive epidemiological study of sites of suicide jumps in Taipei, Taiwan*. Inj Prev. 2009. https://pubmed.ncbi.nlm.nih.gov/19190275/
- Koskela L et al. *Fatal poisonings in Northern Finland: causes, incidence, and rural-urban differences*. Scand J Trauma Resusc Emerg Med. 2017. https://doi.org/10.1186/s13049-017-0431-8
- Statistics Finland. *Causes of death 2020: Accident mortality decreased for women* (accidental poisoning discussion). https://stat.fi/til/ksyyt/2020/ksyyt_2020_2021-12-10_kat_005_en.html
- Public Health Agency of Canada. *Substance-related acute toxicity deaths in Canada from 2016 to 2017: A review of coroner and medical examiner files*. https://www.canada.ca/en/health-canada/services/opioids/data-surveillance-research/substance-related-acute-toxicity-deaths-canada-2016-2017-review-coroner-medical-examiner-files.html

### Cause-conditional PLACE model

- `datasets/places/cause_place_model_v1.json`
- Purpose: extend the existing statistically weighted X80 location feature into one reusable downstream **PLACE** layer. The mortality roll, broad cause, cause detail, suicide context, X80 site roll, X41 drug-class roll and seasonality remain separate and unchanged.
- RNG semantics: generalized PLACE uses its own stream. Existing X80 retains its original `0x5838304C` stream and distribution; X80 is merely rendered through the unified PLACE field. The generalized place stream therefore cannot reshuffle a pre-existing seeded X80 result.
- ICD constraint rule: specific environment information already resolved by ICD wins before statistical refinement. W65/W66 resolve to bathtub and W67/W68 to swimming pool. W69/W70 and watercraft-drowning codes V90/V92 restrict the country model to explicitly compatible natural/open-water categories and renormalize only those categories. Mixed/unspecified residuals are excluded rather than guessed. W73/W74 can use the broader drowning distribution because the code does not already fix a narrower setting.
- Drowning, Finland: Safety Investigation Authority S1/2010Y investigated 228 accidental water-related deaths during 1 Apr 2010–31 Mar 2011: lake 110, sea 51, river 22, pond 14, indoor pool 5, and 26 in smaller water settings/bathtubs. Raw counts are normalized for the broad roll. Natural-water-constrained rolls use only the explicitly compatible lake/sea/river/pond counts.
- Drowning, Canada: the 2024 Canadian Detailed Drowning Report gives the national 2015–2019 distribution lake/pond 35%, river 26%, bathtub 13%, pool 9%, ocean 6%, other 11%. Natural/open-water-constrained rolls use lake/pond, river and ocean only.
- Homicide, Finland: European Homicide Monitor 2003–2006 tables provide sex-specific known-event-location counts (350 male victims, 136 female victims). Unknown location is excluded from the conditional known-place roll. No Canada homicide PLACE fallback is bundled yet; Canadian homicide therefore prints no PLACE rather than borrowing Finnish scene patterns.
- Road traffic, Finland: European Commission/CARE 2020 fatality setting weights are rural road 68%, urban road 28%, motorway 4%. A broad `V01–V99` transport parent is intentionally insufficient to trigger this model; a resolved road/land-transport detail is required so water/air transport cannot acquire a fake road setting.
- Road traffic, Canada: Transport Canada 2023 fatal-collision counts are urban 799, rural 932, not stated 37 (1,768 total), normalized directly.
- Cancer terminal place, Finland: Ahtiluoto et al.'s nationwide 2019 register cohort reports hospital 82.1%, home 11.0%, long-term-care facility 6.8%; rounding is normalized within the model.
- Cancer terminal place, Canada: CIHI/Canadian Partnership Against Cancer reporting for Statistics Canada 2005–2009 gives approximately 70% hospital and 11% home. The remaining 19% is retained explicitly as `other / unspecified`; it is a derived residual, not an observed subcategory split.
- Neurodegenerative terminal place, Finland: the same nationwide register framework gives hospital 43.2%, home 7.0%, long-term care 49.7% for the documented neurodegenerative grouping. No Canadian fallback is used.
- Semantic distinction: `event_setting` (for example lake, homicide scene, rural road) and `terminal_place` (for example hospital/home/LTC) remain distinct in model metadata even though the CLI deliberately presents both under the compact **PLACE** label.
- Absence is meaningful: if neither ICD nor the bundled evidence supports a defensible place distribution for that cause/country, PLACE is omitted.

Key references:

- Safety Investigation Authority Finland. *S1/2010Y Deaths by Drowning in Finland 1.4.2010–31.3.2011*. https://www.turvallisuustutkinta.fi/en/investigations/investigation-reports/s1-2010y-deaths-by-drowning-in-finland-1-4-2010-31-3-2011/
- Lifesaving Society / Drowning Prevention Research Centre Canada. *2024 Canadian Detailed Drowning Report*. https://www.lifesavingsociety.sk.ca/fileadmin/lifesavingsociety/storage/2024/Drowning_Reports/LS-Canadian-Drowning-Report-2024-Web.pdf
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
