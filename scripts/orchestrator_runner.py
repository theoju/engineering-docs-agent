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

from state_io import add_partial, load_voice_samples, resolve_lens


def detect_repo(repo_root: Path) -> dict[str, str]:
    """Detect GitHub owner/name from git remote or GITHUB_REPOSITORY env."""
    import os

    if env := os.environ.get("GITHUB_REPOSITORY"):
        if "/" in env:
            owner, name = env.split("/", 1)
            return {"owner": owner, "name": name}
    r = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    url = r.stdout.strip()
    # Parse github.com/<owner>/<name> from ssh or https URLs.
    import re

    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if m:
        return {"owner": m.group(1), "name": m.group(2)}
    return {"owner": "unknown", "name": "unknown"}


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
    voice_samples = load_voice_samples(repo_root, config)
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

    repo = detect_repo(repo_root)

    now = datetime.now(timezone.utc).isoformat()
    state["current_run"] = {
        "started_at": now,
        "head_sha": head_sha,
        "partial": False,
        "partial_reasons": [],
    }

    jira_payload = config.get("sources", {}).get("jira")
    sc_inputs = {
        "last_sha": state.get("last_successful_run", {}).get("head_sha", ""),
        "head_sha": head_sha,
        "repo": repo,
        "pr_branch_filter": ["docs-agent/*"],
    }
    if jira_payload:
        sc_inputs["jira"] = jira_payload
    sources = dispatch_subagent("source-collector", sc_inputs, dry_run_dir=dry_run_dir)

    prs = sources.get("prs", [])
    jira_issues = sources.get("jira_issues", []) or []
    jira_lookup = {issue["key"]: issue for issue in jira_issues}

    summaries = []
    for pr in prs:
        jira_context = [
            jira_lookup[k] for k in pr.get("jira_keys", []) if k in jira_lookup
        ]
        summary = dispatch_subagent(
            "pr-summarizer",
            {
                "pr": pr,
                "jira_context": jira_context,
                "lens_names": list(config.get("docs", {}).get("lens_paths", {}).keys()),
            },
            dry_run_dir=dry_run_dir,
        )
        summaries.append(summary)

    # Page authoring: aggregate doc_targets per lens.
    import fnmatch

    editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
    per_lens: dict[str, list[dict]] = {}
    for s in summaries:
        for t in s.get("doc_targets", []):
            per_lens.setdefault(t["lens"], []).append({"target": t, "summary": s})

    authored: list[str] = []
    for lens, batch in per_lens.items():
        try:
            lens_path, _opts = resolve_lens(config, lens)
        except KeyError:
            for item in batch:
                add_partial(state, f"unknown_lens: {lens}")
            continue
        for item in batch:
            t = item["target"]
            target_path = repo_root / lens_path / t["page_hint"]
            try:
                rel = target_path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                add_partial(state, f"unsafe_page_path: {t['page_hint']}")
                continue
            if editable_globs and not any(
                fnmatch.fnmatch(str(rel), g) for g in editable_globs
            ):
                add_partial(state, f"unsafe_page_path: {rel}")
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            out = dispatch_subagent(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": t["action"],
                    "lens": lens,
                    "summaries": [item["summary"]],
                    "voice_samples": voice_samples,
                    "frontmatter_template": {
                        "status": "draft",
                        "sources": [
                            pr.get("url")
                            for pr in prs
                            if pr.get("number") == item["summary"].get("pr_number")
                        ],
                        "synthesized_into": [],
                    },
                },
                dry_run_dir=dry_run_dir,
            )
            if out.get("ok"):
                authored.append(str(target_path))
                if dry_run_dir and not target_path.exists():
                    target_path.write_text(
                        "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n"
                        f"# {t['page_hint']}\n\nGenerated by docs-agent.\n"
                    )

    # Content validation
    if authored:
        validation = dispatch_subagent(
            "content-validator",
            {
                "paths": authored,
                "config_path": str(cfg_path),
                "voice_samples": voice_samples,
            },
            dry_run_dir=dry_run_dir,
        )
        for fail in validation.get("failed", []):
            if fail.get("severity") == "block":
                fail_path = Path(fail["path"])
                # Interpret relative paths as repo-relative (some subagent
                # implementations may strip the repo prefix from echoed paths).
                if not fail_path.is_absolute():
                    fail_path = repo_root / fail_path
                # Verify path is inside repo_root before any destructive op.
                try:
                    fail_path.resolve().relative_to(repo_root.resolve())
                except ValueError:
                    state["current_run"]["partial"] = True
                    state["current_run"]["partial_reasons"].append(
                        f"lint_block_unsafe_path: {fail['path']} (outside repo)"
                    )
                    continue
                # If the file exists in HEAD, restore it (edit case).
                # If not (create case), remove it.
                in_head = (
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(repo_root),
                            "cat-file",
                            "-e",
                            f"HEAD:{fail_path.relative_to(repo_root)}",
                        ],
                        capture_output=True,
                    ).returncode
                    == 0
                )
                if in_head:
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(repo_root),
                            "checkout",
                            "HEAD",
                            "--",
                            str(fail_path.relative_to(repo_root)),
                        ],
                        check=False,
                    )
                else:
                    fail_path.unlink(missing_ok=True)
                state["current_run"]["partial"] = True
                state["current_run"]["partial_reasons"].append(
                    f"lint_block: {fail['path']} {fail['rule']}: {fail['message']}"
                )

    # Archive index regeneration
    import archive_indexes

    for lens in config.get("docs", {}).get("lens_paths", {}):
        try:
            lens_path, opts = resolve_lens(config, lens)
        except KeyError:
            continue
        if opts.get("archive_index"):
            archive_indexes.regenerate(repo_root / lens_path)

    # Gap detection
    dismissed = set(state.get("dismissed_gap_flags", {}).keys())
    gap_verdicts = []
    for pr in prs:
        pr_id = f"{repo['owner']}/{repo['name']}#{pr['number']}"
        if pr_id in dismissed:
            continue
        verdict = dispatch_subagent(
            "gap-detector",
            {
                "pr_id": pr_id,
                "pr": pr,
                "config": {
                    "allowlist_paths": config.get("gap_detection", {}).get(
                        "allowlist_paths", []
                    ),
                    "size_filter": config.get("gap_detection", {}).get(
                        "size_filter", {}
                    ),
                },
                "dismissed_flags": list(dismissed),
            },
            dry_run_dir=dry_run_dir,
        )
        gap_verdicts.append(verdict)

    # Prepend What's New entry
    whats_new = repo_root / config["docs"]["whats_new_file"]
    whats_new.parent.mkdir(parents=True, exist_ok=True)
    entry_lines = [f"## {now}"]
    for s in summaries:
        entry_lines.append(f"- PR #{s.get('pr_number')}: {s.get('what_changed', '')}")
    gaps_flagged = [v for v in gap_verdicts if v.get("needs_spec")]
    if gaps_flagged:
        entry_lines.append("### Gaps flagged")
        for g in gaps_flagged:
            entry_lines.append(f"- {g['pr_id']}: {g['reasoning']}")
    entry = "\n".join(entry_lines) + "\n\n"
    existing = whats_new.read_text() if whats_new.exists() else ""
    whats_new.write_text(entry + existing)

    state["current_run"]["pr_number"] = None
    state_path.write_text(json.dumps(state, indent=2))
    if no_pr:
        return 0
    branch = branch_name(now)
    pr_number = open_or_append_pr(
        repo_root,
        branch=branch,
        now_iso=now,
        partial=state["current_run"]["partial"],
        partial_reasons=state["current_run"]["partial_reasons"],
    )
    if pr_number is None:
        return 1
    state["current_run"]["pr_number"] = pr_number
    state_path.write_text(json.dumps(state, indent=2))

    # Compose digest and dispatch notifier.
    digest = {
        "pr_url": f"https://github.com/{repo['owner']}/{repo['name']}/pull/{pr_number}",
        "run_summary_bullets": [
            f"PR #{s.get('pr_number')}: {s.get('what_changed', '')}" for s in summaries
        ],
        "gap_flags": [
            {"pr_id": v["pr_id"], "reasoning": v["reasoning"]}
            for v in gap_verdicts
            if v.get("needs_spec")
        ],
        "lint_failures": state["current_run"]["partial_reasons"],
        "partial_reasons": state["current_run"]["partial_reasons"],
    }
    dispatch_subagent(
        "notifier",
        {
            "digest": digest,
            "slack_config": config.get("notifications", {}).get("slack", {}),
            "email_config": config.get("notifications", {}).get("email", {}),
            "mode": "run",
        },
        dry_run_dir=dry_run_dir,
    )
    return 0


