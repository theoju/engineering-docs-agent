"""Lint runner: dispatch per-rule scripts based on config and aggregate results.

Rule script CLI contract:
  exit 0 — all paths passed the rule
  exit 1 — at least one path failed (severity from JSON output determines
           whether lint_runner exits 1 itself)
  exit 2 — invocation error (bad args, missing config, unhandled exception)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

TIER1_DEFAULT = [
    "frontmatter_schema",
    "internal_links",
    "markdown_hygiene",
    "footnotes",
    "diagrams",
    "framework_build",
    "stub_redirect",
]

# Mapping config keys (in tier2/tier3 dicts) → rule script name.
# voice_consistency is intentionally absent: it's LLM-handled by content-validator.
TIER2_CONFIG_KEYS = {
    "banned_phrases": "banned_phrases",
    "ai_tells": "ai_tells",
    "terminology_glossary": "terminology",
    "second_person_consistency": "second_person",
    "paragraph_max_words": "paragraph_length",
}

TIER3_CONFIG_KEYS = {
    "reading_grade_range": "reading_grade",
    "sentence_variance": "sentence_variance",
    "duplicate_detection": "duplicate_content",
}


def _truthy_key(d: dict, key: str) -> bool:
    """Return True if config key is present and not None/False/empty."""
    if key not in d:
        return False
    v = d[key]
    return v not in (None, False, "")


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def enabled_rules(config: dict[str, Any]) -> list[str]:
    lint = config.get("lint", {}) or {}
    rules: list[str] = []
    if lint.get("tier1") == "default":
        rules.extend(TIER1_DEFAULT)
    tier2 = lint.get("tier2", {}) or {}
    for cfg_key, script_name in TIER2_CONFIG_KEYS.items():
        if _truthy_key(tier2, cfg_key):
            rules.append(script_name)
    tier3 = lint.get("tier3", {}) or {}
    for cfg_key, script_name in TIER3_CONFIG_KEYS.items():
        if _truthy_key(tier3, cfg_key):
            rules.append(script_name)
    return rules


def script_for(rule: str) -> Path:
    base = Path(__file__).parent
    if rule == "footnotes":
        return base / "footnotes.sh"
    return base / f"{rule}.py"


def run_rule(rule: str, config_path: Path, paths: list[Path]) -> dict:
    script = script_for(rule)
    if not script.exists():
        return {
            "rule": rule,
            "severity": "block",
            "results": [
                {
                    "path": str(p),
                    "ok": False,
                    "message": f"rule script missing: {script}",
                }
                for p in paths
            ],
        }
    if rule == "footnotes":
        cmd = ["bash", str(script), "--json", *[str(p) for p in paths]]
    else:
        cmd = [
            sys.executable,
            str(script),
            "--config",
            str(config_path),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not r.stdout.strip():
        return {
            "rule": rule,
            "severity": "block",
            "results": [
                {
                    "path": str(p),
                    "ok": False,
                    "message": f"empty output from {script}: {r.stderr[:200]}",
                }
                for p in paths
            ],
        }
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return {
            "rule": rule,
            "severity": "block",
            "results": [
                {
                    "path": str(p),
                    "ok": False,
                    "message": f"unparseable output: {e}",
                }
                for p in paths
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    rules = enabled_rules(config)

    aggregated: dict[str, Any] = {"version": "1", "results": []}
    any_block_failed = False
    for rule in rules:
        out = run_rule(rule, args.config, args.paths)
        aggregated["results"].append(out)
        if out.get("severity") == "block":
            if any(not r["ok"] for r in out["results"]):
                any_block_failed = True

    if args.json:
        json.dump(aggregated, sys.stdout)
    return 1 if any_block_failed else 0


if __name__ == "__main__":
    sys.exit(main())
