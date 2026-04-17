"""Lobbying Agent for the Prasine Index pipeline.

Cross-references the company against the EU Transparency Register to determine
whether its lobbying activity aligns with or contradicts its green claims. A
company claiming climate leadership while lobbying against climate legislation is
the strongest and most legally actionable form of greenwashing — this agent
surfaces that contradiction explicitly as a primary signal in the Judge Agent's
scoring.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from core.retry import RetryConfig, agent_error_boundary, retry_async
from models.claim import Claim
from models.company import Company
from models.lobbying import LobbyingRecord, LobbyingStance
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "LobbyingAgent",
    "LobbyingInput",
    "LobbyingResult",
]

logger = get_logger(__name__)

_TRANSPARENCY_REGISTER_BASE_URL: str = os.environ.get(
    "EU_TRANSPARENCY_REGISTER_URL",
    "https://ec.europa.eu/transparencyregister/public",
)

# Keywords in lobbying field-of-interest strings that indicate anti-climate activity.
_ANTI_CLIMATE_KEYWORDS: frozenset[str] = frozenset(
    {
        "emission trading",
        "carbon pricing",
        "carbon tax",
        "carbon border",
        "climate levy",
        "carbon leakage",
        "green deal",
        "fit for 55",
        "renewable energy directive",
        "energy efficiency directive",
        "taxonomy regulation",
        "corporate sustainability",
        "csrd",
        "green claims",
    }
)

# Keywords indicating pro-climate lobbying.
_PRO_CLIMATE_KEYWORDS: frozenset[str] = frozenset(
    {
        "climate action",
        "net zero",
        "decarbonisation",
        "clean energy",
        "renewable",
        "sustainable finance",
        "green transition",
    }
)


class LobbyingInput(BaseModel):
    """Input contract for the Lobbying Agent.

    Attributes:
        claim: The claim being assessed.
        company: The company that made the claim.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The claim being assessed.")
    company: Company = Field(..., description="The company that made this claim.")


class LobbyingResult(BaseModel):
    """Output contract of the Lobbying Agent.

    Attributes:
        record: The lobbying record retrieved for this company, or None if
            the company is not registered in the Transparency Register or
            the register is unavailable.
        trace: Structured execution record for this agent step.
    """

    model_config = ConfigDict(from_attributes=True)

    record: LobbyingRecord | None = Field(
        default=None,
        description=(
            "Lobbying record for this company, or None if the company is not registered "
            "or the Transparency Register was unavailable."
        ),
    )
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


