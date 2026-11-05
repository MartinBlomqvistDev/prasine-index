"""Read the Transition Pathway Initiative's current assessments of named companies.

TPI publishes no bulk download of its company data. Each company page on
transitionpathwayinitiative.org is rendered on the server and carries the
company's assessments as structured data: every Management Quality assessment
(level, star, assessment and publication dates, methodology version) and every
Carbon Performance assessment (date, sector, alignment by year). This script reads
those pages with the index's own, identified user agent and writes the latest
assessment of each kind to data/tpi_companies.csv, with the date it was read.

Usage:
    python scripts/refresh_tpi.py "Ryanair Holdings plc=ryanair" "BP plc=bp"
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

import httpx

_DATA = Path(__file__).parent.parent / "data"
_BASE = "https://www.transitionpathwayinitiative.org/corporates/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
        "+https://github.com/MartinBlomqvistDev/prasine-index)"
    ),
}
_COLUMNS = [
    "Company Name",
    "Geography",
    "Sector",
    "ISIN",
    "Level",
    "MQ Assessment Date",
    "MQ Publication Date",
    "MQ Methodology Version",
    "CP Assessment Date",
    "Carbon Performance Alignment 2030",
    "Carbon Performance Alignment 2035",
    "Carbon Performance Alignment 2050",
    "Retrieved",
    "Source URL",
]

_MQ = re.compile(
    r'"title":"Company MQ Assessment - [^"]*","assessmentDate":"(?P<date>[^"]+)",'
    r'"publicationDate":"(?P<published>[^"]*)","methodologyVersion":(?P<version>\d+),'
    r'"fiscalYear":"[^"]*","companyName":"[^"]*","level":(?P<level>[\d.]+),'
    r'"levelStar":(?P<star>true|false)'
)
_CP = re.compile(
    r'"title":"Company CP Assessment - [^"]* - [^"]* - (?P<sector>[^"]+)",'
    r'"assessmentDate":"(?P<date>[^"]+)"'
)
_ALIGNMENTS = re.compile(r'"alignments":\[(?P<items>[^\]]*)\]')
_ITEM = re.compile(r'\{"value":(?:"(?P<value>[^"]*)"|null),"year":(?P<year>\d{4})\}')


def _field(html: str, pattern: str) -> str:
    found = re.search(pattern, html)
    return found.group(1) if found else ""


def _day(iso: str) -> str:
    """Write an ISO timestamp as dd/mm/yyyy, the form the TPI loader reads."""
    return dt.date.fromisoformat(iso[:10]).strftime("%d/%m/%Y") if iso else ""


def read_company(slug: str) -> dict[str, str]:
    """Return the latest Management Quality and Carbon Performance assessment on one page.

    Args:
        slug: The company's address on TPI, e.g. "orsted" or "glencore-diversified-mining".

    Returns:
        One CSV row, keyed by the column names.

    Raises:
        SystemExit: If the page cannot be read or carries no assessment.
    """
    url = _BASE + slug
    response = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
    if response.status_code != 200:
        raise SystemExit(f"{url}: HTTP {response.status_code}")
    html = response.text

    mq = max(_MQ.finditer(html), key=lambda m: m.group("date"), default=None)
    cps = list(_CP.finditer(html))
    sector = _field(html, r'"mappedEntry":\{[^{]*?"sector":\{"title":"([^"]+)"')
    if not sector:
        sector = _field(html, r'"sector":\{"title":"([^"]+)"')
    same_sector = [m for m in cps if m.group("sector") == sector] or cps
    cp = max(same_sector, key=lambda m: m.group("date"), default=None)
    if mq is None and cp is None:
        raise SystemExit(f"{url}: no assessment found on the page")

    alignments: dict[str, str] = {}
    if cp is not None:
        block = _ALIGNMENTS.search(html, cp.end())
        if block:
            for item in _ITEM.finditer(block.group("items")):
                alignments[item.group("year")] = item.group("value") or ""

    level = ""
    if mq is not None:
        number = mq.group("level").removesuffix(".0")
        level = f"{number}STAR" if mq.group("star") == "true" else number

    return {
        "Company Name": _field(html, r'"mappedEntry":\{"meta":\{"pageTitle":"([^"]+)"'),
        "Geography": _field(html, r'"geography":"([^"]+)"'),
        "Sector": sector,
        "ISIN": _field(html, r'"isin":"([^"]*)"'),
        "Level": level,
        "MQ Assessment Date": _day(mq.group("date")) if mq else "",
        "MQ Publication Date": _day(mq.group("published")) if mq else "",
        "MQ Methodology Version": mq.group("version") if mq else "",
        "CP Assessment Date": _day(cp.group("date")) if cp else "",
        "Carbon Performance Alignment 2030": alignments.get("2030", ""),
        "Carbon Performance Alignment 2035": alignments.get("2035", ""),
        "Carbon Performance Alignment 2050": alignments.get("2050", ""),
        "Retrieved": dt.date.today().isoformat(),
        "Source URL": url,
    }


def main(pairs: list[str]) -> int:
    rows = []
    for pair in pairs:
        name, _, slug = pair.partition("=")
        row = read_company(slug.strip())
        rows.append(row)
        print(
            f"{name.strip():24} -> {row['Company Name']} ({row['Sector']}): MQ {row['Level']} "
            f"assessed {row['MQ Assessment Date']}; CP {row['CP Assessment Date']}: "
            f"{row['Carbon Performance Alignment 2030']} / "
            f"{row['Carbon Performance Alignment 2035']} / "
            f"{row['Carbon Performance Alignment 2050']}"
        )
    out = _DATA / "tpi_companies.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} companies written to {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("companies", nargs="+", help='"Company name=TPI page slug"')
    sys.exit(main(parser.parse_args().companies))
