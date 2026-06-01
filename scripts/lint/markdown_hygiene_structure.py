"""Lint rule: markdown_hygiene_structure. Block-severity structural defects in markdown.

Catches unpaired code fences and heading-hierarchy jumps — both of these
genuinely break MkDocs render or produce malformed HTML. The cosmetic
"opening fence missing a language tag" check lives in the sibling
warn-severity rule `markdown_hygiene_lang.py` so that a missing language
tag does not cause the orchestrator to drop the entire authored page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "markdown_hygiene_structure"
SEVERITY = "block"
FENCE_RE = re.compile(r"^```(\S*)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    text = path.read_text()
    problems: list[str] = []
    fences = list(FENCE_RE.finditer(text))
    if len(fences) % 2 != 0:
        problems.append(f"unpaired code fence (count={len(fences)})")
    # CCE-68: pair fences greedily and mask headings inside them. A `#`
    # line inside ```yaml``` (or any fenced block) is a code comment, not
    # a Markdown heading. Without masking, false-positive hierarchy
    # jumps fire on structurally-correct documents.
    fenced_regions = [
        (fences[i].start(), fences[i + 1].end()) for i in range(0, len(fences) - 1, 2)
    ]

    def _in_fence(offset: int) -> bool:
        return any(start <= offset < end for start, end in fenced_regions)

    prev_level = 0
    for m in HEADING_RE.finditer(text):
        if _in_fence(m.start()):
            continue
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
