"""Lobbying Agent for the Prasine Index pipeline.

Cross-references the company against the EU Transparency Register to determine
whether it is a registered EU lobbyist. Registration data comes from the local
register export (data/EU_Transparency register_searchExport.xlsx, refreshed via
scripts/refresh_eu_transparency_register.py) — the same dataset used by the
Verification Agent's register node. Dataset:
https://data.europa.eu/api/hub/search/datasets/transparency-register

Registration alone does not indicate the direction of lobbying; LobbyMap
(queried in the Verification Agent fan-out) provides direction. This agent's
output is therefore contextual: it confirms registered lobbying activity and
carries the registration metadata into the Judge Agent's evidence package.

A failed or empty lookup is a DATA GAP, never a finding. The agent must not
produce output implying a company is "not registered" — name matching against
the export is fuzzy and the export may be absent.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from ingest.eu_transparency_register import lookup_registration, register_export_available
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
        record: The lobbying registration record for this company, or None if
            no match was found in the register export or the export is
            unavailable. None is a data gap, not evidence of non-registration.
        trace: Structured execution record for this agent step.
    """

    model_config = ConfigDict(from_attributes=True)

    record: LobbyingRecord | None = Field(
        default=None,
        description=(
            "Lobbying registration record, or None if no match was found in the "
            "register export or the export was unavailable (data gap, not a finding)."
        ),
    )
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


class LobbyingAgent:
    """Retrieves a company's EU Transparency Register registration.

    Looks the company up in the local register export by declared register ID
    first, then by fuzzy name match. When a registration is found, returns a
    :py:class:`~models.lobbying.LobbyingRecord` with stance UNKNOWN — the
    export records registration metadata only, not lobbying positions.
    Direction of lobbying comes from LobbyMap in the Verification Agent.

    When no registration is found, the result record is None and the trace
    metadata states why (export missing vs. no name match). Downstream prompts
    treat a None record strictly as a data gap.
    """

    async def run(self, input: LobbyingInput) -> LobbyingResult:
        """Retrieve the register entry for the given claim and company.

        Args:
            input: Validated lobbying input containing the claim and company.

        Returns:
            A :py:class:`LobbyingResult` with the registration record (or None
            as a data gap) and the execution trace.
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
        gap_reason: str | None = None

        if not register_export_available():
            outcome = AgentOutcome.PARTIAL
            gap_reason = "register_export_unavailable"
            logger.warning(
                "Lobbying check: local Transparency Register export unavailable — "
                "data gap, not evidence of non-registration. "
                "Run scripts/refresh_eu_transparency_register.py.",
                extra={"operation": "lobbying_export_unavailable"},
            )
        else:
            registration = lookup_registration(input.company.name)
            if registration is None:
                outcome = AgentOutcome.SKIPPED
                gap_reason = "no_match_in_register_export"
                logger.info(
                    f"Lobbying check: no register-export match for {input.company.name!r} "
                    "(fuzzy name lookup) — treated as data gap",
                    extra={"operation": "lobbying_no_match"},
                )
            else:
                record = _build_record(input, registration)
                logger.info(
                    f"Lobbying check: {input.company.name!r} matched register entry "
                    f"{registration['reg_number']} ({registration['category']})",
                    extra={"operation": "lobbying_match", "reg_number": registration["reg_number"]},
                )

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
            metadata={
                "has_record": record is not None,
                "gap_reason": gap_reason,
                "stance": record.stance.value if record else None,
            },
        )

        return LobbyingResult(record=record, trace=trace)


def _build_record(input: LobbyingInput, registration: dict[str, str]) -> LobbyingRecord:
    """Construct a LobbyingRecord from a register-export match.

    The export carries registration metadata only (number, name, status,
    category, country) — no declared fields of interest or activities — so
    the stance is always UNKNOWN and no contradiction is asserted here.
    LobbyMap evidence in the verification fan-out carries lobbying direction.

    Args:
        input: The lobbying agent input.
        registration: Register-export fields from
            :py:func:`~ingest.eu_transparency_register.lookup_registration`.

    Returns:
        A :py:class:`~models.lobbying.LobbyingRecord` with stance UNKNOWN.
    """
    status = registration["status"].strip().lower()
    status_word = "an active" if status == "activated" else f"a {status or 'registered'}"
    return LobbyingRecord(
        company_id=input.company.id,
        claim_id=input.claim.id,
        trace_id=input.claim.trace_id,
        transparency_register_id=registration["reg_number"],
        registrant_name=registration["name"],
        fields_of_interest=[],
        lobbying_activities=[],
        stance=LobbyingStance.UNKNOWN,
        stance_reasoning=(
            f"EU Transparency Register export confirms {registration['name']} is "
            f"{status_word} registrant (category: {registration['category']}, "
            f"HQ: {registration['country']}, reg. no. {registration['reg_number']}). "
            "Registration confirms engagement with EU institutions but does not "
            "indicate the direction of lobbying — cross-reference LobbyMap evidence "
            "for lobbying positions."
        ),
        contradicts_claim=False,
        contradiction_explanation=None,
    )
