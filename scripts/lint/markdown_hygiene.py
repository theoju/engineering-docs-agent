"""Lint rule: markdown_hygiene. Code fences have languages; heading hierarchy is valid."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "markdown_hygiene"
SEVERITY = "block"
FENCE_RE = re.compile(r"^```(\S*)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    text = path.read_text()
    problems: list[str] = []
    fences = list(FENCE_RE.finditer(text))
    for i in range(0, len(fences), 2):
        lang = fences[i].group(1)
        if not lang:
            problems.append(f"code fence at offset {fences[i].start()} has no language")
    prev_level = 0
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        if prev_level and level > prev_level + 1:
            problems.append(f"heading hierarchy jumps from h{prev_level} to h{level}")
        prev_level = level
    if problems:
        return False, "; ".join(problems)
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
