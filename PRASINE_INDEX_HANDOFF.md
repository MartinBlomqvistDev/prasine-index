# Prasine Index — Claude Code Session Handoff

*Read this before writing a single line of code.*

---

## What This Is

Prasine Index is a portfolio project for an AI Engineering job search. It is an open,
live-running AI workflow system that automatically monitors and scores greenwashing
by EU-listed companies — with a full evidence chain that can be cited by journalists,
NGOs, and in court.

The name: *prasine* from Latin/Greek *prasinus* (green). The Index tracks and scores
every green claim made by EU companies against real emissions data.

Target audience for the finished project: Greenpeace, WWF, ClientEarth, EU journalists,
The Guardian, investigative reporters. It should look and feel like something that
already ought to exist in Brussels.

This is also a learning project. The developer (Martin) has strong Python/FastAPI/Asyncio/
Pydantic v2/Anthropic SDK skills (see GALDR Engine for reference). He is learning
LangGraph through this project. Do not suggest LangChain v1 patterns — use LangGraph
(langgraph) exclusively for orchestration where a framework is warranted.

---

## Why This Project Exists (the strategic reasoning)

Martin had an interview at Kognity for an AI Workflow Engineer role. The rejection
stated: "your experience and focus on specific tools and frameworks did not fully align
with the immediate needs of this role." Translation: they wanted LangChain/LangGraph
on the CV.

Prasine Index solves this by using LangGraph where it genuinely adds value (the
Verification Agent with multi-tool parallel calls) while using raw Anthropic SDK
where full control matters (Extraction, Judge, Report agents). The README will
explain this architectural decision explicitly — showing Martin understands tradeoffs,
not just copying tutorials.

---

## Architecture Decisions (do not relitigate these)

### Agent pipeline

7 agents in sequence:

```
Discovery Agent
      ↓
Claim Extraction Agent
      ↓
Context Agent
      ↓
Verification Agent      ← LangGraph here
      ↓
Lobbying Agent
      ↓
Judge Agent
      ↓
Report Agent
```

**Discovery Agent** — monitors EU company IR pages, press releases, CSRD reports
continuously. Triggers the pipeline when new green claims are detected. This is what
makes the system *live* rather than manual.

**Claim Extraction Agent** — reads raw documents and isolates every green claim with
source, date, company, and page reference. Output: `List[Claim]`.
Uses raw Anthropic SDK. Reason: extraction is a single-step structured output task
where full control over the prompt and response format matters more than orchestration.

**Context Agent** — fetches the company's historical claims and scores from PostgreSQL
before verification begins. A claim that a company has made three times without
delivering is scored differently from a first-time claim.

**Verification Agent** — the heaviest agent. Queries CDP, EU ETS, Eurostat, and EUR-Lex
*in parallel* using `asyncio.gather()`. Uses LangGraph for orchestration because this
is the one agent where tool-calling across multiple external APIs benefits from a
framework's retry and state management. Output: `List[Evidence]`.

**Lobbying Agent** — cross-references the company against the EU Transparency Register.
If a company claims climate neutrality but lobbies against climate legislation in
Brussels, that is the strongest form of greenwashing. Separate agent with separate
responsibility.

**Judge Agent** — LLM-as-judge. Receives all Evidence + Context and produces a
`GreenwashingScore` (0–100) with reasoning. Uses raw Anthropic SDK. Reason: the
judging logic is sensitive and needs precise prompt control. Framework abstraction
here would obscure what the model is actually being asked to do.

**Report Agent** — generates the source-chained report. Every claim links to its
counter-evidence with citation. Output is designed to be citable in journalism and
litigation. Uses raw Anthropic SDK.

### Why LangGraph only for Verification Agent

This is an explicit architectural decision that must be documented in the README.
The argument: LangGraph adds value where you have multiple tools, parallel calls,
and complex retry logic. For single-purpose agents with precise output requirements,
raw Anthropic SDK gives better control and cleaner code. This shows Martin understands
*when* to use a framework, not just *that* frameworks exist.

### Storage

PostgreSQL with pgvector extension.

Two reasons for pgvector: (1) semantic search across historical claims — find all
companies that have made similar claims before. (2) shows vector database competence
without adding a separate service.

Tables needed at minimum:
- `companies` — EU company registry
- `claims` — every extracted green claim with lifecycle status
- `evidence` — verification results per claim, linked to claim
- `greenwashing_scores` — scored results per company per time period
- `trace_log` — full audit trail per claim, one row per agent step

