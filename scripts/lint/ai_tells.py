"""Lint rule: ai_tells. Detects AI-writing signals: em-dash density or filler words."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "ai_tells"
SEVERITY = "block"

FILLER_WORDS = ["robust", "comprehensive", "seamless"]
EM_DASH_THRESHOLD = 0.01  # > 1% of word count


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    text = path.read_text()
    problems: list[str] = []

    # Em-dash density check
    words = re.findall(r"\w+", text)
    word_count = len(words)
    em_dash_count = text.count("—")
    if word_count > 0 and em_dash_count / word_count > EM_DASH_THRESHOLD:
        problems.append(
            f"em-dash density too high ({em_dash_count} em-dashes in {word_count} words)"
        )

    # Filler word check (>= 2 distinct filler words)
    text_lower = text.lower()
    found_fillers = [w for w in FILLER_WORDS if w in text_lower]
    if len(found_fillers) >= 2:
        problems.append(f"filler words found: {', '.join(found_fillers)}")

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
