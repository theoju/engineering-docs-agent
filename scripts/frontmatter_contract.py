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

    Frame-robust: absolute and repo-relative pages match via the embedded
    ``docs_dir/path`` suffix. A docs_dir-relative or bare page (one lacking the
    ``docs_dir`` segment entirely) falls back to matching the section ``path``
    alone, so callers in any frame resolve correctly. The fallback fires only
    when the full match found nothing AND ``docs_dir`` is absent from the page,
    so it cannot change the result for any path that already matches. Frame 2
    trades precision for robustness: a bare/relative page that lacks
    ``docs_dir`` but contains a section-name segment will match that section,
    so it is sound for the orchestrator's absolute-path frame (always Frame 1)
    — be deliberate before feeding arbitrary relative paths from outside the
    docs tree.
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

    def _best(needle_for) -> tuple[int, str | None]:
        best_len, best_gen = -1, None
        for s in sections:
            if not isinstance(s, dict):
                continue
            rel = s.get("path")
            rel = rel.strip("/") if isinstance(rel, str) else ""
            if not rel:
                continue
            needle = needle_for(rel)
            if f"/{needle}/" in bounded and len(needle) > best_len:
                best_len = len(needle)
                best_gen = s.get("generator")
        return best_len, best_gen

    # Frame 1 — absolute / repo-relative: page embeds docs_dir/section.
    full_len, full_gen = _best(lambda rel: str(PurePosixPath(docs_dir) / rel))
    # >=0 means a section matched (even a generatorless one, gen=None); do NOT
    # change to `full_gen is not None` or a matched generatorless section would
    # wrongly fall through to Frame 2.
    if full_len >= 0:
        return full_gen
    # Frame 2 — docs_dir-relative / bare: only when docs_dir is truly absent,
    # so a page under docs_dir that matched no section stays None.
    if f"/{docs_dir}/" in bounded:
        return None
    return _best(lambda rel: rel)[1]


def default_frontmatter_dict(sources: list[str] | None = None) -> dict:
    """The default (non-agent-authored) frontmatter the orchestrator authors."""
    return {"status": "draft", "sources": list(sources or []), "synthesized_into": []}


def default_frontmatter_text() -> str:
    """The default frontmatter block for the dry-run page synthesizer."""
    return "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"
