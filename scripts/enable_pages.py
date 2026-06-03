#!/usr/bin/env python3
"""Bootstrap GitHub Pages on a host repo with build_type=workflow.

The setup skill's step 6c calls this once during scaffolding because
actions/configure-pages@v6 with `enablement: true` does NOT actually
work on first deploy — the workflow's GITHUB_TOKEN lacks admin scope
to create a Pages site (`permissions:` blocks can only restrict
default-token scopes, never expand them). The user's admin `gh` auth
does have the required scope.

Behaviors (all return exit 0 — scaffolding must never block on this):
  201 + non-empty JSON body: print "✓ Pages enabled", return 0.
  409 (matched by literal "(HTTP 409)" in stderr, not bare substring):
      print "✓ Pages already enabled (idempotent)", return 0.
  gh not on PATH: print "⚠ `gh` CLI not found" + manual recovery,
      return 0.
  Any other failure (401, 403, 422, 500, exit 139, exit 0 with empty
      body, etc.): print "⚠ Could not enable Pages" + manual recovery
      + the actual error, return 0.

Exit codes:
  0: any of the above behaviors completed.
  2: argument or environment error (missing/empty --owner/--repo).

Reference: CCE-82. See skills/engineering-docs-agent-setup/SKILL.md
step 6c."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys


_RECOVERY_TEMPLATE = (
    "    gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow"
)


def enable_pages(owner: str, repo: str) -> int:
    if not owner or not repo:
        print(
            "✗ --owner and --repo must both be non-empty.",
            file=sys.stderr,
        )
        return 2
    if shutil.which("gh") is None:
        print(
            "⚠ `gh` CLI not found on PATH. Pages must be enabled manually before "
            "first deploy:\n"
            + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
            + "\nContinuing with the rest of scaffolding."
        )
        return 0
    proc = subprocess.run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{repo}/pages",
            "-f",
            "build_type=workflow",
        ],
        capture_output=True,
        text=True,
    )
    # Detect 409 with literal "(HTTP 409)" — matches gh's actual stderr format
    # "gh: ... (HTTP 409)" and avoids false positives from JSON bodies
    # containing `"status":"409"` or prose containing `"already exists"`.
    is_409 = bool(re.search(r"\(HTTP 409\)", proc.stderr))
    if proc.returncode == 0 and proc.stdout.strip():
        # Real Pages creation returns a JSON body with html_url; require
        # non-empty so a network-glitched empty-body exit-0 doesn't
        # false-positive as success.
        print(f"✓ Pages enabled (https://{owner}.github.io/{repo}/)")
        return 0
    if is_409:
        print("✓ Pages already enabled (idempotent)")
        return 0
    err_summary = (proc.stderr or proc.stdout or "(no output)").strip()[:300]
    print(
        "⚠ Could not enable Pages programmatically. Run this manually before first deploy:\n"
        + _RECOVERY_TEMPLATE.format(owner=owner, repo=repo)
        + f"\n(gh exit {proc.returncode}; error: {err_summary})\n"
        + "Continuing with the rest of scaffolding."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bootstrap GitHub Pages on a host repo with build_type=workflow."
    )
    p.add_argument("--owner", required=True, help="GitHub owner (user or org).")
    p.add_argument("--repo", required=True, help="Repository name.")
    args = p.parse_args()
    return enable_pages(args.owner, args.repo)


if __name__ == "__main__":
    sys.exit(main())
