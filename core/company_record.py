"""The company record: what a company does, set beside what it claims.

The record lists the evidence that describes a company as a whole: its lobbying,
its fossil fuel supply, its verified emissions, its targets, investors'
assessments and enforcement decisions. Each line states what its source says,
and the record is built in code from the evidence of a run, with no model
involved.

It opens with the two practices that the UN High-Level Expert Group on net-zero
commitments says a credible climate pledge rules out, new fossil fuel supply and
lobbying against climate policy, and states what the records show on each. It
gives no score.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.evidence_scope import (
    HLEG_FOSSIL_SUPPLY,
    HLEG_LOBBYING,
    HLEG_URL,
    is_recent_finding,
)
from ingest.coal_exit import _EXPANDING_VALUES as _GCEL_EXPANDING
from ingest.gogel import _EXPANDING_VALUES as _GOGEL_EXPANDING
from ingest.lobby_map import _OBSTRUCTIVE_BANDS
from models.evidence import Evidence, EvidenceSource

__all__ = ["render_company_record"]

_OUTCOMES = {
    "BANNED": "complaint upheld",
    "CONFIRMED_MISLEADING": "finding that the advertising breached the rules",
    "FINED": "fine imposed",
    "COMMITMENTS": "commitments, without a finding of breach",
    "WARNING": "guidance or warning",
    "INVESTIGATION": "case opened, no outcome recorded",
    "NOT_UPHELD": "complaint not upheld",
    "ANNULLED": "decision annulled on appeal",
}

_TRACKERS = (
    (
        EvidenceSource.GOGET,
        "developing",
        "Global Oil and Gas Extraction Tracker",
        "field(s) in development",
    ),
    (EvidenceSource.GCPT, "expanding_units", "Global Coal Plant Tracker", "unit(s) in development"),
    (
        EvidenceSource.EGT,
        "expanding",
        "Europe Gas Tracker",
        "asset(s) proposed, announced or under construction",
    ),
)


def _first(evidence: list[Evidence], source: EvidenceSource) -> Evidence | None:
    return next((e for e in evidence if e.source == source), None)


def _unique(evidence: Iterable[Evidence]) -> list[Evidence]:
    """Drop repeats: every claim in a run carries the same company-level records."""
    seen: set[tuple[str, str]] = set()
    unique = []
    for e in evidence:
        key = (e.source.value, e.summary)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _cite(record: Evidence) -> str:
    return f" ({record.source_url})" if record.source_url else ""


def _lobbying(evidence: list[Evidence]) -> tuple[str, str]:
    """Return the record line and the finding on the lobbying practice."""
    record = _first(evidence, EvidenceSource.LOBBY_MAP)
    band = str(record.raw_data.get("performance_band") or "").strip() if record else ""
    if record is None or not band:
        return "No LobbyMap rating for this company.", "LobbyMap has no rating for the company"
    year = record.raw_data.get("year")
    when = f" ({year})" if year else ""
    if band.lower() in _OBSTRUCTIVE_BANDS:
        line = f"LobbyMap band {band}{when}, within LobbyMap's obstructive range, D and below (a score below 50%){_cite(record)}."
        return (
            line,
            f"LobbyMap rates its climate policy engagement {band}, within its obstructive range",
        )
    line = f"LobbyMap band {band}{when}, outside LobbyMap's obstructive range, D and below (a score below 50%){_cite(record)}."
    return (
        line,
        f"LobbyMap rates its climate policy engagement {band}, outside its obstructive range",
    )


def _fossil_supply(evidence: list[Evidence]) -> tuple[str, str]:
    """Return the record line and the finding on new fossil fuel supply."""
    lines: list[str] = []
    expanding = False

    for source, upstream_key, power_key, values, name in (
        (
            EvidenceSource.GOGEL,
            "upstream_expansion",
            "lng_expansion",
            _GOGEL_EXPANDING,
            "Global Oil and Gas Exit List",
        ),
        (
            EvidenceSource.COAL_EXIT,
            "mining_expansion",
            "power_expansion",
            _GCEL_EXPANDING,
            "Global Coal Exit List",
        ),
    ):
        record = _first(evidence, source)
        if record is None:
            continue
        first = str(record.raw_data.get(upstream_key) or "").lower().strip()
        second = str(record.raw_data.get(power_key) or "").lower().strip()
        if first in values or second in values:
            expanding = True
            lines.append(f"{name}: listed as expanding{_cite(record)}.")
        else:
            lines.append(f"{name}: listed, with no expansion recorded{_cite(record)}.")

    for source, field, name, noun in _TRACKERS:
        record = _first(evidence, source)
        count = record.raw_data.get(field) if record else None
        if record is not None and isinstance(count, int) and count > 0:
            expanding = True
            lines.append(f"{name}: {count} {noun}{_cite(record)}.")

    if not lines:
        line = "Not listed in the fossil fuel exit lists or in development in the asset trackers."
        return (
            line,
            "the fossil fuel exit lists and asset trackers do not list it as expanding supply",
        )
    if expanding:
        return " ".join(lines), "the exit lists or asset trackers record new fossil fuel supply"
    return " ".join(lines), "the exit lists record no expansion"


def _emissions(evidence: list[Evidence]) -> str:
    records = [e for e in evidence if e.source == EvidenceSource.EU_ETS]
    if not records:
        return "No EU ETS installations mapped for this assessment."
    histories: list[dict[int, float]] = []
    for record in records:
        history: dict[int, float] = {}
        for row in record.raw_data.get("verified_emissions") or []:
            year, value = row.get("year"), row.get("verifiedEmissions")
            if isinstance(year, int) and isinstance(value, int | float):
                history[year] = float(value)
        if history:
            histories.append(history)
    if not histories:
        return f"EU ETS: {len(records)} mapped installation(s), no verified emissions read."
    # Only years in which every mapped installation reported, so that an
    # installation joining the scheme does not read as a change in emissions.
    common = sorted(set.intersection(*(set(h) for h in histories)))[-3:]
    if not common:
        return f"EU ETS: {len(histories)} mapped installation(s) with no year in common."
    totals = [
        f"{sum(h[year] for h in histories) / 1e6:,.2f} Mt CO2e in {year}"
        for year in reversed(common)
    ]
    return (
        f"EU ETS verified emissions for {len(histories)} mapped installation(s): "
        f"{'; '.join(totals)}."
    )


def _targets(evidence: list[Evidence]) -> str:
    record = _first(evidence, EvidenceSource.SBTI)
    if record is None:
        return "No SBTi record for this company."
    status = record.raw_data.get("status") or "unknown"
    temperature = record.raw_data.get("temp_classification") or "not classified"
    net_zero = record.raw_data.get("net_zero_status") or "none"
    return f"SBTi: status {status}, temperature classification {temperature}, net-zero target {net_zero}."


def _investors(evidence: list[Evidence]) -> str:
    lines = []
    ca100 = _first(evidence, EvidenceSource.CA100)
    if ca100 is not None:
        lines.append(
            f"Climate Action 100+: Net Zero Ambition {ca100.raw_data.get('nz_ambition') or 'not assessed'}, "
            f"capex alignment {ca100.raw_data.get('capex_alignment') or 'not assessed'}."
        )
    tpi = _first(evidence, EvidenceSource.TPI)
    if tpi is not None:
        raw = tpi.raw_data
        assessed = raw.get("cp_assessed") or raw.get("mq_assessed")
        when = f", assessed {assessed}" if assessed else ""
        lines.append(
            f"TPI ({raw.get('sector')}{when}): Management Quality Level {raw.get('mq_level')} "
            f"({raw.get('mq_label')}); carbon performance "
            f"{raw.get('cp_alignment_2025') or 'not assessed'} for 2025, "
            f"{raw.get('cp_alignment_2035') or 'not assessed'} for 2035 and "
            f"{raw.get('cp_alignment_2050') or 'not assessed'} for 2050."
        )
    return " ".join(lines) or "No Climate Action 100+ or TPI assessment."


_FINDINGS = frozenset({"BANNED", "CONFIRMED_MISLEADING", "FINED"})

_NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _number(n: int) -> str:
    return _NUMBERS[n] if n < len(_NUMBERS) else str(n)


def _track_record(evidence: list[Evidence]) -> str:
    """Return the track record point: a rating, then every enforcement record.

    The rating counts findings against the company's environmental marketing,
    meaning upheld complaints, findings of a breach and fines, and how recent
    they are. Commitments, warnings, open cases, complaints that were not
    upheld and annulled decisions are listed but are not findings.
    """
    records = [e for e in evidence if e.source == EvidenceSource.ENFORCEMENT]
    if not records:
        return "**Track record: no enforcement records.**"

    findings = [e for e in records if e.raw_data.get("ruling_type") in _FINDINGS]
    recent = [e for e in findings if is_recent_finding(e)]
    counted = f"{_number(len(findings))} {'finding' if len(findings) == 1 else 'findings'}"
    if not findings:
        rating = "no findings against its environmental marketing"
    elif len(recent) == len(findings):
        rating = f"{counted} against its environmental marketing from the last five years"
    elif recent:
        rating = (
            f"{counted} against its environmental marketing, "
            f"{_number(len(recent))} of them from the last five years"
        )
    else:
        rating = f"{counted} against its environmental marketing, more than five years old"

    entries = []
    for record in sorted(
        records, key=lambda e: str(e.raw_data.get("decision_date", "")), reverse=True
    ):
        outcome = _OUTCOMES.get(str(record.raw_data.get("ruling_type")), "outcome not recorded")
        entries.append(
            f"{record.raw_data.get('authority')} {record.raw_data.get('case_reference')} "
            f"({record.raw_data.get('decision_date')}): {outcome}{_cite(record)}"
        )
    return f"**Track record: {rating}.** {'; '.join(entries)}."


def render_company_record(evidence: Iterable[Evidence]) -> str:
    """Render the Company Record section of a company assessment.

    Args:
        evidence: The verification evidence from every claim in the run.

    Returns:
        The section body in Markdown.
    """
    records = _unique(evidence)
    lobbying_line, lobbying_finding = _lobbying(records)
    fossil_line, fossil_finding = _fossil_supply(records)

    lines = [
        "Records about the company as a whole, set beside its claims.",
        "",
        "**Integrity of a climate pledge.** The UN High-Level Expert Group on the Net Zero "
        "Emissions Commitments of Non-State Entities names two practices that a credible "
        f'pledge rules out (Integrity Matters, 2022, p. 7; {HLEG_URL}): "{HLEG_FOSSIL_SUPPLY}" '
        f'"{HLEG_LOBBYING}" On the first, {fossil_finding}. On the second, {lobbying_finding}.',
        "",
        _track_record(records),
        "",
        f"- **Lobbying:** {lobbying_line}",
        f"- **New fossil fuel supply:** {fossil_line}",
        f"- **Verified emissions:** {_emissions(records)}",
        f"- **Targets:** {_targets(records)}",
        f"- **Investor assessments:** {_investors(records)}",
    ]
    return "\n".join(lines)
