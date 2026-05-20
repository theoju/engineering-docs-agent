"""Generate index.md per archive subdirectory."""

from __future__ import annotations
import argparse, sys
from pathlib import Path

import yaml


def parse_frontmatter(p: Path) -> dict:
    text = p.read_text()
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    return yaml.safe_load(parts[1]) or {}


def build_index(subdir: Path) -> str:
    entries = []
    for md in sorted(subdir.glob("*.md")):
        if md.name == "index.md":
            continue
        fm = parse_frontmatter(md)
        title = md.stem
        status = fm.get("status", "—")
        entries.append(f"- [{title}]({md.name}) — status: `{status}`")
    if not entries:
        return f"# {subdir.name}\n\n_No entries yet._\n"
    return f"# {subdir.name}\n\n" + "\n".join(entries) + "\n"


def regenerate(archive_root: Path) -> None:
    """Regenerate per-subdirectory index.md files under archive_root."""
    if not archive_root.exists():
        return
    for sub in archive_root.iterdir():
        if sub.is_dir():
            (sub / "index.md").write_text(build_index(sub))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args()
    regenerate(args.archive_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
