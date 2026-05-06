# Prasine Index

[![CI](https://github.com/MartinBlomqvistDev/prasine-index/actions/workflows/ci.yml/badge.svg)](https://github.com/MartinBlomqvistDev/prasine-index/actions/workflows/ci.yml)

**Automated EU corporate greenwashing monitoring and scoring.**

Every green claim made by an EU-listed company, verified against real emissions data and lobbying records, with a full evidence chain citable by journalists, NGOs, and in court.

*Prasine* — from Latin/Greek *prasinus* (green).

---

## What It Does

Prasine Index is a live-running AI workflow system that:

1. **Monitors** EU company investor relations pages, press releases, and CSRD reports continuously for new green claims.
2. **Extracts** every green claim as a structured, attributed record — verbatim text, source URL, page reference, publication date.
3. **Verifies** each claim against 21 parallel open data sources — EU ETS, SBTi, InfluenceMap, enforcement rulings, CA100+, Banking on Climate Chaos, GCEL, EUR-Lex, EU Transparency Register, EEA National, Eurostat, EU Innovation Fund, GOGEL, Climate TRACE, TPI, GCPT, EGT, GOGET, EDGAR JRC, E-PRTR, and more.
4. **Cross-references** the company against the EU Transparency Register. A company claiming climate leadership while lobbying against climate legislation in Brussels is flagged explicitly.
5. **Scores** each claim 0–100 using an LLM-as-judge with full chain-of-thought reasoning, broken down by dimension: emissions accuracy, claim substantiation, historical consistency, lobbying alignment, target credibility.
6. **Publishes** a source-chained report in Markdown — every factual assertion is cited, every data gap is disclosed, and the full reasoning is preserved verbatim for audit and citation.
7. **Monitors over time.** If a company re-makes a previously scored claim without evidence of progress, the system flags it automatically. If a company modifies a claim after Prasine Index published a verdict, that modification is flagged as a primary accountability signal.

Target audience: Greenpeace, WWF, ClientEarth, EU investigative journalists, The Guardian, the EU Commission.

---

## Architecture

### The 7-Agent Pipeline

```text
Discovery Agent
      │
      ▼
Claim Extraction Agent    ← raw Anthropic SDK
      │
      ▼
Context Agent             ← PostgreSQL + pgvector
      │
      ▼
Verification Agent        ← LangGraph (parallel fan-out, 21 sources)
      │
      ▼
Lobbying Agent            ← EU Transparency Register
      │
      ▼
Judge Agent               ← raw Anthropic SDK
      │
      ▼
Report Agent              ← raw Anthropic SDK
```

**Discovery Agent** — monitors company IR pages for content changes via SHA-256 hash comparison. Only changed or new pages trigger the downstream pipeline. This is what makes the system live rather than a manual tool.

**Claim Extraction Agent** — uses forced tool use to extract every green claim verbatim from the document with source metadata. Returns `List[Claim]`.

**Context Agent** — queries PostgreSQL for the company's claim history, aggregate scores, score trend, and semantically similar prior claims via pgvector cosine similarity before verification begins.

**Verification Agent** — queries 21 parallel sources simultaneously (see Data Sources below), aggregating results into a `VerificationResult`. See [Why LangGraph is used here and nowhere else](#why-langgraph-for-the-verification-agent-only) below.

**Lobbying Agent** — retrieves the company's Transparency Register record and classifies whether its lobbying activity contradicts its green claims.

**Judge Agent** — LLM-as-judge. Receives the complete evidence package and produces a calibrated `GreenwashingScore` (0–100) with per-dimension breakdown and full chain-of-thought reasoning.

**Report Agent** — generates the publication-ready Markdown report with inline source citations.

---

### Why LangGraph for the Verification Agent Only

This is the most important architectural decision in the codebase, and it is deliberate.

**The case for LangGraph at the Verification Agent:**

The Verification Agent queries 21 independent data sources and must:

- Execute all queries concurrently (never sequentially — latency would compound)
- Accumulate results from each branch as they complete
- Handle partial failures gracefully: if one source is down, the pipeline must continue with the evidence that was retrieved, not fail entirely
- Merge partial state from concurrent branches into a coherent aggregate

This is exactly the problem that LangGraph's `StateGraph` with `operator.add` reducers solves. The fan-out topology is declared explicitly in the graph; parallel execution is handled by the framework's async runtime; partial state merging is automatic. Writing this coordination logic by hand with `asyncio.gather()` and manual exception handling would produce more code, more bugs, and less readability for the same result.

**The case against LangGraph everywhere else:**

The other six agents are single-step operations:

- Extraction: one LLM call with forced tool use, parse the response
- Context: four SQL queries, build a Pydantic model
- Lobbying: one HTTP call, classify the response
- Judge: one LLM call with forced tool use, parse the response
- Report: one LLM call, return the text

For single-step agents, introducing a framework means:

- The prompt and response handling are obscured behind framework abstractions
- Debugging requires understanding the framework's state machine in addition to the business logic
- The model's exact inputs and outputs are harder to inspect and log
- Iteration on prompt changes requires re-learning framework conventions

The Judge Agent is the most sensitive step in the pipeline — its output may be cited in legal proceedings. It needs to be as transparent as possible. A direct Anthropic SDK call with the prompt written as a plain string is auditable; a LangGraph node wrapping a tool call is not. This is not a criticism of LangGraph; it is a recognition that frameworks add value in proportion to the complexity of the orchestration problem they solve.

**The result:** Prasine Index uses LangGraph where it genuinely adds value (21-source parallel fan-out with partial failure tolerance), and raw Anthropic SDK where full control matters (single-step LLM calls with precise prompt requirements). This shows understanding of *when* to use a framework, not just *that* frameworks exist.

---

### Data Model

Every agent communicates exclusively through Pydantic v2 models. No raw strings or untyped dicts cross agent boundaries.

| Model | Description |
| ----- | ----------- |
| `Claim` | Atomic unit of work: a single green claim with full provenance |
| `ClaimLifecycle` | Immutable status transition record; one row per status change |
| `Evidence` | A single data point from one open data source |
| `VerificationResult` | Aggregated evidence package for a claim |
| `GreenwashingScore` | Judge verdict: 0–100 index with dimension breakdown and reasoning |
| `Company` | EU company registry data including LEI and EU ETS installation IDs |
| `CompanyContext` | Historical claim and score aggregates for a company |
| `LobbyingRecord` | EU Transparency Register data with contradiction assessment |
| `AgentTrace` | Structured execution log: agent, outcome, duration, tokens |

### Claim Lifecycle

```text
DETECTED → VERIFIED → SCORED → PUBLISHED → MONITORING
```

Every status transition is recorded as an immutable `ClaimLifecycle` row. The full history of a claim's progression through the pipeline can be reconstructed at any point.

The `MONITORING` state is the system's killer feature: a company that re-makes a previously scored claim without evidence of progress is flagged automatically as a repeat offender. A company that modifies a claim after Prasine Index publishes a verdict has that modification flagged as a primary accountability signal in all subsequent reports.

---

### Storage

**PostgreSQL 15+ with the pgvector extension.**

pgvector serves two purposes:

1. **Semantic search across historical claims.** The `normalised_text` of each claim is embedded and stored as a pgvector column. When a new claim arrives, the Context Agent queries for prior claims from the same company with cosine similarity above a threshold, surfacing repeat claims automatically.

2. **Operational simplicity.** pgvector runs inside the existing PostgreSQL instance. No additional vector database service to provision, monitor, or pay for.

---

## Production-Grade Properties

### 1. Parallel Verification

The Verification Agent never queries data sources sequentially. The LangGraph graph fans out to all 21 sources simultaneously from `START`; the `operator.add` reducer on the `evidence` list merges partial results as each branch completes. A source that takes 8 seconds does not hold up a source that takes 1 second.

### 2. Pydantic End-to-End

Every agent input and every agent output is a Pydantic v2 model. `Claim`, `Evidence`, `GreenwashingScore`, `VerificationResult`, `AgentTrace`, `CompanyContext`, `LobbyingRecord` — no raw strings, no untyped dicts at agent boundaries. Model validation runs on every agent handover.

### 3. Structured Error Boundaries

The `core/retry.py` module provides:

- A typed exception hierarchy (`LLMError`, `DataSourceError`, `ExtractionError`, `RetryExhaustedError`) with retryability expressed as a property, not inferred from the exception type
- Full-jitter exponential backoff via `@retry_async`, with three pre-built configs for LLM calls, HTTP calls, and database queries
- The `agent_error_boundary` async context manager, which guarantees every unhandled exception is logged with full structured context before re-raising — no failure in the pipeline is silent

### 4. Golden Eval Dataset

`eval/golden_dataset.py` contains 20 known greenwashing cases drawn from public record — EU regulatory actions, NGO investigations, court rulings — each with the expected verdict and acceptable score range. The eval runner executes the full pipeline against all 20 cases and reports verdict accuracy, score calibration, and per-agent latency. Exit code 1 if pass rate falls below 80%.

```bash
python -m eval.golden_dataset
```

This is LLMOps: prompt changes, model upgrades, and architectural changes must not silently regress against known outcomes.

### 5. Trace IDs Throughout

Every claim is assigned a `trace_id` at creation. It flows through all seven agents unchanged and is written to every `AgentTrace` row, every `Evidence` record, and every log line. To reconstruct the full execution history of any claim:

```text
GET /trace/{trace_id}
```

Returns every agent step in chronological order with duration, token count, outcome, and error context. Full pipeline replay is possible for any claim.

---

## Tech Stack

| Component | Technology | Justification |
| --------- | ---------- | ------------- |
| Pipeline agents | Python 3.12 + asyncio | Async-first throughout; parallel verification requires it |
| LLM agents (extraction, judge, report) | Raw Anthropic SDK | Full prompt control; no framework abstraction over legally sensitive LLM calls |
| Verification orchestration | LangGraph | 21-source parallel fan-out with partial failure tolerance |
| Data validation | Pydantic v2 | Runtime-validated agent contracts; no untyped data at boundaries |
| API | FastAPI | Async-native, Pydantic-native, production-grade |
| Database | PostgreSQL 15 + pgvector | Relational integrity + vector similarity in one service |
| HTTP client | httpx | Async-native; consistent interface for all external API calls |

---

## Data Sources

21 parallel sources queried per claim. Sources are grouped by evidence type.

### Verified Emissions

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| EU ETS EUTL | Verified annual CO₂ per installation, 2005–present. Third-party verified under Regulation 601/2012. | `refresh_eutl.py` |
| E-PRTR (EEA) | Verified non-CO₂ GHG releases per facility (CH₄, N₂O, HFCs). | `refresh_eprtr.py` |
| Climate TRACE | Independent facility-level emissions estimates from satellite/ML — not self-reported. | Live API (v7) |
| EDGAR JRC (2025) | JRC independent national GHG totals 1970–2024 for all countries. Cross-checks Eurostat and EEA. | Static XLSX (`data/JRC/`) |

### Targets and Benchmarks

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| SBTi | Science-based targets: validated, committed, removed. Removed = CONFIRMED_GREENWASHING at 0.95. | `refresh_sbti.py` |
| CA100+ | Net-zero benchmark for 170 largest emitters (700+ investors, $68tn AUM). "Not Aligned" directly contradicts net-zero claims. | `refresh_ca100.py` |
| TPI | Management quality (0–4) and carbon performance benchmarks for 491 listed companies. | Static CSV (`data/tpi_companies.csv`) |

### Fossil Fuel Expansion

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| GEM Coal Plant Tracker (GCPT) | Every coal power plant worldwide — status, owner, capacity. Expanding coal contradicts clean-energy claims. | Manual form download (GEM reCAPTCHA) |
| GEM Europe Gas Tracker (EGT) | Gas pipelines, LNG terminals, and gas plants across Europe. New infrastructure in construction contradicts Paris-alignment. | Manual form download (GEM reCAPTCHA) |
| GEM Oil & Gas Extraction Tracker (GOGET) | Oil and gas fields worldwide. FID-stage fields = capital committed to decades of upstream production. | Manual form download (GEM reCAPTCHA) |
| Global Coal Exit List (GCEL) | ~1,000 companies in the coal value chain. Standard coal screen under GFANZ/PAII. | `refresh_gcel.py` |
| Urgewald GOGEL | ~1,000 companies in oil and gas expansion. O&G equivalent of GCEL. | `refresh_gogel.py` |

### Financing

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| Banking on Climate Chaos | Fossil fuel financing by 60 largest banks 2016–present. | `refresh_fossil_finance.py` |

### Lobbying and Policy

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| InfluenceMap | Corporate climate lobbying scores A+ to F. D/E/F company claiming green leadership = textbook greenwashing. | `refresh_influencemap.py` |
| EU Transparency Register | Brussels lobbying declarations. Confirms active lobbying; direction requires cross-reference with InfluenceMap. | `refresh_eu_transparency_register.py` |
| Enforcement Rulings | ASA, ACM, AGCM, CMA, EC rulings and court judgments. Prior ruling = strongest evidence category. | Static (embedded in module) |
| EUR-Lex | Green Claims Directive, CSRD ESRS E1, EU ETS legislation as regulatory baseline. | Static (legislation is stable) |

### Statistical Context

| Source | What It Provides | Refresh |
| ------ | ---------------- | ------- |
| Eurostat | Official EU national GHG statistics. Country-level benchmark for company percentage claims. | `refresh_eurostat.py` |
| EEA National Totals | EEA-verified national inventory totals 1990–present. Standard EU reporting benchmark. | `refresh_eea_national.py` |
| EU Innovation Fund | EU-funded decarbonisation projects. Context for whether claimed green investments match emissions scale. | `refresh_eu_innovation_fund.py` |

**Note on CDP:** CDP corporate scores require investor-signatory or paid API access. Not implemented. Self-reported data carries lower evidential weight than verified sources in any case.

---

## run_assessment.py

The fastest way to run the full pipeline against any company:

```bash
# Fetch the sustainability page automatically and assess up to 5 claims:
python scripts/run_assessment.py --company "Shell plc" \
    --url "https://shell.com/sustainability"

# Provide claim text directly (skips page fetch):
python scripts/run_assessment.py --company "Shell plc" \
    --claim "Shell is on track to become net-zero by 2050" \
    --url "https://shell.com/sustainability"

# Refresh all downloadable data sources first:
python scripts/run_assessment.py --company "Shell plc" \
    --url "https://shell.com/sustainability" --refresh-data

# Assess up to 10 claims (more thorough, higher token spend):
python scripts/run_assessment.py --company "Shell plc" \
    --url "https://shell.com/sustainability" --max-claims 10
```

Costs approximately **$0.05 per claim** on Haiku defaults — this is the per-claim floor (one claim through all 7 agents, including 21-source verification). A full company run with `--max-claims 5` (default) costs ~$0.25–$0.75 depending on page length and report verbosity. Budget $3–$7 for a 10-company sweep. `--max-claims 10` is suitable for a full audit (~$0.50–$1.50/company).

Saves numbered reports to `docs/reports/<slug>-{n}.md` and a canonical report (highest-scoring claim) to `docs/reports/<slug>.md`.

---

## Published Assessments

Current results from the 21-source pipeline, as published on [prasineindex.eu](https://martinblomqvistdev.github.io/prasine-index/):

| Company | Sector | Verdict | Score |
| ------- | ------ | ------- | ----- |
| Ryanair Holdings plc | Aviation | CONFIRMED_GREENWASHING | 82/100 |
| KLM Royal Dutch Airlines | Aviation | CONFIRMED_GREENWASHING | 92/100 |
| Glencore plc | Mining | CONFIRMED_GREENWASHING | 82/100 |
| Shell plc | Oil & Gas | GREENWASHING | 78/100 |
| TotalEnergies SE | Oil & Gas | GREENWASHING | 72/100 |
| Enel SpA | Energy | GREENWASHING | 72/100 |
| HSBC Holdings plc | Banking | GREENWASHING | 71/100 |
| RWE AG | Energy | MISLEADING | 56/100 |
| IKEA Group | Retail | MISLEADING | 52/100 |
| Öresundskraft AB | Energy | MISLEADING | 52/100 |
| Ørsted A/S | Energy | INSUFFICIENT_EVIDENCE | 32/100 |

Reports are published to `docs/reports/` as Markdown — every factual assertion cited, every data gap disclosed.

---

## Getting Started

### Prerequisites

- Python 3.12
- PostgreSQL 15+ with the pgvector extension installed
- An Anthropic API key

### Installation

```bash
git clone https://github.com/MartinBlomqvistDev/prasine-index.git
cd prasine-index

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env: set DATABASE_URL and ANTHROPIC_API_KEY
```

### Database Setup

```bash
python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())"
```

### Refreshing Data Sources

```bash
# All downloadable sources at once:
python scripts/run_assessment.py --company "..." --url "..." --refresh-data

# Individual sources:
python scripts/refresh_eutl.py           # EU ETS daily snapshot
python scripts/refresh_sbti.py           # SBTi targets
python scripts/refresh_eprtr.py          # E-PRTR non-CO2 GHG
python scripts/refresh_influencemap.py   # InfluenceMap lobbying scores
python scripts/refresh_ca100.py          # CA100+ benchmark
python scripts/refresh_fossil_finance.py # Banking on Climate Chaos
python scripts/refresh_gcel.py           # Global Coal Exit List
python scripts/refresh_gogel.py          # Urgewald GOGEL
python scripts/refresh_eea_national.py   # EEA National totals
python scripts/refresh_eu_transparency_register.py  # EU TR bulk export
python scripts/refresh_eu_innovation_fund.py        # EU Innovation Fund

# GEM trackers require manual form download (reCAPTCHA):
python scripts/refresh_gcpt.py   # Instructions for Coal Plant Tracker
python scripts/refresh_egt.py    # Instructions for Europe Gas Tracker
python scripts/refresh_goget.py  # Instructions for Oil & Gas Extraction Tracker
```

### Running the Eval

```bash
# Full golden dataset (20 cases):
python -m eval.golden_dataset

# Specific cases:
python -m eval.golden_dataset GW-001 GW-003 GW-010
```

Pass rate target: ≥ 80%. Exit code 1 on failure — suitable as a CI gate.

### Running the Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```text
prasine-index/
├── agents/
│   ├── discovery_agent.py      # Monitors company sources for new content
│   ├── extraction_agent.py     # Extracts green claims (raw Anthropic SDK)
│   ├── context_agent.py        # Retrieves company history from PostgreSQL
│   ├── verification_agent.py   # 21-source parallel fan-out (LangGraph)
│   ├── lobbying_agent.py       # EU Transparency Register cross-reference
│   ├── judge_agent.py          # LLM-as-judge scoring (raw Anthropic SDK)
│   └── report_agent.py         # Publication-ready report (raw Anthropic SDK)
├── models/
│   ├── claim.py                # Claim, ClaimStatus, ClaimLifecycle
│   ├── evidence.py             # Evidence, VerificationResult, EvidenceSource (21 values)
│   ├── score.py                # GreenwashingScore, ScoreVerdict
│   ├── company.py              # Company, CompanyContext
│   ├── lobbying.py             # LobbyingRecord
│   └── trace.py                # AgentTrace
├── core/
│   ├── pipeline.py             # Orchestrates all 7 agents
│   ├── database.py             # PostgreSQL + pgvector async connection
│   ├── logger.py               # Structured JSON logging + ContextVar trace_id
│   └── retry.py                # Typed exceptions, retry decorator, error boundary
├── ingest/
│   ├── eu_ets.py               # EU ETS EUTL verified emissions (local CSV)
│   ├── sbti.py                 # SBTi validated/removed targets (local CSV)
│   ├── eprtr.py                # E-PRTR non-CO2 GHG releases (local CSV)
│   ├── influence_map.py        # InfluenceMap lobbying scores (local CSV)
│   ├── enforcement.py          # ASA/ACM/AGCM/CMA/EC rulings (static, embedded)
│   ├── ca100.py                # CA100+ net-zero benchmark (local CSV)
│   ├── fossil_finance.py       # Banking on Climate Chaos fossil financing (local CSV)
│   ├── coal_exit.py            # Urgewald GCEL coal exposure (local CSV)
│   ├── eurlex.py               # EUR-Lex legislative context (static, embedded)
│   ├── eu_transparency_register.py  # EU Transparency Register (local XLSX)
│   ├── eurostat.py             # Eurostat national GHG statistics (local CSV)
│   ├── eea_national.py         # EEA National inventory totals (local CSV)
│   ├── eu_innovation_fund.py   # EU Innovation Fund projects (local CSV)
│   ├── gogel.py                # Urgewald GOGEL O&G exit list (local CSV)
│   ├── climate_trace.py        # Climate TRACE API v7 (live)
│   ├── tpi.py                  # TPI benchmarks (local CSV)
│   ├── gcpt.py                 # GEM Coal Plant Tracker (local XLSX)
│   ├── egt.py                  # GEM Europe Gas Tracker (local XLSX)
│   ├── goget.py                # GEM Oil & Gas Extraction Tracker (local XLSX)
│   └── edgar.py                # EDGAR JRC GHG booklet (local XLSX)
├── api/
│   └── main.py                 # FastAPI REST API
├── eval/
│   └── golden_dataset.py       # 20 known greenwashing cases + eval runner
├── scripts/
│   ├── run_assessment.py       # Run full pipeline on any company URL or claim text
│   ├── refresh_eutl.py         # Download EU ETS daily snapshot
│   ├── refresh_sbti.py         # Download SBTi CSV
│   ├── refresh_eprtr.py        # Download E-PRTR CSV
│   ├── refresh_influencemap.py # Download InfluenceMap CSV
│   ├── refresh_ca100.py        # Download CA100+ CSV
│   ├── refresh_fossil_finance.py  # Download Banking on Climate Chaos CSV
│   ├── refresh_gcel.py         # Download Urgewald GCEL CSV
│   ├── refresh_gogel.py        # Download Urgewald GOGEL CSV
│   ├── refresh_eea_national.py # Download EEA National totals CSV
│   ├── refresh_eu_transparency_register.py  # Instructions for EU TR bulk export
│   ├── refresh_eu_innovation_fund.py        # Download EU Innovation Fund CSV
│   ├── refresh_gcpt.py         # Instructions for GEM GCPT (reCAPTCHA)
│   ├── refresh_egt.py          # Instructions for GEM EGT (reCAPTCHA)
│   ├── refresh_goget.py        # Instructions for GEM GOGET (reCAPTCHA)
│   └── seed_eval_companies.py  # Insert all 20 eval companies with deterministic UUIDs
├── data/                       # Local bulk datasets (not committed — download via refresh scripts)
│   ├── sbti_companies.csv
│   ├── eprtr_releases.csv
│   ├── influencemap_companies.csv
│   ├── ca100_companies.csv
│   ├── fossil_finance_banks.csv
│   ├── gcel_companies.csv
│   ├── gogel_companies.csv
│   ├── tpi_companies.csv
│   ├── eea_national_ghg.csv
│   ├── eu_innovation_fund_projects.csv
│   ├── EU_Transparency register_searchExport.xlsx
│   ├── Global-Coal-Plant-Tracker-January-2026.xlsx
│   ├── Europe-Gas-Tracker-2026-03-02.xlsx
│   ├── Global-Oil-and-Gas-Extraction-Tracker-March-2026.xlsx
│   └── JRC/
│       └── EDGAR_2025_GHG_booklet_2025.xlsx
├── docs/
│   ├── index.html              # Landing page
│   └── reports/                # Published assessment reports (Markdown)
├── tests/
│   └── test_models.py
├── .env.example
├── DEV_LOG.md                  # Real failures, root causes, and fixes
└── requirements.txt
```

---

## Observability

Every pipeline run produces structured JSON log records to stdout. All records carry `trace_id`, `claim_id`, `agent`, `operation`, `duration_ms`, and `outcome` fields automatically via `contextvars.ContextVar`. Compatible with Google Cloud Logging, Datadog, and any NDJSON log aggregator.

Key operations logged:

| Operation | When |
| --------- | ---- |
| `extraction_start` / `extraction_complete` | Extraction Agent entry and exit |
| `verification_aggregate` | Verification Agent post-fan-out summary |
| `judge_complete` | Judge verdict with score and verdict fields |
| `pipeline_complete` | End-to-end verdict per claim |
| `db_init_complete` | Database schema initialisation on startup |

The `/trace/{trace_id}` endpoint returns the structured execution record for any pipeline run: agent names, outcomes, durations, token counts, and error context in chronological order.

---

## Methodology

Greenwashing scores are calibrated against the EU Green Claims Directive, the Corporate Sustainability Reporting Directive (CSRD), and the EU Taxonomy Regulation. The score scale:

| Range | Verdict | Meaning |
| ----- | ------- | ------- |
| 0–40 | `FABRICATED` | Claim is demonstrably false; directly contradicted by verified data |
| 41–60 | `MISLEADING` | Claim exaggerates through omission or lacks mandatory substantiation under the Green Claims Directive |
| 61–80 | `GREENWASHING` | Claim directly contradicted by verified third-party evidence (emissions data, enforcement rulings, lobbying records) |
| 81–100 | `CONFIRMED_GREENWASHING` | Multiple high-confidence sources contradict the claim; and/or prior regulatory or judicial enforcement action exists |

Prasine Index does not give legal advice. Published reports are evidence compilations intended to support journalistic investigation and civil society accountability work.

---

## Example Output

Below is an abridged real pipeline output for Ryanair's "Europe's greenest airline" claim.

**Claim:** *"Ryanair is Europe's greenest airline."*
**Verdict:** `CONFIRMED_GREENWASHING` — Score: **82 / 100**

```text
REGULATORY ENFORCEMENT ACTIONS
  Ruling body: ENFORCEMENT | Year: 2022 | Confidence: 0.90
  Supports claim: False
  UK Advertising Standards Authority (ASA) banned Ryanair advertisements in 2022
  for claiming to be Europe's greenest airline without substantiation.

EU ETS VERIFIED EMISSIONS (2005–2023)
  Trend: UP 41% from 2005 to 2023
  Most recent: 9,821,432 tCO2e (2023)
  Supports claim: False (confidence: 0.75)
  Ryanair's verified CO2 emissions increased 41% over the monitoring period.

INFLUENCE MAP
  Score: D+ (obstructive climate lobbying)
  Supports claim: False (confidence: 0.85)
  InfluenceMap D+ band: Ryanair has opposed fuel taxation and lobbied against
  aviation inclusion in the EU ETS.
```

**Judge reasoning (excerpt):** *"The ASA ruling is the highest-weight evidence: an independent regulatory authority has already determined this specific claim to be misleading. EU ETS verified emissions showing a 41% increase directly contradict the 'greenest' assertion. InfluenceMap D+ confirms that the green positioning is contradicted by policy behaviour. Score: 82 — CONFIRMED_GREENWASHING."*

Full example reports are in [examples/](examples/).

---

## Licence

MIT
