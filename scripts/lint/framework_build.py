"""Lint rule: framework_build. Runs the host's docs framework build to detect breakage."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

RULE_NAME = "framework_build"
SEVERITY = "block"


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def run_mkdocs(cwd: Path) -> tuple[bool, bool, str]:
    """Returns (ok, skipped, reason_or_message)."""
    if not (cwd / "mkdocs.yml").exists():
        return True, True, "no mkdocs.yml in repo root"
    if shutil.which("mkdocs") is None:
        return True, True, "mkdocs binary not installed"
    r = subprocess.run(
        ["mkdocs", "build", "--strict"], cwd=cwd, capture_output=True, text=True
    )
    if r.returncode != 0:
        return False, False, f"mkdocs build failed: {r.stderr.strip()[:500]}"
    return True, False, "mkdocs build ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    framework = config.get("docs", {}).get("framework", "mkdocs")
    if framework == "mkdocs":
        ok, skipped, reason = run_mkdocs(Path.cwd())
    else:
        ok, skipped, reason = (
            True,
            True,
            f"framework={framework}; build validation not supported in v0.1",
        )
    result = {
        "path": str(args.paths[0]),
        "ok": ok,
        "skipped": skipped,
        "reason": reason,
        "message": reason,  # legacy field
    }
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": [result]}, sys.stdout
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
