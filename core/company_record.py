"""The company record: what a company does, set beside what it claims.

The record lists the evidence that describes a company as a whole: its lobbying,
its fossil fuel supply, its verified emissions, its targets, investors'
assessments and enforcement decisions. Each line states what its source says,
and the record is built in code from the evidence of a run, with no model
involved.

It opens with two of the practices that the UN High-Level Expert Group on
net-zero commitments says a credible climate pledge rules out, new fossil fuel supply and
lobbying against climate policy, and states what the records show on each. It
gives no score.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise

from core.evidence_scope import (
    HLEG_FOSSIL_SUPPLY,
    HLEG_LOBBYING,
    HLEG_URL,
    is_recent_finding,
)
from ingest.ca100 import describe_indicators
from ingest.coal_exit import _EXPANDING_VALUES as _GCEL_EXPANDING
from ingest.gogel import _EXPANDING_VALUES as _GOGEL_EXPANDING
from ingest.lobby_map import _OBSTRUCTIVE_BANDS, engagement_text
from ingest.sbti import describe_targets
from models.evidence import Evidence, EvidenceSource

__all__ = ["render_company_record"]

# LobbyMap's bands from A+ to B, a score above 75%, which it describes as "broad support
# for science-aligned policy for delivering the Paris Agreement's goal".
_SUPPORTIVE_BANDS = frozenset({"a+", "a", "a-", "b+", "b"})

_OUTCOMES = {
    "BANNED": "complaint upheld",
    "CONFIRMED_MISLEADING": "decision against the marketing",
    "FINED": "fine imposed",
    "COMMITMENTS": "commitments to change practices; no finding of a breach and no fine",
    "WARNING": "guidance or warning",
    "INVESTIGATION": "case opened, no outcome recorded",
    "NOT_UPHELD": "not upheld",
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


def _assets(record: Evidence) -> str:
    """Name up to three tracker assets, with the company's share where given."""
    named = []
    for asset in (record.raw_data.get("expanding_assets") or [])[:3]:
        status = str(asset.get("status") or "").replace("-", " ")
        share = asset.get("share")
        detail = ", ".join(filter(None, (status, f"share {share}" if share else "")))
        named.append(f"{asset.get('name')} ({detail})" if detail else str(asset.get("name")))
    return f": {'; '.join(named)}" if named else ""


def _tonnes(value: float) -> str:
    """Print emissions in megatonnes from one megatonne, in tonnes below it."""
    if value >= 1_000_000:
        return f"{value / 1e6:,.2f} Mt"
    return f"{value:,.0f} t"


def _cite(record: Evidence) -> str:
    return f" ({record.source_url})" if record.source_url else ""


def _lobbying(evidence: list[Evidence]) -> tuple[str, str]:
    """Return the record line and the finding on the lobbying practice."""
    record = _first(evidence, EvidenceSource.LOBBY_MAP)
    band = str(record.raw_data.get("performance_band") or "").strip() if record else ""
    if record is None or not band:
        return "No LobbyMap rating for this company.", "LobbyMap has no rating for the company"
    year = record.raw_data.get("year")
    retrieved = record.raw_data.get("retrieved")
    when = f" ({year})" if year else f" (as of {retrieved})" if retrieved else ""
    intensity = engagement_text(record.raw_data.get("active_engagement"), subject="it")
    intensity = f" {intensity[:-1]}" if intensity else ""
    if band.lower() in _OBSTRUCTIVE_BANDS:
        line = (
            f"LobbyMap band {band}{when}, within the range it defines as obstructive "
            f"(D and below, a score under 50%).{intensity}{_cite(record)}."
        )
        return (
            line,
            f"LobbyMap rates the company's climate policy engagement {band}, within the range it "
            "defines as obstructive",
        )
    if band.lower() in _SUPPORTIVE_BANDS:
        # LobbyMap's own reading of its top bands (README_LobbyMap.txt, Performance Band).
        line = (
            f"LobbyMap band {band}{when}, within the range it describes as broad support for "
            f"science-aligned policy (A+ to B, a score above 75%).{intensity}{_cite(record)}."
        )
        return (
            line,
            f"LobbyMap rates the company's climate policy engagement {band}, within the range "
            "it describes as broad support for science-aligned policy",
        )
    line = (
        f"LobbyMap band {band}{when}, outside the range it defines as obstructive "
        f"(D and below, a score under 50%).{intensity}{_cite(record)}."
    )
    return (
        line,
        f"LobbyMap rates the company's climate policy engagement {band}, outside the range it "
        "defines as obstructive",
    )


