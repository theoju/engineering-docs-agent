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
    return f"# {subdir.name}\n\n" + "\n".join(entries) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args()
    for sub in args.archive_root.iterdir():
        if sub.is_dir():
            (sub / "index.md").write_text(build_index(sub))
    return 0


if __name__ == "__main__":
    sys.exit(main())
