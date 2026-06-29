"""Download the LobbyMap Company Climate Policy Engagement dataset.

Run this script whenever you want fresh LobbyMap data:

    python scripts/refresh_lobbymap.py

LobbyMap publishes annual company-level climate lobbying scores (A+ to F)
at lobbymap.org. The bulk company database is available as a free download
from their website — no account required.

The file is saved to data/lobbymap_companies.csv. The pipeline reloads
automatically on next run. Run refresh_cache() from ingest.lobby_map to
reload without restarting.

Sources:
  https://lobbymap.org/
  https://lobbymap.org/report (annual company database releases)
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "lobbymap_companies.csv"

# LobbyMap company database CSV download URL.
# InfluenceMap rebranded to lobbymap.org in 2025. The bulk CSV is no longer
# at a stable public URL — it may require a free account at lobbymap.org.
# If this 404s, see print_manual_instructions() below.
_LM_CSV_URL = "https://lobbymap.org/site/data/000/017/InfluenceMap_Company_Scores.csv"


def check_existing() -> None:
    """Report on the current state of the local LobbyMap CSV."""
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        row_count: int | str
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing LobbyMap CSV: {_DEST} ({size_kb} KB, {row_count} rows)")
    else:
        print(f"No LobbyMap CSV found at: {_DEST}")


def download_lobbymap_csv() -> None:
    """Attempt to download the LobbyMap bulk company scores CSV."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading LobbyMap Company Scores CSV...")
    print(f"  URL: {_LM_CSV_URL}")
    print(f"  Destination: {_DEST}")

    req = urllib.request.Request(
        _LM_CSV_URL,
        headers={
            "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
            "Accept": "text/csv,application/csv,*/*",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code} — {exc.reason}")
        print_manual_instructions()
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\nURL error: {exc.reason}")
        print_manual_instructions()
        sys.exit(1)

    if b"<html" in data[:200].lower():
        print("\nReceived HTML — the URL may have changed or requires authentication.")
        print_manual_instructions()
        sys.exit(1)

    _DEST.write_bytes(data)
    size_kb = len(data) // 1024
    print(f"  Downloaded {size_kb} KB -> {_DEST}")

    try:
        lines = data.decode("utf-8-sig").splitlines()
        print(f"  Rows: {len(lines) - 1} companies (excluding header)")
        if lines:
            print(f"  Columns: {lines[0]}")
    except UnicodeDecodeError:
        pass

    print("Done. Run ingest.lobby_map.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    """Print manual download instructions."""
    print()
    print("Manual download steps:")
    print("  1. Go to https://lobbymap.org/LobbyMapScores")
    print("  2. Create a free account if required, then log in")
    print("  3. Look for a bulk data download / export option")
    print(f"  4. Save the CSV to: {_DEST}")
    print()
    print("Expected columns: Organization, Performance Band, Sector, Engagement Intensity")
    print("The ingest handles column name variants across vintages.")


if __name__ == "__main__":
    check_existing()
    download_lobbymap_csv()
