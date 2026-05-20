"""Verify runner. Invoked by the post-merge workflow."""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path

# Allow importing from sibling script.
sys.path.insert(0, str(Path(__file__).parent))
from gh_client import GhClient  # noqa: E402
from orchestrator_runner import detect_repo, dispatch_subagent, dispatch_validated  # noqa: E402
from state_io import (  # noqa: E402
    ConfigError,
    StateError,
    load_config_validated,
    load_state_validated,
)


def run(repo_root: Path, pr_number: int, *, dry_run_dir: Path | None = None) -> int:
    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    state_path_arg = repo_root / ".engineering-docs-agent" / "state.json"
    try:
        cfg = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2
    try:
        state = load_state_validated(state_path_arg)
    except StateError as e:
        print(f"state invalid: {e}", file=sys.stderr)
        return 2

    repo = detect_repo(repo_root)

    gh = GhClient(repo_root)
    view = gh.pr_view_files(pr_number)
    if not view.ok:
        if dry_run_dir is None:
            # Fire-and-forget: return value discarded, no state to thread reasons into.
            dispatch_subagent(
                "notifier",
                {
                    "digest": {
                        "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
                        "build_status": "verify_runner_error",
                        "failed_urls": [],
                        "partial_reasons": [view.error or "gh failed"],
                    },
                    "slack_config": cfg.get("notifications", {}).get("slack", {}),
                    "email_config": cfg.get("notifications", {}).get("email", {}),
                    "mode": "verify",
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
            return 1
        # dry-run mode tolerates missing gh; proceed with empty changed_paths
        changed_paths: list[str] = []
    else:
        changed_paths = view.value or []

    state_path = repo_root / ".engineering-docs-agent" / "state.json"
    try:
        verdict, verify_reasons = dispatch_validated(
            "publish-verifier",
            {
                "merged_pr_number": pr_number,
                "changed_paths": changed_paths,
                "publishing_config": cfg.get("publishing", {}),
                "repo": repo,
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in verify_reasons:
            state.setdefault("current_run", {}).setdefault(
                "partial_reasons", []
            ).append(r)
            state["current_run"]["partial"] = True
        if verdict is None:
            verdict = {"verified": [], "failed": [], "build_status": "verifier_invalid"}
        _notifier_result, notifier_reasons = dispatch_validated(
            "notifier",
            {
                "digest": {
                    "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
                    "verified": verdict.get("verified", []),
                    "failed_urls": verdict.get("failed", []),
                    "build_status": verdict.get("build_status"),
                },
                "slack_config": cfg.get("notifications", {}).get("slack", {}),
                "email_config": cfg.get("notifications", {}).get("email", {}),
                "mode": "verify",
            },
            dry_run_dir=dry_run_dir,
            cwd=repo_root,
        )
        for r in notifier_reasons:
            state.setdefault("current_run", {}).setdefault(
                "partial_reasons", []
            ).append(r)
            state["current_run"]["partial"] = True

        failed_urls = verdict.get("failed", [])
        build_status = verdict.get("build_status")
        verify_succeeded = not failed_urls and build_status == "success"

        if verify_succeeded and "current_run" in state:
            state["last_successful_run"] = {
                "completed_at": state["current_run"]["started_at"],
                "head_sha": state["current_run"]["head_sha"],
                "pr_number": pr_number,
            }
            state.pop("current_run", None)
        return 0 if verify_succeeded else 1
    finally:
        state_path.write_text(json.dumps(state, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    args = parser.parse_args()
    return run(args.repo_root, args.pr_number, dry_run_dir=args.dry_run_subagents)


if __name__ == "__main__":
    sys.exit(main())
