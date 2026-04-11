"""Pydantic v2 model representing a company's lobbying activity as retrieved from the EU Transparency Register.

A company that simultaneously claims climate leadership while lobbying against
climate legislation in Brussels represents the strongest and most legally
actionable form of greenwashing. This contradiction is surfaced explicitly as a
primary signal in the Judge Agent's scoring and the published report.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LobbyingRecord",
    "LobbyingStance",
]


class LobbyingStance(StrEnum):
    """Assessment of whether the company's lobbying activities align with its green claims.

    Determined by the Lobbying Agent by cross-referencing the company's declared
    fields of interest and lobbying activities against the substance of its claims.
    A PRO_CLIMATE stance does not exonerate a claim, but an ANTI_CLIMATE stance
    is weighted heavily by the Judge Agent as a corroborating greenwashing signal.
    """

    PRO_CLIMATE = "PRO_CLIMATE"
    ANTI_CLIMATE = "ANTI_CLIMATE"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class LobbyingRecord(BaseModel):
    """A company's lobbying activity record as retrieved from the EU Transparency Register.

    The Lobbying Agent retrieves this data for every company under assessment and
    uses it to answer the most important accountability question in the greenwashing
    space: is the company lobbying against the very legislation its public claims
    purport to support?

    When ``contradicts_claim`` is True, the ``contradiction_explanation`` field
    provides a specific natural-language description of the contradiction, which
    is reproduced verbatim in the published report.

    This model is frozen: lobbying records are immutable audit artifacts. A new
    retrieval produces a new record with a new ``retrieved_at`` timestamp, allowing
    the system to track changes in lobbying activity over time.

    Attributes:
        id: Unique identifier for this lobbying record.
        company_id: The Company whose lobbying activity this record describes.
        claim_id: The Claim this record was retrieved in support of assessing.
        trace_id: Pipeline-wide trace identifier, inherited from the Claim.
        transparency_register_id: The registrant's identifier in the EU
            Transparency Register. May belong to a subsidiary or trade
            association acting on the company's behalf.
        registrant_name: The name of the registered lobbying entity, which
            may differ from the parent company name.
        registration_date: Date the lobbying entity was registered, if
            available in the Transparency Register record.
        fields_of_interest: Declared policy areas in which the entity lobbies
            (e.g. ``"Climate policy"``, ``"Energy taxation"``).
        lobbying_activities: Specific activities declared in the register,
            such as meetings with DG CLIMA or participation in consultations.
        estimated_annual_cost_eur: Estimated annual lobbying expenditure in
            euros, as declared in the Transparency Register. This figure is
            self-reported and may be a range; the agent records the midpoint.
        stance: The Lobbying Agent's assessment of whether the lobbying
            activity aligns with or contradicts the company's green claims.
        stance_reasoning: Agent's reasoning for the ``stance`` classification,
            preserved for transparency.
        contradicts_claim: True if the lobbying activity materially contradicts
            the assessed claim. This is the primary output of the Lobbying Agent.
        contradiction_explanation: Specific description of the contradiction,
            reproduced in the published report. Required when
            ``contradicts_claim`` is True.
        retrieved_at: UTC timestamp of when this record was fetched from the
            Transparency Register.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    company_id: uuid.UUID = Field(
        ..., description="Foreign key to the Company this record describes."
    )
    claim_id: uuid.UUID = Field(
        ..., description="Foreign key to the Claim this record was retrieved for."
    )
    trace_id: uuid.UUID = Field(
        ..., description="Pipeline trace identifier, inherited from the Claim."
    )
    transparency_register_id: str = Field(
        ...,
        description=(
            "Registrant identifier in the EU Transparency Register. "
            "May belong to a subsidiary or trade association acting on the company's behalf."
        ),
    )
    registrant_name: str = Field(
        ...,
        description="Registered lobbying entity name; may differ from the parent company name.",
    )
    registration_date: datetime | None = Field(
        default=None,
        description="Date the lobbying entity was registered in the Transparency Register.",
    )
    fields_of_interest: list[str] = Field(
        default_factory=list,
        description="Declared policy areas in which the entity lobbies (e.g. 'Climate policy').",
    )
    lobbying_activities: list[str] = Field(
        default_factory=list,
        description="Specific activities declared in the register, such as DG CLIMA meetings.",
    )
    estimated_annual_cost_eur: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Estimated annual lobbying expenditure in euros as declared in the register. "
            "Self-reported; may reflect a range midpoint."
        ),
    )
    stance: LobbyingStance = Field(
        default=LobbyingStance.UNKNOWN,
        description="Lobbying Agent's assessment of alignment between lobbying activity and green claims.",
    )
    stance_reasoning: str = Field(
        ...,
        description="Agent's reasoning for the stance classification, preserved for transparency.",
    )
    contradicts_claim: bool = Field(
        default=False,
        description=(
            "True if the lobbying activity materially contradicts the assessed claim. "
            "Weighted heavily by the Judge Agent as a primary greenwashing signal."
        ),
    )
    contradiction_explanation: str | None = Field(
        default=None,
        description=(
            "Specific description of the contradiction between lobbying activity and the claim. "
            "Required when contradicts_claim is True; reproduced verbatim in the published report."
        ),
    )
    retrieved_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when this record was fetched from the EU Transparency Register.",
    )
