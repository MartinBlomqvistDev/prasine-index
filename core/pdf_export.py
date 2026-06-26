"""Convert Prasine Index assessment Markdown reports to styled PDFs.

Parses the canonical report format produced by the Report Agent and renders
a print-ready PDF with a score bar, verdict header, evidence chain, and
methodology note. Uses fpdf2 — pure Python, no system-level dependencies.

Usage:
    from core.pdf_export import report_markdown_to_pdf
    report_markdown_to_pdf(Path("docs/reports/ryanair.md"), Path("out/ryanair.pdf"))
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_GREEN = (0, 100, 60)
_CONFIRMED_RED = (170, 25, 25)
_GREENWASHING_ORANGE = (185, 75, 0)
_MISLEADING_AMBER = (150, 110, 0)
_INSUFFICIENT_BLUE = (40, 90, 160)
_SUBSTANTIATED_GREEN = (0, 130, 60)
_TEXT_DARK = (30, 30, 30)
_MUTED = (110, 110, 110)
_RULE = (210, 210, 210)
_CLAIM_BG = (247, 247, 247)

_VERDICT_COLOR: dict[str, tuple[int, int, int]] = {
    "CONFIRMED_GREENWASHING": _CONFIRMED_RED,
    "LIKELY_GREENWASHING": _GREENWASHING_ORANGE,
    "MISLEADING_CLAIM": _MISLEADING_AMBER,
    "UNVERIFIABLE_CLAIM": _MISLEADING_AMBER,
    "INSUFFICIENT_EVIDENCE": _INSUFFICIENT_BLUE,
    "SUBSTANTIATED_CLAIM": _SUBSTANTIATED_GREEN,
}

_VERDICT_LABEL: dict[str, str] = {
    "CONFIRMED_GREENWASHING": "CONFIRMED GREENWASHING",
    "LIKELY_GREENWASHING": "LIKELY GREENWASHING",
    "MISLEADING_CLAIM": "MISLEADING CLAIM",
    "UNVERIFIABLE_CLAIM": "UNVERIFIABLE CLAIM",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT EVIDENCE",
    "SUBSTANTIATED_CLAIM": "SUBSTANTIATED",
}


# ---------------------------------------------------------------------------
# Parsed report structure
# ---------------------------------------------------------------------------


@dataclass
class _Evidence:
    number: int
    title: str
    body: str
    source: str


@dataclass
class _Report:
    company: str
    verdict: str
    score: int
    confidence: float
    published: str
    trace_id: str
    claim_text: str
    claim_source: str
    evidence: list[_Evidence] = field(default_factory=list)
    assessment: str = ""
    key_finding: str = ""
    data_gaps: str = ""
    methodology: str = ""


@dataclass
class _ClaimRow:
    index: int
    score: int
    verdict: str
    preview: str


@dataclass
class _AggregateHeader:
    company: str
    claim_count: int
    score: int
    score_low: int
    score_high: int
    verdict: str
    confidence: float
    claim_rows: list[_ClaimRow]


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------


def _section(text: str, heading: str) -> str:
    m = re.search(rf"### {re.escape(heading)}\n+(.*?)(?=\n---|\n### |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _parse_evidence_items(evidence_text: str) -> list[_Evidence]:
    items: list[_Evidence] = []
    chunks = re.split(r"\n(?=\*\*\d+\.)", evidence_text.strip())
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"\*\*(\d+)\. (.+?)\*\*\n?(.*)", chunk, re.S)
        if not m:
            continue
        number = int(m.group(1))
        title = m.group(2).strip()
        rest = m.group(3).strip()
        source_m = re.search(r"\*Source: (.+?)\*", rest)
        source = source_m.group(1).strip() if source_m else ""
        body = re.sub(r"\n?\*Source:.*?\*$", "", rest, flags=re.S).strip()
        items.append(_Evidence(number=number, title=title, body=body, source=source))
    return items


def _parse_aggregate_header(markdown: str) -> _AggregateHeader | None:
    """Parse the company-level aggregate block if present.

    Returns None for single-claim reports that lack the aggregate prefix.
    """
    agg_m = re.match(r"^## (.+?) — Company Assessment \((\d+) claims?\)", markdown.lstrip())
    if not agg_m:
        return None

    company = agg_m.group(1).strip()
    claim_count = int(agg_m.group(2))

    score_m = re.search(r"\*\*Overall Score: (\d+)/100\*\*", markdown)
    score = int(score_m.group(1)) if score_m else 0

    range_m = re.search(r"\*\*Score range:\*\* (\d+)[–\-](\d+)", markdown)
    score_low = int(range_m.group(1)) if range_m else score
    score_high = int(range_m.group(2)) if range_m else score

    verdict_m = re.search(r"\*\*Verdict:\*\* ([A-Z_]+)", markdown)
    verdict = verdict_m.group(1).strip() if verdict_m else ""

    conf_m = re.search(r"\*\*Confidence:\*\* (\d+)%", markdown)
    confidence = int(conf_m.group(1)) / 100 if conf_m else 0.0

    claim_rows: list[_ClaimRow] = []
    for row_m in re.finditer(r"^\| (\d+) \| (\d+)/100 \| ([A-Z_]+) \| (.+?) \|$", markdown, re.M):
        claim_rows.append(
            _ClaimRow(
                index=int(row_m.group(1)),
                score=int(row_m.group(2)),
                verdict=row_m.group(3).strip(),
                preview=row_m.group(4).strip(),
            )
        )

    return _AggregateHeader(
        company=company,
        claim_count=claim_count,
        score=score,
        score_low=score_low,
        score_high=score_high,
        verdict=verdict,
        confidence=confidence,
        claim_rows=claim_rows,
    )


def _parse(markdown: str) -> _Report:
    # For aggregate reports, the individual claim detail follows the second "---" separator.
    # Strip the aggregate preamble so the per-field regexes find the right values.
    parts = re.split(r"\n---\n", markdown, maxsplit=2)
    detail = parts[-1] if len(parts) >= 2 else markdown

    title_m = re.search(r"^## (.+?) —", detail, re.M)
    company = title_m.group(1).strip() if title_m else "Unknown Company"

    meta_m = re.search(
        r"\*\*Verdict: ([A-Z_]+)\*\*.*?Score: (\d+)/100.*?Confidence: (\d+)%", detail
    )
    verdict = meta_m.group(1) if meta_m else ""
    score = int(meta_m.group(2)) if meta_m else 0
    confidence = int(meta_m.group(3)) / 100 if meta_m else 0.0

    pub_m = re.search(r"\*Published: ([^|]+)\|.*?Trace ID: ([^\*]+)\*", detail)
    published = pub_m.group(1).strip() if pub_m else ""
    trace_id = pub_m.group(2).strip() if pub_m else ""

    claim_section = _section(detail, "The Claim")
    bq_m = re.search(r"^> (.+?)(?=\n\n|\*Source)", claim_section, re.S | re.M)
    claim_text = ""
    if bq_m:
        raw = re.sub(r"\n> ", " ", bq_m.group(1)).strip()
        claim_text = raw.strip('"').strip("“").strip("”").strip()
    source_m = re.search(r"\*Source: (.+?)\*", claim_section)
    claim_source = source_m.group(1).strip() if source_m else ""

    return _Report(
        company=company,
        verdict=verdict,
        score=score,
        confidence=confidence,
        published=published,
        trace_id=trace_id,
        claim_text=claim_text,
        claim_source=claim_source,
        evidence=_parse_evidence_items(_section(detail, "Evidence")),
        assessment=_section(detail, "Assessment"),
        key_finding=_section(detail, "Key Finding"),
        data_gaps=_section(detail, "Data Gaps"),
        methodology=_section(detail, "Methodology Note"),
    )


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------


_UNICODE_MAP = str.maketrans(
    {
        "…": "...",  # ellipsis
        "‘": "'",  # left single quote
        "’": "'",  # right single quote / apostrophe
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "–": "-",  # en dash
        "—": "--",  # em dash
        "×": "x",  # multiplication sign
        " ": " ",  # non-breaking space
        "°": " deg",  # degree sign
        "€": "EUR",  # euro sign
        "→": "->",  # right arrow
        "←": "<-",  # left arrow
        "é": "e",  # é
        "è": "e",  # è
        "ê": "e",  # ê
        "à": "a",  # à
        "â": "a",  # â
        "ö": "o",  # ö
        "ä": "a",  # ä
        "ü": "u",  # ü
        "Å": "A",  # Å
        "å": "a",  # å
    }
)


def _safe(text: str) -> str:
    """Replace characters outside Latin-1 with ASCII fallbacks for Helvetica."""
    text = text.translate(_UNICODE_MAP)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _clean(text: str) -> str:
    """Strip markdown syntax that fpdf2's markdown mode doesn't handle."""
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s?", "", line)
        if line.strip() == "---":
            continue
        lines.append(line)
    return "\n".join(lines).strip()


class _PDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*_GREEN)
        self.cell(100, 5, "PRASINE INDEX", new_x=XPos.RIGHT, new_y=YPos.TOP)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(
            0,
            5,
            "martinblomqvistdev.github.io/prasine-index",
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(0, 5, f"Page {self.page_no()}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(0, 4, "For informational purposes only. Not a legal ruling.", align="C")


def _rule(pdf: _PDF) -> None:
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def _section_heading(pdf: _PDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_GREEN)
    pdf.cell(0, 5, _safe(title.upper()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _rule(pdf)


def _render_cover(pdf: _PDF, data: _Report, agg: _AggregateHeader | None = None) -> None:
    verdict = agg.verdict if agg else data.verdict
    score = agg.score if agg else data.score
    confidence = agg.confidence if agg else data.confidence
    company = agg.company if agg else data.company
    color = _VERDICT_COLOR.get(verdict, _TEXT_DARK)
    cw = pdf.w - pdf.l_margin - pdf.r_margin

    # Company name
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_TEXT_DARK)
    pdf.multi_cell(0, 9, _safe(company), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_MUTED)
    subtitle = (
        f"Greenwashing Assessment — {agg.claim_count} claims assessed"
        if agg
        else "Greenwashing Assessment"
    )
    pdf.cell(0, 6, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Score bar
    bar_w = cw - 28
    bar_h = 9
    bar_x = pdf.l_margin
    bar_y = pdf.get_y()

    pdf.set_fill_color(*_RULE)
    pdf.rect(bar_x, bar_y, bar_w, bar_h, "F")

    filled = max(1.0, bar_w * score / 100)
    pdf.set_fill_color(*color)
    pdf.rect(bar_x, bar_y, filled, bar_h, "F")

    # Score number to the right of bar
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_TEXT_DARK)
    pdf.set_xy(bar_x + bar_w + 3, bar_y - 1)
    pdf.cell(25, bar_h + 2, f"{score}/100", new_x=XPos.LMARGIN, new_y=YPos.TOP)

    pdf.set_y(bar_y + bar_h + 3)

    # Score range (aggregate reports only)
    if agg and agg.score_low != agg.score_high:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(
            0,
            4,
            _safe(f"Range: {agg.score_low}-{agg.score_high}/100"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(1)

    # Verdict label
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*color)
    pdf.cell(0, 6, _VERDICT_LABEL.get(verdict, verdict), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Metadata
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_MUTED)
    short_trace = (data.trace_id[:8] + "...") if len(data.trace_id) > 8 else data.trace_id
    meta = _safe(
        f"Published {data.published}  |  Confidence {confidence:.0%}  |  Trace {short_trace}"
    )
    pdf.cell(0, 5, meta, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)
    _rule(pdf)


def _render_claim_table(pdf: _PDF, agg: _AggregateHeader) -> None:
    """Render the multi-claim summary table between the cover and the detail section."""
    _section_heading(pdf, "Claim Overview")

    col_w = (pdf.w - pdf.l_margin - pdf.r_margin - 28) / 2
    row_h = 5

    for row in agg.claim_rows:
        color = _VERDICT_COLOR.get(row.verdict, _TEXT_DARK)
        label = _VERDICT_LABEL.get(row.verdict, row.verdict)

        # Index + score
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_TEXT_DARK)
        pdf.cell(8, row_h, _safe(f"{row.index}."), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(20, row_h, _safe(f"{row.score}/100"), new_x=XPos.RIGHT, new_y=YPos.TOP)

        # Verdict (colour-coded)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*color)
        pdf.cell(col_w, row_h, _safe(label), new_x=XPos.RIGHT, new_y=YPos.TOP)

        # Claim preview
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_TEXT_DARK)
        preview = _safe(row.preview[:80] + "..." if len(row.preview) > 80 else row.preview)
        pdf.cell(col_w, row_h, preview, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

    pdf.ln(4)
    _rule(pdf)

    # Transition line to the detail section
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*_MUTED)
    best_idx = max(agg.claim_rows, key=lambda r: r.score).index if agg.claim_rows else 1
    pdf.cell(
        0,
        5,
        _safe(f"Detailed assessment of claim {best_idx} (highest severity) follows."),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(5)


def _render_claim(pdf: _PDF, data: _Report) -> None:
    _section_heading(pdf, "The Claim")

    pdf.set_fill_color(*_CLAIM_BG)
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(*_TEXT_DARK)
    display = _safe(f'"{data.claim_text}"') if data.claim_text else "(claim text unavailable)"
    pdf.multi_cell(0, 6, display, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    if data.claim_source:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(
            0, 4, _safe(f"Source: {data.claim_source}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
    pdf.ln(6)


def _render_evidence(pdf: _PDF, data: _Report) -> None:
    if not data.evidence:
        return
    _section_heading(pdf, "Evidence")

    for item in data.evidence:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_TEXT_DARK)
        pdf.multi_cell(
            0,
            5,
            _safe(f"{item.number}. {item.title}"),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(1)

        if item.body:
            body_clean = _safe(_clean(item.body))
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_TEXT_DARK)
            pdf.multi_cell(0, 5, body_clean, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        if item.source:
            pdf.ln(1)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(
                0,
                4,
                _safe(f"Source: {item.source}"),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        pdf.ln(4)


def _render_prose(pdf: _PDF, heading: str, text: str) -> None:
    if not text:
        return
    _section_heading(pdf, heading)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_TEXT_DARK)
    pdf.multi_cell(0, 5, _safe(_clean(text)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def report_markdown_to_pdf(source: Path, dest: Path) -> None:
    """Convert a Prasine Index Markdown report to a styled PDF.

    Handles both single-claim reports and the canonical multi-claim format
    (aggregate header + highest-severity claim detail).

    Args:
        source: Path to the .md report file produced by the Report Agent.
        dest: Output path for the PDF file (will be created or overwritten).
    """
    markdown = source.read_text(encoding="utf-8")
    agg = _parse_aggregate_header(markdown)
    data = _parse(markdown)

    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    _render_cover(pdf, data, agg)
    if agg and len(agg.claim_rows) > 1:
        _render_claim_table(pdf, agg)
    _render_claim(pdf, data)
    _render_evidence(pdf, data)
    _render_prose(pdf, "Assessment", data.assessment)
    _render_prose(pdf, "Key Finding", data.key_finding)
    if data.data_gaps:
        _render_prose(pdf, "Data Gaps", data.data_gaps)
    if data.methodology:
        _render_prose(pdf, "Methodology", data.methodology)

    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