def _fossil_supply(evidence: list[Evidence]) -> tuple[str, str]:
    """Return the record line and the finding on new fossil fuel supply."""
    lines: list[str] = []
    expanding: list[str] = []
    # New coal plants count through the expert group's recommendations for businesses.
    coal_power = False
    # Set when a list or tracker records expansion that does not count as new supply.
    not_counted = False

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
        if record.raw_data.get("lng_counted") is False and first not in values:
            not_counted = True
            lines.append(
                f"{name}: listed for LNG capacity under development that matches a proposal "
                f"more than ten years old, not counted as new supply{_cite(record)}."
            )
        elif first in values or second in values:
            expanding.append(name)
            coal_power = coal_power or (source == EvidenceSource.COAL_EXIT and second in values)
            lines.append(f"{name}: listed as expanding{_cite(record)}.")
        else:
            lines.append(f"{name}: listed, with no expansion recorded{_cite(record)}.")

    for source, field, name, noun in _TRACKERS:
        record = _first(evidence, source)
        count = record.raw_data.get(field) if record else None
        if record is not None and isinstance(count, int) and count > 0:
            expanding.append(name)
            coal_power = coal_power or source == EvidenceSource.GCPT
            plural = noun.replace("(s)", "" if count == 1 else "s")
            lines.append(f"{name}: {count} {plural}{_assets(record)}{_cite(record)}.")
        stalled = record.raw_data.get("stalled_assets") if record else None
        if record is not None and stalled:
            not_counted = True
            listed = "; ".join(
                f"{asset.get('name')} (proposed in {asset.get('proposal_year')})"
                for asset in stalled[:3]
            )
            lines.append(
                f"{name}: {len(stalled)} "
                f"{'proposal' if len(stalled) == 1 else 'proposals'} still at the proposal "
                f"stage more than ten years later, not counted as new supply: {listed}"
                f"{_cite(record)}."
            )

    if not lines:
        line = "Not listed in the fossil fuel exit lists or in development in the asset trackers."
        return (
            line,
            "neither the fossil fuel exit lists nor the asset trackers record it as expanding supply",
        )
    if expanding:
        names = (
            expanding[0]
            if len(expanding) == 1
            else f"{', '.join(expanding[:-1])} and {expanding[-1]}"
        )
        verb = "records" if len(expanding) == 1 else "record"
        coal = (
            ", counting new coal plants, which the expert group's recommendations for "
            "businesses include ending (Integrity Matters, p. 24)"
            if coal_power
            else ""
        )
        return " ".join(lines), f"the {names} {verb} new fossil fuel supply{coal}"
    if not_counted:
        return " ".join(lines), (
            "no record shows new fossil fuel supply that counts; the expansion listed "
            "matches proposals more than ten years old"
        )
    return " ".join(lines), "the exit lists record no expansion"


def _emissions(evidence: list[Evidence]) -> str:
    records = [e for e in evidence if e.source == EvidenceSource.EU_ETS]
    if not records:
        return "No EU ETS installations mapped for this assessment."
    noun = (
        "aircraft operator"
        if all(e.raw_data.get("aircraft_operator") for e in records)
        else "installation"
    )
    histories: list[tuple[str, dict[int, float]]] = []
    for record in records:
        history: dict[int, float] = {}
        for row in record.raw_data.get("verified_emissions") or []:
            year, value = row.get("year"), row.get("verifiedEmissions")
            if isinstance(year, int) and isinstance(value, int | float):
                history[year] = float(value)
        if history:
            histories.append((str(record.raw_data.get("installation_id") or ""), history))
    if not histories:
        return f"EU ETS: {_installations(len(records), noun)}, no verified emissions read."
    # Only years in which every mapped installation reported, so that an
    # installation joining the scheme does not read as a change in emissions.
    every = sorted(set.intersection(*(set(h) for _, h in histories)))
    common = every[-3:]
    if not common:
        return (
            f"EU ETS: {_installations(len(histories), noun)}, with no year in which all of them "
            "report verified emissions."
        )

    def total(year: int) -> str:
        return f"{_tonnes(sum(h[year] for _, h in histories))} CO2e in {year}"

    line = (
        f"EU ETS verified emissions for {_installations(len(histories), noun)}, those mapped to "
        f"the company by name and not necessarily all of its {noun}s: "
        f"{'; '.join(total(year) for year in reversed(common))}."
    )
    # A longer view, so that three years are not read alone.
    earlier = [year for year in every if common[-1] - 10 <= year < common[0]]
    span = [year for year in every if year >= (earlier[0] if earlier else common[0])]
    # A step of more than half in one installation's series can mean a change in what
    # it covers rather than in its emissions, so such a series is named, and it is left
    # out of the comparison across the years.
    breaks: dict[str, list[str]] = {}
    for installation, h in histories:
        for first, second in pairwise(span):
            if h[first] and (h[second] > h[first] * 1.5 or h[second] < h[first] * 0.5):
                breaks.setdefault(installation, []).append(f"between {first} and {second}")
    steady = [(installation, h) for installation, h in histories if installation not in breaks]
    if earlier and steady and len(steady) == len(histories):
        line += f" For comparison, {total(earlier[0])}."
    elif earlier and steady:
        start, end = earlier[0], common[-1]
        some = noun if len(steady) == 1 else f"{noun}s"
        line += (
            f" For comparison, the {len(steady)} {some} whose series "
            f"{'has' if len(steady) == 1 else 'have'} no step of more than half: "
            f"{_tonnes(sum(h[start] for _, h in steady))} CO2e in {start} and "
            f"{_tonnes(sum(h[end] for _, h in steady))} CO2e in {end}."
        )
    if breaks:
        line += (
            " The series change by more than half for "
            + "; ".join(f"{i} {' and '.join(steps)}" for i, steps in breaks.items())
            + ", which can reflect a change in what an installation covers."
        )
    return line


