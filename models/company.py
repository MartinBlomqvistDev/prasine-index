"""Pydantic v2 models representing an EU-listed company and its aggregated context.

Company stores the stable registry data used to route queries to EU ETS, the
Transparency Register, and EUR-Lex. CompanyContext carries the company's claim
history and scoring trends, allowing the Judge Agent to treat repeat offenders
differently from first-time filers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "Company",
    "CompanyContext",
    "ScoreTrend",
]


class ScoreTrend(StrEnum):
    """Direction of a company's greenwashing score over assessed periods.

    Derived by the Context Agent from the sequence of historical GreenwashingScore
    records. Surfaces in the Judge Agent prompt and the published report to provide
    a longitudinal accountability signal.
    """

    IMPROVING = "IMPROVING"
    DETERIORATING = "DETERIORATING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class Company(BaseModel):
    """An EU-listed company that is subject to Prasine Index monitoring.

    Contains the stable registry data required to route verification queries to
    the correct upstream sources. The ``eu_ets_installation_ids`` list is critical
    for retrieving verified emissions data from the EU Emissions Trading System;
    a company may operate multiple installations under a single entity.

    The ``csrd_reporting`` flag indicates whether the company falls under the
    Corporate Sustainability Reporting Directive, which mandates disclosure of
    climate-related data and materially strengthens the evidence base for
    greenwashing assessments.

    Attributes:
        id: Unique identifier for this company record.
        name: Official registered company name.
        lei: Legal Entity Identifier (20-character alphanumeric), the ISO 17442
            standard identifier used across EU financial and regulatory systems.
        isin: International Securities Identification Number (12 characters),
            used when an LEI is unavailable.
        ticker: Stock exchange ticker symbol, if listed.
        country: ISO 3166-1 alpha-2 country code of the registered jurisdiction.
        sector: Primary business sector (e.g. ``"Energy"``, ``"Materials"``).
        sub_sector: More granular industry classification, if available.
        eu_ets_installation_ids: List of EU ETS installation identifiers for
            this company. Used by the Verification Agent to query EUTL for
            verified annual emissions data.
        transparency_register_id: EU Transparency Register identifier, used by
            the Lobbying Agent to retrieve lobbying activity records.
        ir_page_url: URL of the company's investor relations page, monitored
            continuously by the Discovery Agent.
        csrd_reporting: True if the company is subject to CSRD disclosure
            obligations, which strengthens the evidentiary standard applied
            during scoring.
        created_at: UTC timestamp of when this record was first inserted.
        updated_at: UTC timestamp of the most recent update to this record.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(..., description="Official registered company name.")
    lei: str | None = Field(
        default=None,
        description=(
            "Legal Entity Identifier (ISO 17442): 20-character alphanumeric. "
            "Primary identifier for routing queries across EU regulatory systems."
        ),
    )
    isin: str | None = Field(
        default=None,
        description="International Securities Identification Number (12 characters).",
    )
    ticker: str | None = Field(
        default=None,
        description="Stock exchange ticker symbol, if the company is publicly listed.",
    )
    country: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code of the registered jurisdiction.",
    )
    sector: str = Field(
        ...,
        description="Primary business sector (e.g. 'Energy', 'Materials', 'Utilities').",
    )
    sub_sector: str | None = Field(
        default=None,
        description="More granular industry classification, if available.",
    )
    eu_ets_installation_ids: list[str] = Field(
        default_factory=list,
        description=(
            "EU ETS installation identifiers for this company. "
            "One company may operate multiple installations. Used to query EUTL for "
            "verified annual emissions data."
        ),
    )
    transparency_register_id: str | None = Field(
        default=None,
        description="EU Transparency Register identifier used by the Lobbying Agent.",
    )
    ir_page_url: str | None = Field(
        default=None,
        description="URL of the company's investor relations page, monitored by the Discovery Agent.",
    )
    csrd_reporting: bool = Field(
        default=False,
        description=(
            "True if the company is subject to CSRD disclosure obligations. "
            "Strengthens the evidentiary standard applied during scoring."
        ),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of record creation.",
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of the most recent update to this record.",
    )

    @field_validator("lei")
    @classmethod
    def _validate_lei_format(cls, value: str | None) -> str | None:
        """Validate that the LEI conforms to the ISO 17442 format.

        ISO 17442 specifies a 20-character string composed of uppercase
        alphanumeric characters. This validator enforces length and character
        set without performing check-digit verification.

        Args:
            value: The LEI string to validate.

        Returns:
            The validated LEI string, or None.

        Raises:
            ValueError: If the value is not a 20-character alphanumeric string.
        """
        if value is not None:
            if len(value) != 20 or not value.isalnum():
                raise ValueError(
                    f"LEI must be a 20-character alphanumeric string (ISO 17442); received {value!r}."
                )
            return value.upper()
        return value

    @field_validator("isin")
    @classmethod
    def _validate_isin_format(cls, value: str | None) -> str | None:
        """Validate that the ISIN conforms to the ISO 6166 format.

        ISO 6166 specifies a 12-character string: 2-letter country code followed
        by 9 alphanumeric characters and a single check digit.

        Args:
            value: The ISIN string to validate.

        Returns:
            The validated ISIN string in uppercase, or None.

        Raises:
            ValueError: If the value is not a 12-character alphanumeric string.
        """
        if value is not None:
            if len(value) != 12 or not value.isalnum():
                raise ValueError(
                    f"ISIN must be a 12-character alphanumeric string (ISO 6166); received {value!r}."
                )
            return value.upper()
        return value

    @field_validator("country")
    @classmethod
    def _validate_country_code(cls, value: str) -> str:
        """Normalise country code to uppercase.

        Args:
            value: The ISO 3166-1 alpha-2 country code.

        Returns:
            The uppercased country code.
        """
        return value.upper()


