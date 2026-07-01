"""Recompute top-3 aggregate scores from stored per-claim report files.

No API calls. Reads per-claim markdown files, applies the top-3 severity-weighted
formula, and rewrites the aggregate header in each company's main report file.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "docs" / "reports"
TOP_K = 3

COMPANIES = [
    "ryanair-holdings-plc",
    "bp-plc",
    "glencore-plc",
    "enel-spa",
    "ikea-group",
    "h-m-group",
]

SEVERITY = {
    "SUBSTANTIATED_CLAIM": 0,
    "UNVERIFIABLE_CLAIM": 1,
    "MISLEADING_CLAIM": 2,
    "LIKELY_GREENWASHING": 3,
    "CONFIRMED_GREENWASHING": 4,
}


@dataclass
class ClaimData:
    score: float
    score_low: float
    score_high: float
    confidence: float
    verdict: str


def normalise_verdict(raw: str) -> str:
    """Normalise verdict strings to UNDERSCORE_FORMAT regardless of source format."""
    return raw.strip().upper().replace(" ", "_")


def parse_claim_file(path: Path) -> ClaimData | None:
    """Extract score, range, confidence, verdict from a per-claim report file."""
    text = path.read_text(encoding="utf-8")
    # Line format: **Verdict: X** | Score: N/100 (range: A–B) | Confidence: C%
    m = re.search(
        r"\*\*Verdict: ([^*]+)\*\*.*?Score: ([\d.]+)/100 \(range: (\d+)\D+(\d+)\).*?Confidence: (\d+)%",
        text,
    )
    if not m:
        return None
    return ClaimData(
        verdict=normalise_verdict(m.group(1)),
        score=float(m.group(2)),
        score_low=float(m.group(3)),
        score_high=float(m.group(4)),
        confidence=float(m.group(5)) / 100.0,
    )


def weighted_agg(claims: list[ClaimData]) -> tuple[float, float, float, float]:
    weights = [c.confidence * c.score for c in claims]
    total = sum(weights)
    if total == 0:
        n = len(claims)
        return (
            sum(c.score for c in claims) / n,
            sum(c.score_low for c in claims) / n,
            sum(c.score_high for c in claims) / n,
            0.0,
        )
    score = sum(c.score * w for c, w in zip(claims, weights, strict=True)) / total
    low = sum(c.score_low * w for c, w in zip(claims, weights, strict=True)) / total
    high = sum(c.score_high * w for c, w in zip(claims, weights, strict=True)) / total
    conf = sum(c.confidence * w for c, w in zip(claims, weights, strict=True)) / total
    return score, low, high, conf


def recompute(slug: str) -> None:
    main_path = REPORTS_DIR / f"{slug}.md"
    if not main_path.exists():
        print(f"  SKIP  {slug} — no main report file")
        return

    # Collect per-claim files
    claim_files = sorted(REPORTS_DIR.glob(f"{slug}-[0-9]*.md"))
    if not claim_files:
        print(f"  SKIP  {slug} — no per-claim files")
        return

    claims: list[ClaimData] = []
    for f in claim_files:
        c = parse_claim_file(f)
        if c:
            claims.append(c)
        else:
            print(f"  WARN  could not parse {f.name}")

    if not claims:
        print(f"  SKIP  {slug} — no parseable claims")
        return

    # Top-K by score
    top_k = sorted(claims, key=lambda c: c.score, reverse=True)[:TOP_K]
    agg_score, agg_low, agg_high, agg_conf = weighted_agg(top_k)

    # Dominant verdict from ALL claims
    dominant = max(claims, key=lambda c: SEVERITY.get(c.verdict, 0)).verdict

    agg_score_r = round(agg_score)
    agg_low_r = round(agg_low)
    agg_high_r = round(agg_high)
    agg_conf_r = round(agg_conf * 100)
    n = len(claims)
    k = len(top_k)

    print(
        f"  {slug}: {n} claims, top-{k} => "
        f"{agg_score_r}/100 ({agg_low_r}-{agg_high_r}), "
        f"conf {agg_conf_r}%, verdict {dominant}"
    )

    # Rewrite the aggregate header block in the main report file.
    md = main_path.read_text(encoding="utf-8")

    md = re.sub(
        r"\*\*Overall Score: \d+/100\*\*[^\n]*",
        f"**Overall Score: {agg_score_r}/100** (top-{k} severity-weighted across {n} claims)",
        md,
    )
    md = re.sub(
        r"\*\*Score range:\*\* [^\n]+",
        f"**Score range:** {agg_low_r}–{agg_high_r}",
        md,
    )
    md = re.sub(
        r"\*\*Verdict:\*\* [^\n]+",
        f"**Verdict:** {dominant}",
        md,
    )
    md = re.sub(
        r"\*\*Confidence:\*\* \d+%",
        f"**Confidence:** {agg_conf_r}%",
        md,
    )

    main_path.write_text(md, encoding="utf-8")


def main() -> None:
    slugs = sys.argv[1:] or COMPANIES
    print(f"Recomputing top-{TOP_K} aggregates for {len(slugs)} companies...\n")
    for slug in slugs:
        recompute(slug)
    print("\nDone. Review docs/reports/*.md and commit.")


if __name__ == "__main__":
    main()
