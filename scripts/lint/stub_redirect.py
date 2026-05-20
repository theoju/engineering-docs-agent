"""Lint rule: stub_redirect. Enforces 3-line redirect-stub format on declared paths."""

from __future__ import annotations

import argparse
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "stub_redirect"
SEVERITY = "block"
SEE_LINK_RE = re.compile(r"^See: \[.+\]\(.+\)\s*$")


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def is_stub_path(path: Path, patterns: list[str]) -> bool:
    return any(fnmatch(str(path), pat) for pat in patterns)


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    tier1 = config.get("lint", {}).get("tier1", {})
    patterns = tier1.get("stub_paths", []) if isinstance(tier1, dict) else []
    if not is_stub_path(path, patterns):
        return True, "not a stub path; skipped"
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    if len(lines) != 3:
        return False, f"stub must have exactly 3 non-empty lines, found {len(lines)}"
    if not SEE_LINK_RE.match(lines[-1]):
        return False, "stub's third line must match 'See: [text](path)'"
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
