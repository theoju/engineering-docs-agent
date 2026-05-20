"""Orchestrator runner. Used by GitHub Actions and integration tests.

Calls subagents via the Claude Code CLI in production. In `--dry-run-subagents`
mode (used in tests), reads canned JSON outputs from a fixture directory
instead of invoking Claude.
"""

from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml


def load_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text()) or {}


def load_json(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text()) if p.exists() else {}


def dispatch_subagent(name: str, inputs: dict, *, dry_run_dir: Path | None) -> dict:
    """Dispatch a subagent. Returns parsed JSON output.

    In dry-run mode, reads from `<dry_run_dir>/fake_<name_with_underscores>.json`
    instead of invoking Claude.
    """
    if dry_run_dir is not None:
        fixture = dry_run_dir / f"fake_{name.replace('-', '_')}.json"
        if not fixture.exists():
            return {}
        return load_json(fixture)
    payload = json.dumps(inputs)
    r = subprocess.run(
        ["claude", "agent", name, "--input", payload],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"subagent {name} failed: {r.stderr[:500]}")
    return json.loads(r.stdout)


def run(repo_root: Path, *, dry_run_dir: Path | None, no_pr: bool) -> int:
    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    state_path = repo_root / ".engineering-docs-agent" / "state.json"
    if not cfg_path.exists():
        print("no config", file=sys.stderr)
        return 2

    config = load_yaml(cfg_path)
    state = load_json(state_path)
    state.setdefault("version", "1")

    head_sha = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        or "unknown"
    )

    now = datetime.now(timezone.utc).isoformat()
    state["current_run"] = {
        "started_at": now,
        "head_sha": head_sha,
        "partial": False,
        "partial_reasons": [],
    }

    sources = dispatch_subagent(
        "source-collector",
        {
            "last_sha": state.get("last_successful_run", {}).get("head_sha", ""),
            "head_sha": head_sha,
            "repo": {"owner": "x", "name": "y"},
            "pr_branch_filter": ["docs-agent/*"],
        },
        dry_run_dir=dry_run_dir,
    )

    prs = sources.get("prs", [])
    summaries = []
    for pr in prs:
        summary = dispatch_subagent(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": [],
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
            },
            dry_run_dir=dry_run_dir,
        )
        summaries.append(summary)

    # (Page authoring, validation, gap detection wiring goes here in Task 6.3.)

    state_path.write_text(json.dumps(state, indent=2))

    if no_pr:
        return 0
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    parser.add_argument("--no-pr", action="store_true")
    args = parser.parse_args()
    return run(args.repo_root, dry_run_dir=args.dry_run_subagents, no_pr=args.no_pr)


if __name__ == "__main__":
    sys.exit(main())
