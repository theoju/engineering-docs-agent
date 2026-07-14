"""CCE-121: the partial-reasons digest header must reflect the run's `partial`
FLAG, not merely the presence of reasons.

After CCE-118, `partial_reasons` also carries info_only advisory reasons
(benign prose-contamination rescues) that deliberately do NOT flip `partial`.
A non-partial run (which auto-merges under the CCE-101 gate) must therefore
NOT render those reasons under a "WARNING — Partial run" header — that
mislabels a clean run. It renders an INFO/advisory header instead. A genuinely
partial run keeps the warning header.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

_WARN = "WARNING — Partial run"
_INFO = "INFO — advisory notices (run not partial)"


# ---------- the shared formatter ----------


def test_format_partial_digest_partial_true_keeps_warning_header():
    out = orun._format_partial_digest(["some_reason"], partial=True)
    assert _WARN in out
    assert "- some_reason" in out


def test_format_partial_digest_partial_false_uses_info_header():
    out = orun._format_partial_digest(
        ["prose_contamination_rescued: fact-checker"], partial=False
    )
    assert _WARN not in out, out
    assert _INFO in out, out
    # the reasons themselves are still listed — only the header changes
    assert "- prose_contamination_rescued: fact-checker" in out


def test_format_partial_digest_empty_is_blank_regardless_of_flag():
    assert orun._format_partial_digest([], partial=False) == ""
    assert orun._format_partial_digest([], partial=True) == ""


def test_format_partial_digest_defaults_partial_true():
    # Back-compat: callers that don't pass the flag get the warning header.
    assert _WARN in orun._format_partial_digest(["r"])


# ---------- PR body composer ----------


def test_compose_pr_body_non_partial_with_info_reasons_uses_info_header():
    # Mirrors nightly #176: a clean (non-partial) run with changed files whose
    # only reasons are benign info_only rescues.
    body = orun._compose_pr_body(
        changed_files=["docs/site-src/core/foo.md"],
        lens_paths={"core": "docs/site-src/core"},
        partial=False,
        partial_reasons=[
            "prose_contamination_rescued: content-validator",
            "prose_contamination_rescued: fact-checker",
        ],
        baseline_sha="09cdb4a5",
        current_sha="41d2d07a",
    )
    assert _WARN not in body, body
    assert _INFO in body, body
    # reasons still surface for the operator
    assert "prose_contamination_rescued: fact-checker" in body


def test_compose_pr_body_partial_still_warns():
    body = orun._compose_pr_body(
        changed_files=["docs/site-src/core/foo.md"],
        lens_paths={"core": "docs/site-src/core"},
        partial=True,
        partial_reasons=["source_collector_invalid: returned None"],
        baseline_sha="09cdb4a5",
        current_sha="41d2d07a",
    )
    assert _WARN in body, body


# ---------- step summary ----------


def test_step_summary_non_partial_uses_info_header(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    summary.write_text("## existing\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {
            "partial": False,
            "partial_reasons": ["prose_contamination_rescued: fact-checker"],
        },
    }
    orun._write_step_summary(state, tmp_path)
    contents = summary.read_text()
    assert _WARN not in contents, contents
    assert _INFO in contents, contents
    assert "- prose_contamination_rescued: fact-checker" in contents


def test_step_summary_partial_still_warns(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state = {
        "version": "1",
        "current_run": {
            "partial": True,
            "partial_reasons": ["page_author_invalid: docs/site-src/core/index.md"],
        },
    }
    orun._write_step_summary(state, tmp_path)
    assert _WARN in summary.read_text()
