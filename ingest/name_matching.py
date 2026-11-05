"""Whole-word company name matching shared by the ingest modules.

The ingest modules match a company name against the names in open datasets
after normalising both. A plain substring test also matches inside words:
"enel" is a substring of "genel energy", which credited Enel with Genel
Energy's oil fields. Matching on word boundaries keeps the useful partial
matches ("ryanair" in "ryanair dac") without matching inside another word.
"""

from __future__ import annotations

import re

__all__ = ["contains_name", "names_overlap"]


def contains_name(haystack: str, needle: str) -> bool:
    """Return True if ``needle`` occurs in ``haystack`` as whole words.

    Word boundaries are Unicode-aware, so letters such as "ø" or "å" count as
    part of a word and "rsted" does not match inside "ørsted". Both strings
    should already be normalised the same way.

    Args:
        haystack: The name to search in.
        needle: The name to search for. An empty needle never matches.

    Returns:
        Whether ``needle`` appears in ``haystack`` bounded by non-word
        characters or the ends of the string.
    """
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def names_overlap(first: str, second: str) -> bool:
    """Return True if either name contains the other as whole words.

    Args:
        first: One normalised name.
        second: The other normalised name.

    Returns:
        Whether one name appears within the other on word boundaries.
    """
    return contains_name(first, second) or contains_name(second, first)
