"""Export a Prasine Index report Markdown file to a styled PDF.

Usage:
    python scripts/export_pdf.py docs/reports/ryanair-holdings-plc.md
    python scripts/export_pdf.py docs/reports/ryanair-holdings-plc.md -o out/ryanair.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pdf_export import report_markdown_to_pdf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a Prasine Index report to PDF."
    )
    parser.add_argument("report", type=Path, help="Path to the .md report file.")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output PDF path. Defaults to <report>.pdf in the same directory.",
    )
    args = parser.parse_args()

    if not args.report.exists():
        print(f"Error: {args.report} not found.", file=sys.stderr)
        sys.exit(1)

    dest = args.output or args.report.with_suffix(".pdf")
    report_markdown_to_pdf(args.report, dest)
    print(f"PDF written to {dest}")


if __name__ == "__main__":
    main()
