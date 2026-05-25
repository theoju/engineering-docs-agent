"""doc↔source map generator (capability M).

Resolves each site page's `source_files:` globs against the repo's tracked
files into a dual-view artifact. `_glob_to_regex` and `_collect_page_patterns`
are shared with source_drift.py (imported there).
"""

from __future__ import annotations

import re
from pathlib import Path


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
