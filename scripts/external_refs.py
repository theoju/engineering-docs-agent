"""CCE-181: render citations that point into a declared EXTERNAL repository.

`citation_exists` is a Tier-1 block rule and correctly fails a backticked path
that does not exist in the host checkout. That is right for a confabulation and
wrong for an artifact which is real but lives in another repo -- a token that is
simultaneously true and uncitable. Post-CCE-140 such a page is not merely
blocked: the deferral skip abandons the PR and the page is silently never
written.

The escape is opt-in PER TOKEN. Only a token whose first segment is a declared
external repo is rewritten. Absence-of-resolution is deliberately NOT the
trigger: its entry condition is exactly the confabulation population the linter
exists to block, which would turn every BLOCK into a silent PASS (the CCE-141
class).

Pure and stdlib-only. No file I/O -- the orchestrator owns reading and writing.

Spec: docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Same pattern as scripts/citation_repair.py: append (never insert) the lint
# dir, then import bare. Inserting the scripts dir poisons namespace resolution
# for the rest of the session (CCE-122).
_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

from citation_exists import _SUFFIX_RE  # noqa: E402

DEFAULT_REF = "main"
DEFAULT_BLOB_TEMPLATE = "{url}/blob/{ref}/{path}"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


class ExternalRepoConfigError(ValueError):
    """A lint.external_repos declaration is ambiguous or unsafe."""


def resolve_config(
    config: dict, *, host_dirs: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Normalize lint.external_repos, raising on any invalid declaration."""
    lint = config.get("lint") or {}
    raw = lint.get("external_repos") or {}
    if not isinstance(raw, dict):
        raise ExternalRepoConfigError("lint.external_repos must be a mapping")

    out: dict[str, dict] = {}
    for prefix, entry in raw.items():
        if not isinstance(entry, dict):
            raise ExternalRepoConfigError(f"{prefix}: entry must be a mapping")
        if "/" in prefix:
            raise ExternalRepoConfigError(f"{prefix}: prefix must be a single segment")
        if prefix in host_dirs:
            raise ExternalRepoConfigError(
                f"{prefix}: collides with a real directory in this repo"
            )
        url = entry.get("url")
        has_url = isinstance(url, str) and bool(url.strip())
        private = bool(entry.get("private"))
        if has_url and private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares both a url and private; pick exactly one"
            )
        if not has_url and not private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares neither a url nor private; pick exactly one"
            )
        out[prefix] = {
            "url": url.strip() if has_url else None,
            "private": private,
            "ref": str(entry.get("ref") or DEFAULT_REF),
            "blob_template": str(entry.get("blob_template") or DEFAULT_BLOB_TEMPLATE),
        }
    return out
