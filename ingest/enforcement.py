"""Enforcement decisions on environmental claims, as evidence for the Judge Agent.

The records live in :py:mod:`ingest.enforcement_records`. Each was checked
against the authority's own page and re-checked independently, and each carries
a quote copied verbatim from that page. This module matches them to a company
and presents them as evidence in the authority's own terms: reference, date,
party, outcome and quote, with no characterisation added.

A record never decides a score by itself. Whether a decision concerns the claim
under assessment is for the scoring rules to establish; commitments, warnings,
open cases, rejected complaints and annulled decisions are context only.
"""

from __future__ import annotations

from core.logger import get_logger
from ingest.enforcement_records import RULINGS, Ruling
from ingest.name_matching import contains_name
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_enforcement_data"]

logger = get_logger(__name__)

_RULING_TYPES = frozenset(
    {
        "BANNED",
        "CONFIRMED_MISLEADING",
        "FINED",
        "COMMITMENTS",
        "WARNING",
        "INVESTIGATION",
        "NOT_UPHELD",
        "ANNULLED",
    }
)

# How each outcome is described in the evidence summary.
_OUTCOME_TEXT: dict[str, str] = {
    "BANNED": "complaint upheld; the advertising must not appear again in that form",
    "CONFIRMED_MISLEADING": "decision against the marketing",
    "FINED": "fine imposed",
    "COMMITMENTS": "commitments to change practices; no finding of a breach and no fine",
    "WARNING": "guidance or warning, without a finding on the company's own marketing",
    "INVESTIGATION": "case opened; no outcome is recorded",
    "NOT_UPHELD": "not upheld",
    "ANNULLED": "decision annulled on appeal",
}


def _validate(rulings: tuple[Ruling, ...]) -> None:
    """Fail at import if a record lacks what makes it citable.

    Raises:
        ValueError: If a record has no quote, no official URL, an unknown
            outcome, or a malformed date.
    """
    for r in rulings:
        problems = []
        if not r.quote.strip():
            problems.append("no verbatim quote")
        if not r.source_url.startswith(("https://", "http://")):
            problems.append("no official URL")
        if r.ruling_type not in _RULING_TYPES:
            problems.append(f"unknown outcome {r.ruling_type!r}")
        # A bare year where the source gives no date, as an annual report does.
        full = len(r.decision_date) == 10 and r.decision_date[4] == "-" == r.decision_date[7]
        year_only = len(r.decision_date) == 4 and r.decision_date.isdigit()
        if not (full or year_only):
            problems.append(f"date {r.decision_date!r} is neither YYYY-MM-DD nor YYYY")
        if problems:
            raise ValueError(f"Enforcement record {r.case_reference!r}: {', '.join(problems)}")


_validate(RULINGS)


def _normalise_name(name: str) -> str:
    """Lowercase and strip legal suffixes for fuzzy matching."""
    name = name.lower().strip()
    for suffix in (
        " plc",
        " ag",
        " se",
        " sa",
        " s.a.",
        " spa",
        " s.p.a.",
        " nv",
        " bv",
        " gmbh",
        " inc",
        " corp",
        " ltd",
        " limited",
        " group",
        " holding",
        " holdings",
        " a/s",
        " as",
        " ab",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


_BY_COMPANY: dict[str, list[Ruling]] = {}
for _ruling in RULINGS:
    for _alias in {_normalise_name(c) for c in _ruling.companies}:
        _BY_COMPANY.setdefault(_alias, []).append(_ruling)


def _summary(ruling: Ruling) -> str:
    """Describe a record in the authority's own terms."""
    body = f" ({ruling.body})" if ruling.body else ""
    return (
        f"{ruling.authority}{body} {ruling.case_reference} ({ruling.decision_date}), "
        f"{ruling.party_as_named}: {ruling.outcome or _OUTCOME_TEXT[ruling.ruling_type]}. "
        f'Quote from the official source: "{ruling.quote}"'
    )


async def fetch_enforcement_data(claim: Claim, company: object) -> list[Evidence]:
    """Return the verified enforcement records for a company as evidence.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        One Evidence record per matching enforcement record (may be empty).
    """
    name: str = getattr(company, "name", "")
    norm = _normalise_name(name)

    rulings = _BY_COMPANY.get(norm, [])

    # Partial whole-word match: catches "Ryanair Holdings plc" vs "Ryanair"
    if not rulings and len(norm) >= 5:
        for key, key_rulings in _BY_COMPANY.items():
            if contains_name(key, norm):
                rulings = key_rulings
                break

    if not rulings:
        logger.info(
            f"Enforcement: no records found for {name!r}",
            extra={"operation": "enforcement_not_found", "company": name},
        )
        return []

    logger.info(
        f"Enforcement: {len(rulings)} record(s) found for {name!r}",
        extra={"operation": "enforcement_found", "company": name, "count": len(rulings)},
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.ENFORCEMENT,
            evidence_type=EvidenceType.ENFORCEMENT_RULING,
            source_url=ruling.source_url,
            raw_data={
                "authority": ruling.authority,
                "country": ruling.country,
                "decision_date": ruling.decision_date,
                "case_reference": ruling.case_reference,
                "party_as_named": ruling.party_as_named,
                "ruling_type": ruling.ruling_type,
                "claim_type": ruling.claim_type,
                "quote": ruling.quote,
                "description": ruling.description,
                "archive_url": ruling.archive_url,
                "companies_covered": list(ruling.companies),
                "outcome": ruling.outcome,
                "body": ruling.body,
            },
            summary=_summary(ruling),
            data_year=int(ruling.decision_date[:4]),
            supports_claim=None,
            confidence=0.95,
        )
        for ruling in rulings
    ]
