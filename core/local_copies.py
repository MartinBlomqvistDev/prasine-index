"""Local copies of public documents that a site will not serve to the index.

Some sites refuse automated requests. The index does not work around a refusal,
but a person can download a public report in a browser and give the run a local
copy of it. The copy is read in place of the network fetch, and the report is
still cited by its public address, never by the path on disk.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["read_copy", "register_copy"]

_COPIES: dict[str, Path] = {}


def _key(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


def register_copy(url: str, path: Path) -> None:
    """Read ``path`` whenever the run would fetch ``url``.

    Args:
        url: The document's public address, as it will be cited.
        path: A local copy of the same document, PDF or HTML.

    Raises:
        FileNotFoundError: If the copy does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    _COPIES[_key(url)] = path


def read_copy(url: str) -> tuple[str, bytes] | None:
    """Return the content type and bytes of the local copy of ``url``, if one is registered."""
    path = _COPIES.get(_key(url))
    if path is None:
        return None
    kind = "application/pdf" if path.suffix.lower() == ".pdf" else "text/html"
    return kind, path.read_bytes()
