"""Climate Action 100+ (CA100+) Net Zero Company Benchmark ingest module.

Loads the benchmark's assessments from data/ca100_companies.csv, which
scripts/refresh_ca100.py writes from the data sheet CA100+ publishes with each
benchmark. CA100+ is an investor-led initiative; its benchmark assesses the
highest-emitting listed companies on ten indicators, from a net zero ambition and
targets to capital allocation, climate policy engagement and historical
emissions reductions. The TPI Centre, InfluenceMap and the World Benchmarking
Alliance assess the indicators from company disclosures.

Each record names the benchmark it comes from and links the company's
assessment page on climateaction100.org.

Refresh: python scripts/refresh_ca100.py
"""

from __future__ import annotations

import contextlib
import csv
import os
from pathlib import Path

from core.logger import get_logger
from ingest.name_matching import contains_name
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["describe_indicators", "fetch_ca100_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_CA100_CSV: Path = Path(
    os.environ.get(
        "CA100_CSV",
        str(_PROJECT_ROOT / "data" / "ca100_companies.csv"),
    )
)

_CA100_XLSX: Path = Path(
    os.environ.get(
        "CA100_XLSX",
        str(_PROJECT_ROOT / "data" / "ca100_companies.xlsx"),
    )
)

# ---------------------------------------------------------------------------
# Column name variants across CA100+ benchmark CSV vintages
# ---------------------------------------------------------------------------

_COL_COMPANY = ("Company", "company", "Company Name", "Company name", "Name", "Issuer")
_COL_SECTOR = ("Sector", "sector", "Industry", "GICS Sector")
_COL_COUNTRY = ("Country", "country", "HQ Country", "HQ location", "Headquarters Country")
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
_COL_BENCHMARK = ("Benchmark",)
_COL_PAGE = ("Assessment Page",)

_BENCHMARK_PAGE = "https://www.climateaction100.org/net-zero-company-benchmark/"

# The benchmark's ten indicators: the CSV column and the indicator's name in prose,
# in the benchmark's order. A CSV from an earlier edition may hold only some.
_INDICATORS: tuple[tuple[str, str], ...] = (
    ("Net Zero Ambition Benchmark", "net zero by 2050 or sooner ambition"),
    ("Long-term Target", "long-term target (2036 to 2050)"),
    ("Medium-term Target", "medium-term target (2031 to 2035)"),
    ("Short-term Target", "short-term target (up to 2030)"),
    ("Decarbonisation Strategy", "decarbonisation strategy"),
    ("Capex Alignment", "capital allocation"),
    ("Climate Policy Engagement", "climate policy engagement"),
    ("Climate Governance", "climate governance"),
    ("Just Transition", "just transition"),
    ("Historical Emissions Reductions", "historical emissions reductions"),
)
# What the data sheet's progress column says, in prose. "No change in score" and
# "Not Applicable" add nothing to the score.
_CHANGES = {
    "decline in score": "lower than in the previous benchmark",
    "improvement in score": "higher than in the previous benchmark",
}

# ---------------------------------------------------------------------------
# Assessment value normalisation
# ---------------------------------------------------------------------------

_ALIGNED_VALUES = frozenset(
    {
        "yes",
        "aligned",
        "met",
        "achieved",
        "1.5°c aligned",
        "paris aligned",
        "net zero aligned",
        "on track",
    }
)
_PARTIAL_VALUES = frozenset(
    {
        "partial",
        "partially met",
        "some elements",
        "below 2°c",
        "below 2c",
        "moderate ambition",
        "limited",
    }
)
_NOT_ALIGNED_VALUES = frozenset(
    {
        "no",
        "not aligned",
        "not met",
        "not set",
        "no target",
        "insufficient",
        "far from aligned",
        "misaligned",
        "obstructive",
    }
)


class _CA100Record:
    """Internal representation of one CA100+ benchmark result."""

    __slots__ = (
        "benchmark",
        "capex_alignment",
        "climate_lobbying",
        "company",
        "country",
        "indicators",
        "isin",
        "long_term_target",
        "nz_ambition",
        "page",
        "sector",
        "short_term_target",
        "ticker",
        "year",
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
        benchmark: str = "",
        page: str = "",
        indicators: list[dict[str, str]] | None = None,
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
        self.benchmark = benchmark or (f"{year}" if year else "")
        self.page = page or _BENCHMARK_PAGE
        self.indicators = indicators or []

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


def _build_records(
    rows: list[dict[str, str]],
) -> tuple[dict[str, _CA100Record], dict[str, _CA100Record], dict[str, _CA100Record]]:
    by_isin: dict[str, _CA100Record] = {}
    by_name: dict[str, _CA100Record] = {}
    by_ticker: dict[str, _CA100Record] = {}

    for row in rows:
        company = _pick(row, _COL_COMPANY)
        if not company:
            continue

        year_str = _pick(row, _COL_YEAR)
        year: int | None = None
        with contextlib.suppress(ValueError):
            year = int(year_str) if year_str else None

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
            benchmark=_pick(row, _COL_BENCHMARK),
            page=_pick(row, _COL_PAGE),
            indicators=[
                {
                    "indicator": label,
                    "score": row[column].strip(),
                    "change": _CHANGES.get(
                        (row.get(f"{column} Progress") or "").strip().lower(), ""
                    ),
                }
                for column, label in _INDICATORS
                if (row.get(column) or "").strip()
            ],
        )

        norm = _normalise_name(company)
        existing = by_name.get(norm)
        if existing is None or (year is not None and (existing.year or 0) < year):
            by_name[norm] = record

        if record.isin:
            by_isin[record.isin.upper()] = record
        if record.ticker:
            by_ticker[record.ticker.upper()] = record

    return by_isin, by_name, by_ticker


