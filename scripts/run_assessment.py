"""Run the Prasine Index pipeline against a real company claim.

Usage — fetch the page automatically (recommended):
    python scripts/run_assessment.py --company "Shell plc" \\
        --url "https://shell.com/sustainability"

Usage — provide claim text directly:
    python scripts/run_assessment.py --company "Shell plc" \\
        --claim "Shell is on track to become net-zero by 2050" \\
        --url "https://shell.com/sustainability"

Usage — refresh all data sources first (downloads fresh SBTi, LobbyMap,
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
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_core")
warnings.filterwarnings(
    "ignore", message="Workbook contains no default style", category=UserWarning, module="openpyxl"
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import text  # noqa: E402

from agents.extraction_agent import ExtractionInput  # noqa: E402
from core.aggregate import aggregate_claim_scores  # noqa: E402
from core.data_manifest import build_manifest, manifest_to_markdown  # noqa: E402
from core.database import get_session, init_db, teardown_db  # noqa: E402
from core.pipeline import Pipeline, PipelineConfig, PipelineResult  # noqa: E402
from models.claim import SourceType  # noqa: E402
from models.company_score import CompanyScore  # noqa: E402

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
        "refresh_LobbyMap.py",
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
            spec.loader.exec_module(module)
            # Each refresh script exposes a main download function with a predictable name.
            for fn_name in (
                "download_sbti",
                "download_LobbyMap_csv",
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


def _build_aggregate_header(
    company_name: str,
    company_score: CompanyScore,
    results: list[PipelineResult],
) -> str:
    n = company_score.claim_count
    lines = [
        f"## {company_name} — Company Assessment ({n} claim{'s' if n != 1 else ''})",
        "",
        f"**Overall Score: {company_score.score:.0f}/100** "
        f"(confidence-weighted across {n} claim{'s' if n != 1 else ''})  ",
        f"**Score range:** {company_score.score_low:.0f}–{company_score.score_high:.0f}  ",
        f"**Verdict:** {company_score.verdict.value}  ",
        f"**Confidence:** {company_score.confidence:.0%}",
        "",
        "| # | Score | Verdict | Claim |",
        "|---|-------|---------|-------|",
    ]
    for i, claim in enumerate(company_score.claims, start=1):
        preview = claim.claim_text[:120].replace("|", "/").replace("\n", " ")
        lines.append(f"| {i} | {claim.score:.0f}/100 | {claim.verdict.value} | {preview} |")

    best_score = max(r.score.score for r in results)
    lines += [
        "",
        "---",
        "",
        f"*Detailed assessment of the highest-scoring claim "
        f"(score: {best_score:.0f}/100) follows.*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


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
    judge_model: str = "claude-haiku-4-5-20251001",
    report_model: str = "claude-haiku-4-5-20251001",
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(f"[dry-run] Would assess: {company_name}")
        print(f"[dry-run] Source URL : {source_url}")
        print(f"[dry-run] Claim text : {claim_text or '(discover from URL)'}")
        print(f"[dry-run] Max claims : {max_claims}")
        print(f"[dry-run] Judge model: {judge_model}")
        print("[dry-run] No tokens spent. Pass without --dry-run to run the full pipeline.")
        return

    await init_db()

    company_id = uuid.uuid5(uuid.NAMESPACE_DNS, company_name.lower())
    await _ensure_company(company_name, company_id)

    pipeline = Pipeline(config=PipelineConfig(judge_model=judge_model, report_model=report_model))

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

        # Print per-claim verdicts; write each to its own numbered file.
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

        # Aggregate all claims into a company-level score.
        company_score = aggregate_claim_scores(company_name, company_id, results)
        print(f"\n{'=' * 60}")
        print(f"COMPANY ASSESSMENT: {company_name}")
        print(
            f"Overall Score : {company_score.score:.0f}/100  "
            f"(confidence-weighted, {company_score.claim_count} claim"
            f"{'s' if company_score.claim_count != 1 else ''})"
        )
        print(f"Score range   : {company_score.score_low:.0f}–{company_score.score_high:.0f}")
        print(f"Verdict       : {company_score.verdict.value}")
        print(f"{'=' * 60}\n")

        # Write the canonical report: aggregate header + highest-scoring claim detail + manifest.
        best = max(results, key=lambda r: r.score.score)
        best_path = _REPORTS_DIR / f"{slug}.md"
        header = _build_aggregate_header(company_name, company_score, results)
        manifest = build_manifest()
        manifest_path = _REPORTS_DIR / f"{slug}-manifest.json"
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")
        canonical = (
            header
            + (best.report_markdown or "")
            + "\n\n---\n\n"
            + manifest_to_markdown(manifest)
            + "\n"
        )
        best_path.write_text(canonical, encoding="utf-8")
        print(
            f"Canonical report ({company_score.claim_count} claims, "
            f"aggregate score {company_score.score:.0f}/100): {best_path}"
        )
        print(f"Data manifest: {manifest_path}")

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
        help="Download fresh SBTi, LobbyMap, CA100+, EUTL, E-PRTR, GCEL, and Fossil Finance "
        "data before running the assessment.",
    )
    parser.add_argument(
        "--max-claims",
        type=int,
        default=5,
        help="Maximum number of claims to assess across all discovered pages. "
        "Caps token spend. Default: 5.",
    )
    parser.add_argument(
        "--judge-model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model ID for the Judge Agent. Default: claude-haiku-4-5-20251001. "
        "Use claude-opus-4-8 for production-quality legally-citable output.",
    )
    parser.add_argument(
        "--report-model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model ID for the Report Agent. Default: claude-haiku-4-5-20251001. "
        "Use claude-opus-4-8 for showcase or client-facing reports.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be assessed without spending any tokens.",
    )
    args = parser.parse_args()

    if args.refresh_data:
        print("Refreshing data sources...")
        _refresh_data()
        print("\nData refresh complete. Running assessment...\n")

    asyncio.run(
        run(
            args.company,
            args.url,
            args.claim,
            args.max_claims,
            args.judge_model,
            args.report_model,
            dry_run=args.dry_run,
        )
    )
