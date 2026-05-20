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
    ) -> None:
        self._canned = {
            "pr_view_files": pr_view_files,
            "pr_list_for_branch": pr_list_for_branch,
            "pr_create": pr_create,
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