class LobbyingAgent:
    """Retrieves and assesses a company's EU lobbying activity.

    Queries the EU Transparency Register for the company's declared lobbying
    activities and fields of interest. Classifies the stance as PRO_CLIMATE,
    ANTI_CLIMATE, MIXED, or UNKNOWN, and explicitly flags when the lobbying
    activity contradicts the claim under assessment.

    This agent uses raw httpx rather than a dedicated ingest module because
    the Transparency Register provides a public search API that does not
    require the same multi-source fan-out pattern as the Verification Agent.
    A direct HTTP call is simpler and more transparent here.

    Attributes:
        _http_client: Async httpx client for Transparency Register queries.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        """Initialise the Lobbying Agent.

        Args:
            http_client: Optional pre-configured async httpx client. If not
                provided, a default client with a 30-second timeout is created.
                The caller is responsible for closing an externally provided
                client; internally created clients are closed in :py:meth:`aclose`.
        """
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"Accept": "application/json"},
        )

    async def aclose(self) -> None:
        """Close the HTTP client if it was created internally.

        Call this during application shutdown or in a finally block when the
        agent is no longer needed.
        """
        if self._owns_client:
            await self._http_client.aclose()

    async def run(self, input: LobbyingInput) -> LobbyingResult:
        """Retrieve and assess lobbying activity for the given claim and company.

        Args:
            input: Validated lobbying input containing the claim and company.

        Returns:
            A :py:class:`LobbyingResult` with the lobbying record (or None if
            unavailable) and the execution trace.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.LOBBYING.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Lobbying check started",
            extra={
                "operation": "lobbying_start",
                "company_id": str(input.company.id),
            },
        )

        record: LobbyingRecord | None = None
        outcome = AgentOutcome.SUCCESS
        error_type: str | None = None
        error_message: str | None = None

        if not input.company.transparency_register_id:
            # Try to resolve the register ID by name before giving up.
            resolved_id = await self._search_by_name(input.company.name)
            if resolved_id:
                input = LobbyingInput(
                    claim=input.claim,
                    company=input.company.model_copy(
                        update={"transparency_register_id": resolved_id}
                    ),
                )
            else:
                outcome = AgentOutcome.SKIPPED
                logger.info(
                    "Lobbying check skipped: company not found in Transparency Register",
                    extra={"operation": "lobbying_skipped"},
                )

        if input.company.transparency_register_id:
            async with agent_error_boundary(
                agent=AgentName.LOBBYING.value,
                operation="run",
                reraise=False,
            ):
                record = await self._fetch_and_assess(input)

            if record is None and outcome != AgentOutcome.SKIPPED:
                outcome = AgentOutcome.PARTIAL

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.LOBBYING,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.lobbying_agent.LobbyingInput",
            output_schema="agents.lobbying_agent.LobbyingResult",
            error_type=error_type,
            error_message=error_message,
            metadata={
                "has_register_id": bool(input.company.transparency_register_id),
                "contradicts_claim": record.contradicts_claim if record else None,
                "stance": record.stance.value if record else None,
            },
        )

        return LobbyingResult(record=record, trace=trace)

    async def _search_by_name(self, company_name: str) -> str | None:
        """Search the EU Transparency Register by company name.

        Args:
            company_name: The company name to search for.

        Returns:
            The register ID string if a match is found, else None.
        """
        try:
            response = await self._http_client.get(
                f"{_TRANSPARENCY_REGISTER_BASE_URL}/api/v1/organisations",
                params={"name": company_name, "size": 5},
            )
            response.raise_for_status()
            results = response.json()
            items = results if isinstance(results, list) else results.get("content", [])
            if not items:
                return None
            name_lower = company_name.lower()
            for item in items:
                reg_name = (item.get("name") or "").lower()
                if name_lower in reg_name or reg_name in name_lower:
                    reg_id = item.get("id") or item.get("registrationNumber")
                    if reg_id:
                        logger.info(
                            f"Resolved '{company_name}' to register ID {reg_id}",
                            extra={"operation": "lobbying_name_resolved"},
                        )
                        return str(reg_id)
        except Exception as exc:
            logger.debug(
                f"Transparency Register name search failed for '{company_name}': {exc}",
                extra={"operation": "lobbying_search_failed"},
            )
        return None

    @retry_async(config=RetryConfig.DEFAULT_HTTP, operation="lobbying_register_fetch")
    async def _fetch_and_assess(self, input: LobbyingInput) -> LobbyingRecord:
        """Fetch the Transparency Register record and assess lobbying stance.

        Args:
            input: The lobbying agent input.

        Returns:
            A fully assessed :py:class:`~models.lobbying.LobbyingRecord`.

        Raises:
            :py:class:`~core.retry.DataSourceError`: If the Transparency
                Register returns an error response.
        """
        register_id = input.company.transparency_register_id
        assert register_id is not None  # guarded by caller
        url = f"{_TRANSPARENCY_REGISTER_BASE_URL}/api/v1/organisations/{register_id}"

        try:
            response = await self._http_client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            from core.retry import classify_http_error

            raise classify_http_error(
                exc,
                source="EU_TRANSPARENCY_REGISTER",
                agent=AgentName.LOBBYING.value,
            ) from exc

        data = response.json()
        fields_of_interest: list[str] = data.get("fieldsOfInterest", [])
        activities: list[str] = data.get("activitiesDescription", [])

        stance, stance_reasoning = _classify_stance(fields_of_interest, activities)
        contradicts, explanation = _assess_contradiction(
            stance=stance,
            claim_raw_text=input.claim.raw_text,
            fields_of_interest=fields_of_interest,
        )

        return LobbyingRecord(
            company_id=input.company.id,
            claim_id=input.claim.id,
            trace_id=input.claim.trace_id,
            transparency_register_id=register_id,
            registrant_name=data.get("name", input.company.name),
            registration_date=data.get("registrationDate"),
            fields_of_interest=fields_of_interest,
            lobbying_activities=activities,
            estimated_annual_cost_eur=_parse_cost(data.get("estimatedCosts")),
            stance=stance,
            stance_reasoning=stance_reasoning,
            contradicts_claim=contradicts,
            contradiction_explanation=explanation,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_stance(
    fields_of_interest: list[str],
    activities: list[str],
) -> tuple[LobbyingStance, str]:
    """Classify the lobbying stance from declared fields and activities.

    Args:
        fields_of_interest: Declared policy areas from the register.
        activities: Specific lobbying activities declared.

    Returns:
        A tuple of (LobbyingStance, reasoning_string).
    """
    combined = " ".join(fields_of_interest + activities).lower()

    anti_matches = [kw for kw in _ANTI_CLIMATE_KEYWORDS if kw in combined]
    pro_matches = [kw for kw in _PRO_CLIMATE_KEYWORDS if kw in combined]

    if anti_matches and pro_matches:
        stance = LobbyingStance.MIXED
        reasoning = (
            f"Lobbying activity contains both pro-climate signals "
            f"({', '.join(pro_matches[:3])}) and anti-climate signals "
            f"({', '.join(anti_matches[:3])})."
        )
    elif anti_matches:
        stance = LobbyingStance.ANTI_CLIMATE
        reasoning = (
            f"Lobbying activity matches anti-climate keyword(s): {', '.join(anti_matches[:5])}."
        )
    elif pro_matches:
        stance = LobbyingStance.PRO_CLIMATE
        reasoning = (
            f"Lobbying activity matches pro-climate keyword(s): {', '.join(pro_matches[:5])}."
        )
    else:
        stance = LobbyingStance.UNKNOWN
        reasoning = (
            "No climate-related keywords identified in declared fields of interest or activities."
        )

    return stance, reasoning


def _assess_contradiction(
    stance: LobbyingStance,
    claim_raw_text: str,
    fields_of_interest: list[str],
) -> tuple[bool, str | None]:
    """Determine whether lobbying activity contradicts the claim.

    A contradiction is flagged when the company has a climate-related public
    claim AND its lobbying stance is ANTI_CLIMATE or MIXED with anti-climate
    signals in climate-policy areas.

    Args:
        stance: Classified lobbying stance.
        claim_raw_text: The verbatim claim text.
        fields_of_interest: Declared fields of interest.

    Returns:
        A tuple of (contradicts_claim, explanation | None).
    """
    climate_claim_keywords = (
        "net zero",
        "carbon neutral",
        "climate",
        "emission",
        "renewable",
        "sustainability",
        "green",
        "decarboni",
    )
    claim_lower = claim_raw_text.lower()
    is_climate_claim = any(kw in claim_lower for kw in climate_claim_keywords)

    if not is_climate_claim:
        return False, None

    if stance == LobbyingStance.ANTI_CLIMATE:
        contradicting_fields = [
            f for f in fields_of_interest if any(kw in f.lower() for kw in _ANTI_CLIMATE_KEYWORDS)
        ]
        explanation = (
            f"The company publicly claims {claim_raw_text[:120]!r} while simultaneously "
            f"lobbying in the following policy areas that work against climate legislation: "
            f"{', '.join(contradicting_fields[:3])}. "
            "This constitutes a material contradiction between public commitments and "
            "Brussels lobbying activity."
        )
        return True, explanation

    if stance == LobbyingStance.MIXED:
        return True, (
            f"The company publicly claims {claim_raw_text[:120]!r} while its "
            "lobbying activity includes areas that oppose climate legislation alongside "
            "pro-climate areas. The net lobbying effect is mixed."
        )

    return False, None


def _parse_cost(raw_cost: Any) -> float | None:
    """Parse a Transparency Register cost declaration to a float.

    The register may return costs as a range string (e.g. ``"500000-999999"``)
    or as a numeric value. Returns the midpoint for ranges.

    Args:
        raw_cost: The raw cost value from the API response.

    Returns:
        Estimated cost as a float, or None if not parseable.
    """
    if raw_cost is None:
        return None
    try:
        if isinstance(raw_cost, (int, float)):
            return float(raw_cost)
        s = str(raw_cost).replace(",", "").strip()
        if "-" in s:
            parts = s.split("-")
            return (float(parts[0]) + float(parts[1])) / 2.0
        return float(s)
    except (ValueError, IndexError):
        return None