def _installations(count: int, noun: str = "installation") -> str:
    """Write a count of mapped installations, as in "1 mapped installation"."""
    return f"{count} mapped {noun}{'' if count == 1 else 's'}"


def _targets(evidence: list[Evidence]) -> str:
    record = _first(evidence, EvidenceSource.SBTI)
    if record is None:
        return "No SBTi record for this company."
    return describe_targets(record.raw_data)


def _investors(evidence: list[Evidence]) -> str:
    lines = []
    ca100 = _first(evidence, EvidenceSource.CA100)
    if ca100 is not None:
        lines.append(f"Climate Action 100+, {describe_indicators(ca100.raw_data)}")
    tpi = _first(evidence, EvidenceSource.TPI)
    if tpi is not None:
        raw = tpi.raw_data
        mq_dates = ", ".join(
            part
            for part in (
                f"assessed {raw['mq_assessed']}" if raw.get("mq_assessed") else "",
                f"published {raw['mq_published']}" if raw.get("mq_published") else "",
            )
            if part
        )
        cp_date = f" (assessed {raw['cp_assessed']})" if raw.get("cp_assessed") else ""
        level = str(raw.get("mq_level") or "")
        highest = ", the highest of TPI levels" if level == "5" else ""
        if any(raw.get(f"cp_alignment_{year}") for year in ("2030", "2035", "2050")):
            performance = (
                f"carbon performance against the {raw.get('sector')} benchmark{cp_date} "
                f"{raw.get('cp_alignment_2030') or 'not assessed'} for 2030, "
                f"{raw.get('cp_alignment_2035') or 'not assessed'} for 2035 and "
                f"{raw.get('cp_alignment_2050') or 'not assessed'} for 2050"
            )
            if raw.get("regional"):
                performance += f"; against TPI's regional benchmark ({raw['regional']})"
            if raw.get("subsectors"):
                performance += f"; against subsector benchmarks: {raw['subsectors']}"
        else:
            performance = "carbon performance not assessed by TPI"
        lines.append(
            f"TPI ({raw.get('sector')}): Management Quality Level "
            f"{level.replace('STAR', '*')} "
            f"({raw.get('mq_label')}{highest}{'; ' + mq_dates if mq_dates else ''}); "
            f"{performance}."
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
    they are, and then the records of commitments to change it. Warnings, open
    or closed cases without an outcome, complaints that were not upheld and
    annulled decisions are listed but are not findings.
    """
    records = [e for e in evidence if e.source == EvidenceSource.ENFORCEMENT]
    if not records:
        return (
            "**Track record in Prasine's list: no decisions.** The list holds decisions on "
            "environmental marketing checked against the authority's own page; it has no "
            "entry for this company and is not a complete record."
        )

    findings = [e for e in records if e.raw_data.get("ruling_type") in _FINDINGS]
    commitments = [e for e in records if e.raw_data.get("ruling_type") == "COMMITMENTS"]
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
    if commitments:
        rating += (
            f", and {_number(len(commitments))} "
            f"{'record' if len(commitments) == 1 else 'records'} of commitments to change it"
        )

    entries = []
    for record in sorted(
        records, key=lambda e: str(e.raw_data.get("decision_date", "")), reverse=True
    ):
        outcome = record.raw_data.get("outcome") or _OUTCOMES.get(
            str(record.raw_data.get("ruling_type")), "outcome not recorded"
        )
        body = f" ({record.raw_data['body']})" if record.raw_data.get("body") else ""
        entries.append(
            f"{record.raw_data.get('authority')}{body} {record.raw_data.get('case_reference')} "
            f"({record.raw_data.get('decision_date')}), {record.raw_data.get('party_as_named')}: "
            f"{outcome}{_cite(record)}"
        )
    return (
        f"**Track record in Prasine's list: {rating}.** {'; '.join(entries)}. The list holds "
        "decisions checked against the authority's own page and is not a complete record."
    )


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
        "Emissions Commitments of Non-State Entities lists practices that a credible pledge "
        f"rules out (Integrity Matters, 2022, p. 7; {HLEG_URL}). Two of them are checked here: "
        f'"{HLEG_FOSSIL_SUPPLY}" "{HLEG_LOBBYING}" On the first, {fossil_finding}. '
        f"On the second, {lobbying_finding}.",
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
