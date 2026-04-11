"""Download the EEA E-PRTR (European Pollutant Release and Transfer Register) dataset.

Run this script whenever you want fresh E-PRTR data:

    python scripts/refresh_eprtr.py

The EEA publishes the complete E-PRTR bulk dataset as a free CSV download from
the European Industrial Emissions Portal. No account is required.

The file is saved to data/eprtr_releases.csv. The pipeline reloads automatically
on next run. Run refresh_cache() from ingest.eprtr to reload without restarting.

Sources:
  https://industry.eea.europa.eu/
  https://www.eea.europa.eu/data-and-maps/data/industrial-reporting-under-the-industrial-7
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "eprtr_releases.csv"

# EEA E-PRTR bulk CSV download URL. The EEA hosts the industrial emissions portal
# at industry.eea.europa.eu with downloadable CSV exports per pollutant or facility.
# The exact URL below targets the full pollutant releases CSV (all facilities, all years).
# If this URL changes, check: https://industry.eea.europa.eu/ → Data Downloads
_EPRTR_CSV_URL = "https://industry.eea.europa.eu/download?format=csv"

# Alternative: EEA Datahub direct download (may require format adjustment)
_EPRTR_DATAHUB_URL = (
    "https://www.eea.europa.eu/data-and-maps/data/industrial-reporting-under-the-industrial-7/"
    "eprtr-data/eprtr-data/at_download/file"
)


def download_eprtr_csv() -> None:
    """Attempt to download the E-PRTR bulk CSV from the EEA industrial portal."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    urls_to_try = [_EPRTR_CSV_URL, _EPRTR_DATAHUB_URL]

    for url in urls_to_try:
        print(f"Trying: {url}")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
                "Accept": "text/csv,application/csv,*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()

            if b"<html" in data[:200].lower():
                print(f"  Received HTML (login page?) — skipping {url}")
                continue

            _DEST.write_bytes(data)
            size_kb = len(data) // 1024
            print(f"  Downloaded {size_kb} KB -> {_DEST}")

            try:
                lines = data.decode("utf-8-sig").splitlines()
                print(f"  Rows: {len(lines) - 1} release records (excluding header)")
                if lines:
                    print(f"  Columns: {lines[0][:120]}...")
            except UnicodeDecodeError:
                pass

            print("Done. Run ingest.eprtr.refresh_cache() or restart the API to reload.")
            return

        except urllib.error.HTTPError as exc:
            print(f"  HTTP {exc.code} — {exc.reason}")
        except urllib.error.URLError as exc:
            print(f"  URL error: {exc.reason}")

    print()
    print("Automatic download failed. Manual download steps:")
    print("  1. Go to https://industry.eea.europa.eu/")
    print("  2. Navigate to Data Downloads or use the Facility/Pollutant search")
    print("  3. Export all facilities, all pollutants, all years as CSV")
    print(f"  4. Save to: {_DEST}")
    print()
    print("Alternative (EEA Datahub):")
    print(
        "  https://www.eea.europa.eu/data-and-maps/data/industrial-reporting-under-the-industrial-7"
    )
    print("  Download: 'EPRTR data' -> CSV format")
    sys.exit(1)


if __name__ == "__main__":
    download_eprtr_csv()
