# Prasine Index — Data Source Status

Last updated: 2026-06-27.

This document tracks the operational state of all 17 local bulk data sources used by the Verification Agent. Three additional sources are live-only (Climate TRACE API, EUR-Lex static, enforcement static) and have no local files.

---

## Auto-refreshing (Windows Task Scheduler via `refresh_all.py`)

These sources download automatically. Scheduler should run `python scripts/refresh_all.py` daily.

| Source | Key | File | Last refreshed | Notes |
| ------ | --- | ---- | -------------- | ----- |
| EU ETS EUTL | `eutl` | `EUTL24/operators_yearly_activity_daily.csv` | 2026-06-27 | Daily snapshot from EUTL API. Scheduler entry `refresh_eutl.py`. |
| SBTi | `sbti` | `data/sbti_companies.xlsx` | 2026-06-27 | sciencebasedtargets.org bulk XLSX. Scheduler entry `refresh_sbti.py`. |
| CA100+ | `ca100` | `data/ca100_companies.xlsx` | 2026-06-27 | climateaction100.org NZB Excel. Scheduler entry `refresh_ca100.py`. |

---

## Present on disk — URL maintenance needed

Auto-download attempts fail (404 or server-side HTML gate). Existing files are still valid and the pipeline uses them. URLs need updating before the next planned refresh.

| Source | Key | File | Last refreshed | Status | Action |
| ------ | --- | ---- | -------------- | ------ | ------ |
| LobbyMap | `lobbymap` | `data/lobbymap_companies.csv` | 2026-06-24 | 404 on auto-download | Update `_LM_CSV_URL` in `refresh_lobbymap.py`. New bulk CSV is at lobbymap.org — check for "Download" button under company scores section. |
| GCEL | `gcel` | `data/gcel_companies.csv` | 2026-04-07 | 404 on auto-download | Update `_GCEL_CSV_URL` in `refresh_gcel.py`. The 2025 XLSX (`GCEL 2025_Download_0.xlsx`) was manually downloaded; convert to CSV or update ingest to read XLSX. |
| E-PRTR | `eprtr` | `data/eprtr_releases.csv` | 2026-04-07 | EEA API returns 500/HTML | `industry.eea.europa.eu` download endpoint changed. Try: `https://www.eea.europa.eu/en/datahub/datahubitem-view/7c3de2a6-7b88-4e9a-aece-e16d31b03e5b` (E-PRTR v17+). Update `refresh_eprtr.py`. |
| Fossil Finance (BOCC) | `fossil_finance` | `data/fossil_finance_banks.csv` | **MISSING** | 404 on download; BOCC banking CSV absent | `bankingonclimatechaos.org` data URL changed. The `Expansion_Company_List_BOCC_2025.xlsx` on disk is an expansion-companies list, **not** the banking CSV the ingest reads. Manual download from bankingonclimatechaos.org/data required; save as `data/fossil_finance_banks.csv`. |

---

## Manual download only (no auto-refresh possible)

These providers use reCAPTCHA, form submission, or account-gated exports.