class CompanyContext(BaseModel):
    """Aggregated historical context for a Company, assembled by the Context Agent.

    This model is produced immediately before the Verification Agent runs and is
    passed through to the Judge Agent. It provides longitudinal accountability
    signals: a company that has made the same undelivered promise three times is
    treated differently from one making a first-time claim.

    The ``similar_historical_claim_ids`` field contains IDs of semantically similar
    claims retrieved via pgvector cosine similarity on normalised claim text.

    Attributes:
        company: The full Company record.
        total_claims_assessed: Total number of claims from this company that
            have been assessed by the pipeline to date.
        repeat_claim_count: Number of those claims that were flagged as repeats
            of a previously scored claim.
        average_greenwashing_score: Mean greenwashing score across all assessed
            claims, or None if no claims have been scored yet.
        worst_greenwashing_score: Highest (worst) greenwashing score on record
            for this company, or None if no claims have been scored.
        score_trend: Direction of the company's greenwashing scores over time.
        similar_historical_claim_ids: IDs of historical claims with high cosine
            similarity to the current claim under assessment, retrieved via
            pgvector. Passed to the Judge Agent as precedent context.
        last_assessed_at: UTC timestamp of the most recent completed assessment
            for this company, or None if this is the first.
        context_retrieved_at: UTC timestamp of when this context object was
            assembled by the Context Agent.
    """

    model_config = ConfigDict(from_attributes=True)

    company: Company = Field(..., description="The full Company record.")
    total_claims_assessed: int = Field(
        default=0,
        ge=0,
        description="Total claims from this company assessed by the pipeline to date.",
    )
    repeat_claim_count: int = Field(
        default=0,
        ge=0,
        description="Number of assessed claims flagged as repeats of a previously scored claim.",
    )
    average_greenwashing_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Mean greenwashing score across all assessed claims; None if no claims scored.",
    )
    worst_greenwashing_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Highest (worst) greenwashing score on record; None if no claims scored.",
    )
    score_trend: ScoreTrend = Field(
        default=ScoreTrend.INSUFFICIENT_DATA,
        description="Direction of the company's greenwashing scores over assessed periods.",
    )
    similar_historical_claim_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description=(
            "IDs of historical claims with high cosine similarity to the current claim, "
            "retrieved via pgvector. Provided as precedent context to the Judge Agent."
        ),
    )
    last_assessed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the most recent completed assessment; None for first-time companies.",
    )
    context_retrieved_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when this context object was assembled by the Context Agent.",
    )
