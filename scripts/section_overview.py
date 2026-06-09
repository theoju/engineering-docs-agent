"""Upsert a clobber-safe overview block into each section landing + the home.

Pure renderers build the block body per section *type*; ``generate_overviews``
is the only function that touches the filesystem. It owns exactly one managed
region per landing (via managed_block) -- author prose outside the markers
survives every run. Best-effort per section: a malformed landing is recorded
and skipped, never raised, so an advisory generation failure never blocks the
nightly PR. Degrades gracefully: an empty section yields a "No pages yet."
block, never an empty file and never an error.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_indexes  # noqa: E402
import managed_block  # noqa: E402

_NO_PAGES = "_No pages yet._"


def render_directory_overview(children: list[tuple[str, str]]) -> str:
    """children: list of (title, summary). Render an "In this section" list +
    a count footer, or a "No pages yet." line when empty."""
    if not children:
        return _NO_PAGES
    lines = ["**In this section**", ""]
    for title, summary in children:
        lines.append(f"- **{title}** — {summary}" if summary else f"- **{title}**")
    lines.append("")
    lines.append(f"_{len(children)} pages · regenerated nightly_")
    return "\n".join(lines)


def _scan_children(section_dir: Path) -> list[tuple[str, str]]:
    """(title, summary) per child *.md, excluding index.md and _*-prefixed.
    Best-effort: a child that fails to read/parse is skipped, not raised."""
    out: list[tuple[str, str]] = []
    if not section_dir.is_dir():
        return out
    for md in sorted(section_dir.glob("*.md")):
        if md.name == "index.md" or md.name.startswith("_"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        title, summary = archive_indexes.parse_title_and_summary(text)
        title = archive_indexes._strip_inline_links(title) or md.stem
        summary = archive_indexes._strip_inline_links(summary)
        out.append((title, summary))
    return out


def _upsert(landing: Path, body: str, rel: str, written: list, skipped: list) -> None:
    existing = landing.read_text(encoding="utf-8") if landing.exists() else ""
    try:
        new = managed_block.upsert_managed_block(existing, body)
    except ValueError:
        skipped.append(rel)
        return
    if new != existing:
        landing.parent.mkdir(parents=True, exist_ok=True)
        landing.write_text(new, encoding="utf-8")
        written.append(rel)
    else:
        skipped.append(rel)


def _is_page(section: dict) -> bool:
    return section.get("path", "").endswith(".md")


def generate_overviews(repo_root: Path, site_config: dict) -> dict:
    """Upsert an overview block into every eligible section landing + the home.
    Returns {"written": [...], "skipped": [...]} of repo-relative POSIX paths."""
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []
    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")

    home_section = None
    for section in site_config.get("sections", []) or []:
        if section.get("overview") is False:
            continue
        if section.get("key") == "home":
            home_section = section
            continue
        if section.get("generator") == "api-extract":
            continue  # Task 4 replaces this branch
        if _is_page(section):
            continue
        path = section["path"].rstrip("/")
        section_dir = repo_root / docs_dir / path
        rel = f"{docs_dir}/{path}/index.md"
        body = render_directory_overview(_scan_children(section_dir))
        _upsert(repo_root / docs_dir / path / "index.md", body, rel, written, skipped)

    _ = home_section  # home handled in Task 5
    return {"written": written, "skipped": skipped}
