"""Run the Prasine Index pipeline against a real company claim.

Usage — fetch the page automatically (recommended):
    python scripts/run_assessment.py --company "Shell plc" \\
        --url "https://shell.com/sustainability"

Usage — provide claim text directly:
    python scripts/run_assessment.py --company "Shell plc" \\
        --claim "Shell is on track to become net-zero by 2050" \\
        --url "https://shell.com/sustainability"

Usage — refresh all data sources first (downloads fresh SBTi, InfluenceMap,
         CA100+, EUTL, E-PRTR, GCEL, Fossil Finance before running):
    python scripts/run_assessment.py --company "Shell plc" \\
        --url "https://shell.com/sustainability" --refresh-data

When --claim is omitted the pipeline fetches --url and extracts its full text.
Saves a markdown report to docs/reports/<slug>.md and prints the verdict.
Costs ~$0.05 per run on Haiku defaults.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402

from agents.extraction_agent import ExtractionInput  # noqa: E402
from core.database import get_session, init_db, teardown_db  # noqa: E402
from core.pipeline import Pipeline, PipelineConfig  # noqa: E402
from models.claim import SourceType  # noqa: E402

_REPORTS_DIR = Path(__file__).parent.parent / "docs" / "reports"
_SCRIPTS_DIR = Path(__file__).parent


def _slug(name: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _refresh_data() -> None:
    """Download fresh copies of all bulk data sources."""
    import importlib.util

    refresh_scripts = [
        "refresh_sbti.py",
        "refresh_influencemap.py",
        "refresh_ca100.py",
        "refresh_eutl.py",
        "refresh_eprtr.py",
        "refresh_gcel.py",
        "refresh_fossil_finance.py",
        "refresh_eu_innovation_fund.py",
        "refresh_gogel.py",
        "refresh_eea_national.py",
        "refresh_eu_transparency_register.py",
        "refresh_gcpt.py",
        "refresh_egt.py",
        "refresh_goget.py",
    ]

    for script_name in refresh_scripts:
        script_path = _SCRIPTS_DIR / script_name
        if not script_path.exists():
            print(f"  [skip] {script_name} not found")
            continue

        print(f"\n--- {script_name} ---")
        spec = importlib.util.spec_from_file_location("_refresh", script_path)
        if spec is None or spec.loader is None:
            print(f"  [skip] could not load {script_name}")
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            # Each refresh script exposes a main download function with a predictable name.
            for fn_name in (
                "download_sbti",
                "download_influencemap_csv",
                "download_ca100_csv",
                "main",
                "download_bocc_csv",
                "download_gcel_csv",
            ):
                fn = getattr(module, fn_name, None)
                if fn is not None:
                    fn()
                    break
        except SystemExit:
            pass  # refresh scripts call sys.exit(0) on success
        except Exception as exc:
            print(f"  [warn] {script_name} failed: {exc}")


async def _ensure_company(company_name: str, company_id: uuid.UUID) -> None:
    async with get_session() as session:
        await session.execute(
            text("""
                INSERT INTO companies (id, name, country, sector)
                VALUES (:id, :name, 'EU', 'Corporate')
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": str(company_id), "name": company_name},
        )
        await session.commit()


async def run(
    company_name: str,
    source_url: str,
    claim_text: str | None = None,
    max_claims: int = 5,
) -> None:
    await init_db()

    company_id = uuid.uuid5(uuid.NAMESPACE_DNS, company_name.lower())
    await _ensure_company(company_name, company_id)

    pipeline = Pipeline(config=PipelineConfig())

    try:
        if claim_text:
            print(f"Using provided claim text ({len(claim_text)} chars)")
            extraction_input = ExtractionInput(
                trace_id=uuid.uuid4(),
                company_id=company_id,
                source_url=source_url,
                source_type=SourceType.IR_PAGE,
                raw_content=claim_text,
            )
            results = await pipeline.run_from_document(extraction_input)
        else:
            print(
                f"No --claim provided — fetching {source_url} "
                f"and discovering sustainability subpages (max 5, claims capped at {max_claims})..."
            )
            results = await pipeline.run_from_url(company_id, source_url, max_claims=max_claims)

        if not results:
            print("No claims extracted — the page may be JS-rendered or contain no green claims.")
            return

        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slug(company_name)

        # Print all verdicts; write each claim to its own numbered file.
        for i, r in enumerate(results, start=1):
            out_path = _REPORTS_DIR / f"{slug}-{i}.md"
            out_path.write_text(r.report_markdown or "No report generated.", encoding="utf-8")
            print(f"\n{'=' * 60}")
            print(f"Company : {company_name}  [claim {i}/{len(results)}]")
            print(f"Verdict : {r.score.verdict.value}")
            print(f"Score   : {r.score.score:.0f}/100")
            print(f"Claim   : {(r.claim.raw_text or '')[:120]}")
            print(f"Report  : {out_path}")
            print(f"{'=' * 60}\n")

        # Write the highest-scoring claim as the canonical report.
        best = max(results, key=lambda r: r.score.score)
        best_path = _REPORTS_DIR / f"{slug}.md"
        best_path.write_text(best.report_markdown or "No report generated.", encoding="utf-8")
        print(f"Canonical report (highest score {best.score.score:.0f}/100): {best_path}")

    finally:
        await pipeline.aclose()
        await teardown_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Prasine Index pipeline on a company sustainability page."
    )
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument(
        "--url",
        required=True,
        help="Source URL — fetched automatically if --claim is omitted",
    )
    parser.add_argument(
        "--claim",
        default=None,
        help="Claim text to assess. If omitted, the URL is fetched and its full text assessed.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Download fresh SBTi, InfluenceMap, CA100+, EUTL, E-PRTR, GCEL, and Fossil Finance "
        "data before running the assessment.",
    )
    parser.add_argument(
        "--max-claims",
        type=int,
        default=5,
        help="Maximum number of claims to assess across all discovered pages. "
        "Caps token spend. Default: 5.",
    )
    args = parser.parse_args()

    if args.refresh_data:
        print("Refreshing data sources...")
        _refresh_data()
        print("\nData refresh complete. Running assessment...\n")

    asyncio.run(run(args.company, args.url, args.claim, args.max_claims))
