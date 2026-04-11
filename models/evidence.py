"""Pydantic v2 models representing the external evidence gathered by the Verification Agent.

Each Evidence record captures a single data point from one EU open data source,
together with the agent's assessment of whether that data supports or contradicts
the claim. VerificationResult aggregates all evidence for a claim into a single
structured output passed to the Judge Agent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Evidence",
    "EvidenceSource",
    "EvidenceType",
    "VerificationResult",
]


class EvidenceSource(StrEnum):
    """Open data sources queried by the Verification Agent.

    Each value corresponds to a dedicated ingest module under ``ingest/``.
    The Verification Agent queries all applicable sources in parallel via
    ``asyncio.gather()`` and produces one Evidence record per source.
    """

    EU_ETS = "EU_ETS"
    CDP = "CDP"
    EUROSTAT = "EUROSTAT"
    EUR_LEX = "EUR_LEX"
    EU_TRANSPARENCY_REGISTER = "EU_TRANSPARENCY_REGISTER"
    SBTI = "SBTI"
    EPRTR = "EPRTR"
    INFLUENCE_MAP = "INFLUENCE_MAP"
    ENFORCEMENT = "ENFORCEMENT"
    CA100 = "CA100"
    FOSSIL_FINANCE = "FOSSIL_FINANCE"
    COAL_EXIT = "COAL_EXIT"


class EvidenceType(StrEnum):
    """Semantic classification of the evidence, independent of its source.

    Used by the Judge Agent to weight evidence categories differently. Verified
    regulatory emissions data carries more weight than self-reported figures.
    """

    VERIFIED_EMISSIONS = "VERIFIED_EMISSIONS"
    SELF_REPORTED_EMISSIONS = "SELF_REPORTED_EMISSIONS"
    LEGISLATIVE_RECORD = "LEGISLATIVE_RECORD"
    LOBBYING_RECORD = "LOBBYING_RECORD"
    STATISTICAL = "STATISTICAL"
    TARGET_RECORD = "TARGET_RECORD"
    POLLUTION_RECORD = "POLLUTION_RECORD"
    ENFORCEMENT_RULING = "ENFORCEMENT_RULING"
    BENCHMARK_ASSESSMENT = "BENCHMARK_ASSESSMENT"
    FINANCING_RECORD = "FINANCING_RECORD"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class Evidence(BaseModel):
    """A single data point retrieved from one EU open data source.

    Evidence is always attached to a specific Claim and carries the full raw
    response from the upstream data source alongside the Verification Agent's
    structured interpretation. The ``supports_claim`` field is the agent's
    boolean assessment; ``confidence`` quantifies certainty in that assessment.

    This model is frozen: evidence records are write-once to preserve the
    integrity of the audit chain.

    Attributes:
        id: Unique identifier for this evidence record.
        claim_id: The Claim this evidence was gathered against.
        trace_id: Pipeline-wide trace identifier, inherited from the Claim.
        source: The EU open data source that provided this evidence.
        evidence_type: Semantic classification of the evidence type.
        source_url: Direct URL to the specific data point or document, if
            resolvable. Some API responses do not map to a stable URL.
        retrieved_at: UTC timestamp of when the data was fetched.
        raw_data: Full parsed response from the upstream source, preserved
            verbatim for auditability and report citations.
        summary: Verification Agent's natural-language summary of what this
            data point shows in relation to the claim.
        data_year: The reference year the data pertains to, if determinable.
            Critical for matching claimed targets (e.g. "net zero by 2030")
            against the correct measurement period.
        supports_claim: Agent's assessment of whether this evidence supports
            the claim (True), contradicts it (False), or is inconclusive (None).
        confidence: Agent's confidence in ``supports_claim``, in the range
            [0.0, 1.0]. A value of 1.0 indicates unambiguous data; lower values
            reflect missing years, aggregated figures, or ambiguous scope.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    claim_id: uuid.UUID = Field(
        ..., description="Foreign key to the Claim this evidence was gathered against."
    )
    trace_id: uuid.UUID = Field(
        ..., description="Pipeline trace identifier, inherited from the Claim."
    )
    source: EvidenceSource = Field(
        ..., description="EU open data source that provided this evidence."
    )
    evidence_type: EvidenceType = Field(
        ..., description="Semantic classification of the evidence type."
    )
    source_url: str | None = Field(
        default=None,
        description="Direct URL to the specific data point or document, if resolvable.",
    )
    retrieved_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when the data was fetched from the upstream source.",
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Full parsed response from the upstream source, preserved verbatim for audit and citation.",
    )
    summary: str = Field(
        ...,
        description=(
            "Verification Agent's natural-language summary of what this data point "
            "shows in relation to the claim under assessment."
        ),
    )
    data_year: int | None = Field(
        default=None,
        description=(
            "Reference year the data pertains to. Critical for matching claimed targets "
            "against the correct measurement period."
        ),
    )
    supports_claim: bool | None = Field(
        default=None,
        description=(
            "Agent assessment: True if evidence supports the claim, False if it contradicts "
            "it, None if inconclusive or out of scope."
        ),
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the supports_claim assessment, in [0.0, 1.0]. "
            "Lower values reflect missing data years, aggregated figures, or ambiguous scope."
        ),
    )

    @field_validator("data_year")
    @classmethod
    def _validate_data_year(cls, value: int | None) -> int | None:
        """Reject implausible data years.

        Args:
            value: The year value to validate.

        Returns:
            The validated year, or None.

        Raises:
            ValueError: If the year is outside the plausible range for EU
                emissions and climate data (1990–2100).
        """
        if value is not None and not (1990 <= value <= 2100):
            raise ValueError(f"data_year {value!r} is outside the plausible range [1990, 2100].")
        return value


class VerificationResult(BaseModel):
    """Aggregated output of the Verification Agent for a single Claim.

    This model is the complete handover from the Verification Agent to the
    Judge Agent. It contains all gathered evidence, an overall assessment
    narrative, and an explicit list of data gaps — sources that were queried
    but failed or returned no usable data.

    This model is frozen: the verification record is sealed before being
    passed downstream.

    Attributes:
        claim_id: The Claim that was verified.
        trace_id: Pipeline-wide trace identifier, inherited from the Claim.
        evidence: All evidence records gathered during verification. May be
            empty if all sources failed; the Judge Agent handles this case.
        verified_at: UTC timestamp of when verification completed.
        overall_assessment: Verification Agent's free-text summary synthesising
            all evidence, for use as context in the Judge Agent prompt.
        data_gaps: List of source names or descriptions where data was
            unavailable, insufficient, or the upstream source returned an error.
            Explicitly surfaced so the Judge Agent can reflect uncertainty.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    claim_id: uuid.UUID = Field(..., description="Foreign key to the verified Claim.")
    trace_id: uuid.UUID = Field(
        ..., description="Pipeline trace identifier, inherited from the Claim."
    )
    evidence: list[Evidence] = Field(
        default_factory=list,
        description="All evidence records gathered during the verification pass.",
    )
    verified_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when the Verification Agent completed its run.",
    )
    overall_assessment: str = Field(
        ...,
        description=(
            "Verification Agent's synthesised summary of all evidence, provided as "
            "context to the Judge Agent."
        ),
    )
    data_gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Sources that were queried but failed or returned insufficient data. "
            "Surfaced explicitly so the Judge Agent can weight its confidence accordingly."
        ),
    )
    sources_queried: list[str] = Field(
        default_factory=list,
        description="Names of all data sources queried during this verification pass.",
    )
