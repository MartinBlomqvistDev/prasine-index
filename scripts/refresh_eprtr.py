"""Download the EEA E-PRTR (European Pollutant Release and Transfer Register) dataset.

Run this script whenever you want fresh E-PRTR data:

    python scripts/refresh_eprtr.py

The EEA publishes the complete IED/E-PRTR bulk dataset as a free ZIP download from
the EEA SDI geospatial data catalogue. No account is required.

The "User friendly .csv files.zip" is downloaded, inspected, and the pollutant
releases table is extracted to data/eprtr_releases.csv.

Current version: 16.0 (February 2026), covering E-PRTR data 2007-2024.

To find newer versions:
  1. Go to https://sdi.eea.europa.eu/catalogue/srv/eng/catalog.search#/metadata/9405f714-8015-4b5b-a63c-280b82861b3d
  2. Click the latest "ver. X.0 (Tabular data)" child record
  3. Use the GeoNetwork attachments API to find the new UUID and ZIP URL:
     https://sdi.eea.europa.eu/catalogue/srv/api/records/{UUID}/attachments

The file is saved to data/eprtr_releases.csv. Run refresh_cache() from ingest.eprtr
to reload without restarting.

Sources:
  https://sdi.eea.europa.eu/catalogue/srv/eng/catalog.search#/metadata/9405f714-8015-4b5b-a63c-280b82861b3d
  https://industry.eea.europa.eu/
"""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "eprtr_releases.csv"

# EEA SDI catalogue attachment URL for IED/E-PRTR ver. 16.0 (February 2026).
# UUID: 657ac3cb-affa-4295-a4a9-27b4f539adab
# This ZIP contains the "User friendly .csv files" — multiple tables as flat CSVs.
# The pollutant releases table (the one we need) has columns:
#   FacilityReport_FacilityName, FacilityReport_ParentCompanyName,
#   FacilityReport_ReportingYear, PollutantRelease_PollutantName,
#   PollutantRelease_TotalPollutantQuantityKg, PollutantRelease_MediumCode,
#   FacilityReport_CountryCode
_EPRTR_ZIP_URL = (
    "https://sdi.eea.europa.eu/catalogue/api/records/"
    "657ac3cb-affa-4295-a4a9-27b4f539adab/attachments/User%20friendly%20.csv%20files.zip"
)

# Column names that must appear in the target CSV for it to be the pollutant releases table.
_REQUIRED_COLS = frozenset(
    {
        "PollutantRelease_PollutantName",
        "PollutantRelease_TotalPollutantQuantityKg",
        "FacilityReport_ReportingYear",
    }
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count: int | str = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing file: {_DEST} ({size_kb} KB, {row_count} rows)")
    else:
        print(f"No file found at: {_DEST}")


def _find_releases_csv(zf: zipfile.ZipFile) -> str | None:
    """Return the name of the pollutant releases CSV inside the ZIP, or None."""
    candidates = [n for n in zf.namelist() if n.lower().endswith(".csv")]

    # Prefer files with "pollutant" or "release" in the name
    for name in sorted(candidates):
        if "pollutant" in name.lower() or "release" in name.lower():
            with zf.open(name) as f:
                header = f.readline().decode("utf-8-sig").strip()
            cols = set(header.split(","))
            if _REQUIRED_COLS.issubset(cols):
                return name

    # Fallback: check all CSVs for required columns
    for name in sorted(candidates):
        with zf.open(name) as f:
            header = f.readline().decode("utf-8-sig").strip()
        cols = set(header.split(","))
        if _REQUIRED_COLS.issubset(cols):
            return name

    return None


def download_eprtr() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading EEA IED/E-PRTR user-friendly CSV package...")
    print(f"  URL: {_EPRTR_ZIP_URL}")
    print(f"  Destination: {_DEST}")
    print("  (Note: ZIP is ~141 MB — download may take a minute)")

    req = urllib.request.Request(
        _EPRTR_ZIP_URL,
        headers={
            "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
            "Accept": "application/zip,*/*",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            zip_data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code} — {exc.reason}")
        print_manual_instructions()
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\nURL error: {exc.reason}")
        print_manual_instructions()
        sys.exit(1)

    if b"<html" in zip_data[:200].lower():
        print("\nReceived HTML — URL may have changed.")
        print_manual_instructions()
        sys.exit(1)

    print(f"  Downloaded {len(zip_data) // 1024 // 1024} MB")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_data))
    except zipfile.BadZipFile:
        print("\nDownloaded file is not a valid ZIP.")
        print_manual_instructions()
        sys.exit(1)

    csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    print(f"  ZIP contains {len(csv_files)} CSV file(s): {', '.join(csv_files)}")

    target = _find_releases_csv(zf)
    if target is None:
        print("\nCould not find a pollutant releases CSV in the ZIP.")
        print(f"Available CSVs: {csv_files}")
        print_manual_instructions()
        sys.exit(1)

    print(f"  Using: {target}")
    csv_bytes = zf.read(target)
    _DEST.write_bytes(csv_bytes)

    size_kb = len(csv_bytes) // 1024
    try:
        lines = csv_bytes.decode("utf-8-sig").splitlines()
        row_count = len(lines) - 1
        print(f"  Extracted {size_kb} KB, {row_count} rows -> {_DEST}")
        if lines:
            print(f"  Columns: {lines[0][:120]}...")
    except UnicodeDecodeError:
        print(f"  Extracted {size_kb} KB -> {_DEST}")

    print("Done. Run ingest.eprtr.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    print()
    print("Manual download steps:")
    print(
        "  1. Go to https://sdi.eea.europa.eu/catalogue/srv/eng/catalog.search"
        "#/metadata/9405f714-8015-4b5b-a63c-280b82861b3d"
    )
    print("  2. Click the latest 'ver. X.0 ... (Tabular data)' child record")
    print("  3. Download 'User friendly .csv files.zip'")
    print("  4. Extract the CSV containing 'PollutantRelease_PollutantName' column")
    print(f"  5. Save to: {_DEST}")
    print()
    print("Alternative — find the ZIP URL via GeoNetwork API:")
    print("  curl https://sdi.eea.europa.eu/catalogue/srv/api/records/{UUID}/attachments")


if __name__ == "__main__":
    check_existing()
    download_eprtr()
