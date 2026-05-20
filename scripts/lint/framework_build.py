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


def run_mkdocs(cwd: Path) -> tuple[bool, str]:
    if not (cwd / "mkdocs.yml").exists():
        return True, "no mkdocs.yml found; build skipped"
    if shutil.which("mkdocs") is None:
        return True, "mkdocs not installed; build skipped"
    r = subprocess.run(
        ["mkdocs", "build", "--strict"], cwd=cwd, capture_output=True, text=True
    )
    if r.returncode != 0:
        return False, f"mkdocs build failed: {r.stderr.strip()[:500]}"
    return True, "mkdocs build ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    framework = config.get("docs", {}).get("framework", "mkdocs")
    if framework == "mkdocs":
        ok, msg = run_mkdocs(Path.cwd())
    else:
        ok, msg = True, f"framework={framework} not yet supported; skipped"
    result = {"path": str(args.paths[0]), "ok": ok, "message": msg}
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": [result]}, sys.stdout
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
