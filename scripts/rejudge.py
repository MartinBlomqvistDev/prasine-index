"""Score saved judge inputs again, to measure how far the judge's score varies.

An assessment run with PRASINE_JUDGE_INPUTS set to a folder saves each claim's
judge input there as JSON: the claim and every record the judge saw. This script
scores chosen inputs again, one call at a time, and prints each score with its
finding, so that a claim near the edge of a band can be checked before it is
published.

    python scripts/rejudge.py --judge-model claude-opus-5-5 --runs 3 \\
        logs/judge_inputs/<claim id>.json
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import anthropic  # noqa: E402

from agents.judge_agent import JudgeAgent, JudgeInput  # noqa: E402
from models.score import finding_label  # noqa: E402


async def _rejudge(paths: list[Path], runs: int, judge_model: str) -> None:
    """Score each saved input `runs` times, one call at a time, and print the scores.

    Args:
        paths: Saved judge inputs.
        runs: How many times to score each input.
        judge_model: The judge model, as in the run being tested.
    """
    judge = JudgeAgent(client=anthropic.AsyncAnthropic(), model_id=judge_model)
    for path in paths:
        judge_input = JudgeInput.model_validate_json(path.read_text(encoding="utf-8"))
        print(f"\n{path.name}: {judge_input.claim.raw_text[:120]}")
        scores: list[float] = []
        for run in range(1, runs + 1):
            score = (await judge.run(judge_input)).score
            scores.append(score.score)
            print(
                f"  run {run}: {score.score:.0f} ({score.score_low:.0f}-{score.score_high:.0f}), "
                f"{finding_label(score.verdict)}, confidence {score.confidence:.2f}"
                if score.score_low is not None and score.score_high is not None
                else f"  run {run}: {score.score:.0f}, {finding_label(score.verdict)}"
            )
        print(f"  spread: {min(scores):.0f} to {max(scores):.0f}")


def main() -> None:
    """Parse the arguments and score the saved inputs again."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="+", type=Path, help="Saved judge input files")
    parser.add_argument("--runs", type=int, default=3, help="Scorings per input")
    parser.add_argument("--judge-model", required=True, help="Judge model, as in the run")
    args = parser.parse_args()
    asyncio.run(_rejudge(args.inputs, args.runs, args.judge_model))


if __name__ == "__main__":
    main()
