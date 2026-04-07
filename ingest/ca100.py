"""Climate Action 100+ (CA100+) benchmark assessment ingest module.

Loads the CA100+ Net Zero Company Benchmark results from data/ca100_companies.csv,
downloaded via scripts/refresh_ca100.py. CA100+ is the world's largest investor-led
initiative, tracking 170 of the highest-emitting listed companies against a
standardised net-zero benchmark.

CA100+ provides independent third-party assessments of whether companies have:
  - A credible net-zero ambition aligned to 1.5°C
  - Near-, medium-, and long-term decarbonisation targets
  - Capital expenditure aligned to a net-zero pathway
  - Transparent and positive climate policy engagement

A company claiming net-zero ambition while rated "Not Aligned" by CA100+ is a
strong third-party contradiction — assessed by the largest institutional investor
coalition in the world (700+ investors, $68 trillion AUM).

Data source: climateaction100.org/companies
Refresh: python scripts/refresh_ca100.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_ca100_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_CA100_CSV: Path = Path(
    os.environ.get(
        "CA100_CSV",
        str(_PROJECT_ROOT / "data" / "ca100_companies.csv"),
    )
)

# ---------------------------------------------------------------------------
# Column name variants across CA100+ benchmark CSV vintages
# ---------------------------------------------------------------------------

_COL_COMPANY = ("Company", "company", "Company Name", "Name", "Issuer")
_COL_SECTOR = ("Sector", "sector", "Industry", "GICS Sector")
_COL_COUNTRY = ("Country", "country", "HQ Country", "Headquarters Country")
_COL_ISIN = ("ISIN", "isin", "Primary ISIN")
_COL_TICKER = ("Ticker", "ticker", "Bloomberg Ticker")

# Net Zero Ambition / Alignment columns
_COL_NZ_AMBITION = (
    "Net Zero Ambition Benchmark",
    "Net-Zero Ambition",
    "NZC Ambition",
    "net_zero_ambition",
    "Ambition Aligned",
    "NZ Ambition",
)
# Decarbonisation target columns
_COL_SHORT_TARGET = (
    "Short-term Target",
    "Near-term Target",
    "Short Term Target",
    "short_term_target",
    "2030 Target",
)
_COL_LONG_TARGET = (
    "Long-term Target",
    "Long Term Target",
    "long_term_target",
    "Net Zero Target",
    "2050 Target",
)
# Capex alignment
_COL_CAPEX = (
    "Capex Alignment",
    "Capital Expenditure Alignment",
    "CapEx Alignment",
    "capex_alignment",
    "CAPEX Aligned",
)
# Climate lobbying
_COL_LOBBYING = (
    "Climate Policy Engagement",
    "Lobbying Alignment",
    "Climate Lobbying",
    "lobbying",
    "Policy Engagement",
)
_COL_YEAR = ("Year", "year", "Assessment Year", "Benchmark Year")

# ---------------------------------------------------------------------------
# Assessment value normalisation
# ---------------------------------------------------------------------------

_ALIGNED_VALUES = frozenset({
    "yes", "aligned", "met", "achieved", "1.5°c aligned", "paris aligned",
    "net zero aligned", "on track",
})
_PARTIAL_VALUES = frozenset({
    "partial", "partially met", "some elements", "below 2°c", "below 2c",
    "moderate ambition", "limited",
})
_NOT_ALIGNED_VALUES = frozenset({
    "no", "not aligned", "not met", "not set", "no target", "insufficient",
    "far from aligned", "misaligned", "obstructive",
})


class _CA100Record:
    """Internal representation of one CA100+ benchmark result."""

    __slots__ = (
        "company", "sector", "country", "isin", "ticker",
        "nz_ambition", "short_term_target", "long_term_target",
        "capex_alignment", "climate_lobbying", "year",
    )

    def __init__(
        self,
        company: str,
        sector: str,
        country: str,
        isin: str | None,
        ticker: str | None,
        nz_ambition: str,
        short_term_target: str,
        long_term_target: str,
        capex_alignment: str,
        climate_lobbying: str,
        year: int | None,
    ) -> None:
        self.company = company
        self.sector = sector
        self.country = country
        self.isin = isin
        self.ticker = ticker
        self.nz_ambition = nz_ambition
        self.short_term_target = short_term_target
        self.long_term_target = long_term_target
        self.capex_alignment = capex_alignment
        self.climate_lobbying = climate_lobbying
        self.year = year

    def _classify(self, value: str) -> str:
        """Classify a benchmark value as ALIGNED / PARTIAL / NOT_ALIGNED / UNKNOWN."""
        v = value.lower().strip()
        if v in _ALIGNED_VALUES:
            return "ALIGNED"
        if v in _PARTIAL_VALUES:
            return "PARTIAL"
        if v in _NOT_ALIGNED_VALUES:
            return "NOT_ALIGNED"
        return "UNKNOWN"

    @property
    def nz_ambition_class(self) -> str:
        return self._classify(self.nz_ambition)

    @property
    def capex_class(self) -> str:
        return self._classify(self.capex_alignment)

    @property
    def short_target_class(self) -> str:
        return self._classify(self.short_term_target)


# Module-level cache
_cache_by_isin: dict[str, _CA100Record] | None = None
_cache_by_name: dict[str, _CA100Record] | None = None
_cache_by_ticker: dict[str, _CA100Record] | None = None


def refresh_cache() -> None:
    """Reset the CA100+ cache so the next call reloads from disk."""
    global _cache_by_isin, _cache_by_name, _cache_by_ticker
    _cache_by_isin = None
    _cache_by_name = None
    _cache_by_ticker = None
    logger.info("CA100+ cache cleared.", extra={"operation": "ca100_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _normalise_name(name: str) -> str:
    name = name.lower().strip()
    for suffix in (" plc", " ag", " se", " sa", " s.a.", " spa", " s.p.a.", " nv",
                   " bv", " gmbh", " inc", " corp", " ltd", " limited", " group",
                   " holding", " holdings", " a/s", " as", " ab"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> tuple[
    dict[str, _CA100Record],
    dict[str, _CA100Record],
    dict[str, _CA100Record],
]:
    global _cache_by_isin, _cache_by_name, _cache_by_ticker

    if _cache_by_name is not None:
        return _cache_by_isin, _cache_by_name, _cache_by_ticker  # type: ignore[return-value]

    if not _CA100_CSV.exists():
        _cache_by_isin = {}
        _cache_by_name = {}
        _cache_by_ticker = {}
        logger.info(
            "CA100+ data file not found — run scripts/refresh_ca100.py. "
            f"Expected at: {_CA100_CSV}",
            extra={"operation": "ca100_cache_missing"},
        )
        return _cache_by_isin, _cache_by_name, _cache_by_ticker

    by_isin: dict[str, _CA100Record] = {}
    by_name: dict[str, _CA100Record] = {}
    by_ticker: dict[str, _CA100Record] = {}

    with _CA100_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            company = _pick(row, _COL_COMPANY)
            if not company:
                continue

            year_str = _pick(row, _COL_YEAR)
            year: int | None = None
            try:
                year = int(year_str) if year_str else None
            except ValueError:
                pass

            record = _CA100Record(
                company=company,
                sector=_pick(row, _COL_SECTOR),
                country=_pick(row, _COL_COUNTRY),
                isin=_pick(row, _COL_ISIN) or None,
                ticker=_pick(row, _COL_TICKER) or None,
                nz_ambition=_pick(row, _COL_NZ_AMBITION),
                short_term_target=_pick(row, _COL_SHORT_TARGET),
                long_term_target=_pick(row, _COL_LONG_TARGET),
                capex_alignment=_pick(row, _COL_CAPEX),
                climate_lobbying=_pick(row, _COL_LOBBYING),
                year=year,
            )

            norm = _normalise_name(company)
            existing = by_name.get(norm)
            if existing is None or (year is not None and (existing.year or 0) < year):
                by_name[norm] = record

            if record.isin:
                by_isin[record.isin.upper()] = record
            if record.ticker:
                by_ticker[record.ticker.upper()] = record

    _cache_by_isin = by_isin
    _cache_by_name = by_name
    _cache_by_ticker = by_ticker

    logger.info(
        f"CA100+ cache loaded: {len(by_name)} companies",
        extra={"operation": "ca100_cache_loaded"},
    )
    return _cache_by_isin, _cache_by_name, _cache_by_ticker


def _lookup(name: str, isin: str | None, ticker: str | None) -> _CA100Record | None:
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


async def fetch_ca100_data(claim: Claim, company: object) -> list[Evidence]:
    """Return CA100+ net-zero benchmark assessment for a company.

    CA100+ is assessed by 700+ institutional investors representing $68 trillion AUM.
    A company claiming net-zero ambition while rated "Not Aligned" by CA100+ is a
    strong investor-consensus contradiction of that claim.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the company is not in CA100+.
    """
    name: str = getattr(company, "name", "")
    isin: str | None = getattr(company, "isin", None)
    ticker: str | None = getattr(company, "ticker", None)

    record = _lookup(name, isin, ticker)

    if record is None:
        logger.info(
            f"CA100+: {name!r} not in benchmark list",
            extra={"operation": "ca100_not_found", "company": name},
        )
        return []

    supports, confidence = _assess_record(record)
    summary = _build_summary(name, record)

    logger.info(
        f"CA100+: {name!r} — nz_ambition={record.nz_ambition!r}, "
        f"capex={record.capex_alignment!r}, class={record.nz_ambition_class}",
        extra={
            "operation": "ca100_found",
            "company": name,
            "nz_ambition": record.nz_ambition,
            "capex_alignment": record.capex_alignment,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.CA100,
            evidence_type=EvidenceType.BENCHMARK_ASSESSMENT,
            source_url="https://www.climateaction100.org/company-responses/",
            raw_data={
                "company": record.company,
                "sector": record.sector,
                "country": record.country,
                "nz_ambition": record.nz_ambition,
                "short_term_target": record.short_term_target,
                "long_term_target": record.long_term_target,
                "capex_alignment": record.capex_alignment,
                "climate_lobbying": record.climate_lobbying,
                "year": record.year,
            },
            summary=summary,
            data_year=record.year,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _CA100Record) -> tuple[bool | None, float]:
    """Derive supports_claim and confidence from the CA100+ benchmark result."""
    nz = record.nz_ambition_class
    capex = record.capex_class

    if nz == "NOT_ALIGNED" and capex == "NOT_ALIGNED":
        # Both core metrics misaligned — strong contradiction of any net-zero claim.
        return False, 0.85

    if nz == "NOT_ALIGNED":
        return False, 0.80

    if nz == "ALIGNED" and capex == "ALIGNED":
        return True, 0.75

    if nz == "ALIGNED":
        return True, 0.65

    if nz == "PARTIAL":
        return None, 0.55

    return None, 0.45


def _build_summary(company_name: str, record: _CA100Record) -> str:
    year_str = f" ({record.year} benchmark)" if record.year else ""
    nz_class = record.nz_ambition_class
    capex_class = record.capex_class

    if nz_class == "NOT_ALIGNED":
        return (
            f"CA100+ Net Zero Company Benchmark for {company_name}{year_str}: "
            f"Net Zero Ambition = {record.nz_ambition or 'Not Aligned'}; "
            f"Capex Alignment = {record.capex_alignment or 'unknown'}; "
            f"Short-term target = {record.short_term_target or 'unknown'}. "
            f"The CA100+ investor coalition (700+ investors, $68tn AUM) assesses this "
            f"company as NOT aligned with a credible net-zero pathway. Any net-zero or "
            f"Paris-aligned claim by this company is contradicted by this assessment."
        )

    if nz_class == "ALIGNED":
        return (
            f"CA100+ Net Zero Company Benchmark for {company_name}{year_str}: "
            f"Net Zero Ambition = {record.nz_ambition}; "
            f"Capex Alignment = {record.capex_alignment or 'unknown'}; "
            f"Short-term target = {record.short_term_target or 'unknown'}. "
            f"CA100+ investors assess this company as having credible net-zero alignment. "
            f"Supports claims of Paris-compatible climate strategy."
        )

    return (
        f"CA100+ Net Zero Company Benchmark for {company_name}{year_str}: "
        f"Net Zero Ambition = {record.nz_ambition or 'partial/unknown'}; "
        f"Capex Alignment = {record.capex_alignment or 'unknown'}. "
        f"Partial alignment — some elements meet the benchmark, others do not. "
        f"Inconclusive for greenwashing assessment without deeper analysis."
    )
