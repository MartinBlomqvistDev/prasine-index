"""Verification Agent for the Prasine Index pipeline.

Queries four EU open data sources — EU ETS, CDP, EUR-Lex, and Eurostat — in
parallel and aggregates the results into a VerificationResult passed to the
Judge Agent. This is the one agent in the pipeline that uses LangGraph for
orchestration: the parallel fan-out to four independent external APIs, combined
with per-source retry and the need to aggregate partial results when one or more
sources fail, is exactly the class of problem that benefits from a state machine
framework.
"""

from __future__ import annotations

import operator
import time
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from core.retry import DataSourceError, agent_error_boundary
from ingest.cdp import fetch_cdp_data
from ingest.eu_ets import fetch_eu_ets_data
from ingest.eurlex import fetch_eurlex_data
from models.claim import Claim
from models.company import CompanyContext
from models.evidence import Evidence, EvidenceSource, VerificationResult
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "VerificationAgent",
    "VerificationInput",
]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class VerificationState(TypedDict):
    """Mutable state threaded through the LangGraph verification graph.

    The ``evidence`` and ``data_gaps`` fields use ``Annotated`` with
    ``operator.add`` as the reducer. This means each parallel fetch node
    returns a partial list, and LangGraph's runtime merges all partial lists
    via concatenation — no node needs to know what the others returned.

    Attributes:
        claim: The claim under verification. Read-only across all nodes.
        context: Company context assembled by the Context Agent. Read-only.
        evidence: Evidence records accumulated across all fetch nodes.
            Each node appends its own records; LangGraph merges via operator.add.
        data_gaps: Source identifiers for which data retrieval failed.
            Each node appends its own failures; LangGraph merges via operator.add.
    """

    claim: Claim
    context: CompanyContext
    evidence: Annotated[list[Evidence], operator.add]
    data_gaps: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# I/O models
# ---------------------------------------------------------------------------

