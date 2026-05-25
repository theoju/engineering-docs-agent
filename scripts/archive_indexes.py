"""Generate Decision Archive index pages from configured source dirs.

Reads the `archive-index` section's `sources` directories and, for each one,
emits a `<docs_dir>/<archive-path>/<category>.md` index page: date-prefixed
`.md` files grouped by ISO month (newest first), each row carrying title,
status (YAML frontmatter), and a one-line summary, linking back to source via
a resolved repo URL base (or plain text when none resolves).

Pure functions parse and render; `generate_archive` is the only function that
writes files. Unlike the scaffold engine, generated pages are *overwritten*
every run (they carry an auto-generated banner).
"""

from __future__ import annotations
from pathlib import Path


def regenerate(archive_root: Path) -> None:
    """Stub: regenerate index pages (TDD implementation pending)."""
    pass
