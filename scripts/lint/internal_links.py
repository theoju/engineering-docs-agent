"""Lint rule: internal_links. Verifies internal Markdown links resolve."""

from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from typing import Any
import yaml

RULE_NAME = "internal_links"
SEVERITY = "block"
LINK_RE = re.compile(r"\[(?:[^\]]+)\]\(([^)#?\s]+)(?:#[^)]*)?\)")


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "tel:"))


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    broken = []
    for m in LINK_RE.finditer(path.read_text()):
        target = m.group(1)
        if is_external(target):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            broken.append(target)
    if broken:
        return False, f"broken internal link(s): {', '.join(broken)}"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, config)
        results.append({"path": str(p), "ok": ok, "message": message})
        if not ok:
            any_failed = True
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": results}, sys.stdout
        )
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
