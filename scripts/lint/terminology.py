"""Lint rule: terminology. Enforces canonical terms from a glossary file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "terminology"
SEVERITY = "block"


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    glossary_path = config.get("lint", {}).get("tier2", {}).get("terminology_glossary")
    if not glossary_path:
        return True, "ok"
    glossary_file = Path(glossary_path)
    if not glossary_file.exists():
        return False, f"glossary file not found: {glossary_path}"
    glossary: dict[str, list[str]] = yaml.safe_load(glossary_file.read_text()) or {}

    text = path.read_text()
    text_lower = text.lower()
    violations: list[str] = []
    for canonical, variants in glossary.items():
        canonical_present = canonical.lower() in text_lower
        for variant in variants or []:
            if variant.lower() in text_lower and not canonical_present:
                violations.append(f"use '{canonical}' instead of '{variant}'")
    if violations:
        return False, "; ".join(violations)
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
