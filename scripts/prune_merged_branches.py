"""CCE-90: prune local branches whose origin counterpart is gone.

Standalone CLI helper. Solves the recurring local-branch sprawl observed
in the 2026-06-04 sweep (13 stale refs, 5 [gone] + 9 worktree-* orphans).
The actual prevention surfaces are out of scope for this repo's PR cycle:

- /ship post-merge prune lives at ~/.claude/skills/ship/ — tracked by
  CCE-99 (user-global skill edit, non-durable).
- Worktree-orphan cleanup lives in the Workflow tool's isolation mode —
  tracked by CCE-100 (upstream/runtime).

This helper is the in-repo floor: run periodically (or after each batch
of merges in a session) to keep the local branch list at the post-sweep
baseline (~3 branches on a clean workspace).

Usage:
    python3 scripts/prune_merged_branches.py            # dry-run report
    python3 scripts/prune_merged_branches.py --apply    # actually delete
    python3 scripts/prune_merged_branches.py --apply --force-unmerged

Modes:
    - default: list pruneable branches without touching anything.
    - --apply: delete safe-merged + worktree orphans (worktree orphans
      get force-delete since their commits never landed on main by
      design — the Workflow tool's isolation mode creates them as
      throwaway scratch).
    - --force-unmerged: also force-delete branches whose tip is not in
      main's history. Off by default — typical [gone] branches are
      squash-merged so their commits don't appear in main's log; -d
      refuses, the helper safe-skips. Use this flag only if you have
      eyeballed the skip list and confirmed the unmerged refs are
      stranded work you don't need.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROTECT = ("main", "master", "develop")
WORKTREE_ORPHAN_PREFIXES = ("worktree-",)


@dataclass(frozen=True)
class Branch:
    """A local branch the helper has classified as pruneable."""

    name: str
    sha: str
    reason: str  # "gone" | "worktree_orphan"


@dataclass(frozen=True)
class PruneResult:
    """Outcome of attempting to delete a single branch."""

    ok: bool
    action: str  # "deleted" | "force_deleted" | "skipped_unmerged" | "failed"
    error: str = ""


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


def _current_branch(repo_root: Path) -> str:
    r = _run(["git", "branch", "--show-current"], repo_root)
    return r.stdout.strip() if r.returncode == 0 else ""


def _all_local_branches(repo_root: Path) -> list[tuple[str, str, str]]:
    """Return [(name, sha, upstream_track)] for every local branch.

    upstream_track is git's `%(upstream:track)` — `[gone]`, `[ahead 2]`,
    `[behind 3]`, `[ahead 1, behind 2]`, or empty string. The `[gone]`
    marker is the canonical post-`gh pr merge --delete-branch` signal.
    """
    r = _run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname:short)\t%(objectname)\t%(upstream:track)",
            "refs/heads/",
        ],
        repo_root,
    )
    if r.returncode != 0:
        return []
    out: list[tuple[str, str, str]] = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        sha = parts[1].strip()
        track = parts[2].strip() if len(parts) > 2 else ""
        out.append((name, sha, track))
    return out


def find_pruneable_branches(
    repo_root: Path,
    *,
    protect: tuple[str, ...] = DEFAULT_PROTECT,
    worktree_prefixes: tuple[str, ...] = WORKTREE_ORPHAN_PREFIXES,
) -> list[Branch]:
    """Classify every local branch and return the pruneable subset.

    A branch is pruneable when:
      - Its upstream tracks the gone state ([gone] marker), OR
      - Its name matches a worktree-orphan prefix.

    Exclusions: protected names (main/master/develop by default), the
    currently checked-out branch (deleting it would orphan the working
    tree), and anything failing the basic git invariants.
    """
    current = _current_branch(repo_root)
    protected = set(protect)
    out: list[Branch] = []
    for name, sha, track in _all_local_branches(repo_root):
        if name in protected:
            continue
        if name == current:
            continue
        if track.lower() == "[gone]":
            out.append(Branch(name=name, sha=sha, reason="gone"))
            continue
        if any(name.startswith(p) for p in worktree_prefixes):
            out.append(Branch(name=name, sha=sha, reason="worktree_orphan"))
    return out


def prune_branch(
    repo_root: Path, branch: Branch, *, force: bool = False
) -> PruneResult:
    """Attempt to delete a single branch.

    Strategy by `branch.reason`:
      - `gone`: try `git branch -d`. On refusal (unmerged tip), respect
        the safe-skip default unless `force=True` is passed explicitly.
      - `worktree_orphan`: go straight to `git branch -D`. The Workflow
        tool's isolation worktrees are throwaway scratch by design;
        their commits never reach main, so `-d` would always refuse —
        making the worktree case the one place auto-escalation is
        justified.
    """
    if branch.reason == "worktree_orphan":
        r = _run(["git", "branch", "-D", branch.name], repo_root)
        if r.returncode == 0:
            return PruneResult(ok=True, action="force_deleted")
        return PruneResult(ok=False, action="failed", error=r.stderr.strip()[:200])

    safe = _run(["git", "branch", "-d", branch.name], repo_root)
    if safe.returncode == 0:
        return PruneResult(ok=True, action="deleted")

    stderr = safe.stderr.strip()
    if not force:
        return PruneResult(ok=True, action="skipped_unmerged", error=stderr[:200])

    force_r = _run(["git", "branch", "-D", branch.name], repo_root)
    if force_r.returncode == 0:
        return PruneResult(ok=True, action="force_deleted")
    return PruneResult(ok=False, action="failed", error=force_r.stderr.strip()[:200])


def _emit_report(
    branches: list[Branch], outcomes: list[tuple[Branch, PruneResult]] | None
) -> None:
    """Print a structured report to stdout. Dry-run mode passes
    `outcomes=None`; apply mode passes the per-branch results."""
    if not branches:
        print("nothing to prune: 0 branches matched.")
        return

    if outcomes is None:
        print(f"dry-run: {len(branches)} branch(es) would be evaluated:")
        for b in branches:
            print(f"  - {b.name} ({b.reason}) @ {b.sha[:8]}")
        print("\nRe-run with --apply to delete.")
        return

    print(f"apply: {len(outcomes)} branch(es) evaluated:")
    for b, result in outcomes:
        if result.action == "deleted":
            print(f"  - {b.name} ({b.reason}): deleted")
        elif result.action == "force_deleted":
            print(f"  - {b.name} ({b.reason}): force-deleted")
        elif result.action == "skipped_unmerged":
            print(
                f"  - {b.name} ({b.reason}): skipped (unmerged commits; "
                f"re-run with --force-unmerged after manual review)"
            )
        else:
            print(f"  - {b.name} ({b.reason}): failed: {result.error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prune local branches whose origin counterpart is gone, plus "
            "worktree-* orphan refs. Dry-run by default."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: current directory).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete branches. Default is dry-run.",
    )
    parser.add_argument(
        "--force-unmerged",
        action="store_true",
        help=(
            "Force-delete [gone] branches whose tip is not in main's "
            "history. Off by default — squash-merged branches typically "
            "look unmerged to git -d but ARE landed."
        ),
    )
    parser.add_argument(
        "--protect",
        default=",".join(DEFAULT_PROTECT),
        help=(
            "Comma-separated list of branch names to never prune. "
            f"Default: {','.join(DEFAULT_PROTECT)}."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    protect = tuple(p.strip() for p in args.protect.split(",") if p.strip())

    branches = find_pruneable_branches(repo_root, protect=protect)

    if not args.apply:
        _emit_report(branches, outcomes=None)
        return 0

    outcomes: list[tuple[Branch, PruneResult]] = []
    for b in branches:
        result = prune_branch(repo_root, b, force=args.force_unmerged)
        outcomes.append((b, result))
    _emit_report(branches, outcomes=outcomes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
