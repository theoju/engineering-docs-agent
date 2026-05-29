"""Lint rule: markdown_hygiene_lang. Warns when opening code fences omit a language tag.

Cosmetic only — MkDocs still renders untagged fences; the page just loses
syntax highlighting. Structural defects (unpaired fences, heading jumps)
are handled by the block-severity sibling rule `markdown_hygiene_structure`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "markdown_hygiene_lang"
SEVERITY = "warn"
FENCE_RE = re.compile(r"^```(\S*)\s*$", re.MULTILINE)


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    text = path.read_text()
    problems: list[str] = []
    fences = list(FENCE_RE.finditer(text))
    # Treat even-indexed fences as openers; odd-indexed as closers.
    # Structural pairing is the sibling rule's responsibility; here we only
    # care whether each opener carries a language tag.
    for i in range(0, len(fences), 2):
        lang = fences[i].group(1)
        if not lang:
            problems.append(f"code fence at offset {fences[i].start()} has no language")
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
