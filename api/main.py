"""FastAPI application entry point for the Prasine Index REST API.

Exposes endpoints for triggering the assessment pipeline, querying results, and
monitoring system health. The lifespan handler initialises the database schema
and structured logging on startup, and disposes of the connection pool on
shutdown. All heavy lifting is in the agents/ and core/ packages.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from core.database import get_session, healthcheck, init_db, teardown_db
from core.logger import get_logger, setup_logging
from core.pipeline import Pipeline, PipelineConfig, PipelineResult
from models.claim import SourceType

__all__ = ["app"]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown.

    On startup: configures structured logging, initialises the database schema
    (creates tables and enables pgvector if not already present), and wires
    a shared Pipeline instance into application state.

    On shutdown: cleanly disposes of the pipeline clients and database pool.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control to the running application.
    """
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    logger.info("Prasine Index API starting up", extra={"operation": "startup"})

    await init_db()

    pipeline = Pipeline(config=PipelineConfig())
    app.state.pipeline = pipeline

    logger.info("Prasine Index API ready", extra={"operation": "startup_complete"})

    yield

    logger.info("Prasine Index API shutting down", extra={"operation": "shutdown"})
    await pipeline.aclose()
    await teardown_db()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Prasine Index API",
    description=(
        "Automated EU corporate greenwashing monitoring and scoring. "
        "Every green claim by an EU-listed company, verified against real "
        "emissions data and lobbying records, with a full evidence chain "
        "citable in journalism and litigation."
    ),
    version="1.0.0",
    lifespan=_lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AssessDocumentRequest(BaseModel):
    """Request body for the POST /assess endpoint.

    Attributes:
        company_id: UUID of the company that published the document.
        source_url: Canonical URL of the document to assess.
        source_type: Document category.
        raw_content: Full extracted text content of the document.
            The caller is responsible for extracting text from PDFs;
            the pipeline processes plain text.
        publication_date: Publication date of the document, if known.
    """

    company_id: uuid.UUID = Field(..., description="Company that published the document.")
    source_url: str = Field(..., description="Canonical URL of the source document.")
    source_type: SourceType = Field(..., description="Document category.")
    raw_content: str = Field(..., description="Full plain text content of the document.")
    publication_date: str | None = Field(
        default=None,
        description="Publication date in ISO 8601 format (YYYY-MM-DD), if known.",
    )


class AssessDocumentResponse(BaseModel):
    """Response body for the POST /assess endpoint.

    Attributes:
        claims_assessed: Number of claims extracted and assessed.
        results: Summary of each claim's verdict.
        trace_ids: Trace IDs for each assessed claim, for audit queries.
    """

    claims_assessed: int
    results: list[dict[str, Any]]
    trace_ids: list[str]


class HealthResponse(BaseModel):
    """Response body for the GET /health endpoint."""

    status: str
    database: str
    version: str = "1.0.0"


class ClaimResponse(BaseModel):
    """Summary of a single claim and its verdict for API responses."""

    claim_id: str
    trace_id: str
    company_id: str
    raw_text: str
    claim_category: str
    status: str
    source_url: str


class ScoreResponse(BaseModel):
    """Summary of a greenwashing score for API responses."""

    claim_id: str
    company_id: str
    score: float
    verdict: str
    confidence: float
    reasoning: str
    scored_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """Check the health of the Prasine Index API.

    Verifies database connectivity and returns the overall system status.
    Used by load balancers and monitoring systems.

    Returns:
        :py:class:`HealthResponse` with ``status="ok"`` on success.
    """
    db_status = await healthcheck()
    overall = "ok" if db_status["status"] == "ok" else "degraded"
    return HealthResponse(status=overall, database=db_status["status"])


