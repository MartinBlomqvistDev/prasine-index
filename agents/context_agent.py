"""Context Agent for the Prasine Index pipeline.

Runs after claim extraction and before verification. Queries PostgreSQL to
retrieve the company's full claim history, aggregate greenwashing scores, and
score trend — then uses pgvector cosine similarity to find prior claims
semantically equivalent to the current one. This longitudinal context is passed
to both the Verification Agent and the Judge Agent, enabling the pipeline to
treat repeat offenders differently from first-time filers.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.logger import bind_trace_context, get_logger
from core.retry import agent_error_boundary
from models.claim import Claim
from models.company import Company, CompanyContext, ScoreTrend
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "ContextAgent",
    "ContextInput",
    "ContextResult",
]

logger = get_logger(__name__)

# Cosine distance threshold for pgvector similarity search.
# Claims whose normalised_text embeddings are within this distance are
# considered semantically equivalent for repeat-claim detection.
# 0.15 corresponds to approximately cosine similarity >= 0.85.
_SIMILARITY_THRESHOLD: float = 0.15

# Maximum number of similar historical claims to surface in CompanyContext.
_MAX_SIMILAR_CLAIMS: int = 5

# Minimum number of scored periods required to compute a meaningful ScoreTrend.
_MIN_PERIODS_FOR_TREND: int = 2


class ContextInput(BaseModel):
    """Input contract for the Context Agent.

    Produced by the pipeline orchestrator after the Extraction Agent completes.
    Each claim extracted from a document is assessed independently; the Context
    Agent is called once per claim so that the pgvector similarity search is
    scoped to the specific claim text under assessment.

    Attributes:
        claim: The newly extracted claim for which context is being assembled.
        company_id: The company that made this claim. Passed separately to
            allow the Context Agent to query company-level aggregates even
            if the claim record has not yet been persisted.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(
        ..., description="The newly extracted claim for which context is being assembled."
    )
    company_id: uuid.UUID = Field(..., description="Company that made this claim.")


class ContextResult(BaseModel):
    """Output contract of the Context Agent.

    Returned by :py:meth:`ContextAgent.run` and passed to the Verification
    Agent and subsequently to the Judge Agent. The ``context`` field carries
    everything the downstream agents need to situate the current claim within
    the company's historical record.

    Attributes:
        context: Assembled company context including claim history, score
            trend, and semantically similar historical claims.
        trace: Structured execution record for this agent step.
    """

    model_config = ConfigDict(from_attributes=True)

    context: CompanyContext = Field(
        ..., description="Assembled company context for the current claim."
    )
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