def _load_from_csv(
    path: Path,
) -> tuple[dict[str, _CA100Record], dict[str, _CA100Record], dict[str, _CA100Record]]:
    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader]
    return _build_records(rows)


def _load_from_xlsx(
    path: Path,
) -> tuple[dict[str, _CA100Record], dict[str, _CA100Record], dict[str, _CA100Record]]:
    try:
        import openpyxl
    except ImportError:
        logger.warning(
            "openpyxl not installed: cannot read CA100+ XLSX. Run: pip install openpyxl",
            extra={"operation": "ca100_xlsx_missing_dep"},
        )
        return {}, {}, {}

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    raw_rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not raw_rows:
        return {}, {}, {}

    headers = [str(h).strip() if h is not None else "" for h in raw_rows[0]]
    rows = [
        {headers[i]: (str(v).strip() if v is not None else "") for i, v in enumerate(row_vals)}
        for row_vals in raw_rows[1:]
        if any(v is not None for v in row_vals)
    ]
    return _build_records(rows)


def _get_cache() -> tuple[
    dict[str, _CA100Record],
    dict[str, _CA100Record],
    dict[str, _CA100Record],
]:
    global _cache_by_isin, _cache_by_name, _cache_by_ticker

    if _cache_by_name is not None:
        assert _cache_by_isin is not None
        assert _cache_by_ticker is not None
        return _cache_by_isin, _cache_by_name, _cache_by_ticker
    # The curated CSV comes first. The benchmark's own workbook changes layout
    # between editions, so it is only a fallback, and a load that finds no
    # companies is reported instead of passing silently as "not covered".
    _cache_by_isin, _cache_by_name, _cache_by_ticker = {}, {}, {}
    if _CA100_CSV.exists():
        _cache_by_isin, _cache_by_name, _cache_by_ticker = _load_from_csv(_CA100_CSV)
        logger.info(
            f"CA100+ cache loaded from CSV: {len(_cache_by_name)} companies",
            extra={"operation": "ca100_cache_loaded", "source": "csv"},
        )
    if not _cache_by_name and _CA100_XLSX.exists():
        _cache_by_isin, _cache_by_name, _cache_by_ticker = _load_from_xlsx(_CA100_XLSX)
        logger.info(
            f"CA100+ cache loaded from XLSX: {len(_cache_by_name)} companies",
            extra={"operation": "ca100_cache_loaded", "source": "xlsx"},
        )
    if not _cache_by_name and (_CA100_CSV.exists() or _CA100_XLSX.exists()):
        logger.error(
            "CA100+ data files exist but no company could be read from them",
            extra={"operation": "ca100_cache_empty"},
        )
    elif not _cache_by_name:
        logger.info(
            f"CA100+ data file not found: run scripts/refresh_ca100.py. Expected at: {_CA100_CSV}",
            extra={"operation": "ca100_cache_missing"},
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
    if len(norm) >= 5:
        for key, record in by_name.items():
            if contains_name(key, norm):
                return record
    return None


async def fetch_ca100_data(claim: Claim, company: object) -> list[Evidence]:
    """Return the CA100+ Net Zero Company Benchmark assessment of a company.

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
        f"CA100+: {name!r}, nz_ambition={record.nz_ambition!r}, "
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
            source_url=record.page,
            raw_data={
                "benchmark": record.benchmark,
                "indicators": record.indicators,
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
        # Both core metrics misaligned: strong contradiction of any net-zero claim.
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
    return (
        f"Climate Action 100+ Net Zero Company Benchmark for {company_name}: "
        f"{describe_indicators({'benchmark': record.benchmark, 'indicators': record.indicators})}"
    )


def describe_indicators(raw_data: dict[str, object]) -> str:
    """State a CA100+ record's benchmark and every indicator it scores, in prose.

    Args:
        raw_data: The raw_data of a CA100+ Evidence record.

    Returns:
        For example "October 2026 benchmark: net zero by 2050 ambition No, lower
        than in the previous benchmark; long-term target (2036 to 2050) Partial; ..."
    """
    benchmark = str(raw_data.get("benchmark") or "")
    indicators = raw_data.get("indicators")
    if not isinstance(indicators, list) or not indicators:
        return f"{benchmark} benchmark: no indicator scores.".lstrip()
    scores = "; ".join(
        f"{item['indicator']} {item['score']}"
        + (f", {item['change']}" if item.get("change") else "")
        for item in indicators
    )
    return f"{benchmark} benchmark: {scores}.".lstrip()
