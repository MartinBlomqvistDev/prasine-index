# Prasine Index — Dev Log

Real failures encountered during development, with root cause and fix.
Ordered roughly chronologically. Useful for interview prep and post-mortems.

---

## 2026-05-04 — JS-rendered page returns empty content

**Symptom:** Discovery Agent fetched `https://www.oresundskraft.se/hallbarhet/` and
extracted zero claims. The page existed but the pipeline treated it as blank.

**Root cause:** The sustainability page was rendered client-side via JavaScript.
`urllib.request` fetches raw HTML; if content is injected by JS after load,
the fetch returns a shell with no body text. The scraper saw nothing.

**Fix:** Found a static fallback URL (`/hallbarhetsarbete/`) that returned
server-rendered HTML. Longer term: the discovery agent now scores links before
fetching and deprioritises SPA-style URLs. A proper fix would be a headless
browser fallback (Playwright), but the cost/complexity tradeoff is not justified yet.

**Lesson:** Never assume a URL that loads in a browser will return meaningful HTML
to a plain HTTP client. JS rendering is the rule for modern corporate sustainability
pages, not the exception.

---

## 2026-05-04 — Discovery Agent never followed subpage links

**Symptom:** For Öresundskraft, the pipeline only assessed the root URL and missed
the dedicated CCS project page (`/ccs`) which contained the most specific claim
(200,000 tonnes CO₂/year from 2029, EU Innovation Fund grant of EUR 54M).

**Root cause:** `_collect_urls()` returned only the seed URL. There was no link
extraction or subpage discovery — the agent never looked at what the page linked to.

**Fix:** Added `extract_relevant_links(html, base_url, max_links=5)` — an HTML
parser that scores links by sustainability keyword density (bilingual, Swedish +
English) and returns the top N same-domain subpages. The pipeline now runs a
three-phase approach:
1. Fetch seed URL + up to 5 scored subpages
2. Extract all claims cheaply (extraction agent only)
3. Rank all claims by priority score, run full pipeline on top N

**Lesson:** A greenwashing monitor that only reads one page is not a greenwashing
monitor. Corporate CCS/net-zero claims are almost always on dedicated subpages,
not the homepage.

---

## 2026-05-04 — Wrong claims selected for expensive pipeline runs

**Symptom:** The pipeline was spending tokens on vague heading-level claims
("Öresundskraft arbetar för ett hållbart samhälle") and skipping the specific
quantified commitment (200,000 tonnes CO₂/year by 2029).

**Root cause:** Claims were selected by extraction order (first N from the page),
not by specificity. The extraction agent returned headings before body claims.

**Fix:** Added `_claim_priority_score()` with three layers:
- Category weight: NET_ZERO_TARGET=10, CARBON_NEUTRAL=9, EMISSIONS_REDUCTION=8, etc.
- Specificity patterns: percentage figures, tonnage, year targets, named standards
- Compound bonus (+5): large number AND year in the same claim
- Technology bonus (+3): CCS, carbon capture, electrolysis, hydrogen keywords

Claims are now ranked before expensive runs. The CCS/Innozhero claim correctly
scores highest and runs first.

**Lesson:** Extraction order is not claim importance. For cost-capped pipelines,
the ranking step is as important as the extraction step.

---

## 2026-05-04 — Report files silently overwriting each other

**Symptom:** Running the pipeline on Öresundskraft with `max_claims=3` produced
only one report file (`resundskraft.md`) instead of three. The first two claims
were silently lost.

**Root cause:** Every claim result wrote to `{slug}.md`, overwriting the previous
write in the same run. Only the last claim survived.

**Fix:** Each claim now writes to `{slug}-{i}.md` (numbered). The canonical
`{slug}.md` is written once at the end, set to the highest-scoring claim.
The terminal output now also prints the first 120 characters of each claim for
immediate verification.

**Lesson:** Silent data loss is worse than an error. If output is being overwritten,
you have no way to know until you notice the file count is wrong.

---

## 2026-05-04 — Judge Agent crashes on None in score breakdown

**Symptom:** Pipeline crashed with `TypeError: float() argument must be a string
or real number, not 'NoneType'` in `judge_agent.py:_build_score`.

**Root cause:** The LLM's tool call response occasionally returned `null` for a
score dimension (e.g. `historical_consistency: null` when no prior claims existed).
The dict comprehension passed `None` directly to `float()`.

**Fix:** Added `if v is not None` filter in the score breakdown dict comprehension.
None values are now excluded from the weighted average rather than crashing it.

**Lesson:** LLM tool call responses are external data. Even with forced tool use
and a strict Pydantic schema, null fields slip through. Validate at the boundary.

---

## 2026-05-04 — 429 rate limiting under concurrent extraction

**Symptom:** Pipeline crashed with HTTP 429 (Too Many Requests) from the Anthropic
API when running extraction concurrently across multiple pages via `asyncio.gather()`.

**Root cause:** Three concurrent extraction agent calls hit Anthropic's per-minute
token rate limit simultaneously. The burst was within the theoretical limit but
the bursting window was too narrow.

**Fix:** Replaced `asyncio.gather()` with a sequential for loop in the multi-page
extraction phase. Latency increases linearly with page count, but the pipeline
no longer self-disrupts on moderate-sized runs.

**Trade-off noted:** For a production system with a paid tier and proper retry
logic, `asyncio.gather()` with exponential backoff is the right answer. The
sequential loop is the right answer for a dev-tier pipeline where token budget
matters more than latency.

