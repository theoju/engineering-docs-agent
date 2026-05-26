"""Lint rule: frontmatter_schema. Validates required YAML frontmatter fields."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any
import yaml

# import sibling scripts/ module (first lint rule to do so; see archive_indexes.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import frontmatter_contract as fc  # noqa: E402

RULE_NAME = "frontmatter_schema"
SEVERITY = "block"


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    fm = parse_frontmatter(path.read_text())
    if fm is None:
        return False, "no frontmatter or YAML parse error"
    generator = fc.section_generator_for(path, config)
    required = fc.required_fields(generator)
    missing = [f for f in required if f not in fm]
    if missing:
        return False, f"missing required field(s): {', '.join(missing)}"
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
