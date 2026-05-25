"""doc↔source map generator (capability M).

Resolves each site page's `source_files:` globs against the repo's tracked
files into a dual-view artifact. `_glob_to_regex` and `_collect_page_patterns`
are shared with source_drift.py (imported there).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# archive_indexes lives alongside this module; reuse its frontmatter parser.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_indexes import parse_frontmatter  # noqa: E402


def _page_globs(md: Path) -> tuple[list[str], str | None]:
    """Return (globs, skip_reason) for one page. globs is the list of string
    entries in `source_files:` (empty if the page opts out); skip_reason is set
    for malformed frontmatter or a non-list source_files, else None. Never raises.
    """
    try:
        fm = parse_frontmatter(md)
    except (yaml.YAMLError, OSError):
        return [], "malformed frontmatter"
    sf = fm.get("source_files")
    if sf is None:
        return [], None
    if not isinstance(sf, list):
        return [], "source_files is not a list"
    return [x for x in sf if isinstance(x, str) and x], None


def _collect_page_patterns(docs_dir: Path) -> dict[str, list[str]]:
    """Map each opted-in page (POSIX path relative to docs_dir) to its
    source_files globs. Pages that opt out (no/empty source_files) or are malformed are omitted.
    """
    out: dict[str, list[str]] = {}
    if not docs_dir.is_dir():
        return out
    for md in sorted(docs_dir.rglob("*.md")):
        globs, _reason = _page_globs(md)
        if globs:
            out[md.relative_to(docs_dir).as_posix()] = globs
    return out


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a POSIX path glob to an anchored regex (use `.fullmatch`).

    `**/` matches zero or more path segments (incl. none); `**` matches
    anything including `/`; `*` matches a run of non-`/`; `?` matches one
    non-`/`; every other character is escaped. Python 3.9's fnmatch /
    PurePath.match mishandle `**`, hence this explicit translator.
    """
    i, n = 0, len(glob)
    parts: list[str] = []
    while i < n:
        if glob[i : i + 3] == "**/":
            parts.append("(?:.*/)?")
            i += 3
        elif glob[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(parts))
