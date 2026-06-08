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

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator_runner import detect_repo  # noqa: E402
from state_io import ConfigError, load_config_validated  # noqa: E402


DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-\d{2}-")
_SUMMARY_MAX = 120
# Inline markdown link / image -> visible text. A title or summary lifted from a
# source doc can carry a relative link (`[x](2026-..-y.md)`); rendered into an
# archive/ table cell that target resolves against archive/ and aborts
# `mkdocs build --strict`. The Title cell already links to the source, so the
# teaser text needs no navigable links — reduce them to plain text (CCE-104).
_MD_LINK = re.compile(r"!?\[([^\]]+)\]\([^)]*\)")


def _strip_inline_links(text: str) -> str:
    """Reduce inline markdown links/images in `text` to their visible text."""
    return _MD_LINK.sub(r"\1", text)


@dataclass(frozen=True)
class Entry:
    filename: str
    title: str
    status: str
    summary: str
    month: str  # "YYYY-MM"
    source_rel_path: str  # POSIX, relative to repo_root


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


def parse_frontmatter_strict(text: str) -> dict:
    """Like ``parse_frontmatter``, but lets the caller distinguish failure modes.

    - Raises ``yaml.YAMLError`` on parse failure (original exception unwrapped).
    - Raises ``ValueError('no opening fence')`` when the document does not
      start with ``---``; ``ValueError('no closing fence')`` when the opening
      fence has no matching close; ``ValueError('frontmatter is not a mapping')``
      when the YAML parses to a scalar or list rather than a dict.
    - Returns the parsed dict on success; an empty frontmatter block returns ``{}``.

    The lenient sibling ``parse_frontmatter`` stays for callers that intentionally
    want bad input to degrade to an empty dict (whats-new prepend, source_map,
    archive index collection).
    """
    if not text.startswith("---"):
        raise ValueError("no opening fence")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("no closing fence")
    data = yaml.safe_load(parts[1])
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data


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


def collect_entries(source_dir: Path, repo_root: Path) -> list[Entry]:
    """Date-prefixed *.md in source_dir -> Entry list, newest filename first."""
    repo_root = Path(repo_root).resolve()
    entries: list[Entry] = []
    for path in source_dir.glob("*.md"):
        m = DATE_PREFIX.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8")
        title, summary = parse_title_and_summary(text)
        status = str(parse_frontmatter(text).get("status", "") or "").strip()
        entries.append(
            Entry(
                filename=path.name,
                title=title or path.name,
                status=status or "—",
                summary=summary,
                month=f"{m.group(1)}-{m.group(2)}",
                source_rel_path=path.resolve().relative_to(repo_root).as_posix(),
            )
        )
    entries.sort(key=lambda e: e.filename, reverse=True)
    return entries


def render_archive_page(
    label: str, entries: list[Entry], *, link_base: str | None
) -> str:
    """Render one archive index page: banner + month-grouped tables."""
    lines = [f"# {label} archive", ""]
    lines.append(
        f"_Auto-generated; {len(entries)} entries. "
        "Do not edit by hand — see `scripts/archive_indexes.py`._"
    )
    lines.append("")
    if not entries:
        lines.append("_No entries yet._")
        lines.append("")
        return "\n".join(lines)

    # Normalize the base so a caller that omits the trailing slash still
    # produces a well-formed URL (source_rel_path has no leading slash).
    base = link_base.rstrip("/") + "/" if link_base else None

    grouped: dict[str, list[Entry]] = {}
    for e in entries:
        grouped.setdefault(e.month, []).append(e)

    for month in sorted(grouped, reverse=True):
        lines.append(f"## {month}")
        lines.append("")
        lines.append("| Title | Status | Summary |")
        lines.append("|---|---|---|")
        for e in grouped[month]:
            title = _strip_inline_links(e.title).replace("|", "\\|")
            title_cell = f"[{title}]({base}{e.source_rel_path})" if base else title
            summary = _strip_inline_links(e.summary)
            if len(summary) > _SUMMARY_MAX:
                summary = summary[:_SUMMARY_MAX] + "…"
            summary = summary.replace("|", "\\|")
            status = e.status.replace("|", "\\|")
            lines.append(f"| {title_cell} | {status} | {summary} |")
        lines.append("")
    return "\n".join(lines)


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


