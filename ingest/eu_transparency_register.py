"""EU Transparency Register ingest module for the Prasine Index.

Loads the European Transparency Register export from
data/EU_Transparency register_searchExport.xlsx, downloaded via
scripts/refresh_eu_transparency_register.py.

The EU Transparency Register records all organisations that engage with
EU institutions (Commission, Parliament, Council) on policy matters.
Registration is mandatory for organisations that meet certain lobbying
thresholds. As of 2026, the register contains ~17,000 entries.

In an assessment, TR registration is context:
  - A registration shows that a company engages EU institutions.
  - Registration alone does not indicate the direction of lobbying; that comes
    from LobbyMap.
  - Suspended registrations are noted but carry less weight.

Data source: EU Transparency Register public export
  https://ec.europa.eu/transparencyregister/public/consultation/search.do
Refresh: python scripts/refresh_eu_transparency_register.py
"""

from __future__ import annotations

import os
from pathlib import Path

from core.logger import get_logger
from ingest.name_matching import contains_name, fold_name
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = [
    "fetch_eu_transparency_register_data",
    "lookup_registration",
    "refresh_cache",
    "register_export_available",
]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_TR_XLSX: Path = Path(
    os.environ.get(
        "EU_TR_XLSX",
        str(_PROJECT_ROOT / "data" / "EU_Transparency register_searchExport.xlsx"),
    )
)

# Category strings considered direct corporate lobbying (highest signal weight)
_DIRECT_LOBBYING_CATEGORIES = frozenset(
    {
        "Companies & groups",
        "Professional consultancies",
        "Law firms",
        "Self-employed individuals",
    }
)

# Category strings considered indirect / industry lobbying
_INDUSTRY_LOBBYING_CATEGORIES = frozenset(
    {
        "Trade and business associations",
        "Trade unions and professional associations",
    }
)


class _TRRecord:
    """Internal representation of one Transparency Register entry."""

    __slots__ = ("category", "country", "name", "reg_number", "status")

    def __init__(
        self,
        reg_number: str,
        name: str,
        status: str,
        category: str,
        country: str,
    ) -> None:
        self.reg_number = reg_number
        self.name = name
        self.status = status
        self.category = category
        self.country = country

    @property
    def is_active(self) -> bool:
        return self.status.strip().lower() == "activated"

    @property
    def is_direct_lobbyist(self) -> bool:
        return self.category in _DIRECT_LOBBYING_CATEGORIES


# Module-level cache
_cache_by_name: dict[str, _TRRecord] | None = None


def refresh_cache() -> None:
    """Reset the TR cache so the next call reloads from disk."""
    global _cache_by_name
    _cache_by_name = None
    logger.info("EU TR cache cleared.", extra={"operation": "eu_tr_cache_reset"})


