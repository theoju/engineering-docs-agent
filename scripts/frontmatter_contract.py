"""Single source of truth for required frontmatter fields, keyed by the
authoring generator of the site section a page belongs to.

Default (changelog / archive / api / no section / no site block) keeps the
historical set. Only ``agent-authored`` sections (Capability C2 core pages)
use the citation-bearing set. Pure stdlib; never raises on bad input.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

DEFAULT_REQUIRED = ("status", "sources", "synthesized_into")
AGENT_AUTHORED_REQUIRED = ("description", "source_files", "last_reviewed", "status")


def required_fields(generator: str | None) -> tuple[str, ...]:
    """Return the required frontmatter field names for a section generator."""
    if generator == "agent-authored":
        return AGENT_AUTHORED_REQUIRED
    return DEFAULT_REQUIRED


def section_generator_for(page: Path | str, config: dict) -> str | None:
    """Return the generator of the site section that contains ``page``, or None.

    Matches the section whose ``docs_dir/path`` is a path-segment prefix of the
    page (longest match wins, so a nested section beats its parent). Returns
    None when there is no ``site:`` block, no ``docs_dir``, or no match — which
    yields the default field set. Never raises.
    """
    site = (config or {}).get("site") or {}
    docs_dir = str(site.get("docs_dir") or "").strip("/")
    sections = site.get("sections") or []
    if not docs_dir or not sections:
        return None
    page_posix = Path(page).as_posix()
    bounded = f"/{page_posix}/"  # segment-bounded haystack
    best_len = -1
    best_gen: str | None = None
    for s in sections:
        rel = str((s or {}).get("path") or "").strip("/")
        if not rel:
            continue
        full = str(PurePosixPath(docs_dir) / rel)  # e.g. docs/site-src/core
        if f"/{full}/" in bounded:
            if len(full) > best_len:
                best_len = len(full)
                best_gen = s.get("generator")
    return best_gen
