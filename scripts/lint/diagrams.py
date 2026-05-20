"""Lint rule: diagrams. Validates Mermaid code-fence syntax."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "diagrams"
SEVERITY = "block"

MERMAID_FENCE = re.compile(r"^```mermaid\s*$", re.MULTILINE)
FENCE_END = re.compile(r"^```\s*$", re.MULTILINE)


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    text = path.read_text()
    starts = [m.start() for m in MERMAID_FENCE.finditer(text)]
    if not starts:
        return True, "no mermaid blocks"
    for s in starts:
        end_match = FENCE_END.search(text, pos=s + len("```mermaid"))
        if not end_match:
            return False, f"unterminated mermaid fence at offset {s}"
    return True, f"{len(starts)} mermaid block(s) ok"


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