### Claim Lifecycle

Every claim has a status field:

```
DETECTED → VERIFIED → SCORED → PUBLISHED → MONITORING
```

If a company makes the same claim again after being scored, the system detects it
automatically and flags it. If a company modifies a claim after Prasine Index
published a score, the system flags that too. This transforms the system from a
snapshot tool into an accountability tool over time. It is the killer feature.

### Production-grade requirements (non-negotiable)

These five things are what separate this from a tutorial project:

1. **Parallel verification** — `asyncio.gather()` for all data source queries in
   Verification Agent. Never sequential.

2. **Pydantic end-to-end** — every agent input and output is a Pydantic v2 model.
   No raw strings passed between agents. Ever. Models: `Claim`, `Evidence`,
   `GreenwashingScore`, `ClaimLifecycle`, `LobbyingRecord`, `CompanyContext`,
   `VerificationResult`, `AgentTrace`.

3. **Retry logic and failure handling per agent** — explicit error boundaries.
   What happens when CDP API is down? What happens when the LLM returns unexpected
   output? Each agent handles its own failures with defined fallback behaviour.
   Failures are logged, not silent.

4. **Golden eval dataset** — 20 known greenwashing cases with correct scores.
   Runs automatically on every pipeline change. This is LLMOps, not just building.

5. **Trace IDs** — every claim gets a unique trace ID at creation. It follows the
   claim through all 7 agents. Every agent step is logged with the trace ID, duration_ms,
   and outcome. Full replay is possible for any claim. This pattern comes from GALDR
   Engine (Martin's previous project) and from imvi-ai's structured logging with
   ContextVar.

---

## Tech Stack

```
Python 3.12
FastAPI
Asyncio
Pydantic v2
Anthropic SDK (raw) — Extraction, Judge, Report agents
LangGraph — Verification Agent
PostgreSQL + pgvector
```

No LangChain v1. No n8n. No Streamlit (yet — dashboard is FastAPI + HTML/JS).
No unnecessary dependencies. Every dependency must justify its presence.

---

## Data Sources (EU open data)

Start with these three — they are open and either have APIs or bulk download:

| Source | What it provides | Access |
|--------|-----------------|--------|
| EU ETS (European Trading System) | Actual verified emissions per installation | Open API, EUTL |
| CDP Open Data | Companies' self-reported climate data | Open download |
| EUR-Lex | CSRD reports, Green Claims Directive text | REST API |

Add later:
- EU Transparency Register — lobbying data (for Lobbying Agent)
- Eurostat — national emissions statistics

---

## Project Structure (proposed — adjust if needed)

```
prasine-index/
├── agents/
│   ├── discovery_agent.py
│   ├── extraction_agent.py
│   ├── context_agent.py
│   ├── verification_agent.py    ← LangGraph
│   ├── lobbying_agent.py
│   ├── judge_agent.py
│   └── report_agent.py
├── models/
│   ├── claim.py                 ← Claim, ClaimLifecycle
│   ├── evidence.py              ← Evidence, VerificationResult
│   ├── score.py                 ← GreenwashingScore
│   ├── company.py               ← Company, CompanyContext
│   ├── lobbying.py              ← LobbyingRecord
│   └── trace.py                 ← AgentTrace
├── core/
│   ├── pipeline.py              ← orchestrates all 7 agents
│   ├── database.py              ← PostgreSQL + pgvector connection
│   ├── logger.py                ← JSON structured logging + trace_id ContextVar
│   └── retry.py                 ← retry logic, error boundaries
├── ingest/
│   ├── eu_ets.py
│   ├── cdp.py
│   └── eurlex.py
├── api/
│   └── main.py                  ← FastAPI, REST endpoints
├── eval/
│   └── golden_dataset.py        ← 20 known greenwashing cases
├── tests/
│   └── test_models.py
├── .env.example
├── requirements.txt
└── README.md
```

---

## Where to Start

Start with the Pydantic models. They are the foundation everything else builds on.
Once the models are correct, the agent contracts are clear and the rest follows.

Order:
1. `models/claim.py` — `Claim`, `ClaimStatus` (the lifecycle enum), `ClaimLifecycle`
2. `models/evidence.py` — `Evidence`, `VerificationResult`
3. `models/score.py` — `GreenwashingScore`
4. `models/company.py` — `Company`, `CompanyContext`
5. `models/lobbying.py` — `LobbyingRecord`
6. `models/trace.py` — `AgentTrace`
7. `core/logger.py` — structured JSON logging with `contextvars.ContextVar` for trace_id
   (same pattern as imvi-ai's logger.py — Martin built this, he knows it)
8. `core/database.py` — PostgreSQL + pgvector setup
9. First agent: `agents/extraction_agent.py`

Do not start with the pipeline. Do not start with FastAPI. Models first.

---

## Code Standards (non-negotiable)

- Python 3.12
- All functions and methods type-hinted
- Pydantic v2 models everywhere (no dataclasses, no TypedDict for agent I/O)
- Built-in generic types: `list[str]`, `dict[str, int]` — not `List`, `Dict`
- Google-format docstrings on every class, method, function
- 2–4 sentence file description as comment at top of every file
- KISS, DRY, YAGNI, SoC, SRP
- No nested functions
- No regex where simple string methods suffice
- Composition over inheritance
- Each significant public class in its own file

---

## What Martin Already Knows (but please explain either way)

- FastAPI, Asyncio, Pydantic v2 — strong, used in GALDR Engine and imvi-ai
- Anthropic SDK tool use and SSE streaming — built from scratch in imvi-ai
- Structured logging with ContextVar — built in imvi-ai
- Trace IDs through async pipelines — built in GALDR Engine
- PostgreSQL via SQLAlchemy — used in imvi-ai
- LangGraph — learning through this project, explain decisions but do not patronise

---

## Current Implementation State (updated 2026-04-05)

### Pipeline status: WORKING end-to-end

Entry point: `Pipeline().run_from_document(ExtractionInput(...))`

```python
from agents.extraction_agent import ExtractionInput
from core.pipeline import Pipeline
import uuid

extraction_input = ExtractionInput(
    trace_id=uuid.uuid4(),
    company_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    source_url="https://example.com/sustainability",
    source_type="IR_PAGE",   # one of: CSRD_REPORT, ANNUAL_REPORT, PRESS_RELEASE, IR_PAGE, WEBSITE, SOCIAL_MEDIA
    raw_content="Full document text here...",
)
results = await Pipeline().run_from_document(extraction_input)
```

### Real data source: EU ETS

`ingest/eu_ets.py` loads `EUTL24/operators_yearly_activity_daily.csv` into memory
on first call (lazy-loaded, module-level cache). Primary source is the official EU
Union Registry daily snapshot (snapshot_date=2026-04-05). Falls back to
`eutl_2024_202410/compliance.csv` if the daily file is absent.

No HTTP calls at runtime — pure CSV lookup.

**Installation ID formats:**

- DB stores numeric strings: `["201078", "216762", "210498"]`
- `_parse_installation_id()` accepts both `"201078"` and `"IE_201078"` → numeric int
- The EUTL daily CSV uses numeric-only IDs in `INSTALLATION_IDENTIFIER`

**Refreshing EUTL data** (run monthly):

```bash
python scripts/refresh_eutl.py
```

Or use `scripts/refresh_eutl.bat` in Windows Task Scheduler.

**Finding a company's installation IDs** (needed when seeding a new company):

```bash
# Search EUTL24/operators_daily.csv for ACCOUNT_HOLDER_NAME matching the company
grep -i "shell" EUTL24/operators_daily.csv | cut -d, -f1
# Then add matching name_filters to scripts/seed_eval_companies.py and re-run
```

**Ryanair in DB:**

- Company ID: `00000000-0000-0000-0000-000000000001`
- EU ETS installations: `["201078", "216762", "210498"]` (numeric, no country prefix)
- Test result: "Europe's greenest airline" → GREENWASHING 72/100

### All 20 eval companies seeded

Run `python scripts/seed_eval_companies.py` to (re-)seed. Uses deterministic UUIDs
`00000000-0000-0000-0000-000000000001` through `...000019`. Ryanair is skipped
(already present). The GW-020 slot is a VW duplicate — also skipped.

Installation counts after seeding (approximate, from operators_daily.csv name search):
VW=10, Shell=30, Eni=18, Nestlé=24, Lufthansa=7, HeidelbergMaterials=69,
TotalEnergies=35, HSBC=0 (bank), Ørsted=14, BP=14, ArcelorMittal=83, Maersk=4,
Glencore=0 (holding co.), Airbus=15, Unilever=8, easyJet=3, Vestas=0, Holcim=35.

### Ingest modules: status

| Module | Status | Notes |
| --- | --- | --- |
| `ingest/eu_ets.py` | ✅ Working | Daily snapshot, 2005–2024 actuals, ~10,879 installations |
| `ingest/eurlex.py` | ✅ Working | Static regulatory standards (Green Claims Dir, CSRD, EU ETS Dir) |
| `ingest/cdp.py` | ✅ Working | Local bulk CSV — `data/cdp_companies.csv` (free account download from data.cdp.net) |
| `ingest/sbti.py` | ✅ Working | Local bulk CSV — `data/sbti_companies.csv` (auto-download via `scripts/refresh_sbti.py`) |

**SBTi data** — `python scripts/refresh_sbti.py`. No account required.
Saves to `data/sbti_companies.csv`. Removed targets = CONFIRMED_GREENWASHING signal at 0.95 confidence.

**CDP data** — free account required. `python scripts/refresh_cdp.py` for instructions.
Saves to `data/cdp_companies.csv`. Self-reported; confidence capped at 0.65.

**E-PRTR data** — `python scripts/refresh_eprtr.py`. No account required.
Saves to `data/eprtr_releases.csv`. Non-CO2 GHGs (CH4, N2O, HFCs) per industrial facility.
- Rising GHGs (≥20%) → contradicts claim, confidence 0.75
- Falling GHGs (≤-30%) → supports claim, confidence 0.75
- Flat trend → inconclusive, confidence 0.55

**InfluenceMap data** — `python scripts/refresh_influencemap.py`. No account required.
Saves to `data/influencemap_companies.csv`. Lobbying alignment A+ to F.
- D/E/F (obstructive) → contradicts green claims, confidence 0.85
- A+/A/A-/B+ (supportive) → supports green claims, confidence 0.75
- B-/C bands → inconclusive, confidence 0.50

**Verification graph** now has 6 parallel nodes: `fetch_eu_ets`, `fetch_cdp`, `fetch_sbti`,
`fetch_eprtr`, `fetch_influence_map`, `fetch_eurlex`.
`sources_queried` metadata: `["EU_ETS", "CDP", "SBTI", "EPRTR", "INFLUENCE_MAP", "EUR_LEX"]`.

**E-PRTR data** — `python scripts/refresh_eprtr.py`. No account required.
Saves to `data/eprtr_releases.csv`. Tries EEA industrial portal URL first; falls back with manual instructions if download fails.

**InfluenceMap data** — `python scripts/refresh_influencemap.py`. No account required.
Saves to `data/influencemap_companies.csv`.

**Enforcement rulings** — static database embedded in `ingest/enforcement.py`. No refresh needed.
Covers: ASA, ACM, AGCM, CMA, EC, Dutch courts. 15 rulings across 11 companies.
Companies with rulings in the database: Ryanair, HSBC, Shell, KLM/Air France-KLM, Lufthansa,
easyJet, Eni, ArcelorMittal, BP, TotalEnergies, Volkswagen, Glencore.
Confidence: FINED=0.95, BANNED/CONFIRMED_MISLEADING=0.90, WARNING=0.80, INVESTIGATION=0.70.
Returns one Evidence record per ruling — a company with three rulings generates three Evidence items.

**CA100+ data** — `python scripts/refresh_ca100.py`. No account required.
Saves to `data/ca100_companies.csv`. Covers 170 highest-emitting listed companies.
- NOT_ALIGNED + NOT_ALIGNED capex → False, 0.85
- NOT_ALIGNED → False, 0.80
- ALIGNED → True, 0.65–0.75

**Banking on Climate Chaos** — `python scripts/refresh_fossil_finance.py`. No account required.
Saves to `data/fossil_finance_banks.csv`. Covers ~60 largest private-sector banks.
- >$100bn total + net-zero pledge → False, 0.88 (hypocrisy signal)
- >$100bn total → False, 0.80
- >$30bn total → False, 0.65–0.75

**Global Coal Exit List (GCEL)** — `python scripts/refresh_gcel.py`. No account required.
Saves to `data/gcel_companies.csv`. Covers ~1,000 coal-chain companies.
- Expanding → False, 0.90
- Listed but phase-out plan → None, 0.55
- Listed, status unclear → False, 0.65

**Verification graph** now has 10 parallel nodes: `fetch_eu_ets`, `fetch_cdp`, `fetch_sbti`,
`fetch_eprtr`, `fetch_influence_map`, `fetch_enforcement`, `fetch_ca100`,
`fetch_fossil_finance`, `fetch_coal_exit`, `fetch_eurlex`.
`sources_queried`: see `sources_queried` list in `verification_agent.py`.

**New enum values** in `models/evidence.py`:
- `EvidenceSource.CA100 = "CA100"`
- `EvidenceSource.FOSSIL_FINANCE = "FOSSIL_FINANCE"`
- `EvidenceSource.COAL_EXIT = "COAL_EXIT"`
- `EvidenceType.BENCHMARK_ASSESSMENT = "BENCHMARK_ASSESSMENT"` (for CA100+)
- `EvidenceType.FINANCING_RECORD = "FINANCING_RECORD"` (for fossil finance)

**New enum values** in `models/evidence.py`:
- `EvidenceSource.EPRTR = "EPRTR"`
- `EvidenceSource.INFLUENCE_MAP = "INFLUENCE_MAP"`
- `EvidenceSource.ENFORCEMENT = "ENFORCEMENT"`
- `EvidenceType.POLLUTION_RECORD = "POLLUTION_RECORD"` (for E-PRTR)
- `EvidenceType.ENFORCEMENT_RULING = "ENFORCEMENT_RULING"` (for enforcement)

### Judge Agent calibration

`agents/judge_agent.py` system prompt includes explicit score-to-verdict bands:

```
0–20   → SUBSTANTIATED
21–45  → INSUFFICIENT_EVIDENCE
46–60  → MISLEADING
61–80  → GREENWASHING
81–100 → CONFIRMED_GREENWASHING
```

CONFIRMED_GREENWASHING requires lobbying evidence (Lobbying Agent not yet wired with
live data). Claims that would require this verdict are currently capped at GREENWASHING.

### Eval dataset: golden_dataset.py

20 cases in `eval/golden_dataset.py`. Each `EvalCase` has a `company_id` field
(deterministic UUID) so the pipeline fetches real company data from the DB.

Current accuracy on 5-case quick subset: **4/5 (80%)**. Known failures:

- GW-010 Ørsted: getting GREENWASHING/68-72, expected SUBSTANTIATED (0–25). Root cause:
  claim text contains "87% reduction since 2006" (historical, substantiated) AND "carbon
  neutral by 2025" (expired forward-looking target). Judge penalises the expired forward-
  looking element. Eval expectation may need revision — the mixed claim is legitimately
  harder to score as SUBSTANTIATED.
- GW-014 Glencore: now passing (GREENWASHING 65, within 65–95 expected range).

SBTi integration will improve scoring on claims that reference science-based targets,
net zero, or 1.5°C alignment — these are common greenwashing markers with externally
validated ground truth from SBTi.

### Database

Supabase (hosted PostgreSQL + pgvector). **Must use Session pooler URL** — direct DB
DNS fails on IPv6. URL is in `.env` as `DATABASE_URL`.

Schema is created by `core/database.py:init_db()` → `_create_schema()` using raw DDL
(`Base.metadata.create_all` is a no-op with no ORM models).

### Critical asyncpg gotcha

Named bind params (`:param`) and PostgreSQL `::` cast syntax conflict in asyncpg.
**Never write** `:value::jsonb`. Pass the value as a plain `:value` param; PostgreSQL
infers the type. This affected `_persist_trace` and `_persist_score` in `pipeline.py`.

### Key bugs already fixed (do not re-introduce)

- `::jsonb` casts in asyncpg named params → removed from `pipeline.py`
- `Base.metadata.create_all` with no ORM models → `_create_schema()` raw DDL
- `@retry_async` on SQLAlchemy session-bound methods → `InFailedSQLTransactionError` on retry → removed from `context_agent.py`
- `PipelineConfig` model defaults were Opus → fixed to Haiku
- `eu_ets.py` trend assessment used 3-year window → fixed to full-history oldest vs newest
- `eu_ets.py` evidence summary only showed last 5 years → fixed to show full history (oldest 2 + … + recent 5 if >12 years, otherwise all)
- Judge defaulting to 72/GREENWASHING for all uncertain cases → fixed by adding explicit score bands to system prompt

---

## What This Project Must Demonstrate for Hiring Managers

1. LangGraph usage with motivated architectural decision (not just "I used LangGraph")
2. Multi-agent pipeline with clean separation of concerns
3. Production-grade observability (structured logging, trace IDs, latency per agent)
4. LLM-as-judge eval pattern
5. Real external data sources, not fabricated test data
6. Parallel async at the right layer
7. A real problem that real organisations care about
