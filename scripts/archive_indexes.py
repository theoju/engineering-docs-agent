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

import yaml


def parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter block as a dict ({} if absent/malformed)."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_title_and_summary(text: str) -> tuple[str, str]:
    """Title from the first '# ' heading; summary from the first non-blank,
    non-heading line after it."""
    title = ""
    summary = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if title and stripped and not stripped.startswith("#"):
            summary = stripped
            break
    return title, summary


# --- Legacy lens-based archive (orchestrator-driven) -------------------------
# orchestrator_runner.py calls regenerate() for lens_paths entries flagged
# `archive_index: true`. This is the pre-S model; the site-based generator
# (generate_archive, CCE-23 capability D) supersedes it. The legacy path is
# retained until the orchestrator-integration step folds lens_paths into
# site: sections and removes it.


def build_index(subdir: Path) -> str:
    entries: list[str] = []
    for md in sorted(subdir.glob("*.md")):
        if md.name == "index.md":
            continue
        status = parse_frontmatter(md.read_text(encoding="utf-8")).get("status", "—")
        entries.append(f"- [{md.stem}]({md.name}) — status: `{status}`")
    if not entries:
        return f"# {subdir.name}\n\n_No entries yet._\n"
    return f"# {subdir.name}\n\n" + "\n".join(entries) + "\n"


def regenerate(archive_root: Path) -> None:
    """Regenerate per-subdirectory index.md files under archive_root."""
    if not archive_root.exists():
        return
    for sub in archive_root.iterdir():
        if sub.is_dir():
            (sub / "index.md").write_text(build_index(sub), encoding="utf-8")
