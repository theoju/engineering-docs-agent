"""Centralized gh CLI wrapper. Every gh call goes through here."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re
import subprocess
from typing import Any, Callable


@dataclass
class GhResult:
    ok: bool
    value: Any = None
    error: str | None = None


class GhClient:
    def __init__(self, repo_root: Path) -> None:
        self._cwd = repo_root

    def pr_view_files(self, pr_number: int) -> GhResult:
        return self._run_json(
            ["gh", "pr", "view", str(pr_number), "--json", "files"],
            extract=lambda d: [f["path"] for f in d.get("files", [])],
        )

    def pr_list_docs_agent_open(self) -> GhResult:
        """List all open PRs whose head branch starts with `docs-agent/`.

        CCE-89 D2: surface the candidate set for auto-close. Returns a list of
        dicts with `number` and `headRefName` keys for the auto-closer to
        iterate. Empty list is the no-prior-PRs case.
        """
        return self._run_json(
            [
                "gh",
                "pr",
                "list",
                "--search",
                "head:docs-agent/",
                "--state",
                "open",
                "--json",
                "number,headRefName",
                "-L",
                "50",
            ],
            extract=lambda d: list(d) if isinstance(d, list) else [],
        )

    def pr_view_commits(self, pr_number: int) -> GhResult:
        """Return commits + their authors for a PR.

        CCE-89 D2: fuel for the human-edit guard. Each list entry has an
        `authors` array of `{name, login, email}` dicts. The auto-closer
        skips a PR if any author looks human (no bot match).
        """
        return self._run_json(
            ["gh", "pr", "view", str(pr_number), "--json", "commits"],
            extract=lambda d: list(d.get("commits") or []),
        )

    def pr_checks(self, pr_number: int) -> GhResult:
        """CI check states for a PR, parsed per the CCE-83 vocabulary
        (name/state/bucket — never statusCheckRollup/conclusion).

        CCE-101: `gh pr checks` exit codes are data, not errors —
        0 = all green, 8 = pending, 1 = failing OR "no checks reported".
        Deliberately NOT routed through _run_json (check=True would turn
        a pending poll into an exception). "No checks reported" maps to
        ok-with-[] so the caller's zero-checks grace path can decide.
        """
        try:
            r = subprocess.run(
                ["gh", "pr", "checks", str(pr_number), "--json", "name,state,bucket"],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if "no checks reported" in (r.stderr or "").lower():
            return GhResult(ok=True, value=[])
        try:
            data = json.loads(r.stdout or "null")
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return GhResult(ok=True, value=data)
        return GhResult(
            ok=False,
            error=f"gh_pr_checks_failed: rc={r.returncode} {(r.stderr or '')[:200]}",
        )

    def pr_close(self, pr_number: int, comment: str) -> GhResult:
        """Close a PR with an explanatory comment.

        CCE-89 D2: the spec mandates a fixed comment text on auto-close so
        operators see why the PR was closed without paging in the runbook.
        """
        try:
            r = subprocess.run(
                [
                    "gh",
                    "pr",
                    "close",
                    str(pr_number),
                    "--comment",
                    comment,
                ],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if r.returncode != 0:
            return GhResult(
                ok=False,
                error=f"gh_pr_close_failed: {(r.stderr or '')[:200]}",
            )
        return GhResult(ok=True, value=pr_number)

    def pr_list_for_branch(self, branch: str) -> GhResult:
        return self._run_json(
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
            extract=lambda d: d[0]["number"] if d else None,
        )

    def pr_create(self, branch: str, title: str, body: str) -> GhResult:
        try:
            r = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--head",
                    branch,
                    "--title",
                    title,
                    "--body",
                    body,
                ],
                cwd=self._cwd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        if r.returncode != 0:
            return GhResult(
                ok=False, error=f"gh_pr_create_failed: {(r.stderr or '')[:200]}"
            )
        return self._parse_pr_create_output(r.stdout, branch)

    def _parse_pr_create_output(self, stdout: str, branch: str) -> GhResult:
        last = stdout.strip().split("/")[-1] if stdout.strip() else ""
        if last.isdigit():
            return GhResult(ok=True, value=int(last))
        m = re.search(r"/pull/(\d+)", stdout)
        if m:
            return GhResult(ok=True, value=int(m.group(1)))
        fallback = self.pr_list_for_branch(branch)
        if fallback.ok and fallback.value is not None:
            return fallback
        return GhResult(ok=False, error=f"gh_pr_create_unparseable: {stdout[:200]}")

    def _run_json(self, cmd: list[str], *, extract: Callable[[Any], Any]) -> GhResult:
        try:
            r = subprocess.run(
                cmd, cwd=self._cwd, capture_output=True, text=True, check=True
            )
        except FileNotFoundError:
            return GhResult(ok=False, error="gh_not_installed")
        except subprocess.CalledProcessError as e:
            return GhResult(ok=False, error=f"gh_failed: {(e.stderr or '')[:200]}")
        try:
            data = json.loads(r.stdout or "null")
        except json.JSONDecodeError as e:
            return GhResult(ok=False, error=f"gh_bad_json: {e}")
        return GhResult(ok=True, value=extract(data))


class FakeGhClient:
    """Test injection point. Constructor takes canned GhResult per method."""

    def __init__(
        self,
        *,
        pr_view_files: GhResult | None = None,
        pr_list_for_branch: GhResult | None = None,
        pr_create: GhResult | None = None,
        pr_list_docs_agent_open: GhResult | None = None,
        pr_view_commits: GhResult | None = None,
        pr_close: GhResult | None = None,
    ) -> None:
        self._canned = {
            "pr_view_files": pr_view_files,
            "pr_list_for_branch": pr_list_for_branch,
            "pr_create": pr_create,
            "pr_list_docs_agent_open": pr_list_docs_agent_open,
            "pr_view_commits": pr_view_commits,
            "pr_close": pr_close,
        }
        self.calls: list[tuple[str, tuple]] = []

    def pr_view_files(self, pr_number: int) -> GhResult:
        self.calls.append(("pr_view_files", (pr_number,)))
        return self._canned["pr_view_files"] or GhResult(ok=True, value=[])

    def pr_list_for_branch(self, branch: str) -> GhResult:
        self.calls.append(("pr_list_for_branch", (branch,)))
        return self._canned["pr_list_for_branch"] or GhResult(ok=True, value=None)

    def pr_create(self, branch: str, title: str, body: str) -> GhResult:
        self.calls.append(("pr_create", (branch, title, body)))
        return self._canned["pr_create"] or GhResult(ok=True, value=1)

    def pr_list_docs_agent_open(self) -> GhResult:
        self.calls.append(("pr_list_docs_agent_open", ()))
        return self._canned["pr_list_docs_agent_open"] or GhResult(ok=True, value=[])

    def pr_view_commits(self, pr_number: int) -> GhResult:
        self.calls.append(("pr_view_commits", (pr_number,)))
        return self._canned["pr_view_commits"] or GhResult(ok=True, value=[])

    def pr_close(self, pr_number: int, comment: str) -> GhResult:
        self.calls.append(("pr_close", (pr_number, comment)))
        return self._canned["pr_close"] or GhResult(ok=True, value=pr_number)