def _normalise_name(name: str) -> str:
    name = fold_name(name)
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
        " companies",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> dict[str, _TRRecord]:
    global _cache_by_name

    if _cache_by_name is not None:
        return _cache_by_name

    if not _TR_XLSX.exists():
        _cache_by_name = {}
        logger.info(
            "EU TR XLSX not found: run scripts/refresh_eu_transparency_register.py. "
            f"Expected at: {_TR_XLSX}",
            extra={"operation": "eu_tr_cache_missing"},
        )
        return _cache_by_name

    try:
        import openpyxl
    except ImportError:
        _cache_by_name = {}
        logger.warning(
            "openpyxl not installed: cannot load EU TR XLSX. Run: pip install openpyxl",
            extra={"operation": "eu_tr_cache_no_openpyxl"},
        )
        return _cache_by_name

    by_name: dict[str, _TRRecord] = {}

    wb = openpyxl.load_workbook(_TR_XLSX, read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    next(rows)  # skip header

    for row in rows:
        if not row or len(row) < 6:
            continue
        reg_number = str(row[0] or "").strip()
        name = str(row[1] or "").strip()
        status = str(row[2] or "").strip()
        category = str(row[3] or "").strip()
        country = str(row[5] or "").strip()

        if not name:
            continue

        record = _TRRecord(
            reg_number=reg_number,
            name=name,
            status=status,
            category=category,
            country=country,
        )
        by_name[_normalise_name(name)] = record

    wb.close()
    _cache_by_name = by_name

    logger.info(
        f"EU TR cache loaded: {len(by_name)} organisations",
        extra={"operation": "eu_tr_cache_loaded"},
    )
    return _cache_by_name


def _lookup(company_name: str) -> _TRRecord | None:
    cache = _get_cache()
    norm = _normalise_name(company_name)

    if norm in cache:
        return cache[norm]

    # Whole-word fallback
    if len(norm) >= 4 or "&" in norm:
        for key, record in cache.items():
            if contains_name(key, norm):
                return record

    return None


def register_export_available() -> bool:
    """Return True if the local Transparency Register export is loaded and non-empty.

    Used by callers to distinguish "company not found in the register export"
    (a genuine negative lookup) from "the export file is missing" (a data gap
    that must never be reported as non-registration).
    """
    return bool(_get_cache())


def lookup_registration(company_name: str) -> dict[str, str] | None:
    """Look up a company in the local Transparency Register export by name.

    Public wrapper around the internal cache lookup, used by the Lobbying
    Agent. Matching normalises legal suffixes and falls back to substring
    containment, so a miss is not proof of non-registration.

    Args:
        company_name: Company name to look up.

    Returns:
        A dict with keys ``reg_number``, ``name``, ``status``, ``category``,
        ``country``, or None if no match was found.
    """
    record = _lookup(company_name)
    if record is None:
        return None
    return {
        "reg_number": record.reg_number,
        "name": record.name,
        "status": record.status,
        "category": record.category,
        "country": record.country,
    }


async def fetch_eu_transparency_register_data(claim: Claim, company: object) -> list[Evidence]:
    """Return EU Transparency Register evidence for a company.

    Checks whether the company is registered as an EU lobbyist. Registration
    is contextual evidence; the Judge Agent weighs it alongside LobbyMap
    data to assess whether the company is lobbying against the climate policies
    it publicly claims to support.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if not on the register.
    """
    name: str = getattr(company, "name", "")

    record = _lookup(name)

    if record is None:
        logger.info(
            f"EU TR: {name!r} not on Transparency Register",
            extra={"operation": "eu_tr_not_found", "company": name},
        )
        return []

    summary = _build_summary(name, record)

    logger.info(
        f"EU TR: {name!r} found, category={record.category!r}, "
        f"active={record.is_active}, country={record.country}",
        extra={"operation": "eu_tr_found", "company": name},
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EU_TRANSPARENCY_REGISTER,
            evidence_type=EvidenceType.LOBBYING_RECORD,
            source_url=(
                "https://transparency-register.europa.eu/search-register-or-update/"
                f"organisation-detail_en?id={record.reg_number}"
            ),
            raw_data={
                "reg_number": record.reg_number,
                "name": record.name,
                "status": record.status,
                "category": record.category,
                "country": record.country,
            },
            summary=summary,
            data_year=None,
            # Contextual: direction of lobbying unknown from registration alone
            supports_claim=None,
            confidence=0.75,
        )
    ]


def _build_summary(company_name: str, record: _TRRecord) -> str:
    status_str = "active" if record.is_active else "suspended"
    # The register's own category name, as in "Companies & groups".
    direct_str = f"registered in the category {record.category}"

    matched = f" (matched to {company_name})" if record.name != company_name else ""
    return (
        f"EU Transparency Register: {record.name}{matched} "
        f"{'is registered' if status_str == 'active' else 'has a suspended registration'} "
        f"({direct_str}, head office in {record.country.title()}, registration number "
        f"{record.reg_number}). Registration shows that the organisation engages EU "
        f"institutions on policy; it does not show the direction of that engagement."
    )
