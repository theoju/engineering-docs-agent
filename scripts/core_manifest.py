"""Detect the canonical-core page set and write .doc-core-manifest.json (C2).

Detection is stdlib-only and deterministic. The artifact is a sibling to
.doc-source-map.json under docs_dir; it declares each core page and the
source_files globs M uses for file-drift. Never raises on bad input.

`site_config` is the `site:` block itself (the {docs_dir, sections, ...} dict),
matching what setup_scaffold loads from the site YAML.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discover  # noqa: E402
import source_map  # noqa: E402  reuse _resolve_tracked_files / _glob_to_regex

_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")
_SLUG_NONWORD = re.compile(r"[^a-z0-9]+")
_BACKTICK = re.compile(r"`([^`\n]+)`")


def _agent_authored_section(site_config) -> dict | None:
    """The site section whose generator is agent-authored, or None. Never raises."""
    if not isinstance(site_config, dict):
        return None
    for s in site_config.get("sections") or []:
        if isinstance(s, dict) and s.get("generator") == "agent-authored":
            return s
    return None


def _source_root_glob(repo_root: Path) -> str | None:
    """A recursive *.py glob rooted at the detected Python scan dir, or None."""
    py = setup_discover.detect_python(Path(repo_root))
    if py.get("detected") and py.get("scan_dir"):
        return f"{py['scan_dir']}/**/*.py"
    return None


def _resolve_specs_dir(repo_root: Path, site_config, specs_dir=None) -> Path | None:
    """Resolve the specs directory: explicit arg wins; else the archive
    section's spec-like source; else docs/superpowers/specs. None if none exist.
    """
    repo_root = Path(repo_root)
    if specs_dir is not None:
        p = Path(specs_dir)
        p = p if p.is_absolute() else repo_root / p
        return p if p.is_dir() else None
    sections = site_config.get("sections") if isinstance(site_config, dict) else None
    for s in sections or []:
        if isinstance(s, dict) and s.get("generator") == "archive-index":
            for src in s.get("sources") or []:
                if isinstance(src, str) and "spec" in src.lower():
                    cand = repo_root / src
                    if cand.is_dir():
                        return cand
    default = repo_root / "docs" / "superpowers" / "specs"
    return default if default.is_dir() else None
