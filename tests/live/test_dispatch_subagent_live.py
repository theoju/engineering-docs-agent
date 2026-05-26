"""Live integration tests for dispatch_subagent.

Invoke the real `claude` CLI; require claude installed + authenticated,
network, and API quota (each test ~$0.10-$0.50).
Run with: `pytest -m live tests/live/test_dispatch_subagent_live.py -v`
NEVER run on every `pytest`. Default-skipped by conftest.py.
"""

from __future__ import annotations
import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner  # noqa: E402


def _require_claude_cli():
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not installed")


@pytest.mark.live
def test_dispatch_notifier_happy_path():
    """notifier with a trivial digest produces a parseable dict response."""
    _require_claude_cli()
    digest = {
        "pr_url": "https://github.com/example/repo/pull/1",
        "run_summary_bullets": [
            "Added a hello-world doc to confirm the live-test gate works.",
        ],
        "doc_links": [],
    }
    result = orchestrator_runner.dispatch_subagent("notifier", digest, dry_run_dir=None)
    assert result is not None, (
        "dispatch_subagent returned None — check claude CLI auth, agent "
        "resolution, and the JSON parsing path in dispatch_subagent"
    )
    assert isinstance(result, dict), f"expected dict response; got {type(result)}"


@pytest.mark.live
def test_dispatch_pr_summarizer_happy_path():
    """pr-summarizer with a canned PR payload returns a schema-conformant dict.

    Different agent + payload shape than the notifier test. Also confirms
    pr-summarizer's per-agent --allowedTools=Read (CCE-7) doesn't break it.
    Required keys per agents/schemas/pr_summarizer.schema.json: pr_number, doc_targets.
    """
    _require_claude_cli()
    pr_input = {
        "pr": {
            "number": 1,
            "title": "Add hello-world doc",
            "body": "Adds docs/hello.md as a smoke test for the live integration gate.",
            "merged_at": "2026-05-22T00:00:00Z",
            "merge_sha": "abc123",
            "files": [{"path": "docs/hello.md", "additions": 5, "deletions": 0}],
        },
        "jira_issues": [],
    }
    result = orchestrator_runner.dispatch_subagent(
        "pr-summarizer", pr_input, dry_run_dir=None
    )
    assert result is not None, "dispatch_subagent returned None"
    assert isinstance(result, dict), f"expected dict; got {type(result)}"
    for required_key in ("pr_number", "doc_targets"):
        assert required_key in result, (
            f"pr-summarizer response missing required key '{required_key}'; "
            f"got keys: {list(result.keys())}"
        )