class VerificationInput(BaseModel):
    """Input contract for the Verification Agent.

    Produced by the pipeline orchestrator after the Context Agent completes.

    Attributes:
        claim: The claim to verify.
        context: Company context assembled by the Context Agent.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The claim to verify against EU open data sources.")
    context: CompanyContext = Field(..., description="Company context assembled by the Context Agent.")


# ---------------------------------------------------------------------------
# Graph node functions
# ---------------------------------------------------------------------------

async def _node_fetch_eu_ets(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch verified emissions data from the EU ETS EUTL.

    Queries the European Union Transaction Log for verified annual emissions
    data for all EU ETS installation IDs registered against this company.
    Returns partial state containing either the evidence record or a data gap
    entry if the upstream source is unavailable.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]
    installation_ids = context.company.eu_ets_installation_ids

    if not installation_ids:
        logger.info(
            "EU ETS fetch skipped: no installation IDs registered for company",
            extra={"operation": "fetch_eu_ets_skipped"},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: no installation IDs registered"],
        }

    try:
        evidence = await fetch_eu_ets_data(
            claim=claim,
            installation_ids=installation_ids,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"EU ETS fetch failed: {exc.message}",
            extra={
                "operation": "fetch_eu_ets_failed",
                "error_type": type(exc).__name__,
                "http_status": exc.status_code,
                "source": EvidenceSource.EU_ETS.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"EU ETS fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eu_ets_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_cdp(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch self-reported climate data from the CDP open dataset.

    Queries the CDP (formerly Carbon Disclosure Project) open data export for
    the company's self-reported emissions, targets, and climate governance data.
    CDP data is self-reported and weighted accordingly by the Judge Agent.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_cdp_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"CDP fetch failed: {exc.message}",
            extra={
                "operation": "fetch_cdp_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.CDP.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.CDP}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"CDP fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_cdp_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.CDP}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_eurlex(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch legislative and CSRD context from EUR-Lex.

    Queries the EUR-Lex REST API for CSRD disclosure records, Green Claims
    Directive references, and any legislative proceedings relevant to the
    claim's subject matter. Legislative records provide the regulatory
    framework within which claims are assessed.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eurlex_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"EUR-Lex fetch failed: {exc.message}",
            extra={
                "operation": "fetch_eurlex_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.EUR_LEX.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EUR_LEX}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"EUR-Lex fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eurlex_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EUR_LEX}: unexpected error — {type(exc).__name__}"],
        }


async def _node_aggregate(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: synthesise all evidence into an overall assessment.

    Runs after all parallel fetch nodes have completed. Receives the fully
    merged ``evidence`` and ``data_gaps`` lists and produces an
    ``overall_assessment`` string summarising what the collected evidence
    shows in aggregate. This summary is provided as context to the Judge
    Agent alongside the individual evidence records.

    The aggregate node does not call an LLM — the summary is constructed
    programmatically from the evidence records to keep this step fast and
    deterministic. The Judge Agent has the LLM reasoning step.

    Args:
        state: Final verification graph state with all evidence merged.

    Returns:
        Partial state dict (no-op; the state is complete at this point).
        The :py:class:`VerificationAgent` reads the final state directly
        to construct the :py:class:`~models.evidence.VerificationResult`.
    """
    evidence = state["evidence"]
    data_gaps = state["data_gaps"]

    supporting = sum(1 for e in evidence if e.supports_claim is True)
    contradicting = sum(1 for e in evidence if e.supports_claim is False)
    inconclusive = sum(1 for e in evidence if e.supports_claim is None)

    logger.info(
        f"Evidence aggregation complete: {len(evidence)} record(s) — "
        f"{supporting} supporting, {contradicting} contradicting, "
        f"{inconclusive} inconclusive; {len(data_gaps)} data gap(s)",
        extra={
            "operation": "verification_aggregate",
            "outcome": AgentOutcome.SUCCESS.value if evidence else AgentOutcome.PARTIAL.value,
        },
    )

    # No state mutation needed — the agent reads the final state post-graph
    return {}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_verification_graph() -> StateGraph:
    """Construct the LangGraph StateGraph for parallel source verification.

    The graph fans out from START to four independent fetch nodes, each
    querying a different EU open data source. All four nodes converge at
    the ``aggregate`` node before reaching END.

    Because each fetch node returns a *partial* state update to the
    ``evidence`` and ``data_gaps`` lists (using ``operator.add`` reducers),
    LangGraph merges the partial results automatically as the parallel
    branches complete. No explicit synchronisation is required.

                START
              ↙   ↓   ↓   ↘
        EU_ETS CDP EUR-LEX EUROSTAT (future)
              ↘   ↓   ↓   ↙
              aggregate
                 ↓
               END

    Returns:
        An uncompiled :py:class:`~langgraph.graph.StateGraph` instance.
    """
    graph = StateGraph(VerificationState)

    graph.add_node("fetch_eu_ets", _node_fetch_eu_ets)
    graph.add_node("fetch_cdp", _node_fetch_cdp)
    graph.add_node("fetch_eurlex", _node_fetch_eurlex)
    graph.add_node("aggregate", _node_aggregate)

    # Fan out from START to all fetch nodes — LangGraph runs these in parallel
    graph.add_edge(START, "fetch_eu_ets")
    graph.add_edge(START, "fetch_cdp")
    graph.add_edge(START, "fetch_eurlex")

    # All fetch nodes converge at aggregate
    graph.add_edge("fetch_eu_ets", "aggregate")
    graph.add_edge("fetch_cdp", "aggregate")
    graph.add_edge("fetch_eurlex", "aggregate")

    graph.add_edge("aggregate", END)

    return graph


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class VerificationAgent:
    """Verifies green claims against EU open data sources using a LangGraph graph.

    Orchestrates parallel queries to EU ETS, CDP, and EUR-Lex via a
    LangGraph StateGraph where each data source is a dedicated node. The
    fan-out topology ensures all sources are queried concurrently; the
    ``operator.add`` reducer on the ``evidence`` list merges partial results
    as each node completes.

    LangGraph is used here — and only here in the pipeline — because this
    agent has exactly the characteristics that benefit from a framework:
    multiple independent tools, parallel execution, partial-failure tolerance,
    and state that accumulates across branches. The other agents are
    single-step LLM calls or pure database queries where a framework adds
    indirection without value.

    Attributes:
        _graph: The compiled LangGraph state graph.
    """

    def __init__(self) -> None:
        """Initialise the Verification Agent and compile the LangGraph graph.

        The graph is compiled once at agent construction time. Compilation
        is a synchronous operation that validates the graph topology and
        produces the runnable object used for all subsequent invocations.
        """
        self._graph = _build_verification_graph().compile()
        logger.info(
            "Verification graph compiled",
            extra={"operation": "verification_graph_compiled"},
        )

    async def run(self, input: VerificationInput) -> tuple[VerificationResult, AgentTrace]:
        """Run the parallel verification graph for the given claim.

        Invokes the compiled LangGraph graph with the initial state derived
        from the input, then reads the final merged state to construct a
        :py:class:`~models.evidence.VerificationResult`.

        Args:
            input: Validated verification input containing the claim and
                company context.

        Returns:
            A tuple of:
            - :py:class:`~models.evidence.VerificationResult`: All gathered
              evidence and the aggregate assessment narrative.
            - :py:class:`~models.trace.AgentTrace`: Execution trace for this
              agent step.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.VERIFICATION.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Verification started",
            extra={
                "operation": "verification_start",
                "company_id": str(input.context.company.id),
            },
        )

        result: VerificationResult | None = None
        outcome = AgentOutcome.SUCCESS

        async with agent_error_boundary(agent=AgentName.VERIFICATION.value, operation="run"):
            initial_state: VerificationState = {
                "claim": input.claim,
                "context": input.context,
                "evidence": [],
                "data_gaps": [],
            }

            final_state: VerificationState = await self._graph.ainvoke(initial_state)

            evidence = final_state["evidence"]
            data_gaps = final_state["data_gaps"]

            if not evidence or data_gaps:
                outcome = AgentOutcome.PARTIAL

            overall_assessment = _build_assessment_summary(evidence, data_gaps)

            result = VerificationResult(
                claim_id=input.claim.id,
                trace_id=input.claim.trace_id,
                evidence=evidence,
                overall_assessment=overall_assessment,
                data_gaps=data_gaps,
            )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.VERIFICATION,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.verification_agent.VerificationInput",
            output_schema="models.evidence.VerificationResult",
            metadata={
                "evidence_count": len(result.evidence) if result else 0,
                "data_gap_count": len(result.data_gaps) if result else 0,
                "sources_queried": ["EU_ETS", "CDP", "EUR_LEX"],
            },
        )

        return result, trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_assessment_summary(
    evidence: list[Evidence],
    data_gaps: list[str],
) -> str:
    """Construct a plain-text summary of the aggregated verification evidence.

    Produces a concise, structured summary suitable for inclusion in the
    Judge Agent's context. The summary describes the counts of supporting,
    contradicting, and inconclusive evidence records, and explicitly lists
    any data gaps so the Judge Agent can reflect on missing coverage.

    Args:
        evidence: All evidence records gathered during verification.
        data_gaps: Descriptions of sources that failed or returned no data.

    Returns:
        A plain-text assessment summary string.
    """
    if not evidence and not data_gaps:
        return "No evidence was gathered and no data sources were queried."

    supporting = [e for e in evidence if e.supports_claim is True]
    contradicting = [e for e in evidence if e.supports_claim is False]
    inconclusive = [e for e in evidence if e.supports_claim is None]

    lines: list[str] = [
        f"Verification retrieved {len(evidence)} evidence record(s) from "
        f"{len({e.source for e in evidence})} source(s).",
        f"  Supporting the claim:    {len(supporting)}",
        f"  Contradicting the claim: {len(contradicting)}",
        f"  Inconclusive:            {len(inconclusive)}",
    ]

    if contradicting:
        lines.append("Contradicting evidence summaries:")
        for e in contradicting:
            lines.append(f"  - [{e.source.value}] {e.summary}")

    if data_gaps:
        lines.append(f"{len(data_gaps)} data source(s) were unavailable:")
        for gap in data_gaps:
            lines.append(f"  - {gap}")

    return "\n".join(lines)
