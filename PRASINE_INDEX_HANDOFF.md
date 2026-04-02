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

## What This Project Must Demonstrate for Hiring Managers

1. LangGraph usage with motivated architectural decision (not just "I used LangGraph")
2. Multi-agent pipeline with clean separation of concerns
3. Production-grade observability (structured logging, trace IDs, latency per agent)
4. LLM-as-judge eval pattern
5. Real external data sources, not fabricated test data
6. Parallel async at the right layer
7. A real problem that real organisations care about