def branch_name(now_iso: str) -> str:
    return f"docs-agent/{now_iso[:10]}"


def existing_pr_for_branch(repo_root: Path, branch: str) -> int | None:
    r = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number",
            "-L",
            "1",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    items = json.loads(r.stdout or "[]")
    return items[0]["number"] if items else None


def open_or_append_pr(
    repo_root: Path,
    *,
    branch: str,
    now_iso: str,
    partial: bool,
    partial_reasons: list[str],
) -> int | None:
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-B", branch], check=True)
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True)
    commit_msg = f"docs(agent): run {now_iso}"
    if partial:
        commit_msg += " (partial)"
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", commit_msg], check=False
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "push", "-u", "origin", branch], check=True
    )
    existing = existing_pr_for_branch(repo_root, branch)
    if existing:
        return existing
    body = (
        "WARNING — Partial run — " + "; ".join(partial_reasons)
        if partial
        else "docs-agent run"
    )
    r = subprocess.run(
        ["gh", "pr", "create", "--head", branch, "--title", commit_msg, "--body", body],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    return int(r.stdout.strip().split("/")[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--dry-run-subagents", type=Path, default=None)
    parser.add_argument("--no-pr", action="store_true")
    args = parser.parse_args()
    return run(args.repo_root, dry_run_dir=args.dry_run_subagents, no_pr=args.no_pr)


if __name__ == "__main__":
    sys.exit(main())
