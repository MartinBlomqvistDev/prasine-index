"""What an evidence record can speak to: one specific claim, or the company as a whole.

A verified emissions record for the installations a claim is about can show that
claim to be true or false. A lobbying rating, an investor benchmark or a list of
expanding companies describes the company as a whole and is context for any one
claim. Enforcement decisions are reported with their quotations but never carry
a score on their own: Prasine reports what authorities decided and does not rest
its own findings on those decisions. The judge's band rules and the published
evidence list both rest on these distinctions, so they are defined once, here.
"""

from __future__ import annotations

from models.evidence import Evidence, EvidenceSource

__all__ = [
    "CLAIM_LEVEL_SOURCES",
    "OFFICIAL_RECORD_SOURCES",
    "is_claim_level",
    "record_scope",
]

# Sources whose records can speak to one specific claim.
CLAIM_LEVEL_SOURCES = frozenset(
    {
        EvidenceSource.EU_ETS,
        EvidenceSource.EPRTR,
        EvidenceSource.CLIMATE_TRACE,
        EvidenceSource.SBTI,
        EvidenceSource.SOURCE_DOCUMENT,
        EvidenceSource.GOGET,
        EvidenceSource.GCPT,
        EvidenceSource.EGT,
    }
)

# Official records that can show a claim to be false outright.
OFFICIAL_RECORD_SOURCES = frozenset(
    {EvidenceSource.EU_ETS, EvidenceSource.EPRTR, EvidenceSource.SBTI}
)


def is_claim_level(evidence: Evidence) -> bool:
    """Return whether a record can speak to one specific claim."""
    return evidence.source in CLAIM_LEVEL_SOURCES


def record_scope(evidence: Evidence) -> str:
    """Describe what a record can speak to, for prompts and logs."""
    if evidence.source == EvidenceSource.ENFORCEMENT:
        outcome = evidence.raw_data.get("ruling_type", "unknown")
        return f"enforcement record, context ({outcome})"
    return "claim-level" if is_claim_level(evidence) else "company-level"