**Lesson:** Concurrent LLM calls at development API limits will hit 429s reliably.
Design for sequential-first, parallel-later, not the reverse.

---

## 2026-05-04 — Ruff CI failures after version drift

**Symptom:** CI pipeline failed on `ruff` formatting checks after a dependency
update pulled in a newer ruff version with stricter import sorting rules.

**Root cause:** `requirements.txt` had `ruff` without a pinned version. A minor
version bump changed the expected import order for `from __future__ import annotations`.

**Fix:** Pinned `ruff==0.15.8` in `requirements.txt`. All files reformatted
to match.

**Lesson:** Linter versions must be pinned. A formatting-only CI failure that
blocks a real fix is a workflow tax that compounds over time.

---

## 2026-05-04 — `_re.I` undefined after import cleanup

**Symptom:** `NameError: name '_re' is not defined` at runtime after refactoring
`import re as _re` to `import re` in `pipeline.py`.

**Root cause:** The refactor renamed the import alias but missed several call sites
that still referenced `_re.I` (the case-insensitive regex flag).

**Fix:** Global find-replace `_re.` → `re.` across the file. Confirmed with
`python -c "from core.pipeline import Pipeline"` before committing.

**Lesson:** Alias renames require a full search across the file, not just the
import line. A quick import test catches this before CI does.

---

## 2026-05-04 — `SourceType` undefined in pipeline.py (F821)

**Symptom:** Ruff raised `F821 Undefined name 'SourceType'` in `pipeline.py`
during CI, blocking merge.

**Root cause:** `run_from_url()` used `SourceType.IR_PAGE` but `SourceType` was
not included in the `from models.claim import ...` line when the method was added.

**Fix:** Added `SourceType` to the import statement.

**Lesson:** When adding new functionality that references symbols from existing
modules, check the import block explicitly. Ruff F821 catches this but only
at lint time — a type checker running in the editor would catch it immediately.

---

## 2026-05-05 — Swedish characters stripped from report filenames

**Symptom:** `Öresundskraft` assessment saved to `resundskraft.md` — the `Ö`
was stripped entirely, not transliterated.

**Root cause:** `_slug()` uses a regex `[^a-z0-9]+` which removes non-ASCII
characters rather than mapping them to ASCII equivalents. `Ö` → `""` not `"o"`.

**Fix:** Added `unicodedata.normalize("NFKD", name).encode("ascii", "ignore")`
before the regex. NFKD decomposes composed characters to their base ASCII
equivalents before stripping — `Ö` → `O` → `o`, `Å` → `A` → `a`. No lookup
table needed; handles all European diacritics automatically.

**Lesson:** Unicode normalisation via NFKD is the robust solution for slug
generation over arbitrary European company names. A lookup table would miss
characters; regex stripping silently truncates names.

---

## 2026-05-05 — ruff format CI failure on 19 new files

**Symptom:** CI passed `ruff check` but failed `ruff format --check` on all
19 new and modified files added during the 21-source expansion.

**Root cause:** Files were written manually and not run through `ruff format`
before committing. `ruff format` and `ruff check` are separate passes — the
linter does not enforce formatting; the formatter does not enforce lint rules.

**Fix:** `ruff format <files>` run locally, one extra commit.

**Lesson:** The CI workflow runs both `ruff check` and `ruff format --check`
as separate steps. Always run `ruff format .` before committing new files,
not just `ruff check .`.

---

## 2026-05-05 — mypy return-value error in edgar.py

**Symptom:** mypy reported `Incompatible return value type` on `_ensure_loaded()`:
returned `tuple[dict | None, dict]` but signature declared `tuple[dict, dict]`.

**Root cause:** The module-level `_totals_cache` is typed `dict | None`. After
the `if _totals_cache is None` guard assigns to it, mypy does not narrow the
type back to `dict` — the global write is not flow-analysed as narrowing.

**Fix:** `return _totals_cache or {}, _sector_cache or {}` — the `or {}` guards
both values at the return site, satisfying the declared return type.

**Lesson:** mypy does not narrow module-level globals through assignment in
conditionals. Either use a local variable or guard at the return site.

---

## 2026-05-05 — mypy no-any-return in climate_trace.py

**Symptom:** mypy reported `Returning Any from function declared to return
dict[str, Any]` on `json.loads()` in `_fetch_aggregate_sync()`.

**Root cause:** `json.loads()` returns `Any` in typeshed. Returning `Any` from
a function with a concrete return type annotation violates `no-any-return`.

**Fix:** `cast("dict[str, Any]", json.loads(...))` with a quoted string argument
(required by ruff TC006 — type expressions in `cast()` must be strings in
Python 3.12+ type narrowing contexts).

**Lesson:** `json.loads()` always returns `Any`. Any function that parses JSON
and returns a typed structure needs an explicit cast at the return site.

---

## Pipeline architecture decisions that proved correct

**LangGraph only in Verification Agent.** Originally considered using it for the
full pipeline. The Verification Agent's parallel fan-out to 21 independent sources
with partial failure tolerance is exactly the problem LangGraph solves. The other
agents are single LLM calls — wrapping them in a state machine would add
indirection with no benefit. This boundary held cleanly throughout development.

**Pydantic v2 contracts at every agent boundary.** Caught the `None` in the judge
score breakdown, caught missing fields in extraction output, caught type mismatches
in pipeline wiring. Every agent boundary is a validation checkpoint.

**Three-phase `run_from_url()`.** Extract cheap first, rank, then run expensive.
This was the correct answer to the token spend problem. The alternative (run full
pipeline on every discovered claim) would have been 5-10x more expensive per run.
