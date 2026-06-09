"""Deterministic architecture-vs-archive routing (CCE-107).

The pr-summarizer emits a per-target ``doc_kind`` ("architecture" | "decision").
``route_create_hint`` maps a *decision* page to the host's archive-index section
(discovered by generator marker via ``archive_indexes._find_archive_section`` —
never a hardcoded name); every other case keeps the agent's chosen hint. Pure
functions: no I/O, no agent dependence, so the routing decision is unit-testable
unlike the agent's semantic judgment. Generic-first: a host with no archive-index
section (``archive_section`` is None) leaves all hints untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_indexes  # noqa: E402


def archive_section_leaf(site_config: dict | None) -> str | None:
    """Leaf directory name of the section whose generator is ``archive-index``,
    or None when the host declares no such section."""
    section = archive_indexes._find_archive_section(site_config or {})
    if not section:
        return None
    path = str(section.get("path") or "").rstrip("/")
    return path.rsplit("/", 1)[-1] or None


def route_create_hint(
    page_hint: str,
    doc_kind: str | None,
    archive_section: str | None,
    available_sections: list[str],
) -> str:
    """Rewrite a *decision* create-target's hint into the archive section.

    ``doc_kind == "decision"`` AND an archive section exists AND it is present in
    ``available_sections`` -> ``"<archive_section>/<filename>"``. Any other case
    (architecture/unknown/absent ``doc_kind``, no archive section, or the archive
    dir not yet on disk) returns ``page_hint`` unchanged.
    """
    if (
        doc_kind == "decision"
        and archive_section
        and archive_section in available_sections
    ):
        filename = page_hint.rsplit("/", 1)[-1]
        return f"{archive_section}/{filename}"
    return page_hint
