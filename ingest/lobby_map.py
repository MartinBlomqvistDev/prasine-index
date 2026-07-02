"""LobbyMap climate lobbying scores ingest module for the Prasine Index.

Loads the LobbyMap Company Climate Policy Engagement database from
data/lobbymap_companies.csv, downloaded via scripts/refresh_lobbymap.py.
Provides lobbying-alignment evidence for claims from companies that simultaneously
advocate for climate action while opposing climate legislation in Brussels or
Washington.

LobbyMap independently assesses corporate climate policy engagement, scoring
companies A+ (strongly supportive) to F (obstructive). A company scoring D or F
while making green claims is a direct greenwashing signal — the company lobbies
against the legislation it publicly claims to support.

Data source: LobbyMap (lobbymap.org)
Refresh: python scripts/refresh_lobbymap.py
"""

from __future__ import annotations

import contextlib
import csv
import os
import time
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.company import Company
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_lobby_map_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_LM_CSV: Path = Path(
    os.environ.get(
        "LOBBYMAP_CSV",
        str(_PROJECT_ROOT / "data" / "lobbymap_companies.csv"),
    )
)

# ---------------------------------------------------------------------------
# Column name variants across LobbyMap CSV vintages
# ---------------------------------------------------------------------------

_COL_COMPANY = ("Company", "company", "Organization", "Name")
_COL_TICKER = ("Ticker", "ticker", "Stock Ticker", "Symbol")
_COL_COUNTRY = ("Country", "country", "HQ Country")
_COL_SECTOR = ("Sector", "sector", "Industry")
_COL_SCORE = (
    "InfluenceMap Score",
    "Climate Policy Engagement Score",
    "Score",
    "score",
    "Band",
    "band",
    "influencemap_score",
)
_COL_PERFORMANCE_BAND = ("Performance Band", "performance_band", "Band Letter", "Grade")
_COL_ENGAGEMENT = (
    "Active Engagement on Climate Policy",
    "engagement",
    "Engagement",
    "Climate Policy Engagement",
)
_COL_YEAR = ("Year", "year", "Assessment Year", "ReportYear")

# ---------------------------------------------------------------------------
# Score classification
# ---------------------------------------------------------------------------

# Bands that indicate obstructive lobbying — contradict green claims.
_OBSTRUCTIVE_BANDS = frozenset({"d+", "d", "d-", "e+", "e", "e-", "f+", "f", "f-"})

# Bands that indicate supportive engagement — support green claims.
_SUPPORTIVE_BANDS = frozenset({"a+", "a", "a-", "b+", "b"})

# Bands that are neutral / inconclusive.
_NEUTRAL_BANDS = frozenset({"b-", "c+", "c", "c-"})


class _LobbyMapRecord:
    """Internal representation of one LobbyMap company record."""

    __slots__ = (
        "active_engagement",
        "company",
        "country",
        "performance_band",
        "score",
        "sector",
        "ticker",
        "year",
    )

    def __init__(
        self,
        company: str,
        ticker: str | None,
        country: str,
        sector: str,
        score: str,
        performance_band: str,
        active_engagement: str,
        year: int | None,
    ) -> None:
        self.company = company
        self.ticker = ticker
        self.country = country
        self.sector = sector
        self.score = score
        self.performance_band = performance_band
        self.active_engagement = active_engagement
        self.year = year

    @property
    def band_normalised(self) -> str:
        """Lowercase band letter, stripped of surrounding whitespace."""
        raw = (self.performance_band or self.score or "").strip().lower()
        return raw

    @property
    def is_obstructive(self) -> bool:
        return self.band_normalised in _OBSTRUCTIVE_BANDS

    @property
    def is_supportive(self) -> bool:
        return self.band_normalised in _SUPPORTIVE_BANDS


# Module-level cache: {normalised_company: _LobbyMapRecord}
_cache_by_name: dict[str, _LobbyMapRecord] | None = None
_cache_by_ticker: dict[str, _LobbyMapRecord] | None = None
_cache_loaded_at: float = 0.0
_CACHE_TTL_S: float = 86_400.0  # 24 hours


