"""SBTi (Science Based Targets initiative) ingest module for the Prasine Index.

Loads the SBTi Companies Taking Action dataset from a local Excel or CSV file
downloaded via scripts/refresh_sbti.py. Provides target validation evidence for
any claim containing science-based target language.

SBTi data is a high-quality signal: targets are externally validated by SBTi,
and withdrawn/removed status is a direct CONFIRMED_GREENWASHING indicator:
the company no longer has a valid commitment despite continuing to claim one.

Data source: sciencebasedtargets.org/companies-taking-action
Refresh: python scripts/refresh_sbti.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["describe_targets", "fetch_sbti_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_SBTI_CSV: Path = Path(
    os.environ.get(
        "SBTI_CSV",
        str(_PROJECT_ROOT / "data" / "sbti_companies.csv"),
    )
)

# SBTi Excel download (alternative to CSV: parsed at cache load time)
_SBTI_XLSX: Path = Path(
    os.environ.get(
        "SBTI_XLSX",
        str(_PROJECT_ROOT / "data" / "sbti_companies.xlsx"),
    )
)

# Column name variants across different SBTi download vintages.
# SBTi has changed their column headers several times.
_COL_COMPANY = ("Company Name", "Organization", "company_name", "Name")
_COL_ISIN = ("ISIN", "isin", "ISIN Code")
_COL_STATUS = (
    "near_term_status",
    "Status",
    "Near-term target status",
    "Near-term Targets Status",
    "Target Status",
    "Commitment Status",
)
_COL_TEMP = (
    "near_term_target_classification",
    "Near-term Targets Classification",
    "Near-term target classification",
    "Target Classification",
    "Temperature Classification",
    "Classification",
)
_COL_NET_ZERO = (
    "net_zero_status",
    "long_term_status",
    "Net-Zero Target in SBTi",
    "Net-zero target status",
    "Long-term target status",
    "Net Zero Status",
)
_COL_SECTOR = ("Sector", "sector", "Industry")
_COL_DATE = ("date_updated", "Date", "Commitment Date", "date_committed", "Target Set Date")
_COL_NET_ZERO_YEAR = ("net_zero_year", "Net-Zero Year")
_COL_TARGET_TEXT = ("full_target_language", "Target Language", "Target Wording")

# The register's own wording of the targets is quoted whole up to this many characters;
# a longer text is cut at a sentence and marked as shortened.
_TARGET_TEXT_LIMIT = 4000

# Register fields stated beside the status, by the name the record gives them.
_DETAIL_COLUMNS = {
    "near_term_year": ("near_term_target_year",),
    "classification_text": ("target_classification_long",),
    "long_term_status": ("long_term_status",),
    "long_term_classification": ("long_term_target_classification",),
    "long_term_year": ("long_term_target_year",),
    "ba15_status": ("ba15_status",),
    "ba15_date": ("ba15_date",),
}

# Status values that indicate a withdrawn/removed target.
_REMOVED_STATUSES = frozenset(
    {
        "removed",
        "no longer valid",
        "expired",
        "commitment removed",
        "targets removed",
        "withdrawn",
    }
)

# Status values that indicate a validated target. "Committed" is a commitment to
# set a target, not a validated one.
_ACTIVE_STATUSES = frozenset(
    {
        "validated targets",
        "validated",
        "targets set",
        "target set",
        "achieved",
        "science-based target set",
    }
)
_COMMITTED_STATUSES = frozenset({"committed", "commitment"})


class _SBTiRecord:
    """Internal representation of one SBTi company record."""

    __slots__ = (
        "date",
        "details",
        "isin",
        "name",
        "net_zero_status",
        "net_zero_year",
        "sector",
        "status",
        "target_text",
        "temp_classification",
    )

    def __init__(
        self,
        name: str,
        isin: str | None,
        status: str,
        temp_classification: str,
        net_zero_status: str,
        sector: str,
        date: str,
        net_zero_year: str = "",
        target_text: str = "",
        details: dict[str, str] | None = None,
    ) -> None:
        self.net_zero_year = net_zero_year
        self.target_text = target_text
        self.details = details or {}
        self.name = name
        self.isin = isin
        self.status = status
        self.temp_classification = temp_classification
        self.net_zero_status = net_zero_status
        self.sector = sector
        self.date = date

    @property
    def is_removed(self) -> bool:
        return self.status.lower().strip() in _REMOVED_STATUSES

    @property
    def is_active(self) -> bool:
        return self.status.lower().strip() in _ACTIVE_STATUSES

    @property
    def is_committed(self) -> bool:
        return self.status.lower().strip() in _COMMITTED_STATUSES


# Module-level cache: {isin: _SBTiRecord} and {normalised_name: _SBTiRecord}
_cache_by_isin: dict[str, _SBTiRecord] | None = None
_cache_by_name: dict[str, _SBTiRecord] | None = None


def refresh_cache() -> None:
    """Reset the SBTi cache so the next call reloads from disk.

    Call this after running scripts/refresh_sbti.py.
    """
    global _cache_by_isin, _cache_by_name
    _cache_by_isin = None
    _cache_by_name = None
    logger.info("SBTi cache cleared.", extra={"operation": "sbti_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    """Return the value of the first matching column name, or empty string."""
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _normalise_name(name: str) -> str:
    """Lowercase and strip legal suffixes for fuzzy company name matching."""
    name = name.lower().strip().rstrip(".,;:")
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


def _details(row: dict[str, str]) -> dict[str, str]:
    """Return the register fields stated beside the status, without empty ones."""
    found = {key: _pick(row, columns) for key, columns in _DETAIL_COLUMNS.items()}
    return {key: value for key, value in found.items() if value and value.lower() != "none"}


def _year(value: str) -> str:
    """Write a register year as the register means it: "2030.0" as "2030", "FY2030" as is."""
    return value[:-2] if value.endswith(".0") else value


def _load_from_csv(path: Path) -> tuple[dict[str, _SBTiRecord], dict[str, _SBTiRecord]]:
    """Parse the SBTi CSV into lookup caches."""
    by_isin: dict[str, _SBTiRecord] = {}
    by_name: dict[str, _SBTiRecord] = {}

    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = _pick(row, _COL_COMPANY)
            if not name:
                continue
            record = _SBTiRecord(
                name=name,
                isin=_pick(row, _COL_ISIN) or None,
                status=_pick(row, _COL_STATUS),
                temp_classification=_pick(row, _COL_TEMP),
                net_zero_status=_pick(row, _COL_NET_ZERO),
                sector=_pick(row, _COL_SECTOR),
                date=_pick(row, _COL_DATE),
                net_zero_year=_pick(row, _COL_NET_ZERO_YEAR),
                target_text=_pick(row, _COL_TARGET_TEXT),
                details=_details(row),
            )
            if record.isin:
                by_isin[record.isin.upper()] = record
            by_name[_normalise_name(name)] = record

    return by_isin, by_name


def _load_from_xlsx(path: Path) -> tuple[dict[str, _SBTiRecord], dict[str, _SBTiRecord]]:
    """Parse the SBTi Excel file. Converts to CSV rows via openpyxl."""
    try:
        import openpyxl
    except ImportError:
        logger.warning(
            "openpyxl not installed: cannot read SBTi XLSX. "
            "Run: pip install openpyxl, or use the CSV download.",
            extra={"operation": "sbti_xlsx_missing_dep"},
        )
        return {}, {}

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    # SBTi workbook has one main data sheet: use the first sheet.
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}, {}

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    by_isin: dict[str, _SBTiRecord] = {}
    by_name: dict[str, _SBTiRecord] = {}

    for row_vals in rows[1:]:
        if not any(row_vals):
            continue
        row = {
            headers[i]: (str(v).strip() if v is not None else "") for i, v in enumerate(row_vals)
        }
        name = _pick(row, _COL_COMPANY)
        if not name:
            continue
        record = _SBTiRecord(
            name=name,
            isin=_pick(row, _COL_ISIN) or None,
            status=_pick(row, _COL_STATUS),
            temp_classification=_pick(row, _COL_TEMP),
            net_zero_status=_pick(row, _COL_NET_ZERO),
            sector=_pick(row, _COL_SECTOR),
            date=_pick(row, _COL_DATE),
            net_zero_year=_pick(row, _COL_NET_ZERO_YEAR),
            target_text=_pick(row, _COL_TARGET_TEXT),
            details=_details(row),
        )
        if record.isin:
            by_isin[record.isin.upper()] = record
        by_name[_normalise_name(name)] = record

    wb.close()
    return by_isin, by_name


def _get_cache() -> tuple[dict[str, _SBTiRecord], dict[str, _SBTiRecord]]:
    """Return module-level caches, loading from disk on first call."""
    global _cache_by_isin, _cache_by_name

    if _cache_by_isin is not None:
        return _cache_by_isin, _cache_by_name  # type: ignore[return-value]

    if _SBTI_CSV.exists():
        _cache_by_isin, _cache_by_name = _load_from_csv(_SBTI_CSV)
        logger.info(
            f"SBTi cache loaded from CSV: {len(_cache_by_isin)} by ISIN, "
            f"{len(_cache_by_name)} by name",
            extra={"operation": "sbti_cache_loaded", "source": "csv"},
        )
    elif _SBTI_XLSX.exists():
        _cache_by_isin, _cache_by_name = _load_from_xlsx(_SBTI_XLSX)
        logger.info(
            f"SBTi cache loaded from XLSX: {len(_cache_by_isin)} by ISIN, "
            f"{len(_cache_by_name)} by name",
            extra={"operation": "sbti_cache_loaded", "source": "xlsx"},
        )
    else:
        _cache_by_isin, _cache_by_name = {}, {}
        logger.info(
            "SBTi data file not found: run scripts/refresh_sbti.py to download. "
            f"Expected at: {_SBTI_CSV}",
            extra={"operation": "sbti_cache_missing"},
        )

    return _cache_by_isin, _cache_by_name


def _lookup(isin: str | None, name: str) -> _SBTiRecord | None:
    """Look up a company by ISIN (preferred) or normalised name."""
    by_isin, by_name = _get_cache()
    if isin and isin.upper() in by_isin:
        return by_isin[isin.upper()]
    normalised = _normalise_name(name)
    return by_name.get(normalised)


async def fetch_sbti_data(claim: Claim, company: object) -> list[Evidence]:
    """Return SBTi target validation evidence for a company.

    Looks up the company by ISIN then normalised name. Returns Evidence
    assessing whether the company has a current, validated SBTi target,
    an expired/removed one, or no record at all.

    A removed target while the company continues to claim science-based
    targets is a direct CONFIRMED_GREENWASHING indicator.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with an Evidence record, or empty list if
        the claim contains no science-based target language and no SBTi
        record exists.
    """
    claim_lower = claim.raw_text.lower()
    sbti_keywords = ("science-based", "sbti", "science based target", "1.5°c", "1.5c aligned")
    is_sbti_claim = any(kw in claim_lower for kw in sbti_keywords)

    isin: str | None = getattr(company, "isin", None)
    name: str = getattr(company, "name", "")

    record = _lookup(isin, name)

    if record is None:
        if not is_sbti_claim:
            return []
        # Claim references SBTi but company has no SBTi record.
        summary = (
            f"{name} is not listed in the SBTi Companies Taking Action database. "
            "The company has no validated, committed, or removed SBTi target on record. "
            "A claim referencing science-based targets without SBTi registration "
            "cannot be independently verified."
        )
        logger.info(
            f"SBTi: {name!r} not found in database",
            extra={"operation": "sbti_not_found", "company": name},
        )
        return [
            Evidence(
                claim_id=claim.id,
                trace_id=claim.trace_id,
                source=EvidenceSource.SBTI,
                evidence_type=EvidenceType.TARGET_RECORD,
                source_url="https://sciencebasedtargets.org/companies-taking-action",
                raw_data={"found": False, "company": name},
                summary=summary,
                data_year=None,
                supports_claim=False,
                confidence=0.8,
            )
        ]

    supports, confidence = _assess_record(record, is_sbti_claim)
    summary = _build_summary(name, record, is_sbti_claim)

    logger.info(
        f"SBTi: {name!r} found, status={record.status!r}, "
        f"temp={record.temp_classification!r}, removed={record.is_removed}",
        extra={"operation": "sbti_found", "company": name, "status": record.status},
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.SBTI,
            evidence_type=EvidenceType.TARGET_RECORD,
            source_url="https://sciencebasedtargets.org/companies-taking-action",
            raw_data={
                "company": record.name,
                "isin": record.isin,
                "status": record.status,
                "temp_classification": record.temp_classification,
                "net_zero_status": record.net_zero_status,
                "net_zero_year": _year(record.net_zero_year),
                "sector": record.sector,
                "date": record.date,
                **record.details,
            },
            summary=summary,
            data_year=None,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _SBTiRecord, is_sbti_claim: bool) -> tuple[bool | None, float]:
    """Determine whether the SBTi record supports or contradicts the claim.

    Args:
        record: The SBTi record for the company.
        is_sbti_claim: Whether the claim text explicitly references SBTi.

    Returns:
        Tuple of (supports_claim, confidence).
    """
    if record.is_removed:
        # Company had a target but it was removed: directly contradicts SBTi claims.
        if is_sbti_claim:
            return False, 0.95
        # Even if not an SBTi claim, removed status is relevant negative context.
        return False, 0.75

    if record.is_active:
        if is_sbti_claim:
            return True, 0.90
        # Active target supports general emissions reduction claims.
        return True, 0.70

    # Status is something like "Committed" (no validated target yet), neutral.
    if is_sbti_claim:
        return None, 0.65

    return None, 0.5


def _build_summary(company_name: str, record: _SBTiRecord, is_sbti_claim: bool) -> str:
    """Build a human-readable summary for the Judge Agent.

    Args:
        company_name: Display name of the company.
        record: The SBTi record.
        is_sbti_claim: Whether the claim text explicitly references SBTi.

    Returns:
        A plain-text summary string.
    """
    status_display = record.status or "unknown"
    temp_display = record.temp_classification or "not classified"
    net_zero_display = record.net_zero_status or "none"
    year = _year(record.net_zero_year)
    net_zero_display += f" (net-zero year {year})" if year else ""
    date_display = f"; register entry updated {record.date[:10]}" if record.date else ""
    # The register's own name for the entity, which can differ from the company's.
    entry = f"SBTi register entry {record.name!r}" + (
        f" (matched to {company_name})" if record.name != company_name else ""
    )
    details = record.details

    if record.is_removed:
        return (
            f"{entry}: status {status_display}. "
            f"The SBTi register records an earlier target as removed or no longer "
            f"valid{date_display}."
        )

    if record.is_active:
        standing = "The register lists the targets as validated."
    elif record.is_committed:
        standing = "The register lists a commitment to set targets, not validated targets."
    else:
        standing = f"The register lists the status as {status_display}."

    near = f"near-term targets {status_display}"
    if details.get("near_term_year"):
        near += f" for {_year(details['near_term_year'])}"
    near += f", temperature classification {temp_display}"
    parts = [near]
    if details.get("classification_text"):
        parts.append(f'the register\'s classification reads "{details["classification_text"]}"')
    if details.get("long_term_status"):
        long_term = f"long-term targets {details['long_term_status']}"
        if details.get("long_term_year"):
            long_term += f" for {_year(details['long_term_year'])}"
        if details.get("long_term_classification"):
            long_term += f", classification {details['long_term_classification']}"
        parts.append(long_term)
    parts.append(f"net-zero target {net_zero_display}")
    if details.get("ba15_status"):
        since = f" since {details['ba15_date'][:10]}" if details.get("ba15_date") else ""
        parts.append(f"Business Ambition for 1.5°C: {details['ba15_status']}{since}")
    summary = f"{entry}: {'; '.join(parts)}{date_display}. {standing}"
    text = " ".join(record.target_text.split())
    if text:
        shortened = len(text) > _TARGET_TEXT_LIMIT
        if shortened:
            cut = text[:_TARGET_TEXT_LIMIT]
            text = (cut[: cut.rfind(". ") + 1] if ". " in cut else cut) + " ..."
        label = "Target wording in the register" + (", shortened" if shortened else "")
        summary += f' {label}: "{text}"'
    return summary


def describe_targets(raw_data: dict[str, object]) -> str:
    """State an SBTi record for the company record: statuses, classification and years.

    Args:
        raw_data: The raw_data of an SBTi Evidence record.

    Returns:
        For example 'SBTi (Enel SpA): near-term targets Validated Targets for 2030,
        classification 1.5°C ("The targets covering ... (scopes 1 and 2) ..."); ...'
    """

    def field(key: str) -> str:
        return str(raw_data.get(key) or "")

    near = f"near-term targets {field('status') or 'unknown'}"
    if field("near_term_year"):
        near += f" for {_year(field('near_term_year'))}"
    near += f", classification {field('temp_classification') or 'none'}"
    if field("classification_text"):
        near += f' ("{field("classification_text")}")'
    parts = [near]
    if field("long_term_status"):
        long_term = f"long-term targets {field('long_term_status')}"
        if field("long_term_year"):
            long_term += f" for {_year(field('long_term_year'))}"
        parts.append(long_term)
    net_zero = f"net-zero target {field('net_zero_status') or 'none'}"
    if field("net_zero_year"):
        net_zero += f" for {field('net_zero_year')}"
    parts.append(net_zero)
    return f"SBTi ({field('company')}): {'; '.join(parts)}."
