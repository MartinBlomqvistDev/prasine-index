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
3. **Verifies** each claim against EU ETS verified emissions data, CDP self-reported disclosures, and EUR-Lex legislative records — in parallel.
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
Verification Agent        ← LangGraph (parallel fan-out)
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

**Verification Agent** — queries ten parallel sources: EU ETS, CDP, SBTi, E-PRTR, InfluenceMap, enforcement rulings, CA100+, Banking on Climate Chaos, GCEL, and EUR-Lex, aggregating results into a `VerificationResult`. See [Why LangGraph is used here and nowhere else](#why-langgraph-for-the-verification-agent-only) below.

**Lobbying Agent** — retrieves the company's Transparency Register record and classifies whether its lobbying activity contradicts its green claims.

**Judge Agent** — LLM-as-judge. Receives the complete evidence package and produces a calibrated `GreenwashingScore` (0–100) with per-dimension breakdown and full chain-of-thought reasoning.

**Report Agent** — generates the publication-ready Markdown report with inline source citations.

---

### Why LangGraph for the Verification Agent Only

This is the most important architectural decision in the codebase, and it is deliberate.

**The case for LangGraph at the Verification Agent:**

The Verification Agent queries ten independent data sources — EU ETS, CDP, SBTi, E-PRTR, InfluenceMap, enforcement rulings, CA100+, Banking on Climate Chaos, GCEL, and EUR-Lex — and must:

- Execute all four queries concurrently (never sequentially — latency would compound)
- Accumulate results from each branch as they complete
- Handle partial failures gracefully: if CDP is down, the pipeline must continue with the evidence that was retrieved, not fail entirely
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

**The result:** Prasine Index uses LangGraph where it genuinely adds value (multi-tool parallel calls with partial failure tolerance), and raw Anthropic SDK where full control matters (single-step LLM calls with precise prompt requirements). This shows understanding of *when* to use a framework, not just *that* frameworks exist.

---

### Data Model

Every agent communicates exclusively through Pydantic v2 models. No raw strings or untyped dicts cross agent boundaries.

| Model | Description |
| ----- | ----------- |
| `Claim` | Atomic unit of work: a single green claim with full provenance |
| `ClaimLifecycle` | Immutable status transition record; one row per status change |
| `Evidence` | A single data point from one EU open data source |
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

The Verification Agent never queries data sources sequentially. The LangGraph graph fans out to all sources simultaneously from `START`; the `operator.add` reducer on the `evidence` list merges partial results as each branch completes. A source that takes 8 seconds does not hold up a source that takes 1 second.

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
| Verification orchestration | LangGraph | Multi-tool parallel fan-out with partial failure tolerance — the specific problem LangGraph solves well |
| Data validation | Pydantic v2 | Runtime-validated agent contracts; no untyped data at boundaries |
| API | FastAPI | Async-native, Pydantic-native, production-grade |
| Database | PostgreSQL 15 + pgvector | Relational integrity + vector similarity in one service |
| HTTP client | httpx | Async-native; consistent interface for all external API calls |

---

## Data Sources

| Source | What It Provides | Status |
| ------ | ---------------- | ------ |
| EU ETS EUTL | **Verified** annual CO2 emissions per installation, 2005–present | **Active** — daily snapshot from union-registry-data.ec.europa.eu |
| CDP Open Data | Self-reported scores, targets, governance | **Paywalled** — `data.cdp.net` is cities/regions only; corporate scores require investor signatory or paid access |
| SBTi Companies Taking Action | Validated/removed near-term and net-zero targets | **Active** — local bulk CSV via `scripts/refresh_sbti.py` |
| E-PRTR (EEA) | Verified non-CO2 GHG releases per facility (CH4, N2O, HFCs) | **Active** — local bulk CSV via `scripts/refresh_eprtr.py` |
| InfluenceMap | Corporate climate lobbying scores (A+ to F) | **Active** — local bulk CSV via `scripts/refresh_influencemap.py` |
| Enforcement rulings | ASA, ACM, AGCM, CMA, EC, court judgments against greenwashing claims | **Active** — static curated database (no refresh needed) |
| Climate Action 100+ | Net-zero benchmark for 170 largest emitters (700+ investors, $68tn AUM) | **Active** — local bulk CSV via `scripts/refresh_ca100.py` |
| Banking on Climate Chaos | Fossil fuel financing by 60 largest banks, 2016–present | **Active** — local bulk CSV via `scripts/refresh_fossil_finance.py` |
| Global Coal Exit List (GCEL) | ~1,000 companies active in coal mining or power | **Active** — local bulk CSV via `scripts/refresh_gcel.py` |
| EUR-Lex | Green Claims Directive, CSRD, and EU ETS legislation as regulatory baseline | **Active** — static standards (legislation does not change) |
| EU Transparency Register | Lobbying activities and fields of interest | Planned — Lobbying Agent |

**EU ETS** data is verified by accredited independent third parties under EU Regulation 601/2012. It is the highest-quality ground truth for CO2 emission claims — a company claiming reductions that do not appear in EUTL verified data is the most direct greenwashing signal available.

**E-PRTR** extends the emissions picture to non-CO2 GHGs (methane, nitrous oxide, HFCs, etc.) and industrial pollutants not covered by the EU carbon market. Published annually by the EEA under E-PRTR Regulation (EC) No 166/2006.

**SBTi** targets are externally validated by the Science Based Targets initiative. A removed or expired target — while the company continues to claim science-based alignment — is a CONFIRMED_GREENWASHING signal.

**InfluenceMap** independently scores corporate climate policy engagement A+ (strongly supportive) to F (obstructive). A company scoring D or worse while making green claims is engaging in textbook greenwashing: publicly claiming climate leadership while privately lobbying against climate legislation.

**Enforcement rulings** is a curated static database of confirmed regulatory bans, fines, misleading-claim rulings, and active investigations from ASA (UK), ACM (Netherlands), AGCM (Italy), CMA (UK), the European Commission, and national courts. A prior regulatory ruling against a company's green claims is the strongest possible evidence category — an independent authority has already determined the claim was unsubstantiated. No refresh script is needed; rulings are permanent and embedded directly in the module.

**Climate Action 100+ (CA100+)** is the world's largest investor-led initiative, assessing the 170 highest-emitting listed companies against a standardised net-zero benchmark (net-zero ambition, decarbonisation targets, capex alignment). Backed by 700+ investors representing $68 trillion AUM. A company claiming net-zero ambition while rated "Not Aligned" by CA100+ is contradicted by the consensus of the world's largest institutional investors.

**Banking on Climate Chaos** tracks fossil fuel financing by the world's 60 largest banks from 2016 onwards, published annually by RAN, Sierra Club, and Oil Change International. A bank claiming net-zero leadership while financing hundreds of billions in fossil fuel expansion — the HSBC pattern — is the canonical financial sector greenwashing case.

**Global Coal Exit List (GCEL)** by Urgewald tracks ~1,000 companies across the coal value chain. A company listed as actively expanding coal capacity while claiming a clean-energy transition fails the standard coal screen used by 400+ financial institutions under GFANZ and PAII.

The EUR-Lex ingest returns the applicable legislative standards (Green Claims Directive Article 3, CSRD ESRS E1, EU ETS Article 15) as structured evidence per claim category. No API call is made — the legislation is stable and embedded directly in the module.

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
# PostgreSQL must be running with pgvector installed.
# init_db() in core/database.py creates all tables on first startup.
# To run manually:
python -c "import asyncio; from core.database import init_db; asyncio.run(init_db())"
```

### Seeding Evaluation Companies

```bash
# Inserts all 20 golden dataset companies with deterministic UUIDs.
# Safe to re-run — uses INSERT ... ON CONFLICT DO NOTHING.
# Reads EU ETS installation IDs from EUTL24/operators_daily.csv automatically.
python scripts/seed_eval_companies.py
```

### Refreshing EU ETS Data

The EUTL daily snapshot is downloaded from the EU Union Registry and stored locally. Run monthly or on demand:

```bash
python scripts/refresh_eutl.py
```

On Windows, `scripts/refresh_eutl.bat` is provided for Windows Task Scheduler.

### Refreshing SBTi Data

SBTi publishes a bulk CSV of all companies with active, committed, or removed targets. No account required:

```bash
python scripts/refresh_sbti.py
```

Saves to `data/sbti_companies.csv`. Run when a new SBTi data release is announced (typically quarterly).

### Refreshing CDP Data

CDP requires a free account for bulk downloads. Run the script to see manual instructions:

```bash
python scripts/refresh_cdp.py
```

Saves to `data/cdp_companies.csv`. Download the latest survey year from data.cdp.net and place it there.

### Refreshing E-PRTR Data

E-PRTR non-CO2 GHG release data from the EEA (all industrial facilities, all pollutants):

```bash
python scripts/refresh_eprtr.py
```

Saves to `data/eprtr_releases.csv`. No account required.

### Refreshing InfluenceMap Data

InfluenceMap corporate climate lobbying scores:

```bash
python scripts/refresh_influencemap.py
```

Saves to `data/influencemap_companies.csv`. No account required.

### Refreshing CA100+ Data

Climate Action 100+ net-zero benchmark (170 largest emitters, updated annually):

```bash
python scripts/refresh_ca100.py
```

Saves to `data/ca100_companies.csv`. No account required.

### Refreshing Banking on Climate Chaos Data

Fossil fuel financing by the 60 largest banks (updated annually in May):

```bash
python scripts/refresh_fossil_finance.py
```

Saves to `data/fossil_finance_banks.csv`. No account required.

### Refreshing the Global Coal Exit List

Urgewald GCEL — ~1,000 companies across the coal value chain (updated at COP):

```bash
python scripts/refresh_gcel.py
```

Saves to `data/gcel_companies.csv`. No account required.

### Running the API

```bash
uvicorn api.main:app --reload
```

API documentation is available at `http://localhost:8000/docs`.

### Submitting a Document for Assessment

```bash
curl -X POST http://localhost:8000/assess \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "00000000-0000-0000-0000-000000000001",
    "source_url": "https://example.com/sustainability-report-2024.pdf",
    "source_type": "CSRD_REPORT",
    "raw_content": "We will achieve net zero by 2040, with a 50% reduction in scope 1 and 2 emissions by 2030.",
    "publication_date": "2024-03-15"
  }'
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
│   ├── verification_agent.py   # Parallel EU data source queries (LangGraph)
│   ├── lobbying_agent.py       # EU Transparency Register cross-reference
│   ├── judge_agent.py          # LLM-as-judge scoring (raw Anthropic SDK)
│   └── report_agent.py         # Publication-ready report (raw Anthropic SDK)
├── models/
│   ├── claim.py                # Claim, ClaimStatus, ClaimLifecycle
│   ├── evidence.py             # Evidence, VerificationResult
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
│   ├── cdp.py                  # CDP self-reported scores (local CSV)
│   ├── sbti.py                 # SBTi validated/removed targets (local CSV)
│   ├── eprtr.py                # E-PRTR non-CO2 GHG releases (local CSV)
│   ├── influence_map.py        # InfluenceMap lobbying scores (local CSV)
│   ├── enforcement.py          # ASA/ACM/AGCM/CMA/EC rulings (static, embedded)
│   ├── ca100.py                # CA100+ net-zero benchmark (local CSV)
│   ├── fossil_finance.py       # Banking on Climate Chaos fossil financing (local CSV)
│   ├── coal_exit.py            # Urgewald GCEL coal exposure (local CSV)
│   └── eurlex.py               # EUR-Lex legislative context (static, embedded)
├── api/
│   └── main.py                 # FastAPI REST API
├── eval/
│   └── golden_dataset.py       # 20 known greenwashing cases + eval runner
├── scripts/
│   ├── refresh_eutl.py         # Download latest EU ETS daily snapshot
│   ├── refresh_eutl.bat        # Windows Task Scheduler wrapper
│   ├── refresh_sbti.py         # Download SBTi Companies Taking Action CSV
│   ├── refresh_cdp.py          # Instructions for CDP bulk CSV (requires free account)
│   ├── refresh_eprtr.py        # Download EEA E-PRTR pollutant releases CSV
│   ├── refresh_influencemap.py # Download InfluenceMap company scores CSV
│   ├── refresh_ca100.py        # Download CA100+ benchmark CSV
│   ├── refresh_fossil_finance.py  # Download Banking on Climate Chaos CSV
│   ├── refresh_gcel.py         # Download Urgewald Global Coal Exit List CSV
│   └── seed_eval_companies.py  # Insert all 20 eval companies with deterministic UUIDs
├── data/                       # Local bulk datasets (not committed — download via refresh scripts)
│   ├── sbti_companies.csv      # SBTi target data
│   ├── cdp_companies.csv       # CDP self-reported data
│   ├── eprtr_releases.csv      # E-PRTR non-CO2 GHG releases
│   ├── influencemap_companies.csv  # InfluenceMap lobbying scores
│   ├── ca100_companies.csv     # CA100+ net-zero benchmark
│   ├── fossil_finance_banks.csv   # Banking on Climate Chaos
│   └── gcel_companies.csv      # Global Coal Exit List
├── tests/
│   └── test_models.py          # Pydantic model unit tests
├── EUTL24/                     # EU ETS daily snapshot (not committed — download via refresh_eutl.py)
│   ├── operators_yearly_activity_daily.csv  # Verified emissions per installation per year
│   ├── operators_daily.csv                  # Installation names and account holder names
│   ├── accounts_daily.csv                   # Account metadata
│   └── registry_holdings_daily.csv          # Allowance holdings
├── .env.example
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

Greenwashing scores are calibrated against the EU Green Claims Directive, the Corporate Sustainability Reporting Directive (CSRD), and the EU Taxonomy Regulation. The scoring methodology and data source descriptions are published at `/docs`.

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
  for claiming to be Europe's greenest airline without substantiation. The ASA ruled
  the claim misleading and prohibited its use.

EU ETS VERIFIED EMISSIONS (2005–2023)
  Trend: UP 41% from 2005 to 2023
  Most recent: 9,821,432 tCO2e (2023)
  Supports claim: False (confidence: 0.75)
  Ryanair's verified CO2 emissions increased 41% over the monitoring period.
  Among the highest per-passenger emissions of any European airline.

INFLUENCE MAP
  Score: D+ (obstructive climate lobbying)
  Supports claim: False (confidence: 0.85)
  InfluenceMap D+ band: Ryanair has opposed fuel taxation and lobbied against
  aviation inclusion in the EU ETS.
```

**Judge reasoning (excerpt):** *"The ASA ruling is the highest-weight evidence: an independent regulatory authority has already determined this specific claim to be misleading. EU ETS verified emissions showing a 41% increase directly contradict the 'greenest' assertion. InfluenceMap D+ confirms that the green positioning is contradicted by policy behaviour. No evidence supports the claim. Score: 82 — CONFIRMED_GREENWASHING."*

Full example reports are in [examples/](examples/).

---

## Licence

MIT
