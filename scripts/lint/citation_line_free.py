"""Lint rule: citation_line_free (CCE-122, Tier-1, advisory).

Flags inline `path:line` code citations. Line numbers drift under unrelated
code churn, so they are banned in favor of `path:symbol` / bare `path`. This
rule is SEVERITY=warn: it surfaces the finding but never fails a run, so a
host still carrying legacy :line pins is nudged, not blocked. Detection reuses
citation_exists.line_pinned_citations (single source of the :line grammar).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import citation_exists

RULE_NAME = "citation_line_free"
SEVERITY = "warn"


def check_path(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError) as e:
        return False, f"file unreadable: {e}"
    pins = citation_exists.line_pinned_citations(text)
    if pins:
        joined = ", ".join(pins)
        return False, f"prefer path:symbol or bare path over line pins: {joined}"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p)
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
