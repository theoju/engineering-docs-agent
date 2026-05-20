"""Lint rule: reading_grade. Warns if Flesch-Kincaid grade level is outside configured range."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "reading_grade"
SEVERITY = "warn"


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def syllables(word: str) -> int:
    """Count approximate syllables in a word."""
    word = word.lower()
    count = 0
    vowels = "aeiouy"
    if word and word[0] in vowels:
        count += 1
    for i in range(1, len(word)):
        if word[i] in vowels and word[i - 1] not in vowels:
            count += 1
    if word.endswith("e"):
        count = max(1, count - 1)
    return max(1, count)


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    rng = config.get("lint", {}).get("tier3", {}).get("reading_grade_range", [8, 12])
    text = path.read_text()
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"\b\w+\b", text)
    if len(sentences) < 2 or len(words) < 20:
        return True, "too short for grade-level measurement"
    syl_count = sum(syllables(w) for w in words)
    grade = (
        (0.39 * (len(words) / len(sentences)))
        + (11.8 * (syl_count / len(words)))
        - 15.59
    )
    if grade < rng[0] or grade > rng[1]:
        return False, f"reading grade {grade:.1f} outside range {rng}"
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
    return 2 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
