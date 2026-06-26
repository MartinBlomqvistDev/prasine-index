"""Build a content-hash manifest of all local bulk data files.

Records which version of each data source was active at the time of a
pipeline run, enabling verdict reconstruction and audit trail. Used by
scripts/run_assessment.py (to append the manifest to each report) and by
scripts/detect_changes.py (to diff against a later refresh).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["DataManifest", "build_manifest", "load_manifest", "manifest_to_markdown"]

_DATA_DIR = Path(__file__).parent.parent / "data"

# Glob patterns relative to _DATA_DIR, in source-name order.
# Large files are hashed too — takes ~2s per 500 MB file, acceptable at run time.
_PATTERNS: list[tuple[str, str]] = [
    ("sbti", "sbti_companies*"),
    ("lobbymap", "lobbymap_companies.csv"),
    ("ca100", "ca100_companies.csv"),
    ("eprtr", "eprtr_releases.csv"),
    ("fossil_finance", "Expansion_Company_List_*.xlsx"),
    ("gcel", "gcel_companies.csv"),
    ("gogel", "gogel_companies.csv"),
    ("tpi", "tpi_companies.csv"),
    ("eea_national", "eea_national_ghg.csv"),
    ("eu_innovation_fund", "eu_innovation_fund_projects.csv"),
    ("eu_transparency_register", "EU_Transparency register_searchExport.xlsx"),
    ("gcpt", "Global-Coal-Plant-Tracker-*.xlsx"),
    ("egt", "Europe-Gas-Tracker-*.xlsx"),
    ("goget_tracker", "Global-Oil-and-Gas-Extraction-Tracker-*.xlsx"),
    ("edgar_jrc", "JRC/EDGAR_2025_GHG_booklet_2025.xlsx"),
    ("eutl", "emissions_high_granularity.csv"),
    ("influencemap", "influencemap_companies.csv"),
]


@dataclass
class DataManifest:
    """Snapshot of local bulk data file hashes at a given point in time.

    Attributes:
        generated_at: UTC timestamp when the manifest was built.
        sources: Maps source key to SHA-256 hex digest (first 16 chars),
                 or "not_present" if the expected file was not found.
    """

    generated_at: datetime
    sources: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialise to a compact JSON string."""
        return json.dumps(
            {
                "generated_at": self.generated_at.isoformat(),
                "sources": self.sources,
            },
            indent=2,
        )


def _sha256_prefix(path: Path, prefix_len: int = 16) -> str:
    """Return the first *prefix_len* hex chars of the SHA-256 of *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:prefix_len]


def build_manifest() -> DataManifest:
    """Scan local data files and compute a SHA-256-based manifest.

    Returns:
        A :py:class:`DataManifest` with hashes for all found files.
    """
    sources: dict[str, str] = {}
    for key, pattern in _PATTERNS:
        matches = sorted(_DATA_DIR.glob(pattern))
        if not matches:
            sources[key] = "not_present"
        else:
            # If multiple versions exist (e.g. dated GEM files), take the newest.
            path = max(matches, key=lambda p: p.stat().st_mtime)
            sources[key] = _sha256_prefix(path)
    return DataManifest(generated_at=datetime.now(UTC), sources=sources)


def manifest_to_markdown(manifest: DataManifest) -> str:
    """Format the manifest as a Markdown section for inclusion in reports.

    Args:
        manifest: The manifest to format.

    Returns:
        A Markdown string starting with ``### Data Manifest``.
    """
    ts = manifest.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "### Data Manifest",
        "",
        f"*Sources active at assessment time — {ts}*",
        "",
        "| Source | SHA-256 (16 hex) |",
        "|--------|-----------------|",
    ]
    for key, sha in manifest.sources.items():
        status = f"`{sha}`" if sha != "not_present" else "*not present*"
        lines.append(f"| {key} | {status} |")
    return "\n".join(lines)


def load_manifest(path: Path) -> DataManifest | None:
    """Load a manifest previously saved as JSON.

    Args:
        path: Path to the JSON manifest file.

    Returns:
        A :py:class:`DataManifest`, or ``None`` if the file does not exist.
    """
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return DataManifest(
        generated_at=datetime.fromisoformat(raw["generated_at"]),
        sources=raw["sources"],
    )
