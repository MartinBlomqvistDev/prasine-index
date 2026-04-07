"""Global Coal Exit List (GCEL) ingest module for the Prasine Index.

Loads the Urgewald Global Coal Exit List from data/gcel_companies.csv, downloaded
via scripts/refresh_gcel.py. The GCEL tracks approximately 1,000 companies that
develop, mine, or burn coal — covering the full coal value chain.

A company on the GCEL with an "expanding" classification while claiming a clean
energy transition or climate leadership is a primary greenwashing signal: the
company is simultaneously claiming to leave coal while actively expanding its
coal capacity. This pattern is documented for Glencore, TotalEnergies, Uniper,
RWE, and others.

GCEL data is used by institutional investors under the GFANZ Net Zero Investment
Framework and the Paris Aligned Investment Initiative to screen coal exposure.
A company claiming alignment with 1.5°C while actively listed as a coal expander
contradicts the most widely used coal screen in ESG investing.

Data source: Urgewald (urgewald.org) — published annually at COP
Refresh: python scripts/refresh_gcel.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_coal_exit_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_GCEL_CSV: Path = Path(
    os.environ.get(
        "GCEL_CSV",
        str(_PROJECT_ROOT / "data" / "gcel_companies.csv"),
    )
)

# ---------------------------------------------------------------------------
# Column variants
# ---------------------------------------------------------------------------

_COL_COMPANY = ("Company", "company", "Company Name", "Name", "Issuer")
_COL_COUNTRY = ("Country", "country", "HQ Country", "Headquarters")
_COL_ISIN = ("ISIN", "isin", "Primary ISIN", "ISIN Code")
_COL_TICKER = ("Ticker", "ticker", "Bloomberg Ticker", "Stock Ticker")
_COL_SECTOR = (
    "Coal Sector",
    "Sector",
    "sector",
    "Coal Value Chain",
    "Business Activity",
)
_COL_MINING_STATUS = (
    "Coal Mining Expansion",
    "Mining Expansion",
    "mining_expansion",
    "Expanding Mining",
    "New Coal Mines",
    "Coal Mine Expansion",
)
_COL_POWER_STATUS = (
    "Coal Power Expansion",
    "Power Expansion",
    "power_expansion",
    "New Coal Plants",
    "Coal Power Development",
)
_COL_PHASE_OUT = (
    "Coal Phase-out Plan",
    "Phase Out",
    "phase_out",
    "Phase-out Target",
    "Coal Phase-out Year",
    "Exit Date",
)
_COL_MINING_CAPACITY = (
    "Coal Mining Capacity (Mtpa)",
    "Mining Capacity",
    "mining_capacity_mtpa",
    "Annual Coal Production (Mt)",
)
_COL_POWER_CAPACITY = (
    "Coal Power Capacity (GW)",
    "Power Capacity",
    "power_capacity_gw",
    "Installed Coal Power (GW)",
)

# Values indicating active coal expansion
_EXPANDING_VALUES = frozenset({
    "yes", "expanding", "expansion", "new capacity", "developing", "under construction",
    "planned", "under development", "active development", "increase",
})
# Values indicating phase-out / exit
_PHASEOUT_VALUES = frozenset({
    "no new", "phasing out", "phase-out", "phase out", "no expansion",
    "committed to exit", "coal free", "exiting", "no coal",
})


class _GCELRecord:
    """Internal representation of one GCEL company record."""

    __slots__ = (
        "company", "country", "isin", "ticker", "sector",
        "mining_expansion", "power_expansion", "phase_out_plan",
        "mining_capacity_mtpa", "power_capacity_gw",
    )

    def __init__(
        self,
        company: str,
        country: str,
        isin: str | None,
        ticker: str | None,
        sector: str,
        mining_expansion: str,
        power_expansion: str,
        phase_out_plan: str,
        mining_capacity_mtpa: float | None,
        power_capacity_gw: float | None,
    ) -> None:
        self.company = company
        self.country = country
        self.isin = isin
        self.ticker = ticker
        self.sector = sector
        self.mining_expansion = mining_expansion
        self.power_expansion = power_expansion
        self.phase_out_plan = phase_out_plan
        self.mining_capacity_mtpa = mining_capacity_mtpa
        self.power_capacity_gw = power_capacity_gw

    @property
    def is_expanding(self) -> bool:
        m = self.mining_expansion.lower().strip()
        p = self.power_expansion.lower().strip()
        return m in _EXPANDING_VALUES or p in _EXPANDING_VALUES

    @property
    def is_phasing_out(self) -> bool:
        po = self.phase_out_plan.lower().strip()
        m = self.mining_expansion.lower().strip()
        p = self.power_expansion.lower().strip()
        return (po in _PHASEOUT_VALUES) or (
            m in _PHASEOUT_VALUES and p in _PHASEOUT_VALUES
        )


# Module-level cache
_cache_by_isin: dict[str, _GCELRecord] | None = None
_cache_by_name: dict[str, _GCELRecord] | None = None
_cache_by_ticker: dict[str, _GCELRecord] | None = None


def refresh_cache() -> None:
    """Reset the GCEL cache so the next call reloads from disk."""
    global _cache_by_isin, _cache_by_name, _cache_by_ticker
    _cache_by_isin = None
    _cache_by_name = None
    _cache_by_ticker = None
    logger.info("GCEL cache cleared.", extra={"operation": "gcel_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _parse_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


def _normalise_name(name: str) -> str:
    name = name.lower().strip()
    for suffix in (" plc", " ag", " se", " sa", " s.a.", " spa", " s.p.a.", " nv",
                   " bv", " gmbh", " inc", " corp", " ltd", " limited", " group",
                   " holding", " holdings", " a/s", " as", " ab",
                   " energy", " power", " resources"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> tuple[
    dict[str, _GCELRecord],
    dict[str, _GCELRecord],
    dict[str, _GCELRecord],
]:
    global _cache_by_isin, _cache_by_name, _cache_by_ticker

    if _cache_by_name is not None:
        return _cache_by_isin, _cache_by_name, _cache_by_ticker  # type: ignore[return-value]

    if not _GCEL_CSV.exists():
        _cache_by_isin = {}
        _cache_by_name = {}
        _cache_by_ticker = {}
        logger.info(
            "GCEL data file not found — run scripts/refresh_gcel.py to download. "
            f"Expected at: {_GCEL_CSV}",
            extra={"operation": "gcel_cache_missing"},
        )
        return _cache_by_isin, _cache_by_name, _cache_by_ticker

    by_isin: dict[str, _GCELRecord] = {}
    by_name: dict[str, _GCELRecord] = {}
    by_ticker: dict[str, _GCELRecord] = {}

    with _GCEL_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            company = _pick(row, _COL_COMPANY)
            if not company:
                continue
            record = _GCELRecord(
                company=company,
                country=_pick(row, _COL_COUNTRY),
                isin=_pick(row, _COL_ISIN) or None,
                ticker=_pick(row, _COL_TICKER) or None,
                sector=_pick(row, _COL_SECTOR),
                mining_expansion=_pick(row, _COL_MINING_STATUS),
                power_expansion=_pick(row, _COL_POWER_STATUS),
                phase_out_plan=_pick(row, _COL_PHASE_OUT),
                mining_capacity_mtpa=_parse_float(_pick(row, _COL_MINING_CAPACITY)),
                power_capacity_gw=_parse_float(_pick(row, _COL_POWER_CAPACITY)),
            )
            norm = _normalise_name(company)
            by_name[norm] = record
            if record.isin:
                by_isin[record.isin.upper()] = record
            if record.ticker:
                by_ticker[record.ticker.upper()] = record

    _cache_by_isin = by_isin
    _cache_by_name = by_name
    _cache_by_ticker = by_ticker

    logger.info(
        f"GCEL cache loaded: {len(by_name)} companies",
        extra={"operation": "gcel_cache_loaded"},
    )
    return _cache_by_isin, _cache_by_name, _cache_by_ticker


def _lookup(name: str, isin: str | None, ticker: str | None) -> _GCELRecord | None:
    by_isin, by_name, by_ticker = _get_cache()
    if isin and isin.upper() in by_isin:
        return by_isin[isin.upper()]
    if ticker and ticker.upper() in by_ticker:
        return by_ticker[ticker.upper()]
    norm = _normalise_name(name)
    if norm in by_name:
        return by_name[norm]
    for key, record in by_name.items():
        if norm in key or key in norm:
            return record
    return None


async def fetch_coal_exit_data(claim: Claim, company: object) -> list[Evidence]:
    """Return Global Coal Exit List evidence for a company.

    A company listed on the GCEL as actively expanding coal capacity while making
    clean-energy transition claims is engaging in documented greenwashing. The GCEL
    is used by 400+ financial institutions under GFANZ and PAII investment frameworks.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the company is not on the GCEL.
    """
    name: str = getattr(company, "name", "")
    isin: str | None = getattr(company, "isin", None)
    ticker: str | None = getattr(company, "ticker", None)

    record = _lookup(name, isin, ticker)

    if record is None:
        logger.info(
            f"GCEL: {name!r} not on Global Coal Exit List",
            extra={"operation": "gcel_not_found", "company": name},
        )
        return []

    supports, confidence = _assess_record(record)
    summary = _build_summary(name, record)

    logger.info(
        f"GCEL: {name!r} found — expanding={record.is_expanding}, "
        f"phasing_out={record.is_phasing_out}",
        extra={
            "operation": "gcel_found",
            "company": name,
            "is_expanding": record.is_expanding,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.COAL_EXIT,
            evidence_type=EvidenceType.TARGET_RECORD,
            source_url="https://www.urgewald.org/en/themen/global-coal-exit-list",
            raw_data={
                "company": record.company,
                "country": record.country,
                "sector": record.sector,
                "mining_expansion": record.mining_expansion,
                "power_expansion": record.power_expansion,
                "phase_out_plan": record.phase_out_plan,
                "mining_capacity_mtpa": record.mining_capacity_mtpa,
                "power_capacity_gw": record.power_capacity_gw,
            },
            summary=summary,
            data_year=None,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _GCELRecord) -> tuple[bool | None, float]:
    """Assess whether GCEL status supports or contradicts green claims."""
    if record.is_expanding:
        return False, 0.90

    if record.is_phasing_out:
        # On GCEL but with a documented phase-out plan — nuanced
        return None, 0.55

    # Listed on GCEL but expansion status unclear — still a negative signal
    return False, 0.65


def _build_summary(company_name: str, record: _GCELRecord) -> str:
    capacity_parts = []
    if record.mining_capacity_mtpa:
        capacity_parts.append(f"{record.mining_capacity_mtpa:.0f} Mtpa coal mining")
    if record.power_capacity_gw:
        capacity_parts.append(f"{record.power_capacity_gw:.1f} GW coal power")
    capacity_str = "; ".join(capacity_parts) or "capacity not disclosed"

    if record.is_expanding:
        return (
            f"Urgewald Global Coal Exit List: {company_name} is listed as ACTIVELY "
            f"EXPANDING coal capacity ({capacity_str}). "
            f"Mining expansion status: {record.mining_expansion or 'unknown'}; "
            f"Power expansion status: {record.power_expansion or 'unknown'}. "
            f"Any claim of clean energy transition or Paris alignment is directly "
            f"contradicted by this documented coal expansion. "
            f"The GCEL is used by 400+ financial institutions (GFANZ, PAII) as the "
            f"standard coal screen — this company fails it."
        )

    if record.is_phasing_out:
        phase_str = record.phase_out_plan or "plan details not disclosed"
        return (
            f"Urgewald Global Coal Exit List: {company_name} is listed on the GCEL "
            f"({capacity_str}) but has a documented coal phase-out plan: {phase_str}. "
            f"Presence on GCEL is a negative signal; phase-out plan partially mitigates it. "
            f"Transition claims should be verified against the phase-out timeline."
        )

    return (
        f"Urgewald Global Coal Exit List: {company_name} is listed on the GCEL "
        f"({capacity_str}). Expansion status unclear — classified as a coal company "
        f"by Urgewald. Any clean energy transition claims require scrutiny against "
        f"this coal exposure."
    )