class ContextAgent:
    """Assembles historical company context before verification begins.

    Queries PostgreSQL to retrieve the company's claim history, aggregate
    greenwashing scores, score trend, and semantically similar historical
    claims via pgvector cosine similarity on normalised claim text.

    This agent has no LLM dependency. It is a pure data retrieval step whose
    output is a fully populated :py:class:`~models.company.CompanyContext`
    that gives downstream agents the longitudinal view required to distinguish
    a company making a claim for the first time from one repeating an
    undelivered commitment.

    The agent does not itself set ``Claim.is_repeat`` or
    ``Claim.previous_claim_id`` — those mutations are applied by the pipeline
    orchestrator using the ``similar_historical_claim_ids`` returned here,
    keeping the agent's responsibility narrowly scoped to data retrieval.
    """

    async def run(self, input: ContextInput) -> ContextResult:
        """Assemble company context for the given claim.

        Binds pipeline context variables and executes four database queries:
        the company record, aggregate claim statistics, aggregate score
        statistics, and the pgvector similarity search for equivalent prior
        claims. All four queries share a single database session.

        Args:
            input: Validated context input containing the claim and company ID.

        Returns:
            A :py:class:`ContextResult` with the assembled
            :py:class:`~models.company.CompanyContext` and the execution trace.

        Raises:
            :py:class:`~core.retry.PrasineError`: If the company record cannot
                be found or a database query fails after retries.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.CONTEXT.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Context retrieval started",
            extra={
                "operation": "context_start",
                "company_id": str(input.company_id),
            },
        )

        context: CompanyContext | None = None
        outcome = AgentOutcome.SUCCESS
        error_type: str | None = None
        error_message: str | None = None

        async with agent_error_boundary(agent=AgentName.CONTEXT.value, operation="run"):
            context = await self._assemble_context(input)
            logger.info(
                "Context retrieval completed",
                extra={
                    "operation": "context_complete",
                    "outcome": outcome.value,
                    "company_id": str(input.company_id),
                },
            )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.CONTEXT,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.context_agent.ContextInput",
            output_schema="agents.context_agent.ContextResult",
            error_type=error_type,
            error_message=error_message,
            metadata={
                "company_id": str(input.company_id),
                "similar_claims_found": len(context.similar_historical_claim_ids) if context else 0,
                "total_claims_assessed": context.total_claims_assessed if context else 0,
            },
        )

        assert context is not None, (
            "Context Agent: context must be set if error boundary did not raise"
        )

        return ContextResult(context=context, trace=trace)

    async def _assemble_context(self, input: ContextInput) -> CompanyContext:
        """Execute all database queries and construct a CompanyContext.

        Args:
            input: The context input containing the claim and company ID.

        Returns:
            A fully populated :py:class:`~models.company.CompanyContext`.
        """
        async with get_session() as session:
            company = await self._fetch_company(session, input.company_id)
            claim_stats = await self._fetch_claim_stats(session, input.company_id)
            score_stats = await self._fetch_score_stats(session, input.company_id)
            similar_ids = await self._find_similar_claims(session, input.claim)

        trend = _compute_score_trend(score_stats["score_history"])

        return CompanyContext(
            company=company,
            total_claims_assessed=claim_stats["total"],
            repeat_claim_count=claim_stats["repeat_count"],
            average_greenwashing_score=score_stats["average"],
            worst_greenwashing_score=score_stats["worst"],
            score_trend=trend,
            similar_historical_claim_ids=similar_ids,
            last_assessed_at=claim_stats["last_assessed_at"],
            context_retrieved_at=datetime.now(UTC),
        )

    async def _fetch_company(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
    ) -> Company:
        """Retrieve the Company record from PostgreSQL.

        Returns a stub Company when the ID is not found in the database so
        that eval runs and ad-hoc pipeline calls with synthetic company IDs
        proceed gracefully. The stub carries the UUID and unknown placeholders;
        downstream agents treat missing EU ETS installation IDs and a null
        Transparency Register ID as data gaps, which is the correct behaviour.

        Args:
            session: Active async database session.
            company_id: UUID of the company to retrieve.

        Returns:
            The :py:class:`~models.company.Company` record, or a stub if not found.
        """
        # Import here to avoid circular dependency with ORM models (not yet written).
        # When the ORM layer is added, replace this raw SQL with a typed select().
        result = await session.execute(
            text(
                "SELECT id, name, lei, isin, ticker, country, sector, sub_sector, "
                "eu_ets_installation_ids, transparency_register_id, ir_page_url, "
                "csrd_reporting, created_at, updated_at "
                "FROM companies WHERE id = :company_id"
            ),
            {"company_id": str(company_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            logger.info(
                f"Company {company_id} not found in database — using stub record",
                extra={"operation": "context_company_stub", "company_id": str(company_id)},
            )
            return Company(
                id=company_id,
                name="Unknown Company",
                country="EU",
                sector="Unknown",
                csrd_reporting=False,
            )

        return Company(
            id=row["id"],
            name=row["name"],
            lei=row["lei"],
            isin=row["isin"],
            ticker=row["ticker"],
            country=row["country"],
            sector=row["sector"],
            sub_sector=row["sub_sector"],
            eu_ets_installation_ids=row["eu_ets_installation_ids"] or [],
            transparency_register_id=row["transparency_register_id"],
            ir_page_url=row["ir_page_url"],
            csrd_reporting=bool(row["csrd_reporting"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def _fetch_claim_stats(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate claim statistics for the company.

        Counts total assessed claims, the number flagged as repeats, and the
        timestamp of the most recent completed assessment. Only claims that
        have reached SCORED status or beyond are included — DETECTED claims
        that are still in the pipeline are excluded to avoid inflating the
        count with in-flight work.

        Args:
            session: Active async database session.
            company_id: UUID of the company.

        Returns:
            A dict with keys ``total`` (int), ``repeat_count`` (int), and
            ``last_assessed_at`` (datetime | None).
        """
        result = await session.execute(
            text(
                "SELECT "
                "  COUNT(*)                              AS total, "
                "  SUM(CASE WHEN is_repeat THEN 1 ELSE 0 END) AS repeat_count, "
                "  MAX(detected_at)                     AS last_assessed_at "
                "FROM claims "
                "WHERE company_id = :company_id "
                "  AND status IN ('SCORED', 'PUBLISHED', 'MONITORING')"
            ),
            {"company_id": str(company_id)},
        )
        row = result.mappings().one()
        return {
            "total": int(row["total"] or 0),
            "repeat_count": int(row["repeat_count"] or 0),
            "last_assessed_at": row["last_assessed_at"],
        }

    async def _fetch_score_stats(
        self,
        session: AsyncSession,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate greenwashing score statistics and history for the company.

        Retrieves the average score, the worst (highest) score, and the
        chronological sequence of scores used to compute the trend. The
        score history is limited to the ten most recent scored periods to
        keep the trend computation bounded.

        Args:
            session: Active async database session.
            company_id: UUID of the company.

        Returns:
            A dict with keys ``average`` (float | None), ``worst``
            (float | None), and ``score_history`` (list[float]).
        """
        agg_result = await session.execute(
            text(
                "SELECT AVG(score) AS average, MAX(score) AS worst "
                "FROM greenwashing_scores "
                "WHERE company_id = :company_id"
            ),
            {"company_id": str(company_id)},
        )
        agg_row = agg_result.mappings().one()

        history_result = await session.execute(
            text(
                "SELECT score FROM greenwashing_scores "
                "WHERE company_id = :company_id "
                "ORDER BY scored_at ASC "
                "LIMIT 10"
            ),
            {"company_id": str(company_id)},
        )
        score_history = [float(r["score"]) for r in history_result.mappings().all()]

        return {
            "average": float(agg_row["average"]) if agg_row["average"] is not None else None,
            "worst": float(agg_row["worst"]) if agg_row["worst"] is not None else None,
            "score_history": score_history,
        }

    async def _find_similar_claims(
        self,
        session: AsyncSession,
        claim: Claim,
    ) -> list[uuid.UUID]:
        """Find semantically similar historical claims via pgvector cosine distance.

        Queries the ``claims`` table for previously scored claims from the same
        company whose ``embedding`` column is within ``_SIMILARITY_THRESHOLD``
        cosine distance of the current claim's normalised text. Returns up to
        ``_MAX_SIMILAR_CLAIMS`` results ordered by ascending distance (most
        similar first).

        The embedding for the current claim is not yet stored at this point in
        the pipeline — it is generated and stored by the pipeline orchestrator
        after context retrieval. This query therefore uses the stored embeddings
        of historical claims only; the current claim's normalised_text is sent
        to the embedding model inline.

        If the current claim has no normalised_text or no embedding model is
        configured, returns an empty list gracefully.

        Args:
            session: Active async database session.
            claim: The current claim under assessment.

        Returns:
            List of UUIDs of similar historical claims, ordered by similarity
            (most similar first), capped at ``_MAX_SIMILAR_CLAIMS``.
        """
        if not claim.normalised_text:
            logger.info(
                "Skipping similarity search: claim has no normalised_text",
                extra={"operation": "context_similarity_skipped"},
            )
            return []

        try:
            # The embedding column stores pgvector vectors generated from
            # normalised_text. The <=> operator computes cosine distance.
            # This query requires a pre-built HNSW or IVFFlat index on
            # claims.embedding for acceptable performance at scale.
            result = await session.execute(
                text(
                    "SELECT id "
                    "FROM claims "
                    "WHERE company_id = :company_id "
                    "  AND status IN ('SCORED', 'PUBLISHED', 'MONITORING') "
                    "  AND id != :claim_id "
                    "  AND embedding IS NOT NULL "
                    "  AND embedding <=> ( "
                    "      SELECT embedding FROM claims WHERE id = :claim_id "
                    "  ) < :threshold "
                    "ORDER BY embedding <=> ( "
                    "    SELECT embedding FROM claims WHERE id = :claim_id "
                    ") ASC "
                    "LIMIT :limit"
                ),
                {
                    "company_id": str(claim.company_id),
                    "claim_id": str(claim.id),
                    "threshold": _SIMILARITY_THRESHOLD,
                    "limit": _MAX_SIMILAR_CLAIMS,
                },
            )
            similar_ids = [uuid.UUID(str(row["id"])) for row in result.mappings().all()]

            if similar_ids:
                logger.info(
                    f"Found {len(similar_ids)} similar historical claim(s)",
                    extra={
                        "operation": "context_similarity_complete",
                        "company_id": str(claim.company_id),
                    },
                )

            return similar_ids

        except Exception as exc:
            # Similarity search failures are non-fatal. The pipeline continues
            # with an empty similar_ids list; the Judge Agent will note the
            # absence of repeat-claim context in its confidence weighting.
            logger.warning(
                f"pgvector similarity search failed — proceeding without similar claims: {exc}",
                extra={
                    "operation": "context_similarity_failed",
                    "error_type": type(exc).__name__,
                },
            )
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_score_trend(score_history: list[float]) -> ScoreTrend:
    """Derive a ScoreTrend from the chronological sequence of greenwashing scores.

    Requires at least ``_MIN_PERIODS_FOR_TREND`` data points. With fewer
    points returns INSUFFICIENT_DATA. With sufficient data, computes the
    linear regression slope over the score sequence: a positive slope (scores
    increasing over time, meaning worsening greenwashing) returns DETERIORATING;
    a negative slope returns IMPROVING; a near-zero slope returns STABLE.

    The slope threshold of ±2.0 per period prevents noisy oscillation from
    being misclassified as a meaningful trend.

    Args:
        score_history: Chronologically ordered list of greenwashing scores.

    Returns:
        The :py:class:`~models.company.ScoreTrend` value for this history.
    """
    if len(score_history) < _MIN_PERIODS_FOR_TREND:
        return ScoreTrend.INSUFFICIENT_DATA

    n = len(score_history)
    x_mean = (n - 1) / 2.0
    y_mean = sum(score_history) / n

    numerator = sum((i - x_mean) * (score_history[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0.0:
        return ScoreTrend.STABLE

    slope = numerator / denominator

    if slope > 2.0:
        return ScoreTrend.DETERIORATING
    if slope < -2.0:
        return ScoreTrend.IMPROVING
    return ScoreTrend.STABLE
