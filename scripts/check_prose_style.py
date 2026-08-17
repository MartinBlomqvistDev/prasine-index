"""Check prose and typography conventions across the repo's written surfaces.

Site copy, documentation, comments and docstrings are held to the same
conventions so that text reads consistently wherever it appears. The rules are
mechanical ones that reviewers should not have to spend attention on:

* Dashes. Punctuate with a colon for an introduction, a semicolon for a
  connective pause, or commas for an aside. Ranges take an en dash (0-20).
* No non-breaking spaces. They are invisible in review and break grep.
* No trailing whitespace.

What is checked, and what is not:

* Text a person reads is checked. In Python that means comments and
  docstrings; everywhere else it means the whole file.
* Model-facing prompt text in agents/ is not. Its punctuation belongs to the
  generated report, not to the repo's own voice, and editing it would shift
  the eval baseline for no reader-facing gain.
* Report format templates are not, because core/pdf_export.py and
  web/lib/parse-report.ts match the punctuation in the generated report header.
* Verbatim quotations are not. Rewriting a quotation to house style falsifies
  it.

A line that must break a rule for functional reasons is exempted by putting
`style-ok` in a comment on that line.

Usage:
    python scripts/check_prose_style.py
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

EXEMPT_MARKER = "style-ok"

REPO_ROOT = Path(__file__).resolve().parent.parent

# (label, test, hint)
RULES: tuple[tuple[str, str, str], ...] = (
    ("em dash", "—", "use a colon, a semicolon, or commas"),
    ("non-breaking space", " ", "use an ordinary space"),
)

# Surfaces held to these conventions.
SCOPE: tuple[str, ...] = (
    "web",
    "docs/index.html",
    "agents",
    "api",
    "core",
    "eval",
    "ingest",
    "models",
    "scripts",
    "tests",
    "README.md",
    "docs/data-sources.md",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "Makefile",
)

SKIP_DIRS = {"node_modules", ".next", ".git", "__pycache__", ".venv"}

# Tool-generated files. web/AGENTS.md carries a vendored nextjs-agent-rules block
# that Next.js rewrites on upgrade, so editing it here would not hold.
SKIP_FILES = {"web/AGENTS.md"}

PY_SUFFIXES = {".py"}

CHECKED_SUFFIXES = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".md",
    ".json",
    ".mjs",
    ".py",
    ".toml",
    ".txt",
    ".yml",
    ".ini",
    "",
}


def files_in_scope() -> list[Path]:
    """Collect every file the conventions apply to."""
    found: list[Path] = []
    for entry in SCOPE:
        target = REPO_ROOT / entry
        if target.is_file():
            found.append(target)
            continue
        for path in target.rglob("*"):
            if not path.is_file() or path.suffix not in CHECKED_SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if SKIP_DIRS & set(rel.parts) or rel.as_posix() in SKIP_FILES:
                continue
            found.append(path)
    return sorted(found)


def _python_prose_lines(text: str) -> set[int]:
    """Line numbers of comments and docstrings, the human-read parts of a module."""
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
        tree = ast.parse(text)
    except (SyntaxError, tokenize.TokenError):
        return lines

    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        doc = body[0].value
        if isinstance(doc, ast.Constant) and isinstance(doc.value, str):
            lines.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return lines


def offences(path: Path) -> list[tuple[int, str, str]]:
    """Return (line number, rule label, line) for each unexempted breach."""
    text = path.read_text(encoding="utf-8", errors="replace")
    prose = _python_prose_lines(text) if path.suffix in PY_SUFFIXES else None

    found: list[tuple[int, str, str]] = []
    for num, line in enumerate(text.splitlines(), start=1):
        if EXEMPT_MARKER in line:
            continue
        if line != line.rstrip():
            found.append((num, "trailing whitespace", line.strip()))
        if prose is not None and num not in prose:
            continue
        for label, char, _hint in RULES:
            if char in line:
                found.append((num, label, line.strip()))
    return found


def main() -> int:
    hints = {label: hint for label, _char, hint in RULES}
    hints["trailing whitespace"] = "strip it"

    total = 0
    for path in files_in_scope():
        for num, label, line in offences(path):
            total += 1
            rel = path.relative_to(REPO_ROOT).as_posix()
            print(f"{rel}:{num}: {label} ({hints[label]}): {line[:100]}")

    if total:
        print(f"\n{total} issue(s). Mark a line `{EXEMPT_MARKER}` if the character is functional.")
        return 1

    print(f"Prose style clean across {len(SCOPE)} paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
