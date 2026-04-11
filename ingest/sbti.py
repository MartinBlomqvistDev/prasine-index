"""SBTi (Science Based Targets initiative) ingest module for the Prasine Index.

Loads the SBTi Companies Taking Action dataset from a local Excel or CSV file
downloaded via scripts/refresh_sbti.py. Provides target validation evidence for
any claim containing science-based target language.

SBTi data is a high-quality signal: targets are externally validated by SBTi,
and withdrawn/removed status is a direct CONFIRMED_GREENWASHING indicator —
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

__all__ = ["fetch_sbti_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_SBTI_CSV: Path = Path(
    os.environ.get(
        "SBTI_CSV",
        str(_PROJECT_ROOT / "data" / "sbti_companies.csv"),
    )
)

# SBTi Excel download (alternative to CSV — parsed at cache load time)
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
    "Status",
    "Near-term target status",
    "Near-term Targets Status",
    "Target Status",
    "Commitment Status",
)
_COL_TEMP = (
    "Near-term Targets Classification",
    "Near-term target classification",
    "Target Classification",
    "Temperature Classification",
    "Classification",
)
_COL_NET_ZERO = (
    "Net-Zero Target in SBTi",
    "Net-zero target status",
    "Long-term target status",
    "Net Zero Status",
)
_COL_SECTOR = ("Sector", "sector", "Industry")
_COL_DATE = ("Date", "Commitment Date", "date_committed", "Target Set Date")

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

# Status values that indicate an active, validated target.
_ACTIVE_STATUSES = frozenset(
    {
        "targets set",
        "committed",
        "achieved",
        "net zero",
        "science-based target set",
    }
)


class _SBTiRecord:
    """Internal representation of one SBTi company record."""

    __slots__ = (
        "date",
        "isin",
        "name",
        "net_zero_status",
        "sector",
        "status",
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
    ) -> None:
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
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


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
            "openpyxl not installed — cannot read SBTi XLSX. "
            "Run: pip install openpyxl, or use the CSV download.",
            extra={"operation": "sbti_xlsx_missing_dep"},
        )
        return {}, {}

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    # SBTi workbook has one main data sheet — use the first sheet.
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
            "SBTi data file not found — run scripts/refresh_sbti.py to download. "
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
        f"SBTi: {name!r} found — status={record.status!r}, "
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
                "sector": record.sector,
                "date": record.date,
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
        # Company had a target but it was removed — directly contradicts SBTi claims.
        if is_sbti_claim:
            return False, 0.95
        # Even if not an SBTi claim, removed status is relevant negative context.
        return False, 0.75

    if record.is_active:
        if is_sbti_claim:
            return True, 0.90
        # Active target supports general emissions reduction claims.
        return True, 0.70

    # Status is something like "Committed" (no validated target yet) — neutral.
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
    date_display = f", committed {record.date}" if record.date else ""

    if record.is_removed:
        return (
            f"SBTi target for {company_name}: STATUS = {status_display.upper()}. "
            f"The company previously had an SBTi-registered target but it has been "
            f"removed or is no longer valid{date_display}. "
            f"Any current claim referencing SBTi-validated targets is unsubstantiated."
        )

    return (
        f"SBTi target for {company_name}: status={status_display}, "
        f"temperature classification={temp_display}, "
        f"net-zero target={net_zero_display}{date_display}. "
        f"{'Claim references SBTi — target is ' + ('active and validated' if record.is_active else 'committed but not yet validated') + '.' if is_sbti_claim else 'SBTi record provides context for emissions reduction claims.'}"
    )
