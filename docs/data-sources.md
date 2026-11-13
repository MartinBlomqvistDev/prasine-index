# Prasine Index: Data Sources

State of the data used for the version 2 assessments, made on 6 November 2026 and, for IKEA, on 12 November 2026. The manifests show the same local files on both dates, except the SBTi file. The Verification Agent reads 21 open data sources and the claim's own source document. Each published report has a `<slug>-manifest.json` beside it that records a SHA-256 prefix of every local dataset the run used. That file is the record of what a given assessment read. The README lists what each source provides.

---

## Local bulk files

These sources are read from files in `data/` (not committed) or from the EUTL snapshot in `EUTL24/`.

| Source | Key | How the file is brought in | Edition or note |
| ------ | --- | -------------------------- | --------------- |
| EU ETS EUTL | `eutl` | `scripts/refresh_eutl.py` | Daily snapshot of the Union Registry, `EUTL24/operators_yearly_activity_daily.csv` |
| SBTi | `sbti` | `scripts/refresh_sbti.py` | `data/sbti_companies.xlsx` |
| E-PRTR | `eprtr` | `scripts/refresh_eprtr.py` | `data/eprtr_releases.csv`; the EEA endpoint has changed before, so check the download |
| CA100+ | `ca100` | `scripts/refresh_ca100.py` | Net Zero Company Benchmark of October 2026, ten indicators |
| TPI | `tpi` | `scripts/refresh_tpi.py "Company=slug" ...` | Read from TPI's company pages, which carry the dates of each assessment |
| LobbyMap | `lobbymap` | Saved by hand from LobbyMap's league table | Edition of 5 November 2026. `scripts/refresh_lobbymap.py` fetches an older file and would overwrite it |
| Global Coal Exit List | `gcel` | `scripts/convert_urgewald_lists.py --gcel` | GCEL 2026 workbook from urgewald. `scripts/refresh_gcel.py` downloads the 2023 list and would overwrite the 2026 data |
| Urgewald GOGEL | `gogel` | `scripts/convert_urgewald_lists.py --gogel` | GOGEL 2025 V2 workbook from urgewald. `scripts/refresh_gogel.py` downloads the 2024 list and would overwrite the 2025 V2 data |
| Banking on Climate Chaos | `fossil_finance` | `scripts/refresh_fossil_finance.py` | `data/fossil_finance_banks.csv` |
| EEA national inventories | `eea_national` | `scripts/refresh_eea_national.py` | Package `eea_t_national-emissions-reported_*` |
| EU Transparency Register | `eu_transparency_register` | Manual export; `scripts/refresh_eu_transparency_register.py` prints the steps | `data/EU_Transparency register_searchExport.xlsx` |
| GEM Coal Plant Tracker | `gcpt` | Manual form download; `scripts/refresh_gcpt.py` prints the steps | January 2026 |
| GEM Europe Gas Tracker | `egt` | Manual form download; `scripts/refresh_egt.py` prints the steps | 2 March 2026 |
| GEM Oil & Gas Extraction Tracker | `goget_tracker` | Manual form download; `scripts/refresh_goget.py` prints the steps | March 2026 |
| EDGAR JRC | `edgar_jrc` | Manual download from edgar.jrc.ec.europa.eu | GHG booklet 2025, `data/JRC/` |

---

## Sources without a local file

| Source | Where it comes from |
| ------ | ------------------- |
| Climate TRACE | Live API (v7) |
| Eurostat | Live API (`env_air_gge`) |
| Enforcement records | Static records embedded in `ingest/enforcement_records.py`, each checked twice against the authority's own page, in two separate passes made with language-model agents |
| EUR-Lex | Static provisions embedded in `ingest/eurlex.py` |
| The claim's own source document | Fetched at run time |

---

## Sources with no data in the current deployment

| Source | Expected file | Why |
| ------ | ------------- | --- |
| CDP | `data/cdp_companies.csv` | CDP's bulk dataset needs paid or investor-signatory access. No report carries a CDP record. |
| EU Innovation Fund | `data/eu_innovation_fund_projects.csv` | The file has not been downloaded. Each report's data manifest lists the source as `not_present`. |

---

## Refreshing

`scripts/refresh_all.py` runs the refresh scripts in sequence, including `refresh_lobbymap.py`, `refresh_gcel.py` and `refresh_gogel.py`, which would overwrite the LobbyMap, GCEL and GOGEL data of the version 2 assessments. Do not run it before the next assessment. `scripts/detect_changes.py` compares the files in `data/` with the hashes of the stored manifest. Compare the data manifest of a new run with the previous one before publishing its results.
