"""Verify runner. Invoked by the post-merge workflow."""

from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

# Allow importing from sibling script.
sys.path.insert(0, str(Path(__file__).parent))
from orchestrator_runner import dispatch_subagent, load_yaml, load_json  # noqa: E402


def run(repo_root: Path, pr_number: int) -> int:
    cfg = load_yaml(repo_root / ".engineering-docs-agent" / "config.yml")
    state = load_json(repo_root / ".engineering-docs-agent" / "state.json")
    r = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "files"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    changed_paths = [f["path"] for f in json.loads(r.stdout).get("files", [])]
    verdict = dispatch_subagent(
        "publish-verifier",
        {
            "merged_pr_number": pr_number,
            "changed_paths": changed_paths,
            "publishing_config": cfg.get("publishing", {}),
            "repo": {"owner": "x", "name": "y"},
        },
        dry_run_dir=None,
    )
    dispatch_subagent(
        "notifier",
        {
            "digest": {
                "pr_url": f"https://github.com/x/y/pull/{pr_number}",
                "verified": verdict.get("verified", []),
                "failed_urls": verdict.get("failed", []),
                "build_status": verdict.get("build_status"),
            },
            "slack_config": cfg.get("notifications", {}).get("slack", {}),
            "email_config": cfg.get("notifications", {}).get("email", {}),
            "mode": "verify",
        },
        dry_run_dir=None,
    )
    if "current_run" in state:
        state["last_successful_run"] = {
            "completed_at": state["current_run"]["started_at"],
            "head_sha": state["current_run"]["head_sha"],
            "pr_number": pr_number,
        }
    (repo_root / ".engineering-docs-agent" / "state.json").write_text(
        json.dumps(state, indent=2)
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    args = parser.parse_args()
    return run(args.repo_root, args.pr_number)


if __name__ == "__main__":
    sys.exit(main())
