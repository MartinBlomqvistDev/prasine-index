"""Discovery Agent for the Prasine Index pipeline.

Continuously monitors EU company investor relations pages, press release feeds,
and CSRD report repositories for new content. When new content is detected that
may contain green claims, it fetches the full text and dispatches an
ExtractionInput to the pipeline. This agent transforms Prasine Index from a
manual tool into a live accountability system: no new greenwashing claim by an
EU company goes undetected for long.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from agents.extraction_agent import ExtractionInput
from core.database import get_session
from core.logger import bind_trace_context, get_logger
from core.retry import DataSourceError, RetryConfig, agent_error_boundary, retry_async
from models.claim import SourceType
from models.company import Company
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "DiscoveredDocument",
    "DiscoveryAgent",
    "DiscoveryResult",
]

logger = get_logger(__name__)

# Maximum number of characters extracted from a fetched page. Large CSRD PDFs
# may exceed model context; the extraction agent handles chunking if needed.
_MAX_CONTENT_CHARS: int = int(os.environ.get("DISCOVERY_MAX_CONTENT_CHARS", "200000"))

# HTTP request timeout for page fetches.
_FETCH_TIMEOUT_SECONDS: float = float(os.environ.get("DISCOVERY_FETCH_TIMEOUT", "30.0"))


class DiscoveredDocument(BaseModel):
    """A document newly detected by the Discovery Agent.

    Represents a page or file that has changed since the last check and may
    contain green claims. Passed to the pipeline orchestrator which dispatches
    it to the Extraction Agent.

    Attributes:
        company_id: The company whose source page was checked.
        source_url: URL of the discovered document.
        source_type: Detected document category.
        raw_content: Extracted text content of the document.
        content_hash: SHA-256 hash of the raw content, used to detect future
            modifications to this document after scoring.
        publication_date: Detected or estimated publication date.
        trace_id: New trace ID assigned to this discovery event.
    """

    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID = Field(..., description="Company whose source page was checked.")
    source_url: str = Field(..., description="URL of the discovered document.")
    source_type: SourceType = Field(..., description="Detected document category.")
    raw_content: str = Field(..., description="Extracted text content.")
    content_hash: str = Field(..., description="SHA-256 of raw_content for change detection.")
    publication_date: datetime | None = Field(default=None, description="Detected publication date.")
    trace_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="New trace ID assigned to this discovery event.",
    )

    def to_extraction_input(self) -> ExtractionInput:
        """Convert this discovery result to an ExtractionAgent input.

        Returns:
            An :py:class:`~agents.extraction_agent.ExtractionInput` ready to
            be passed directly to :py:meth:`~agents.extraction_agent.ExtractionAgent.run`.
        """
        return ExtractionInput(
            trace_id=self.trace_id,
            company_id=self.company_id,
            source_url=self.source_url,
            source_type=self.source_type,
            raw_content=self.raw_content,
            publication_date=self.publication_date,
        )


class DiscoveryResult(BaseModel):
    """Output contract of a single Discovery Agent check run.

    Attributes:
        company_id: The company whose sources were checked.
        documents_found: New or changed documents found in this check run.
        sources_checked: Number of URLs checked.
        trace: Execution trace for this check run.
    """

    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID = Field(..., description="Company whose sources were checked.")
    documents_found: list[DiscoveredDocument] = Field(
        default_factory=list,
        description="New or changed documents found in this check run.",
    )
    sources_checked: int = Field(default=0, description="Number of URLs checked.")
    trace: AgentTrace = Field(..., description="Execution trace for this check run.")


class DiscoveryAgent:
    """Monitors EU company sources for new green claims.

    Checks a company's registered IR page URL and any additional monitored
    sources for new or changed content. Change detection is based on SHA-256
    hashing of fetched content compared against the last known hash stored in
    PostgreSQL. Only changed or new pages trigger downstream extraction.

    The Discovery Agent is the entry point of the pipeline. It is typically
    called on a schedule (e.g. every 6 hours per company) by a background task
    or a cron job via the FastAPI scheduler. The pipeline orchestrator receives
    :py:class:`DiscoveredDocument` instances and dispatches each to the
    Extraction Agent.

    Attributes:
        _http_client: Async httpx client for page fetches.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        """Initialise the Discovery Agent.

        Args:
            http_client: Optional pre-configured async httpx client. If not
                provided, a default client is created with a standard timeout
                and browser-compatible User-Agent to avoid bot-blocking.
        """
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(_FETCH_TIMEOUT_SECONDS),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
                    "+https://prasine-index.eu/bot)"
                ),
                "Accept": "text/html,application/xhtml+xml,application/pdf",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        """Close the HTTP client if it was created internally."""
        if self._owns_client:
            await self._http_client.aclose()

    async def run(self, company: Company) -> DiscoveryResult:
        """Check all registered sources for a company and return new documents.

        Iterates over all monitored URLs for the company, fetches each, and
        compares the content hash against the last known value in the database.
        Returns a :py:class:`DiscoveryResult` with any new or changed documents.

        Args:
            company: The company whose sources are to be checked.

        Returns:
            A :py:class:`DiscoveryResult` with discovered documents and trace.
        """
        trace_id = uuid.uuid4()
        bind_trace_context(trace_id=trace_id, agent_name=AgentName.DISCOVERY.value)
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Discovery check started",
            extra={
                "operation": "discovery_start",
                "company_id": str(company.id),
            },
        )

        documents: list[DiscoveredDocument] = []
        urls_to_check = _collect_urls(company)
        sources_checked = 0
        outcome = AgentOutcome.SUCCESS

        async with agent_error_boundary(agent=AgentName.DISCOVERY.value, operation="run"):
            for url, source_type in urls_to_check:
                sources_checked += 1
                doc = await self._check_url(company, url, source_type, trace_id)
                if doc is not None:
                    documents.append(doc)

        logger.info(
            f"Discovery complete: {len(documents)} new/changed document(s) found "
            f"from {sources_checked} source(s)",
            extra={
                "operation": "discovery_complete",
                "outcome": outcome.value,
                "company_id": str(company.id),
            },
        )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=trace_id,
            claim_id=None,
            agent=AgentName.DISCOVERY,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="models.company.Company",
            output_schema="agents.discovery_agent.DiscoveryResult",
            metadata={
                "company_id": str(company.id),
                "sources_checked": sources_checked,
                "documents_found": len(documents),
            },
        )

        return DiscoveryResult(
            company_id=company.id,
            documents_found=documents,
            sources_checked=sources_checked,
            trace=trace,
        )

    async def _check_url(
        self,
        company: Company,
        url: str,
        source_type: SourceType,
        trace_id: uuid.UUID,
    ) -> DiscoveredDocument | None:
        """Fetch a URL and return a DiscoveredDocument if content has changed.

        Args:
            company: The company that owns this URL.
            url: The URL to fetch.
            source_type: The document category for this URL.
            trace_id: The trace ID for this discovery run.

        Returns:
            A :py:class:`DiscoveredDocument` if the content has changed since
            the last check, or None if the content is unchanged.
        """
        try:
            content = await self._fetch_url(url)
        except DataSourceError as exc:
            logger.warning(
                f"Failed to fetch {url}: {exc.message}",
                extra={"operation": "discovery_fetch_failed", "error_type": type(exc).__name__},
            )
            return None

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        last_known_hash = await self._load_last_hash(url)

        if last_known_hash == content_hash:
            logger.info(
                f"No change detected at {url}",
                extra={"operation": "discovery_no_change"},
            )
            return None

        await self._save_hash(url, content_hash)
        logger.info(
            f"Content change detected at {url}",
            extra={"operation": "discovery_change_detected", "company_id": str(company.id)},
        )

        return DiscoveredDocument(
            company_id=company.id,
            source_url=url,
            source_type=source_type,
            raw_content=content[:_MAX_CONTENT_CHARS],
            content_hash=content_hash,
            trace_id=trace_id,
        )

    @retry_async(config=RetryConfig.DEFAULT_HTTP, operation="discovery_fetch_url")
    async def _fetch_url(self, url: str) -> str:
        """Fetch the text content of a URL.

        Args:
            url: The URL to fetch.

        Returns:
            The text content of the response.

        Raises:
            :py:class:`~core.retry.DataSourceError`: On HTTP errors.
        """
        try:
            response = await self._http_client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            from core.retry import classify_http_error
            raise classify_http_error(
                exc,
                source="DISCOVERY",
                agent=AgentName.DISCOVERY.value,
            ) from exc

        return response.text

    async def _load_last_hash(self, url: str) -> str | None:
        """Load the last known content hash for a URL from the database.

        Args:
            url: The URL whose hash to retrieve.

        Returns:
            The last known SHA-256 hash, or None if this URL has not been
            checked before.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT content_hash FROM discovery_state "
                        "WHERE source_url = :url"
                    ),
                    {"url": url},
                )
                row = result.one_or_none()
                return row[0] if row else None
        except Exception as exc:
            logger.warning(
                f"Could not load last hash for {url}: {exc}",
                extra={"operation": "discovery_hash_load_failed"},
            )
            return None

    async def _save_hash(self, url: str, content_hash: str) -> None:
        """Persist the new content hash for a URL to the database.

        Uses an upsert so the first check creates the row and subsequent
        checks update it.

        Args:
            url: The URL whose hash to save.
            content_hash: The new SHA-256 hash to store.
        """
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO discovery_state (source_url, content_hash, last_checked_at) "
                        "VALUES (:url, :hash, :now) "
                        "ON CONFLICT (source_url) DO UPDATE SET "
                        "  content_hash = EXCLUDED.content_hash, "
                        "  last_checked_at = EXCLUDED.last_checked_at"
                    ),
                    {
                        "url": url,
                        "hash": content_hash,
                        "now": datetime.now(UTC),
                    },
                )
        except Exception as exc:
            logger.warning(
                f"Could not save hash for {url}: {exc}",
                extra={"operation": "discovery_hash_save_failed"},
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_urls(company: Company) -> list[tuple[str, SourceType]]:
    """Collect all monitored URLs for a company with their source type.

    Args:
        company: The company to collect URLs for.

    Returns:
        List of (url, SourceType) tuples to check.
    """
    urls: list[tuple[str, SourceType]] = []
    if company.ir_page_url:
        urls.append((company.ir_page_url, SourceType.IR_PAGE))
    return urls
