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
import setup_discover  # noqa: E402
import site_structure  # noqa: E402

_NO_PAGES = "_No pages yet._"


def render_home_overview(entries: list[tuple[str, str]]) -> str:
    """entries: list of (title, target). Render the grid-cards section directory
    that lives inside the home's managed block."""
    if not entries:
        return _NO_PAGES
    cards = [f"-   __{title}__\n\n    [Open →]({target})" for title, target in entries]
    return '<div class="grid cards" markdown>\n\n' + "\n\n".join(cards) + "\n\n</div>"


def render_directory_overview(children: list[tuple[str, str]]) -> str:
    """children: list of (title, summary). Render an "In this section" list +
    a count footer, or a "No pages yet." line when empty."""
    if not children:
        return _NO_PAGES
    lines = ["**In this section**", ""]
    for title, summary in children:
        lines.append(f"- **{title}** — {summary}" if summary else f"- **{title}**")
    lines.append("")
    lines.append(f"_{_plural(len(children), 'page')} · regenerated nightly_")
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


def _upsert(repo_root: Path, rel: str, body: str, written: list, skipped: list) -> None:
    """Upsert the managed block of ``repo_root / rel`` with ``body``, recording
    ``rel`` in ``written`` (content changed) or ``skipped`` (unchanged or the
    existing file's markers are malformed)."""
    landing = repo_root / rel
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


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def render_api_overview(
    idents: list[str], groups: list, contract_links: list[tuple[str, str]]
) -> str:
    """Render the API landing block: CCE-105 groups + counts (or a flat module
    count when no groups), then links to the on-disk contracts pages."""
    lines: list[str] = []
    if groups:
        counts: dict[str, int] = {}
        for ident in idents:
            name = site_structure.assign_group(ident, groups) or "Other"
            counts[name] = counts.get(name, 0) + 1
        # "Other" is the implicit unmatched bucket; only append it when no
        # operator-declared group already carries that name, so a collision
        # renders one merged line, not a duplicated/double-counted pair.
        order = [g["name"] for g in groups]
        if "Other" not in order:
            order.append("Other")
        lines.append("**Components**")
        lines.append("")
        for name in order:
            if counts.get(name):
                lines.append(f"- **{name}** — {_plural(counts[name], 'module')}")
        lines.append("")
    elif idents:
        lines.append(
            f"_{_plural(len(idents), 'module')} documented · regenerated nightly_"
        )
        lines.append("")
    if contract_links:
        lines.append("**Contracts**")
        lines.append("")
        for title, rel in contract_links:
            lines.append(f"- [{title}]({rel})")
        lines.append("")
    body = "\n".join(lines).rstrip("\n")
    return body or _NO_PAGES


def _api_idents(repo_root: Path) -> list[str]:
    """Dotted idents of the host's python modules, mirroring gen_ref_pages'
    rglob + filter. Empty when no python is detected (degrade-gracefully)."""
    py = setup_discover.detect_python(repo_root)
    if not py.get("detected"):
        return []
    scan_dir = repo_root / (py.get("scan_dir") or ".")
    root = repo_root / (py.get("path_root") or ".")
    idents: list[str] = []
    for path in sorted(scan_dir.rglob("*.py")):
        if path.name.startswith("_") or any(p in ("tests", "test") for p in path.parts):
            continue
        try:
            parts = path.relative_to(root).with_suffix("").parts
        except ValueError:
            continue
        if parts:
            idents.append(".".join(parts))
    return idents


def _contract_links(
    repo_root: Path, docs_dir: str, api_path: str
) -> list[tuple[str, str]]:
    contracts_dir = repo_root / docs_dir / api_path / "contracts"
    links: list[tuple[str, str]] = []
    if not contracts_dir.is_dir():
        return links
    for md in sorted(contracts_dir.glob("*.md")):
        if md.name == "index.md":
            continue
        try:
            title, _ = archive_indexes.parse_title_and_summary(
                md.read_text(encoding="utf-8")
            )
        except OSError:
            title = ""
        links.append((title or md.stem, f"contracts/{md.name}"))
    return links


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
            api_path = section["path"].rstrip("/")
            rel = f"{docs_dir}/{api_path}/index.md"
            body = render_api_overview(
                _api_idents(repo_root),
                section.get("groups") or [],
                _contract_links(repo_root, docs_dir, api_path),
            )
            _upsert(repo_root, rel, body, written, skipped)
            continue
        if _is_page(section):
            continue
        path = section["path"].rstrip("/")
        rel = f"{docs_dir}/{path}/index.md"
        body = render_directory_overview(_scan_children(repo_root / docs_dir / path))
        _upsert(repo_root, rel, body, written, skipped)

    if home_section is not None:
        entries: list[tuple[str, str]] = []
        for section in site_config.get("sections", []) or []:
            if section.get("key") == "home":
                continue
            path = section["path"]
            target = path if _is_page(section) else f"{path.rstrip('/')}/index.md"
            entries.append((section["title"], target))
        rel = f"{docs_dir}/{home_section['path'].rstrip('/')}"
        _upsert(repo_root, rel, render_home_overview(entries), written, skipped)
    return {"written": written, "skipped": skipped}
