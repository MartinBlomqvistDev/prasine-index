"""Banking on Climate Chaos — fossil fuel financing database ingest module.

Loads the Banking on Climate Chaos annual report data from
data/fossil_finance_banks.csv, downloaded via scripts/refresh_fossil_finance.py.

Banking on Climate Chaos is an annual report by a coalition of NGOs (RAN,
Sierra Club, BankTrack, Indigenous Environmental Network, Oil Change International,
Rainforest Action Network) tracking fossil fuel financing by the world's 60 largest
private-sector banks from 2016 onwards.

A bank that claims climate leadership or net-zero commitments while financing
hundreds of billions in fossil fuel expansion is a textbook financial sector
greenwashing case. HSBC (ASA banned 2022), BNP Paribas, Barclays, Deutsche Bank,
and others have made green claims while ranking among the largest fossil fuel
financiers in the world.

This source is specifically relevant for financial sector companies (banks, asset
managers, insurers) making net-zero or climate-finance claims.

Data source: bankingonclimatechaos.org
Refresh: python scripts/refresh_fossil_finance.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_fossil_finance_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_CSV: Path = Path(
    os.environ.get(
        "FOSSIL_FINANCE_CSV",
        str(_PROJECT_ROOT / "data" / "fossil_finance_banks.csv"),
    )
)

# ---------------------------------------------------------------------------
# Column variants across Banking on Climate Chaos CSV vintages
# ---------------------------------------------------------------------------

_COL_BANK = ("Bank", "bank", "Institution", "Financial Institution", "Company")
_COL_COUNTRY = ("Country", "country", "HQ Country", "Headquarters")
_COL_TOTAL = (
    "Total Fossil Fuel Financing (USD Billion)",
    "Total 2016-2023 (USD Billion)",
    "Total Financing ($bn)",
    "Total ($bn)",
    "total_bn",
    "Grand Total",
)
_COL_COAL = ("Coal Financing ($bn)", "Coal ($bn)", "coal_bn", "Coal Total")
_COL_OIL_GAS = (
    "Oil and Gas Financing ($bn)",
    "Oil & Gas ($bn)",
    "oil_gas_bn",
    "Oil+Gas Total",
    "Fossil Fuel Expansion ($bn)",
)
_COL_NZ_PLEDGE = (
    "Net Zero Commitment",
    "net_zero_commitment",
    "Net Zero Pledge",
    "Signed NZBA",
    "NZBA Member",
)
_COL_YEAR_RANGE = ("Period", "year_range", "Years Covered", "Data Years")


class _FossilFinanceRecord:
    """Internal representation of one bank's fossil fuel financing record."""

    __slots__ = ("bank", "country", "total_bn", "coal_bn", "oil_gas_bn",
                 "nz_pledge", "year_range")

    def __init__(
        self,
        bank: str,
        country: str,
        total_bn: float | None,
        coal_bn: float | None,
        oil_gas_bn: float | None,
        nz_pledge: str,
        year_range: str,
    ) -> None:
        self.bank = bank
        self.country = country
        self.total_bn = total_bn
        self.coal_bn = coal_bn
        self.oil_gas_bn = oil_gas_bn
        self.nz_pledge = nz_pledge
        self.year_range = year_range

    @property
    def has_nz_pledge(self) -> bool:
        return self.nz_pledge.lower().strip() in ("yes", "true", "1", "signed", "member")


# Module-level cache
_cache_by_name: dict[str, _FossilFinanceRecord] | None = None


