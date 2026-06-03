"""Behavioral coverage of scripts/enable_pages.py — all four failure-mode
branches plus the substring-false-positive risk and the argv contract.

The test installs a `gh` stub in tmp_path/bin and PATH-shadows the real
binary. Real gh exits 1 on all HTTP 4xx (not 4 or 22 — those would be
curl-style codes); the stub mimics this. Each stub also writes its argv
to a side-channel file so the test can assert the script invokes gh with
the expected `repos/<owner>/<repo>/pages` path + `build_type=workflow`
form-field. Without that argv assertion a future refactor swapping owner
and repo would pass every other test.

Reference: CCE-82. See SKILL.md step 6c and scripts/enable_pages.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "enable_pages.py"


def _install_gh_stub(
    bin_dir: Path,
    exit_code: int,
    stdout: str,
    stderr: str,
    argv_capture: Path | None = None,
) -> None:
    """Write a shell script named `gh` that exits with the given code/output.

    If argv_capture is set, the stub writes its full argv to that file so
    tests can assert the script invoked gh with the expected arguments.

    The stderr in real gh follows `gh: <message> (HTTP <code>)` — tests
    that simulate HTTP errors should include the literal `(HTTP NNN)`
    substring in `stderr` to match the script's detection logic.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gh"
    capture = f'printf "%s\\n" "$@" > {argv_capture}\n' if argv_capture else ""
    stub.write_text(
        f"#!/bin/sh\n"
        f"{capture}"
        f"cat >&2 <<'STDERR_EOF'\n{stderr}\nSTDERR_EOF\n"
        f"cat <<'STDOUT_EOF'\n{stdout}\nSTDOUT_EOF\n"
        f"exit {exit_code}\n"
    )
    stub.chmod(0o755)


def _run_cli(
    bin_dir: Path,
    owner: str = "octocat",
    repo: str = "sample",
) -> subprocess.CompletedProcess:
    """Run scripts/enable_pages.py with PATH containing only the stub dir
    (plus the inherited PATH appended). This is per-process so it survives
    pytest-xdist if that's ever added to the suite."""
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return subprocess.run(
        [sys.executable, str(_CLI), "--owner", owner, "--repo", repo],
        capture_output=True,
        text=True,
        env=env,
    )


# --- Happy path ---


def test_happy_path_201_prints_success_and_returns_zero(tmp_path):
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"https://octocat.github.io/sample/","build_type":"workflow"}',
        stderr="",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, proc.stderr
    assert "✓ Pages enabled" in proc.stdout
    assert "octocat.github.io/sample" in proc.stdout


def test_argv_carries_correct_path_and_build_type(tmp_path):
    """Highest-leverage hardening: a future refactor that swaps owner/repo
    or drops `-f build_type=workflow` would still pass every other test
    because the stub ignores argv. This test asserts gh was called with
    the right path components and the build_type form-field."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    _run_cli(tmp_path / "bin", owner="my-org", repo="some-repo")
    argv = argv_file.read_text().splitlines()
    # ["api", "-X", "POST", "repos/my-org/some-repo/pages", "-f", "build_type=workflow"]
    assert "repos/my-org/some-repo/pages" in argv, f"argv was: {argv}"
    assert "build_type=workflow" in argv, f"argv was: {argv}"
    assert "POST" in argv
    assert "api" in argv


# --- 409 idempotent ---


def test_already_enabled_409_is_idempotent(tmp_path):
    # Real gh stderr format: "gh: <message> (HTTP 409)" — the literal
    # "(HTTP 409)" substring (with parens) is what the script matches.
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,  # gh exits 1 on HTTP 4xx regardless of HTTP code
        stdout="",
        stderr="gh: Pages site already created (HTTP 409)",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" in proc.stdout.lower()
    assert "⚠" not in proc.stdout  # not a warning path


def test_409_substring_false_positive_is_not_classified_as_idempotent(tmp_path):
    """A 500 whose error body QUOTES `HTTP 409` (or contains the bare
    phrase `already exists` in unrelated prose) must NOT be classified
    as idempotent. The script uses re.search(r"\\(HTTP 409\\)", stderr) —
    literal parens, so this 500 reaches the graceful-fallback branch."""
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=1,
        stdout="",
        stderr="gh: Internal Server Error: previous request returned HTTP 409 - not retried (HTTP 500)",
    )
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0
    assert "already enabled" not in proc.stdout.lower(), proc.stdout
    assert "⚠ Could not enable" in proc.stdout


# --- Fallback path (all non-201/409 cases collapse to graceful fallback) ---


@pytest.mark.parametrize(
    "exit_code,stderr",
    [
        (1, "gh: Resource not accessible by integration (HTTP 403)"),
        (1, "gh: Unauthorized (HTTP 401)"),
        (1, "gh: Validation failed (HTTP 422)"),
        (1, "gh: Internal Server Error (HTTP 500)"),
        (139, ""),  # segfault — empty stderr
        (0, ""),  # exit 0 but empty body — could be proxy interception
    ],
    ids=[
        "403_auth",
        "401_unauth",
        "422_validation",
        "500_server",
        "139_segfault",
        "0_empty_body",
    ],
)
def test_all_non_201_non_409_paths_fall_back_gracefully(tmp_path, exit_code, stderr):
    _install_gh_stub(tmp_path / "bin", exit_code=exit_code, stdout="", stderr=stderr)
    proc = _run_cli(tmp_path / "bin")
    assert proc.returncode == 0, "must never block scaffolding"
    assert "⚠ Could not enable Pages" in proc.stdout
    assert (
        "gh api -X POST repos/octocat/sample/pages -f build_type=workflow"
        in proc.stdout
    )
    assert "Continuing" in proc.stdout


# --- gh missing ---


def test_gh_missing_prints_recovery_and_returns_zero(tmp_path):
    # PATH intentionally empty-except-for-stub-dir to force shutil.which('gh') -> None
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(empty_bin)
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--owner", "octocat", "--repo", "sample"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "`gh` CLI not found" in proc.stdout
    assert "gh api -X POST repos/octocat/sample/pages" in proc.stdout


# --- Argparse boundary ---


def test_missing_args_returns_nonzero(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_CLI)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    # argparse default is exit 2 on missing required
    assert "owner" in proc.stderr.lower() or "owner" in proc.stdout.lower()


def test_empty_owner_or_repo_rejected_with_exit_2(tmp_path):
    """argparse `required=True` only guards missingness, not empty strings.
    The script rejects empty strings explicitly, otherwise it would POST
    to `repos//<repo>/pages` and confuse gh."""
    for args in [["--owner", "", "--repo", "x"], ["--owner", "x", "--repo", ""]]:
        proc = subprocess.run(
            [sys.executable, str(_CLI), *args],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2, (
            f"expected exit 2 for empty owner/repo, args={args}, got {proc.returncode}"
        )


# --- Argparse cosmetics ---


def test_owner_with_hyphen_works(tmp_path):
    """argparse handles hyphens in values fine; pin the contract so a
    future refactor that adds a stripping step would break this test."""
    argv_file = tmp_path / "gh.argv"
    _install_gh_stub(
        tmp_path / "bin",
        exit_code=0,
        stdout='{"html_url":"x"}',
        stderr="",
        argv_capture=argv_file,
    )
    proc = _run_cli(
        tmp_path / "bin",
        owner="my-cool-org-name",
        repo="repo-with-dashes",
    )
    assert proc.returncode == 0
    argv = argv_file.read_text().splitlines()
    assert "repos/my-cool-org-name/repo-with-dashes/pages" in argv
