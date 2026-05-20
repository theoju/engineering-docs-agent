"""Lint rule: second_person. Flags mixed second/third-person when 'you' is present."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "second_person"
SEVERITY = "block"

SLIP_PHRASES = ["the user", "the developer", "the engineer", "the reader"]


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    text = path.read_text()
    text_lower = text.lower()

    # Rule only applies when file uses second-person "you"
    if not re.search(r"\byou\b", text_lower):
        return True, "ok"

    slips = [phrase for phrase in SLIP_PHRASES if phrase in text_lower]
    if slips:
        slip_labels = [p.replace("the ", "") for p in slips]
        return False, (
            f"second-person inconsistency: 'you' AND "
            + ", ".join(f"'the {s}'" for s in slip_labels)
        )
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