def refresh_cache() -> None:
    """Reset the LobbyMap cache so the next call reloads from disk.

    Call this after running scripts/refresh_lobbymap.py.
    """
    global _cache_by_name, _cache_by_ticker, _cache_loaded_at
    _cache_by_name = None
    _cache_by_ticker = None
    _cache_loaded_at = 0.0
    logger.info("LobbyMap cache cleared.", extra={"operation": "lobbymap_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    """Return the value of the first matching column name, or empty string."""
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _normalise_name(name: str) -> str:
    """Lowercase and strip legal suffixes for fuzzy matching."""
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


def _get_cache() -> tuple[dict[str, _LobbyMapRecord], dict[str, _LobbyMapRecord]]:
    """Return module-level caches, loading from disk on first call or after TTL expiry."""
    global _cache_by_name, _cache_by_ticker, _cache_loaded_at

    if _cache_by_name is not None:
        age = time.monotonic() - _cache_loaded_at
        if age < _CACHE_TTL_S:
            return _cache_by_name, _cache_by_ticker  # type: ignore[return-value]
        logger.info(
            f"LobbyMap cache expired after {age / 3600:.1f}h — reloading from disk.",
            extra={"operation": "lobbymap_cache_expired"},
        )
        _cache_by_name = None
        _cache_by_ticker = None

    if not _LM_CSV.exists():
        _cache_by_name = {}
        _cache_by_ticker = {}
        logger.info(
            "LobbyMap data file not found — run scripts/refresh_lobbymap.py. "
            f"Expected at: {_LM_CSV}",
            extra={"operation": "lobbymap_cache_missing"},
        )
        return _cache_by_name, _cache_by_ticker

    by_name: dict[str, _LobbyMapRecord] = {}
    by_ticker: dict[str, _LobbyMapRecord] = {}

    with _LM_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            company = _pick(row, _COL_COMPANY)
            if not company:
                continue

            year_str = _pick(row, _COL_YEAR)
            year: int | None = None
            with contextlib.suppress(ValueError):
                year = int(year_str) if year_str else None

            record = _LobbyMapRecord(
                company=company,
                ticker=_pick(row, _COL_TICKER) or None,
                country=_pick(row, _COL_COUNTRY),
                sector=_pick(row, _COL_SECTOR),
                score=_pick(row, _COL_SCORE),
                performance_band=_pick(row, _COL_PERFORMANCE_BAND),
                active_engagement=_pick(row, _COL_ENGAGEMENT),
                year=year,
            )

            norm = _normalise_name(company)
            # Keep the more recent record if duplicate
            existing = by_name.get(norm)
            if existing is None or (year is not None and (existing.year or 0) < year):
                by_name[norm] = record

            if record.ticker:
                by_ticker[record.ticker.upper()] = record

    _cache_by_name = by_name
    _cache_by_ticker = by_ticker
    _cache_loaded_at = time.monotonic()

    logger.info(
        f"LobbyMap cache loaded: {len(by_name)} companies",
        extra={"operation": "lobbymap_cache_loaded"},
    )
    return _cache_by_name, _cache_by_ticker


def _lookup(name: str, ticker: str | None) -> _LobbyMapRecord | None:
    """Look up a company by ticker (preferred) or normalised name.

    Args:
        name: Company name.
        ticker: Stock ticker symbol, if available.

    Returns:
        The matching LobbyMapRecord, or None.
    """
    by_name, by_ticker = _get_cache()

    if ticker and ticker.upper() in by_ticker:
        return by_ticker[ticker.upper()]

    norm = _normalise_name(name)
    if norm in by_name:
        return by_name[norm]

    # Partial substring match as last resort
    if len(norm) >= 5:
        for key, record in by_name.items():
            if norm in key:
                return record

    return None


async def fetch_lobby_map_data(claim: Claim, company: Company) -> list[Evidence]:
    """Return LobbyMap lobbying alignment evidence for a company.

    Looks up the company's climate policy engagement score. Obstructive
    lobbying (D/E/F band) while making green claims is a direct greenwashing
    signal — the company works against the policies it publicly supports.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with an Evidence record, or empty list if the
        company is not in the LobbyMap database.
    """
    name: str = getattr(company, "name", "")
    ticker: str | None = getattr(company, "ticker", None)

    record = _lookup(name, ticker)

    if record is None:
        logger.info(
            f"LobbyMap: {name!r} not found in database",
            extra={"operation": "lobbymap_not_found", "company": name},
        )
        return []

    supports, confidence = _assess_record(record)
    summary = _build_summary(name, record)

    logger.info(
        f"LobbyMap: {name!r} — band={record.band_normalised!r}, "
        f"obstructive={record.is_obstructive}, supportive={record.is_supportive}",
        extra={
            "operation": "lobbymap_found",
            "company": name,
            "band": record.band_normalised,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.LOBBY_MAP,
            evidence_type=EvidenceType.LOBBYING_RECORD,
            source_url="https://lobbymap.org/",
            raw_data={
                "company": record.company,
                "ticker": record.ticker,
                "country": record.country,
                "sector": record.sector,
                "score": record.score,
                "performance_band": record.performance_band,
                "active_engagement": record.active_engagement,
                "year": record.year,
            },
            summary=summary,
            data_year=record.year,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _LobbyMapRecord) -> tuple[bool | None, float]:
    """Determine whether the LobbyMap record supports or contradicts the claim.

    Args:
        record: The LobbyMap record for the company.

    Returns:
        Tuple of (supports_claim, confidence).
    """
    if record.is_obstructive:
        # Company lobbies against climate policy — directly contradicts green claims.
        return False, 0.85

    if record.is_supportive:
        # Company actively supports climate policy — consistent with green claims.
        return True, 0.75

    # Neutral band — inconclusive, include with low confidence.
    return None, 0.50


def _build_summary(company_name: str, record: _LobbyMapRecord) -> str:
    """Build a human-readable summary for the Judge Agent.

    Args:
        company_name: Display name of the company.
        record: The LobbyMap record.

    Returns:
        A plain-text summary string.
    """
    band = record.band_normalised.upper() or "not scored"
    engagement = record.active_engagement or "not assessed"
    year_str = f" (assessment year: {record.year})" if record.year else ""

    if record.is_obstructive:
        return (
            f"LobbyMap climate policy engagement score for {company_name}: {band}{year_str}. "
            f"Active engagement classification: {engagement}. "
            f"This score indicates obstructive engagement — the company actively opposes or "
            f"delays climate legislation while making green claims. "
            f"This is a primary greenwashing indicator: stated climate commitments are "
            f"contradicted by the company's own lobbying activity."
        )

    if record.is_supportive:
        return (
            f"LobbyMap climate policy engagement score for {company_name}: {band}{year_str}. "
            f"Active engagement classification: {engagement}. "
            f"This score indicates supportive engagement — the company's lobbying activity "
            f"is broadly consistent with its public climate commitments."
        )

    return (
        f"LobbyMap climate policy engagement score for {company_name}: {band}{year_str}. "
        f"Active engagement classification: {engagement}. "
        f"This score indicates neutral or mixed engagement — inconclusive for greenwashing assessment."
    )