| Source | Key | File | Last refreshed | How to refresh |
| ------ | --- | ---- | -------------- | -------------- |
| TPI | `tpi` | `data/tpi_companies.csv` | 2026-05-04 | transitionpathwayinitiative.org → Data → Company Latest Assessments → Download CSV. Save as `data/tpi_companies.csv`. |
| EU Transparency Register | `eu_transparency_register` | `data/EU_Transparency register_searchExport.xlsx` | 2026-05-04 | ec.europa.eu/transparencyregister → Advanced search → (no filters) → Export results. Run `refresh_eu_transparency_register.py` for instructions. |
| GEM Coal Plant Tracker (GCPT) | `gcpt` | `data/Global-Coal-Plant-Tracker-*.xlsx` | 2026-05-04 | globalenergymonitor.org/projects/global-coal-plant-tracker/download-data/ — requires form. Run `refresh_gcpt.py` for step-by-step. |
| GEM Europe Gas Tracker (EGT) | `egt` | `data/Europe-Gas-Tracker-*.xlsx` | 2026-05-04 | globalenergymonitor.org/projects/europe-gas-tracker/download-data/ — requires form. Run `refresh_egt.py`. |
| GEM Oil & Gas Extraction Tracker (GOGET) | `goget_tracker` | `data/Global-Oil-and-Gas-Extraction-Tracker-*.xlsx` | 2026-05-04 | globalenergymonitor.org/projects/global-oil-gas-extraction-tracker/download-data/ — requires form. Run `refresh_goget.py`. |
| EDGAR JRC | `edgar_jrc` | `data/JRC/EDGAR_2025_GHG_booklet_2025.xlsx` | 2026-05-04 | edgar.jrc.ec.europa.eu → Downloads → GHG emissions of all world countries 2025. |
| InfluenceMap | `influencemap` | `data/influencemap_companies.csv` | 2026-04-07 | influencemap.org — same organisation as LobbyMap; bulk data may require account. Cross-check with `data/lobbymap_companies.csv` (same dataset, different vintage). |
| EEA National Inventory | `eea_national` | `data/eea_t_national-emissions-reported_*/UNFCCC_v28.csv` | 2026-04-07 | eea.europa.eu/data-and-maps/data/national-emissions-reported-to-the-unfccc → Download package. Run `refresh_eea_national.py --force`. |

---

## Missing — pipeline falls back gracefully

These files are absent. The ingest module returns an empty list and logs a one-time INFO message. Gaps are disclosed in the judge prompt and the report's data-gaps section.

| Source | Key | Expected file | Why missing | Action |
| ------ | --- | ------------- | ----------- | ------ |
| GOGEL | `gogel` | `data/gogel_companies.csv` | Never downloaded. `GCEL 2025_Download_0.xlsx` on disk is GCEL not GOGEL. | urgewald.org/gogel → Public Download → CSV. Save as `data/gogel_companies.csv`. Run `refresh_gogel.py` which tries an automated download (URL may be 404 — manual fallback). |
| EU Innovation Fund | `eu_innovation_fund` | `data/eu_innovation_fund_projects.csv` | EC Open Data Portal URL broken. | opendata.ec.europa.eu/dataset/innovation-fund-projects-and-grants → CSV download. Save as `data/eu_innovation_fund_projects.csv`. |
| CDP | N/A | `data/cdp_companies.csv` | Paid/investor-signatory access only. | Not planned. CDP is self-reported data weighted below verified sources. Run `refresh_cdp.py` for access options. |

---

## Manifest bugs fixed (2026-06-27)

Three patterns in `core/data_manifest.py` were pointing to wrong files. Fixed in commit `[fix: data manifest patterns — eutl/eea_national/ca100/fossil_finance]`.

| Source | Old pattern | Issue | New pattern |
| ------ | ----------- | ----- | ----------- |
| `eutl` | `data/emissions_high_granularity.csv` | Old EEA ETS export; ingest reads `EUTL24/operators_yearly_activity_daily.csv` | `EUTL24/operators_yearly_activity_daily.csv` (project root) |
| `eea_national` | `data/eea_national_ghg.csv` | File doesn't exist; ingest reads versioned subdirectory | `data/eea_t_national-emissions-reported_*/UNFCCC_v28.csv` |
| `ca100` | `data/ca100_companies.csv` | Matched 15 KB stub from April; ingest falls back to XLSX | `data/ca100_companies*` (glob, newest wins) |
| `fossil_finance` | `data/Expansion_Company_List_*.xlsx` | Wrong dataset (expansion cos, not banking CSV); showed hash when data was effectively absent | `data/fossil_finance_banks.csv` (correctly shows `not_present`) |

---

## Scheduler setup (Windows Task Scheduler)

The scheduler runs `python scripts/refresh_all.py` daily. Exit behaviour:

- **Exit 0**: all auto-downloadable sources succeeded; soft-fail sources printed `[WARN]` but have usable existing files.
- **Exit 1**: a hard-fail source failed (currently: none in the hard-fail list).

Soft-fail sources (expected `[WARN]` in scheduler log — not failures):
`refresh_cdp.py`, `refresh_eprtr.py`, `refresh_gcel.py`, `refresh_gogel.py`, `refresh_fossil_finance.py`, `refresh_eu_innovation_fund.py`, `refresh_lobbymap.py`
