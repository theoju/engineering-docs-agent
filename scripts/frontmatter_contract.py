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
