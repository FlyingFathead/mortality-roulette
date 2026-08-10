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
