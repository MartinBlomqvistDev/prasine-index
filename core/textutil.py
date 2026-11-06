"""Shared HTML-to-plain-text extraction.

Used by the pipeline's page fetcher and the Discovery Agent so both paths
feed the same clean text to the Extraction Agent. Lives in its own module
because pipeline.py imports the Discovery Agent, a shared utility here
avoids a circular import.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

__all__ = ["final_counters", "html_to_text"]

_SKIP_TAGS = frozenset(
    {"script", "style", "nav", "footer", "header", "noscript", "iframe", "aside", "form"}
)

# An animated counter shows a starting number and keeps its real value in data-final.
_COUNTER = re.compile(
    r"<(\w+)([^>]*?)\sdata-final=([\"'])([^\"']*)\3([^>]*)>[^<]*</\1>", re.IGNORECASE
)


def final_counters(html: str) -> str:
    """Put each animated counter's final value in place of its starting number.

    Args:
        html: Raw HTML string.

    Returns:
        The HTML with the text of every element that has a data-final value replaced
        by that value.
    """
    return _COUNTER.sub(lambda m: f"<{m[1]}{m[2]}{m[5]}>{m[4]}</{m[1]}>", html)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts)).strip()


def html_to_text(html: str) -> str:
    """Extract readable plain text from an HTML document.

    Skips script/style/navigation/footer content and collapses excess
    blank lines. Safe on malformed HTML; the stdlib parser is tolerant.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text with one line per text node.
    """
    extractor = _TextExtractor()
    extractor.feed(final_counters(html))
    return extractor.get_text()