def refresh_cache() -> None:
    """Reset the fossil finance cache so the next call reloads from disk."""
    global _cache_by_name
    _cache_by_name = None
    logger.info("Fossil finance cache cleared.", extra={"operation": "fossil_finance_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _parse_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace("$", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


def _normalise_name(name: str) -> str:
    name = name.lower().strip()
    for suffix in (" plc", " ag", " se", " sa", " s.a.", " spa", " nv", " bv",
                   " gmbh", " inc", " corp", " ltd", " limited", " group",
                   " bank", " financial group", " holdings", " holding"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> dict[str, _FossilFinanceRecord]:
    global _cache_by_name

    if _cache_by_name is not None:
        return _cache_by_name

    if not _CSV.exists():
        _cache_by_name = {}
        logger.info(
            "Fossil finance data file not found — run scripts/refresh_fossil_finance.py. "
            f"Expected at: {_CSV}",
            extra={"operation": "fossil_finance_cache_missing"},
        )
        return _cache_by_name

    by_name: dict[str, _FossilFinanceRecord] = {}

    with _CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            bank = _pick(row, _COL_BANK)
            if not bank:
                continue
            record = _FossilFinanceRecord(
                bank=bank,
                country=_pick(row, _COL_COUNTRY),
                total_bn=_parse_float(_pick(row, _COL_TOTAL)),
                coal_bn=_parse_float(_pick(row, _COL_COAL)),
                oil_gas_bn=_parse_float(_pick(row, _COL_OIL_GAS)),
                nz_pledge=_pick(row, _COL_NZ_PLEDGE),
                year_range=_pick(row, _COL_YEAR_RANGE) or "2016–present",
            )
            by_name[_normalise_name(bank)] = record

    _cache_by_name = by_name
    logger.info(
        f"Fossil finance cache loaded: {len(by_name)} banks",
        extra={"operation": "fossil_finance_cache_loaded"},
    )
    return _cache_by_name


def _lookup(name: str) -> _FossilFinanceRecord | None:
    cache = _get_cache()
    norm = _normalise_name(name)
    if norm in cache:
        return cache[norm]
    for key, record in cache.items():
        if norm in key or key in norm:
            return record
    return None


async def fetch_fossil_finance_data(claim: Claim, company: object) -> list[Evidence]:
    """Return fossil fuel financing evidence for a financial institution.

    Looks up the company in the Banking on Climate Chaos database. Banks and
    financial institutions making net-zero or climate-positive claims while
    financing hundreds of billions in fossil fuel expansion are engaging in the
    most direct form of financial sector greenwashing.

    Only returns evidence for companies found in the database — typically banks,
    asset managers, and insurance companies. Manufacturing and energy companies
    will not be found here (those are covered by EU ETS, E-PRTR, etc.).

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if not a tracked institution.
    """
    name: str = getattr(company, "name", "")
    record = _lookup(name)

    if record is None:
        logger.info(
            f"Fossil finance: {name!r} not in database",
            extra={"operation": "fossil_finance_not_found", "company": name},
        )
        return []

    supports, confidence = _assess_record(record)
    summary = _build_summary(name, record)

    logger.info(
        f"Fossil finance: {name!r} — total={record.total_bn}bn, "
        f"nz_pledge={record.has_nz_pledge}",
        extra={
            "operation": "fossil_finance_found",
            "company": name,
            "total_bn": record.total_bn,
            "has_nz_pledge": record.has_nz_pledge,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.FOSSIL_FINANCE,
            evidence_type=EvidenceType.FINANCING_RECORD,
            source_url="https://www.bankingonclimatechaos.org/",
            raw_data={
                "bank": record.bank,
                "country": record.country,
                "total_fossil_bn": record.total_bn,
                "coal_bn": record.coal_bn,
                "oil_gas_bn": record.oil_gas_bn,
                "net_zero_pledge": record.nz_pledge,
                "period": record.year_range,
            },
            summary=summary,
            data_year=None,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


# Thresholds (USD billion) for classifying financing magnitude
_HIGH_FINANCING_THRESHOLD = 100.0   # >$100bn total = very high
_MODERATE_FINANCING_THRESHOLD = 30.0  # >$30bn total = moderate


def _assess_record(record: _FossilFinanceRecord) -> tuple[bool | None, float]:
    """Assess whether fossil financing contradicts green claims."""
    total = record.total_bn

    if total is None:
        # In database but no financing figure — existence alone is notable
        return None, 0.45

    if total >= _HIGH_FINANCING_THRESHOLD:
        if record.has_nz_pledge:
            # High financing + net-zero pledge = hypocrisy signal
            return False, 0.88
        return False, 0.80

    if total >= _MODERATE_FINANCING_THRESHOLD:
        if record.has_nz_pledge:
            return False, 0.75
        return False, 0.65

    # Lower-end financing — still notable but less directly contradicting
    return None, 0.50


def _build_summary(company_name: str, record: _FossilFinanceRecord) -> str:
    total_str = f"${record.total_bn:.1f}bn" if record.total_bn else "amount not disclosed"
    coal_str = f"${record.coal_bn:.1f}bn coal" if record.coal_bn else ""
    og_str = f"${record.oil_gas_bn:.1f}bn oil & gas" if record.oil_gas_bn else ""
    breakdown = ", ".join(x for x in [coal_str, og_str] if x)
    nz_str = (
        "Despite having a net-zero pledge, this bank"
        if record.has_nz_pledge
        else "This bank"
    )

    return (
        f"Banking on Climate Chaos: {company_name} provided {total_str} in fossil fuel "
        f"financing ({record.year_range}){(' — ' + breakdown) if breakdown else ''}. "
        f"{nz_str} ranks among the world's largest financiers of fossil fuel "
        f"expansion. Any green banking or climate-leadership claim is directly "
        f"contradicted by this financing record."
    )
