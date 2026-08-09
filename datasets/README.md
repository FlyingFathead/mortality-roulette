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