def _find_archive_section(site: dict) -> dict | None:
    for s in site.get("sections", []) or []:
        if s.get("generator") == "archive-index":
            return s
    return None


def generate_archive(
    repo_root: Path, site_config: dict, *, repo_url_base: str | None = None
) -> dict:
    """Generate one archive index page per configured source.

    Skips (records) a source whose dir is missing or has no dated .md; never
    emits an empty page. Generated pages are overwritten every run. Returns
    {"written": [...], "skipped": [...]} of repo-relative POSIX page paths.
    """
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []

    section = _find_archive_section(site_config)
    if section is None:
        return {"written": written, "skipped": skipped}
    sources = section.get("sources") or []
    if not sources:
        return {"written": written, "skipped": skipped}

    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")
    section_path = (section.get("path") or "").rstrip("/")
    out_dir = repo_root / docs_dir / section_path
    link_base = resolve_repo_url_base(repo_root, section, override=repo_url_base)

    # Categories already written, so a second source with the same leaf name
    # (e.g. team-a/specs and team-b/specs) is skipped rather than silently
    # overwriting an earlier page.
    written_categories: set[str] = set()

    for source in sources:
        category = Path(source).name
        out_rel = f"{docs_dir}/{section_path}/{category}.md"
        src_dir = repo_root / source
        if not src_dir.is_dir():
            print(f"warning: archive source not found: {source}", file=sys.stderr)
            skipped.append(out_rel)
            continue
        if category in written_categories:
            print(
                f"warning: duplicate archive category {category!r} (source {source}); "
                "skipping to avoid overwriting an earlier page",
                file=sys.stderr,
            )
            skipped.append(out_rel)
            continue
        try:
            entries = collect_entries(src_dir, repo_root)
            if not entries:
                print(f"warning: no dated .md in source: {source}", file=sys.stderr)
                skipped.append(out_rel)
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{category}.md").write_text(
                render_archive_page(
                    category.capitalize(), entries, link_base=link_base
                ),
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            # A read/path error — a bad component, or a symlinked source that
            # resolves outside repo_root (ValueError from relative_to) — skips
            # this source instead of aborting mid-run with a partial ledger.
            print(f"warning: failed to process source {source}: {exc}", file=sys.stderr)
            skipped.append(out_rel)
            continue
        written_categories.add(category)
        written.append(out_rel)

    return {"written": written, "skipped": skipped}


def resolve_repo_url_base(
    repo_root: Path, section: dict, *, override: str | None = None
) -> str | None:
    """Base URL that source links hang off, or None for plain text.

    Order: explicit override / section['repo_url_base'] -> derived GitHub blob
    URL (detect_repo + current branch, default 'main') -> None.
    """
    explicit = override or section.get("repo_url_base")
    if explicit:
        base = str(explicit)
        return base if base.endswith("/") else base + "/"
    repo = detect_repo(repo_root)
    if repo.get("owner") == "unknown" or repo.get("name") == "unknown":
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    ref = proc.stdout.strip()
    if proc.returncode != 0 or ref in ("", "HEAD"):
        ref = "main"
    return f"https://github.com/{repo['owner']}/{repo['name']}/blob/{ref}/"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument(
        "--config",
        type=Path,
        required=True,
        help="config.yml with a site: block (locates archive sources)",
    )
    ap.add_argument(
        "--repo-url-base",
        default=None,
        help="override base URL for source links (else derived from git)",
    )
    args = ap.parse_args(argv)

    try:
        config = load_config_validated(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    site = config.get("site")
    if not site:
        print("error: config has no site: block", file=sys.stderr)
        return 1

    result = generate_archive(args.repo_root, site, repo_url_base=args.repo_url_base)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
