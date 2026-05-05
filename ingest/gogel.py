"""Global Oil and Gas Exit List (GOGEL) ingest module for the Prasine Index.

Loads the Urgewald Global Oil and Gas Exit List from data/gogel_companies.csv,
downloaded via scripts/refresh_gogel.py. The GOGEL tracks approximately 1,000
companies responsible for the majority of global oil and gas production,
development, and expansion.

A company on the GOGEL actively developing new upstream oil and gas while claiming
a clean energy transition or Paris alignment is a primary greenwashing signal —
the same pattern documented for BP, Shell, Equinor, TotalEnergies, and others.

GOGEL is used by the GFANZ Net Zero Investment Framework, the Paris Aligned
Investment Initiative, and major institutional investors to screen fossil fuel
expansion exposure. A company claiming 1.5°C alignment while listed as a
GOGEL expander contradicts the most widely used oil and gas screen in ESG investing.

Data source: Urgewald (urgewald.org) — published annually
Refresh: python scripts/refresh_gogel.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_gogel_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_GOGEL_CSV: Path = Path(
    os.environ.get(
        "GOGEL_CSV",
        str(_PROJECT_ROOT / "data" / "gogel_companies.csv"),
    )
)

# Column variants across GOGEL export formats
_COL_COMPANY = ("Company", "company", "Company Name", "Name", "Issuer")
_COL_COUNTRY = ("Country", "country", "HQ Country", "Headquarters")
_COL_ISIN = ("ISIN", "isin", "Primary ISIN", "ISIN Code")
_COL_TICKER = ("Ticker", "ticker", "Bloomberg Ticker", "Stock Ticker")
_COL_SECTOR = ("Sector", "sector", "Business Activity", "Oil and Gas Sector")
_COL_UPSTREAM = (
    "Upstream Expansion",
    "upstream_expansion",
    "New Oil & Gas Reserves",
    "Expanding Upstream",
    "Upstream Development",
)
_COL_LNG = (
    "LNG Expansion",
    "lng_expansion",
    "LNG Development",
    "New LNG",
    "LNG Capacity",
)
_COL_PRODUCTION = (
    "Production (boe/d)",
    "production_boed",
    "Daily Production",
    "Oil & Gas Production",
    "BOE/day",
)
_COL_RESERVES = (
    "Proven Reserves (boe)",
    "proven_reserves_boe",
    "P1 Reserves",
    "Proven + Probable",
    "Reserves",
)
_COL_PHASE_OUT = (
    "Phase-out Plan",
    "phase_out",
    "Fossil Fuel Exit Plan",
    "Transition Plan",
    "Divestment Plan",
)

_EXPANDING_VALUES = frozenset(
    {
        "yes",
        "expanding",
        "expansion",
        "new capacity",
        "developing",
        "under development",
        "new licensing",
        "active development",
        "increase",
        "planned",
        "under construction",
    }
)
_PHASEOUT_VALUES = frozenset(
    {
        "no new",
        "phasing out",
        "phase-out",
        "phase out",
        "committed to exit",
        "no expansion",
        "fossil free",
        "no new licenses",
        "transition only",
    }
)


class _GOGELRecord:
    """Internal representation of one GOGEL company record."""

    __slots__ = (
        "company",
        "country",
        "isin",
        "lng_expansion",
        "phase_out_plan",
        "production_boed",
        "proven_reserves_boe",
        "sector",
        "ticker",
        "upstream_expansion",
    )

    def __init__(
        self,
        company: str,
        country: str,
        isin: str | None,
        ticker: str | None,
        sector: str,
        upstream_expansion: str,
        lng_expansion: str,
        phase_out_plan: str,
        production_boed: float | None,
        proven_reserves_boe: float | None,
    ) -> None:
        self.company = company
        self.country = country
        self.isin = isin
        self.ticker = ticker
        self.sector = sector
        self.upstream_expansion = upstream_expansion
        self.lng_expansion = lng_expansion
        self.phase_out_plan = phase_out_plan
        self.production_boed = production_boed
        self.proven_reserves_boe = proven_reserves_boe

    @property
    def is_expanding(self) -> bool:
        u = self.upstream_expansion.lower().strip()
        lng = self.lng_expansion.lower().strip()
        return u in _EXPANDING_VALUES or lng in _EXPANDING_VALUES

    @property
    def is_phasing_out(self) -> bool:
        po = self.phase_out_plan.lower().strip()
        u = self.upstream_expansion.lower().strip()
        return po in _PHASEOUT_VALUES or u in _PHASEOUT_VALUES


# Module-level cache
_cache_by_isin: dict[str, _GOGELRecord] | None = None
_cache_by_name: dict[str, _GOGELRecord] | None = None
_cache_by_ticker: dict[str, _GOGELRecord] | None = None


def refresh_cache() -> None:
    """Reset the GOGEL cache so the next call reloads from disk."""
    global _cache_by_isin, _cache_by_name, _cache_by_ticker
    _cache_by_isin = None
    _cache_by_name = None
    _cache_by_ticker = None
    logger.info("GOGEL cache cleared.", extra={"operation": "gogel_cache_reset"})


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
        " energy",
        " oil",
        " gas",
        " petroleum",
        " resources",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> tuple[
    dict[str, _GOGELRecord],
    dict[str, _GOGELRecord],
    dict[str, _GOGELRecord],
]:
    global _cache_by_isin, _cache_by_name, _cache_by_ticker

    if _cache_by_name is not None:
        return _cache_by_isin, _cache_by_name, _cache_by_ticker  # type: ignore[return-value]

    if not _GOGEL_CSV.exists():
        _cache_by_isin = {}
        _cache_by_name = {}
        _cache_by_ticker = {}
        logger.info(
            "GOGEL data file not found — run scripts/refresh_gogel.py to download. "
            f"Expected at: {_GOGEL_CSV}",
            extra={"operation": "gogel_cache_missing"},
        )
        return _cache_by_isin, _cache_by_name, _cache_by_ticker

    by_isin: dict[str, _GOGELRecord] = {}
    by_name: dict[str, _GOGELRecord] = {}
    by_ticker: dict[str, _GOGELRecord] = {}

    with _GOGEL_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            company = _pick(row, _COL_COMPANY)
            if not company:
                continue
            record = _GOGELRecord(
                company=company,
                country=_pick(row, _COL_COUNTRY),
                isin=_pick(row, _COL_ISIN) or None,
                ticker=_pick(row, _COL_TICKER) or None,
                sector=_pick(row, _COL_SECTOR),
                upstream_expansion=_pick(row, _COL_UPSTREAM),
                lng_expansion=_pick(row, _COL_LNG),
                phase_out_plan=_pick(row, _COL_PHASE_OUT),
                production_boed=_parse_float(_pick(row, _COL_PRODUCTION)),
                proven_reserves_boe=_parse_float(_pick(row, _COL_RESERVES)),
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
        f"GOGEL cache loaded: {len(by_name)} companies",
        extra={"operation": "gogel_cache_loaded"},
    )
    return _cache_by_isin, _cache_by_name, _cache_by_ticker


def _lookup(name: str, isin: str | None, ticker: str | None) -> _GOGELRecord | None:
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


async def fetch_gogel_data(claim: Claim, company: object) -> list[Evidence]:
    """Return Global Oil and Gas Exit List evidence for a company.

    A company listed on the GOGEL as actively expanding upstream oil and gas
    production while making clean-energy transition or Paris-alignment claims
    is engaging in documented greenwashing. GOGEL is used by 400+ financial
    institutions under the GFANZ and PAII frameworks.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the company is not on the GOGEL.
    """
    name: str = getattr(company, "name", "")
    isin: str | None = getattr(company, "isin", None)
    ticker: str | None = getattr(company, "ticker", None)

    record = _lookup(name, isin, ticker)

    if record is None:
        logger.info(
            f"GOGEL: {name!r} not on Global Oil and Gas Exit List",
            extra={"operation": "gogel_not_found", "company": name},
        )
        return []

    supports, confidence = _assess_record(record)
    summary = _build_summary(name, record)

    logger.info(
        f"GOGEL: {name!r} found — expanding={record.is_expanding}, "
        f"phasing_out={record.is_phasing_out}",
        extra={
            "operation": "gogel_found",
            "company": name,
            "is_expanding": record.is_expanding,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.GOGEL,
            evidence_type=EvidenceType.FINANCING_RECORD,
            source_url="https://gogel.org/",
            raw_data={
                "company": record.company,
                "country": record.country,
                "sector": record.sector,
                "upstream_expansion": record.upstream_expansion,
                "lng_expansion": record.lng_expansion,
                "phase_out_plan": record.phase_out_plan,
                "production_boed": record.production_boed,
                "proven_reserves_boe": record.proven_reserves_boe,
            },
            summary=summary,
            data_year=None,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _GOGELRecord) -> tuple[bool | None, float]:
    """Assess whether GOGEL status supports or contradicts clean-energy claims."""
    if record.is_expanding:
        return False, 0.90
    if record.is_phasing_out:
        return None, 0.55
    # On GOGEL but status unclear — still a negative signal for clean claims
    return False, 0.65


def _build_summary(company_name: str, record: _GOGELRecord) -> str:
    capacity_parts = []
    if record.production_boed:
        capacity_parts.append(f"{record.production_boed:,.0f} boe/d production")
    if record.proven_reserves_boe:
        capacity_parts.append(f"{record.proven_reserves_boe:,.0f} boe proven reserves")
    capacity_str = "; ".join(capacity_parts) or "production data not disclosed"

    if record.is_expanding:
        return (
            f"Urgewald Global Oil and Gas Exit List: {company_name} is listed as "
            f"ACTIVELY EXPANDING oil and gas capacity ({capacity_str}). "
            f"Upstream expansion: {record.upstream_expansion or 'yes'}; "
            f"LNG expansion: {record.lng_expansion or 'unknown'}. "
            f"Any claim of clean energy transition or Paris alignment is directly "
            f"contradicted by this documented fossil fuel expansion. "
            f"GOGEL is used by 400+ financial institutions (GFANZ, PAII) as the "
            f"standard oil and gas screen — this company fails it."
        )

    if record.is_phasing_out:
        phase_str = record.phase_out_plan or "plan details not disclosed"
        return (
            f"Urgewald Global Oil and Gas Exit List: {company_name} is listed on GOGEL "
            f"({capacity_str}) but has a documented fossil fuel phase-out plan: "
            f"{phase_str}. Presence on GOGEL is a negative signal; "
            f"phase-out plan partially mitigates it. "
            f"Transition claims should be verified against the phase-out timeline."
        )

    return (
        f"Urgewald Global Oil and Gas Exit List: {company_name} is listed on GOGEL "
        f"({capacity_str}). Expansion status unclear — classified as an oil and gas "
        f"company by Urgewald. Any clean energy transition claims require scrutiny "
        f"against this fossil fuel exposure."
    )
