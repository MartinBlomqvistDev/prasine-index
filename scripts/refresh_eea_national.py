"""Download EEA national greenhouse gas emissions inventories (UNFCCC reporting).

Run this script whenever you want fresh national emissions data:

    python scripts/refresh_eea_national.py

The EEA national emissions dataset contains GHG inventory data reported by
EU member states and other UNFCCC parties to the EEA. It covers all greenhouse
gases (CO2, CH4, N2O, F-gases) across all IPCC sectors, from 1990 to the most
recent submission year.

Used to validate country-proportion claims (e.g. "our project covers X% of
Sweden's total emissions") and to provide context on national emission trends.

Data is published on the EEA Data Hub — free, no registration required.
Saves to data/eea_t_national-emissions-reported_p_2025_v03_r00/UNFCCC_v28.csv.

The data directory already contains a current copy (v03_r00, March 2025).
This script downloads a fresh copy if a newer version is available.

Sources:
  https://www.eea.europa.eu/en/datahub/datahubitem-view/3b313f97-7730-4b57-9ef4-4d4c38a82cfa
  https://sdi.eea.europa.eu/catalogue/srv/api/records/3b313f97-7730-4b57-9ef4-4d4c38a82cfa
"""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_EXPECTED_CSV = (
    _DATA_DIR
    / "eea_t_national-emissions-reported_p_2025_v03_r00"
    / "UNFCCC_v28.csv"
)

# EEA data hub bulk download URL for the national emissions dataset.
# If this URL changes, find the latest at:
#   https://www.eea.europa.eu/en/datahub/datahubitem-view/3b313f97-7730-4b57-9ef4-4d4c38a82cfa
_EEA_ZIP_URL = (
    "https://sdi.eea.europa.eu/data/3b313f97-7730-4b57-9ef4-4d4c38a82cfa"
)

_EEA_ZIP_URL_DIRECT = (
    "https://www.eea.europa.eu/en/datahub/datahubitem-view/"
    "3b313f97-7730-4b57-9ef4-4d4c38a82cfa/@@download/file/"
    "eea_t_national-emissions-reported_p_2025_v03_r00.zip"
)


def check_existing() -> None:
    if _EXPECTED_CSV.exists():
        size_kb = _EXPECTED_CSV.stat().st_size // 1024
        try:
            lines = _EXPECTED_CSV.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(
            f"Existing EEA national emissions data:\n"
            f"  {_EXPECTED_CSV}\n"
            f"  ({size_kb} KB, {row_count} rows)"
        )
    else:
        print(f"EEA national emissions CSV not found at: {_EXPECTED_CSV}")


def download_eea_national() -> None:
    """Attempt to download the EEA national emissions ZIP and extract it."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_dest = _DATA_DIR / "eea_national_emissions.zip"

    for url in (_EEA_ZIP_URL_DIRECT, _EEA_ZIP_URL):
        print(f"\nAttempting download from:\n  {url}")
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "PrasineIndex/1.0 (EU greenwashing monitor; "
                    "contact: info@prasine.index)"
                },
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()

            if len(data) < 1000:
                print(f"  Response too small ({len(data)} bytes) — skipping.")
                continue

            zip_dest.write_bytes(data)
            print(f"  Downloaded {len(data) // 1024} KB → {zip_dest}")

            # Extract ZIP
            with zipfile.ZipFile(zip_dest) as zf:
                zf.extractall(_DATA_DIR)
            zip_dest.unlink(missing_ok=True)

            if _EXPECTED_CSV.exists():
                print(f"  Extracted → {_EXPECTED_CSV}")
                return
            else:
                print(f"  Extraction done but expected CSV not found at {_EXPECTED_CSV}")
                print("  Contents extracted:", [str(p) for p in _DATA_DIR.rglob("UNFCCC*.csv")])
                return

        except Exception as exc:
            print(f"  Failed: {exc}")
            continue

    print(
        "\nAutomatic download failed. The existing data copy should still work.\n"
        "To refresh manually:\n"
        "  1. Go to: https://www.eea.europa.eu/en/datahub/datahubitem-view/"
        "3b313f97-7730-4b57-9ef4-4d4c38a82cfa\n"
        "  2. Download the ZIP\n"
        f"  3. Extract to: {_DATA_DIR}\n"
    )
    if _EXPECTED_CSV.exists():
        print("Using existing data file — not a fatal error.")
    else:
        sys.exit(1)


def main() -> None:
    print("EEA National Emissions data refresh")
    print("=" * 50)
    check_existing()
    if _EXPECTED_CSV.exists():
        print("\nExisting data found — skipping download. Use --force to re-download.")
        print("(Pass --force as argument to override)")
        import sys
        if "--force" not in sys.argv:
            return
    download_eea_national()
    print("\nDone. Re-run refresh_cache() from ingest.eea_national to reload.")


if __name__ == "__main__":
    main()