@app.post(
    "/assess",
    response_model=AssessDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["pipeline"],
)
async def assess_document(
    request: AssessDocumentRequest,
    background_tasks: BackgroundTasks,
) -> AssessDocumentResponse:
    """Submit a document for greenwashing assessment.

    Accepts a company document (press release, CSRD report, IR page) as
    plain text and runs the full Prasine Index pipeline: extraction,
    context retrieval, parallel verification against EU open data, lobbying
    check, LLM-as-judge scoring, and report generation.

    Multiple claims may be found in a single document; each is assessed
    independently and receives its own verdict and report.

    The pipeline runs synchronously for documents with a small number of
    claims. For large CSRD reports, consider using the background task
    variant at POST /assess/async.

    Args:
        request: The document submission request.
        background_tasks: FastAPI background task manager.

    Returns:
        :py:class:`AssessDocumentResponse` with verdict summaries for each
        extracted claim.

    Raises:
        HTTPException 400: If the request is malformed.
        HTTPException 500: If a critical pipeline step fails.
    """
    from datetime import datetime

    from agents.extraction_agent import ExtractionInput

    publication_date = None
    if request.publication_date:
        try:
            publication_date = datetime.fromisoformat(request.publication_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid publication_date format: {request.publication_date!r}. Use YYYY-MM-DD.",
            ) from exc

    extraction_input = ExtractionInput(
        trace_id=uuid.uuid4(),
        company_id=request.company_id,
        source_url=request.source_url,
        source_type=request.source_type,
        raw_content=request.raw_content,
        publication_date=publication_date,
    )

    pipeline: Pipeline = app.state.pipeline

    try:
        results: list[PipelineResult] = await pipeline.run_from_document(extraction_input)
    except Exception as exc:
        logger.error(
            f"Pipeline failed for {request.source_url}: {exc}",
            exc_info=True,
            extra={"operation": "assess_pipeline_failed", "error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {type(exc).__name__}: {exc}",
        ) from exc

    response_results = [
        {
            "claim_id": str(r.claim.id),
            "trace_id": str(r.claim.trace_id),
            "verdict": r.score.verdict.value,
            "score": r.score.score,
            "confidence": r.score.confidence,
            "claim_preview": r.claim.raw_text[:150],
        }
        for r in results
    ]

    return AssessDocumentResponse(
        claims_assessed=len(results),
        results=response_results,
        trace_ids=[str(r.claim.trace_id) for r in results],
    )


@app.get(
    "/claims/{claim_id}",
    response_model=ClaimResponse,
    tags=["results"],
)
async def get_claim(claim_id: uuid.UUID) -> ClaimResponse:
    """Retrieve a claim record by ID.

    Args:
        claim_id: UUID of the claim to retrieve.

    Returns:
        :py:class:`ClaimResponse` with claim metadata.

    Raises:
        HTTPException 404: If the claim does not exist.
    """
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT id, trace_id, company_id, raw_text, claim_category, status, source_url "
                "FROM claims WHERE id = :claim_id"
            ),
            {"claim_id": str(claim_id)},
        )
        row = result.mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim {claim_id} not found.",
        )

    return ClaimResponse(
        claim_id=str(row["id"]),
        trace_id=str(row["trace_id"]),
        company_id=str(row["company_id"]),
        raw_text=row["raw_text"],
        claim_category=row["claim_category"],
        status=row["status"],
        source_url=row["source_url"],
    )


@app.get(
    "/claims/{claim_id}/report",
    tags=["results"],
    response_class=JSONResponse,
)
async def get_report(claim_id: uuid.UUID) -> JSONResponse:
    """Retrieve the published Markdown report for a claim.

    Args:
        claim_id: UUID of the claim whose report to retrieve.

    Returns:
        JSON with ``report_markdown`` and ``published_at`` fields.

    Raises:
        HTTPException 404: If the report has not been published yet.
    """
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT report_markdown, published_at FROM reports "
                "WHERE claim_id = :claim_id"
            ),
            {"claim_id": str(claim_id)},
        )
        row = result.mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No published report found for claim {claim_id}.",
        )

    return JSONResponse(
        content={
            "claim_id": str(claim_id),
            "report_markdown": row["report_markdown"],
            "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        }
    )


@app.get(
    "/companies/{company_id}/scores",
    response_model=list[ScoreResponse],
    tags=["results"],
)
async def get_company_scores(company_id: uuid.UUID) -> list[ScoreResponse]:
    """Retrieve all greenwashing scores for a company.

    Returns scores in reverse chronological order (most recent first).
    Used by the public dashboard and by downstream consumers building
    company-level accountability timelines.

    Args:
        company_id: UUID of the company.

    Returns:
        List of :py:class:`ScoreResponse` records.
    """
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT claim_id, company_id, score, verdict, confidence, "
                "reasoning, scored_at "
                "FROM greenwashing_scores "
                "WHERE company_id = :company_id "
                "ORDER BY scored_at DESC"
            ),
            {"company_id": str(company_id)},
        )
        rows = result.mappings().all()

    return [
        ScoreResponse(
            claim_id=str(r["claim_id"]),
            company_id=str(r["company_id"]),
            score=float(r["score"]),
            verdict=r["verdict"],
            confidence=float(r["confidence"]),
            reasoning=r["reasoning"],
            scored_at=r["scored_at"].isoformat(),
        )
        for r in rows
    ]


@app.get(
    "/trace/{trace_id}",
    tags=["observability"],
    response_class=JSONResponse,
)
async def get_trace(trace_id: uuid.UUID) -> JSONResponse:
    """Retrieve the full agent execution trace for a pipeline run.

    Returns all AgentTrace rows for the given trace_id in chronological
    order. Enables complete replay and latency analysis of any pipeline run.

    Args:
        trace_id: The pipeline trace ID (shared across all agent steps).

    Returns:
        JSON array of trace records.
    """
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT id, trace_id, claim_id, agent, outcome, "
                "started_at, completed_at, duration_ms, "
                "input_schema, output_schema, error_type, error_message, "
                "retry_count, llm_model_id, tokens_used, metadata "
                "FROM trace_log "
                "WHERE trace_id = :trace_id "
                "ORDER BY started_at ASC"
            ),
            {"trace_id": str(trace_id)},
        )
        rows = result.mappings().all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trace records found for trace_id {trace_id}.",
        )

    return JSONResponse(
        content={
            "trace_id": str(trace_id),
            "steps": [
                {
                    "id": str(r["id"]),
                    "agent": r["agent"],
                    "outcome": r["outcome"],
                    "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                    "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                    "duration_ms": r["duration_ms"],
                    "llm_model_id": r["llm_model_id"],
                    "tokens_used": r["tokens_used"],
                    "error_type": r["error_type"],
                    "metadata": r["metadata"],
                }
                for r in rows
            ],
        }
    )
