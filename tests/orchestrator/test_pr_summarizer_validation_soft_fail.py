"""When pr-summarizer returns a schema-invalid output, the orchestrator
records a partial reason and continues with the remaining PRs (CCE-17).

The plumbing exists in scripts/orchestrator_runner.py:495-516 +
scripts/contracts.py:89-102; this test pins the soft-fail contract
end-to-end via the dry-run fixture path.
"""

from __future__ import annotations
import json
from pathlib import Path
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_invalid_page_hint_yields_schema_invalid_reason(tmp_path: Path) -> None:
    """A pr-summarizer output with a source-tree page_hint is rejected by
    the schema; the orchestrator surfaces a `schema_invalid: pr-summarizer: ...`
    reason and (summary, reasons) returns (None, [reason])."""
    bad_output = {
        "pr_number": 99,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "scripts/foo.py"}
        ],
    }
    fake_dir = tmp_path / "dry"
    fake_dir.mkdir()
    (fake_dir / "fake_pr_summarizer.json").write_text(json.dumps(bad_output))

    summary, reasons = orun.dispatch_validated(
        "pr-summarizer",
        {
            "pr": {"number": 99},
            "jira_context": [],
            "lens_names": ["core", "superpowers"],
        },
        dry_run_dir=fake_dir,
        cwd=tmp_path,
    )
    assert summary is None, "Schema-invalid output should return None"
    assert any("schema_invalid" in r and "pr-summarizer" in r for r in reasons), (
        f"Expected schema_invalid: pr-summarizer reason; got: {reasons}"
    )


def test_valid_sandbox_create_passes(tmp_path: Path) -> None:
    """A clean sandbox-relative create page_hint validates and returns the dict."""
    good_output = {
        "pr_number": 42,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": "_agent-sandbox/2026-05-21-foo.md",
            }
        ],
    }
    fake_dir = tmp_path / "dry"
    fake_dir.mkdir()
    (fake_dir / "fake_pr_summarizer.json").write_text(json.dumps(good_output))

    summary, reasons = orun.dispatch_validated(
        "pr-summarizer",
        {
            "pr": {"number": 42},
            "jira_context": [],
            "lens_names": ["core", "superpowers"],
        },
        dry_run_dir=fake_dir,
        cwd=tmp_path,
    )
    assert summary is not None, f"Expected valid summary; reasons={reasons}"
    assert summary["pr_number"] == 42
    assert reasons == [] or all("rescued" in r for r in reasons), (
        f"Expected no reasons (or only rescue tags); got: {reasons}"
    )


def test_json_source_path_rejected(tmp_path: Path) -> None:
    """Source-file extensions (.json) are schema-caught.

    Lens-prefix doubling (e.g. lens=superpowers + page_hint starting with
    `docs/superpowers/...`) is NOT schema-caught — it's host-config-specific
    and surfaces as `unsafe_page_path` from the orchestrator's editable_paths
    filter at runtime. The schema enforces universal structural rules; the
    orchestrator's filter is the host-aware safety net.
    """
    bad_output = {
        "pr_number": 12,
        "doc_targets": [
            {
                "lens": "core",
                "action": "create",
                "page_hint": ".claude-plugin/plugin.json",
            }
        ],
    }
    fake_dir = tmp_path / "dry"
    fake_dir.mkdir()
    (fake_dir / "fake_pr_summarizer.json").write_text(json.dumps(bad_output))

    summary, reasons = orun.dispatch_validated(
        "pr-summarizer",
        {
            "pr": {"number": 12},
            "jira_context": [],
            "lens_names": ["core", "superpowers"],
        },
        dry_run_dir=fake_dir,
        cwd=tmp_path,
    )
    assert summary is None
    assert any("schema_invalid" in r for r in reasons), reasons
