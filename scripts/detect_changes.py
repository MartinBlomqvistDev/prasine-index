"""Detect whether local data sources changed since the last assessment.

Compares file-content hashes from the stored manifest against the current
state of data/. Reports which sources changed, appeared, or disappeared.
Use as a lightweight pre-check before triggering an expensive re-run.

Usage:
    python scripts/detect_changes.py --company "Ryanair Holdings plc"
    python scripts/detect_changes.py --company "Ryanair Holdings plc" --verbose
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.data_manifest import build_manifest, load_manifest

_REPORTS_DIR = Path(__file__).parent.parent / "docs" / "reports"


def _slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect data-source changes since the last Prasine Index assessment."
    )
    parser.add_argument(
        "--company",
        required=True,
        help="Company name (must match a stored report slug)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show unchanged sources in addition to changed ones",
    )
    args = parser.parse_args()

    slug = _slug(args.company)
    manifest_path = _REPORTS_DIR / f"{slug}-manifest.json"

    stored = load_manifest(manifest_path)
    if stored is None:
        print(f"No stored manifest for '{args.company}'.")
        print(f"  Expected: {manifest_path}")
        print("  Run scripts/run_assessment.py first to establish a baseline.")
        sys.exit(1)

    print(f"Baseline : {stored.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print("Computing current hashes...")
    current = build_manifest()

    all_keys = sorted(set(stored.sources) | set(current.sources))
    changed: list[tuple[str, str, str]] = []
    appeared: list[tuple[str, str]] = []
    disappeared: list[tuple[str, str]] = []
    unchanged: list[str] = []

    for key in all_keys:
        old = stored.sources.get(key)
        new = current.sources.get(key)

        if old is None:
            appeared.append((key, new or ""))
        elif new is None:
            disappeared.append((key, old))
        elif old == new:
            unchanged.append(key)
        elif old == "not_present" and new != "not_present":
            appeared.append((key, new))
        elif old != "not_present" and new == "not_present":
            disappeared.append((key, old))
        else:
            changed.append((key, old, new))

    print()

    if changed:
        print(f"UPDATED ({len(changed)}):")
        for key, old, new in changed:
            print(f"  {key}: {old} -> {new}")

    if appeared:
        print(f"APPEARED ({len(appeared)}):")
        for key, new in appeared:
            print(f"  {key}: {new}")

    if disappeared:
        print(f"DISAPPEARED ({len(disappeared)}):")
        for key, old in disappeared:
            print(f"  {key}: was {old}")

    if not changed and not appeared and not disappeared:
        print("No changes detected. Stored assessment is current.")
        sys.exit(0)

    n = len(changed) + len(appeared) + len(disappeared)
    print(f"\n{n} source(s) changed since {stored.generated_at.strftime('%Y-%m-%d')}.")
    print("Re-run scripts/run_assessment.py to generate an updated verdict.")

    if args.verbose and unchanged:
        print(f"\nUNCHANGED ({len(unchanged)}):")
        for key in unchanged:
            print(f"  {key}")


if __name__ == "__main__":
    main()
