"""Pydantic v2 models representing a green claim's full lifecycle within the Prasine Index pipeline.

A Claim is the atomic unit of work: it originates from a company document, travels
through all seven agents, and accumulates a verdict. ClaimLifecycle records every
status transition as an immutable audit event, providing a complete replay trail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "Claim",
    "ClaimCategory",
    "ClaimLifecycle",
    "ClaimStatus",
    "SourceType",
]


class ClaimStatus(StrEnum):
    """Ordered lifecycle states of a green claim as it moves through the pipeline.

    Values progress forward with the exception of MONITORING, which is re-entered
    after PUBLISHED when the claim is placed under ongoing surveillance.
    """

    DETECTED = "DETECTED"
    VERIFIED = "VERIFIED"
    SCORED = "SCORED"
    PUBLISHED = "PUBLISHED"
    MONITORING = "MONITORING"


class ClaimCategory(StrEnum):
    """Taxonomy of green claim types, aligned with EU environmental claims taxonomy (EmpCo 2024/825).

    This classification drives how the Verification Agent selects evidence sources
    and how the Judge Agent weights contradicting data.
    """

    NET_ZERO_TARGET = "NET_ZERO_TARGET"
    CARBON_NEUTRAL = "CARBON_NEUTRAL"
    EMISSIONS_REDUCTION = "EMISSIONS_REDUCTION"
    RENEWABLE_ENERGY = "RENEWABLE_ENERGY"
    SUSTAINABLE_SUPPLY_CHAIN = "SUSTAINABLE_SUPPLY_CHAIN"
    BIODIVERSITY = "BIODIVERSITY"
    CIRCULAR_ECONOMY = "CIRCULAR_ECONOMY"
    SCIENCE_BASED_TARGETS = "SCIENCE_BASED_TARGETS"
    OTHER = "OTHER"


class SourceType(StrEnum):
    """Categories of source documents from which claims are extracted."""

    CSRD_REPORT = "CSRD_REPORT"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    PRESS_RELEASE = "PRESS_RELEASE"
    IR_PAGE = "IR_PAGE"
    WEBSITE = "WEBSITE"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class Claim(BaseModel):
    """A single green claim extracted from a company document.

    This is the central entity in the Prasine Index pipeline. Every other model
    — Evidence, GreenwashingScore, LobbyingRecord, AgentTrace — references a
    Claim by its ``id``. The ``trace_id`` follows the claim through all seven
    agents and links every AgentTrace row for full audit replay.

    Two accountability signals are tracked explicitly: whether the claim is a
    repeat of a previously scored claim (``is_repeat``), and whether the company
    modified the claim text after Prasine Index published a verdict
    (``modified_after_scoring``). Both are strong greenwashing indicators and
    are surfaced prominently in the Report Agent output.

    Attributes:
        id: Unique identifier for this claim instance.
        trace_id: Pipeline-wide trace identifier shared across all agent steps
            for this claim. Used to correlate AgentTrace rows.
        company_id: Reference to the Company that made this claim.
        source_url: Canonical URL of the source document.
        source_type: Category of document from which the claim was extracted.
        raw_text: Verbatim claim text as found in the source document.
        normalised_text: Cleaned, lower-cased text used for pgvector semantic
            similarity comparison against historical claims.
        claim_category: EU environmental claim taxonomy classification (EmpCo 2024/825).
        page_reference: Page number or section identifier within the source
            document, if applicable.
        publication_date: Date the source document was published, if known.
        detected_at: UTC timestamp of when the Discovery Agent first found
            this claim.
        status: Current lifecycle status.
        is_repeat: True if the company has made an equivalent claim previously,
            as determined by pgvector similarity search.
        previous_claim_id: ID of the most recent prior equivalent claim if
            ``is_repeat`` is True.
        modified_after_scoring: True if the company altered the claim text after
            Prasine Index published a greenwashing score — a strong accountability
            signal that is flagged in the published report.
        original_scored_text: Verbatim claim text at the time of scoring,
            preserved for comparison when ``modified_after_scoring`` becomes True.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    trace_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    company_id: uuid.UUID = Field(
        ..., description="Foreign key to the Company that made this claim."
    )
    source_url: str = Field(..., description="Canonical URL of the source document.")
    source_type: SourceType = Field(..., description="Category of the source document.")
    raw_text: str = Field(..., description="Verbatim claim text as found in the source document.")
    normalised_text: str | None = Field(
        default=None,
        description="Cleaned text used for pgvector semantic similarity search against historical claims.",
    )
    claim_category: ClaimCategory = Field(
        default=ClaimCategory.OTHER,
        description="EU environmental claim taxonomy classification (EmpCo 2024/825).",
    )
    page_reference: str | None = Field(
        default=None,
        description="Page number or section identifier within the source document.",
    )
    publication_date: datetime | None = Field(
        default=None,
        description="Date the source document was published, if determinable.",
    )
    detected_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of initial detection by the Discovery Agent.",
    )
    status: ClaimStatus = Field(
        default=ClaimStatus.DETECTED,
        description="Current lifecycle status of the claim.",
    )
    is_repeat: bool = Field(
        default=False,
        description=(
            "True if the company has made an equivalent claim previously. "
            "Determined by pgvector cosine similarity against historical normalised_text values."
        ),
    )
    previous_claim_id: uuid.UUID | None = Field(
        default=None,
        description="ID of the prior equivalent claim when is_repeat is True.",
    )
    modified_after_scoring: bool = Field(
        default=False,
        description=(
            "True if the company modified this claim after Prasine Index published "
            "a greenwashing score. Surfaced as a primary accountability signal in reports."
        ),
    )
    original_scored_text: str | None = Field(
        default=None,
        description="Verbatim claim text at time of scoring; populated when modification is detected.",
    )

    @model_validator(mode="after")
    def _validate_repeat_claim_reference(self) -> Claim:
        """Ensure repeat claims carry a reference to the prior equivalent claim.

        Returns:
            The validated Claim instance.

        Raises:
            ValueError: If ``is_repeat`` is True but ``previous_claim_id`` is None.
        """
        if self.is_repeat and self.previous_claim_id is None:
            raise ValueError("previous_claim_id must be provided when is_repeat is True.")
        return self

    @model_validator(mode="after")
    def _validate_modification_preserves_original(self) -> Claim:
        """Ensure modified claims preserve the original scored text for comparison.

        Returns:
            The validated Claim instance.

        Raises:
            ValueError: If ``modified_after_scoring`` is True but
                ``original_scored_text`` is None.
        """
        if self.modified_after_scoring and self.original_scored_text is None:
            raise ValueError(
                "original_scored_text must be preserved when modified_after_scoring is True."
            )
        return self


