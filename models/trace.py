"""Pydantic v2 model representing a single agent execution step within the Prasine Index pipeline.

Every agent writes an AgentTrace row when it starts and updates it on completion
or failure, providing a full structured audit log for any claim. Combined with
the claim-level trace_id, this enables complete pipeline replay, latency analysis
per agent, and LLMOps observability without an external tracing service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "AgentName",
    "AgentOutcome",
    "AgentTrace",
]


class AgentName(StrEnum):
    """Canonical identifiers for the seven agents in the Prasine Index pipeline.

    These values appear in every AgentTrace row, enabling per-agent performance
    analysis and selective replay of failed pipeline stages.
    """

    DISCOVERY = "DISCOVERY"
    EXTRACTION = "EXTRACTION"
    CONTEXT = "CONTEXT"
    VERIFICATION = "VERIFICATION"
    LOBBYING = "LOBBYING"
    JUDGE = "JUDGE"
    REPORT = "REPORT"


class AgentOutcome(StrEnum):
    """Terminal outcome of an agent execution step.

    PARTIAL indicates the agent completed but with degraded output — for example,
    the Verification Agent returning evidence from only a subset of queried sources
    due to upstream failures. The Judge Agent is designed to handle PARTIAL
    verification results gracefully.
    """

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class AgentTrace(BaseModel):
    """A structured execution log entry for a single agent step in the pipeline.

    One AgentTrace row is created when an agent begins processing and updated
    when it completes (successfully or otherwise). The combination of ``trace_id``
    and ``agent`` uniquely identifies a step within a claim's pipeline run.

    The ``trace_id`` is shared with the Claim and all associated models, making
    it the single correlation key for reconstructing the full execution history
    of any claim. Structured fields (``duration_ms``, ``tokens_used``,
    ``retry_count``) expose the metrics required for LLMOps analysis without
    relying on log parsing.

    Attributes:
        id: Unique identifier for this trace entry.
        trace_id: Pipeline-wide trace identifier inherited from the Claim.
            Used to correlate all agent steps for a given claim.
        claim_id: The Claim being processed. None only for the Discovery Agent,
            which produces claims rather than consuming them.
        agent: The agent that produced this trace entry.
        outcome: Terminal outcome of the execution step.
        started_at: UTC timestamp of when the agent began processing.
        completed_at: UTC timestamp of when the agent finished. None while
            the agent is still running.
        duration_ms: Wall-clock execution time in milliseconds, computed from
            ``started_at`` and ``completed_at``. None until completion.
        input_schema: Fully-qualified name of the Pydantic model class received
            as input (e.g. ``"models.claim.Claim"``). Preserved for replay.
        output_schema: Fully-qualified name of the Pydantic model class produced
            as output. None if the agent failed before producing output.
        error_type: Exception class name if the agent raised an unhandled
            exception (e.g. ``"httpx.TimeoutException"``).
        error_message: Exception message or structured error detail.
        retry_count: Number of retries attempted before the final outcome was
            reached. Zero for first-attempt successes.
        llm_model_id: Identifier of the LLM called by this agent, if any
            (e.g. ``"claude-opus-4-6"``). None for non-LLM agents.
        tokens_used: Total tokens consumed by LLM calls within this agent step.
            None for non-LLM agents or if the upstream API did not return
            usage data.
        metadata: Agent-specific supplementary data (e.g. number of sources
            queried, semantic similarity scores). Not part of the core schema.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    trace_id: uuid.UUID = Field(
        ...,
        description="Pipeline trace identifier shared with the Claim and all associated models.",
    )
    claim_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Foreign key to the Claim being processed. None only for the Discovery Agent, "
            "which produces claims rather than consuming them."
        ),
    )
    agent: AgentName = Field(..., description="The agent that produced this trace entry.")
    outcome: AgentOutcome = Field(
        default=AgentOutcome.SUCCESS,
        description="Terminal outcome of the execution step.",
    )
    started_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when the agent began processing.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of when the agent finished; None while still running.",
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Wall-clock execution time in milliseconds; None until completion.",
    )
    input_schema: str = Field(
        ...,
        description="Fully-qualified Pydantic model class name received as input (e.g. 'models.claim.Claim').",
    )
    output_schema: str | None = Field(
        default=None,
        description="Fully-qualified Pydantic model class name produced as output; None on failure.",
    )
    error_type: str | None = Field(
        default=None,
        description="Exception class name if the agent raised an unhandled exception.",
    )
    error_message: str | None = Field(
        default=None,
        description="Exception message or structured error detail.",
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of retries attempted before the final outcome was reached.",
    )
    llm_model_id: str | None = Field(
        default=None,
        description="LLM identifier used in this agent step (e.g. 'claude-opus-4-6'); None for non-LLM agents.",
    )
    tokens_used: int | None = Field(
        default=None,
        ge=0,
        description="Total tokens consumed by LLM calls within this step; None for non-LLM agents.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Agent-specific supplementary data not part of the core schema "
            "(e.g. source query counts, similarity scores)."
        ),
    )

    @model_validator(mode="after")
    def _validate_duration_consistency(self) -> AgentTrace:
        """Validate that duration_ms is consistent with the completion timestamps.

        If both ``completed_at`` and ``duration_ms`` are set, verifies that
        ``duration_ms`` is non-negative and that ``completed_at`` is not before
        ``started_at``.

        Returns:
            The validated AgentTrace instance.

        Raises:
            ValueError: If ``completed_at`` precedes ``started_at``, or if
                ``duration_ms`` is provided without ``completed_at``.
        """
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError(
                "completed_at cannot precede started_at."
            )
        if self.duration_ms is not None and self.completed_at is None:
            raise ValueError(
                "duration_ms requires completed_at to be set."
            )
        return self

    @model_validator(mode="after")
    def _validate_error_fields_on_failure(self) -> AgentTrace:
        """Validate that failure outcomes carry diagnostic error information.

        Returns:
            The validated AgentTrace instance.

        Raises:
            ValueError: If ``outcome`` is FAILURE but neither ``error_type``
                nor ``error_message`` is provided.
        """
        if self.outcome == AgentOutcome.FAILURE and self.error_type is None and self.error_message is None:
            raise ValueError(
                "AgentTrace with outcome FAILURE must set at least one of "
                "error_type or error_message."
            )
        return self
