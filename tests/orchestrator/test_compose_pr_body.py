"""CCE-89 D1: PR-body enrichment.

Pure-function tests for `_compose_pr_body` — the composer that turns a list
of changed files + lens config + partial state into the body of a
docs-agent PR. Keeps the orchestrator's `open_or_append_pr` thin and lets us
exercise the body shape without git/subprocess.

D1 scope (per CCE-89):
  - top-N changed pages (capped at 5)
  - file count by lens path
  - partial_reasons inline (when partial)
  - baseline head SHA + current head SHA in header (so the operator sees the
    review window without opening state.json)
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402


# ---------- minimal / backwards-compat cases ----------


def test_compose_pr_body_minimal_falls_back_to_legacy_string():
    """No data passed → returns the old 'docs-agent run' sentinel so existing
    callers that don't yet pass lens_paths/baseline/current don't get a body
    full of empty sections."""
    body = orun._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    assert body == "docs-agent run"


def test_compose_pr_body_minimal_partial_uses_existing_digest_only():
    """Partial run with no other data → behaves like _format_partial_digest
    (the pre-CCE-89 minimal partial body shape)."""
    body = orun._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=True,
        partial_reasons=["source_collector_invalid:returned None"],
        baseline_sha="",
        current_sha="",
    )
    assert "WARNING — Partial run" in body
    assert "- source_collector_invalid:returned None" in body


# ---------- enrichment: header SHAs ----------


def test_compose_pr_body_includes_baseline_and_current_sha_header():
    body = orun._compose_pr_body(
        changed_files=["docs/site-src/architecture/foo.md"],
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="bdf0da1abc",
        current_sha="1234567890",
    )
    assert "bdf0da1a" in body, "baseline SHA must appear in header"
    assert "1234567" in body, "current SHA must appear in header"


def test_compose_pr_body_baseline_only_when_provided():
    """Empty baseline → no review-window header (avoid emitting 'baseline:'
    pointing at nothing)."""
    body = orun._compose_pr_body(
        changed_files=["docs/site-src/architecture/foo.md"],
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    assert "baseline" not in body.lower()


# ---------- enrichment: file-count-by-lens ----------


def test_compose_pr_body_counts_files_by_lens():
    """3 docs/site-src/architecture/* + 1 docs/site-src/runtime/* → architecture: 3, runtime: 1.

    Resolution is by lens-name prefix match on the file path.
    """
    body = orun._compose_pr_body(
        changed_files=[
            "docs/site-src/architecture/a.md",
            "docs/site-src/architecture/b.md",
            "docs/site-src/architecture/c.md",
            "docs/site-src/runtime/d.md",
        ],
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    # Single lens `core` covers all 4 files; expect "core: 4".
    assert "core: 4" in body


def test_compose_pr_body_multi_lens_with_longest_prefix_match():
    """A file matching two lens prefixes is assigned to the longest match."""
    body = orun._compose_pr_body(
        changed_files=[
            "docs/site-src/architecture/a.md",
            "docs/site-src/runtime/d.md",
            "docs/site-src/other.md",
        ],
        lens_paths={
            "core": "docs/site-src/",
            "architecture": "docs/site-src/architecture/",
        },
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    # `a.md` is under architecture/ → architecture lens (longest prefix).
    # `d.md` is under runtime/ → core lens (no narrower prefix).
    # `other.md` is under core/ root → core lens.
    assert "architecture: 1" in body
    assert "core: 2" in body


def test_compose_pr_body_other_bucket_for_files_outside_any_lens():
    body = orun._compose_pr_body(
        changed_files=[
            "docs/site-src/architecture/a.md",
            "scripts/foo.py",  # not under any lens path
            "Makefile",  # not under any lens path
        ],
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    assert "core: 1" in body
    assert "other: 2" in body


# ---------- enrichment: top-N pages ----------


def test_compose_pr_body_lists_top_n_pages_capped_at_5():
    """8 changed files → list top 5, then a '(N more)' note."""
    files = [f"docs/site-src/architecture/page-{i}.md" for i in range(1, 9)]
    body = orun._compose_pr_body(
        changed_files=files,
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
        top_n=5,
    )
    # All 5 top entries appear.
    for i in range(1, 6):
        assert f"page-{i}.md" in body
    # Truncation note for the remaining 3.
    assert "3 more" in body


def test_compose_pr_body_does_not_truncate_when_under_top_n():
    files = [
        "docs/site-src/architecture/a.md",
        "docs/site-src/architecture/b.md",
    ]
    body = orun._compose_pr_body(
        changed_files=files,
        lens_paths={"core": "docs/site-src/"},
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
        top_n=5,
    )
    assert "a.md" in body
    assert "b.md" in body
    assert "more" not in body.lower()


# ---------- partial-reasons inline ----------


def test_compose_pr_body_partial_reasons_inlined_alongside_enrichment():
    """Real CCE-89 telemetry: partial run with files AND reasons → BOTH the
    enrichment sections AND the partial-reasons digest appear."""
    body = orun._compose_pr_body(
        changed_files=["docs/site-src/architecture/state-advancement.md"],
        lens_paths={"core": "docs/site-src/"},
        partial=True,
        partial_reasons=[
            "prose_contamination_rescued:source-collector",
            "internal-link broken on framework-none.md ../../../../CLAUDE.md",
        ],
        baseline_sha="bdf0da1a",
        current_sha="abcd1234",
    )
    # Enrichment sections present.
    assert "core: 1" in body
    assert "state-advancement.md" in body
    # Partial-reasons digest also present.
    assert "WARNING — Partial run" in body
    assert "prose_contamination_rescued:source-collector" in body
    assert "internal-link broken on framework-none.md" in body
    # Baseline header present.
    assert "bdf0da1a" in body
