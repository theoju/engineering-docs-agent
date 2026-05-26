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
    yields the default field set. Never raises (malformed config -> None).

    ``page`` must be in the same path frame as ``docs_dir`` (absolute or
    repo-relative) for the prefix match to fire; a docs_dir-relative or bare
    page path will not match and yields the default field set. Never raises
    (malformed config -> None).
    """
    site = config.get("site") if isinstance(config, dict) else None
    if not isinstance(site, dict):
        return None
    docs_dir = site.get("docs_dir")
    docs_dir = docs_dir.strip("/") if isinstance(docs_dir, str) else ""
    sections = site.get("sections")
    if not docs_dir or not isinstance(sections, list):
        return None
    try:
        page_posix = Path(page).as_posix()
    except TypeError:
        return None
    bounded = f"/{page_posix}/"  # segment-bounded haystack
    best_len = -1
    best_gen: str | None = None
    for s in sections:
        if not isinstance(s, dict):
            continue
        rel = s.get("path")
        rel = rel.strip("/") if isinstance(rel, str) else ""
        if not rel:
            continue
        full = str(PurePosixPath(docs_dir) / rel)
        if f"/{full}/" in bounded and len(full) > best_len:
            best_len = len(full)
            best_gen = s.get("generator")
    return best_gen


def default_frontmatter_dict(sources: list[str] | None = None) -> dict:
    """The default (non-agent-authored) frontmatter the orchestrator authors."""
    return {"status": "draft", "sources": list(sources or []), "synthesized_into": []}


def default_frontmatter_text() -> str:
    """The default frontmatter block for the dry-run page synthesizer."""
    return "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"
