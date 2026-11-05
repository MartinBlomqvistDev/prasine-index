"""What an evidence record can speak to: one specific claim, or the company as a whole.

A verified emissions record for the installations a claim is about can show that
claim to be true or false. A lobbying rating, an investor benchmark or a list of
expanding companies usually describes the company as a whole and is context for
any one claim.

Climate pledges are the exception. A net-zero target, a carbon-neutrality claim
or a science-based target is a commitment about the whole company, and the UN
High-Level Expert Group on net-zero commitments set out what such a pledge must
include: no new fossil fuel supply and no lobbying against climate policy. For a
pledge, the records that measure those two things are evidence about the claim
itself.

Enforcement decisions are reported with their quotations. A decision counts as
evidence about a claim only when the judge identifies it as a finding on the
same claim, or materially identical wording, from the last five years.

The judge's band rules and the published evidence list both rest on these
distinctions, so they are defined once, here.
"""

from __future__ import annotations

from datetime import date

from models.claim import Claim, ClaimCategory
from models.evidence import Evidence, EvidenceSource

__all__ = [
    "CLAIM_LEVEL_SOURCES",
    "FINDING_OUTCOMES",
    "HLEG_CITATION",
    "HLEG_FOSSIL_SUPPLY",
    "HLEG_LOBBYING",
    "HLEG_URL",
    "INTEGRITY_SOURCES",
    "OFFICIAL_RECORD_SOURCES",
    "is_claim_level",
    "is_pledge",
    "is_recent_finding",
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

# Company records that measure what a climate pledge must include: new fossil
# fuel supply, lobbying, and investors' assessments of the pledge itself.
INTEGRITY_SOURCES = frozenset(
    {
        EvidenceSource.LOBBY_MAP,
        EvidenceSource.GOGEL,
        EvidenceSource.COAL_EXIT,
        EvidenceSource.CA100,
        EvidenceSource.TPI,
        EvidenceSource.FOSSIL_FINANCE,
    }
)

# Enforcement outcomes that are findings against the advertising itself.
FINDING_OUTCOMES = frozenset({"BANNED", "CONFIRMED_MISLEADING", "FINED"})

# A finding on the same claim counts for five years after the decision.
FINDING_MAX_AGE_YEARS = 5

_PLEDGE_CATEGORIES = frozenset(
    {
        ClaimCategory.NET_ZERO_TARGET,
        ClaimCategory.CARBON_NEUTRAL,
        ClaimCategory.SCIENCE_BASED_TARGETS,
    }
)

_PLEDGE_TERMS = (
    "net zero",
    "net-zero",
    "netzero",
    "carbon neutral",
    "carbon-neutral",
    "climate neutral",
    "climate-neutral",
    "paris agreement",
    "paris-aligned",
    "paris aligned",
    "1.5°c",
    "1.5 °c",
    "1.5c",
    "1.5 degrees",
)

HLEG_CITATION = (
    "UN High-Level Expert Group on the Net Zero Emissions Commitments of Non-State "
    "Entities, Integrity Matters: Net Zero Commitments by Businesses, Financial "
    "Institutions, Cities and Regions (2022), p. 7"
)
HLEG_URL = "https://www.un.org/sites/un2.un.org/files/high-levelexpertgroupupdate7.pdf"
HLEG_FOSSIL_SUPPLY = (
    "Non-state actors cannot claim to be net zero while continuing to build or invest "
    "in new fossil fuel supply."
)
HLEG_LOBBYING = (
    "Non-state actors cannot lobby to undermine ambitious government climate policies "
    "either directly or through trade associations or other bodies."
)


def is_pledge(claim: Claim | None) -> bool:
    """Return whether a claim is a company-wide climate pledge.

    A pledge is a net-zero target, a carbon-neutrality claim, a science-based
    target, or a claim that names net zero, climate neutrality, the Paris
    Agreement or 1.5°C.
    """
    if claim is None:
        return False
    if claim.claim_category in _PLEDGE_CATEGORIES:
        return True
    text = claim.raw_text.lower()
    return any(term in text for term in _PLEDGE_TERMS)


def is_recent_finding(evidence: Evidence, today: date | None = None) -> bool:
    """Return whether an enforcement record is a finding from the last five years."""
    if evidence.source != EvidenceSource.ENFORCEMENT:
        return False
    if evidence.raw_data.get("ruling_type") not in FINDING_OUTCOMES:
        return False
    decided = str(evidence.raw_data.get("decision_date", ""))[:4]
    if not decided.isdigit():
        return False
    year = (today or date.today()).year
    return year - int(decided) <= FINDING_MAX_AGE_YEARS


def is_claim_level(evidence: Evidence, claim: Claim | None = None) -> bool:
    """Return whether a record can speak to this specific claim.

    Enforcement records are never claim-level by source alone; a finding on the
    same claim is admitted separately, by the judge naming it.
    """
    if evidence.source in CLAIM_LEVEL_SOURCES:
        return True
    return evidence.source in INTEGRITY_SOURCES and is_pledge(claim)


def record_scope(evidence: Evidence, claim: Claim | None = None) -> str:
    """Describe what a record can speak to, for prompts and logs."""
    if evidence.source == EvidenceSource.ENFORCEMENT:
        outcome = evidence.raw_data.get("ruling_type", "unknown")
        if is_recent_finding(evidence):
            return f"enforcement finding from the last five years ({outcome})"
        return f"enforcement record, context ({outcome})"
    if evidence.source in CLAIM_LEVEL_SOURCES:
        return "claim-level"
    if evidence.source in INTEGRITY_SOURCES and is_pledge(claim):
        return "claim-level for this pledge (integrity criterion)"
    return "company-level"
