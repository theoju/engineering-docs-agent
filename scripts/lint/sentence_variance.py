"""Lint rule: sentence_variance. Warns if sentence-length variance is too low."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "sentence_variance"
SEVERITY = "warn"


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    text = path.read_text()
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    lengths = [len(s.split()) for s in sentences]
    if len(lengths) < 5:
        return True, "too few sentences for variance check"
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    if variance < 10:
        return False, f"sentence-length variance {variance:.1f} too low"
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