class ClaimLifecycle(BaseModel):
    """An immutable record of a single status transition for a Claim.

    One ClaimLifecycle row is inserted per status change. The complete sequence
    of rows for a given ``claim_id`` constitutes the full lifecycle audit trail
    and can be replayed to reconstruct the claim's history at any point in time.

    This model is frozen: lifecycle events are write-once and are never modified
    after creation.

    Attributes:
        id: Unique identifier for this lifecycle event.
        claim_id: The Claim that underwent the transition.
        from_status: The status before the transition. None for the initial
            DETECTED insertion.
        to_status: The status after the transition.
        transitioned_at: UTC timestamp of when the transition occurred.
        transitioned_by: Identifier of the agent or system component that
            triggered the transition (e.g. ``"extraction_agent"``,
            ``"judge_agent"``, ``"system"``).
        notes: Optional free-text annotation providing context for the
            transition, such as a failure reason or manual override rationale.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    claim_id: uuid.UUID = Field(..., description="Foreign key to the Claim that transitioned.")
    from_status: ClaimStatus | None = Field(
        default=None,
        description="Status before transition; None for the initial DETECTED insertion.",
    )
    to_status: ClaimStatus = Field(..., description="Status after the transition.")
    transitioned_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of the transition.",
    )
    transitioned_by: str = Field(
        ...,
        description="Agent or system component that triggered this transition.",
    )
    notes: str | None = Field(
        default=None,
        description="Optional annotation providing context for this transition.",
    )
