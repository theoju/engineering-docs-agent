# tests/orchestrator/test_degraded_advance_non_truncated.py
"""CCE-151: a degraded run must not advance the watermark past an undocumented PR.

`deferred_pages_by_pr` used to be read only inside `if time_truncated:`. The
`else` branch assigned `advance_sha = state["current_run"]["head_sha"]` — the
full window HEAD — without consulting it, so a run that admitted a PR, wrote no
page for it, and was never truncated still walked the cursor past that PR. The
cursor is consume-once: the window is never re-read and the content is lost for
good.

The run exits 0, so no failure signal fires and nobody investigates. That
invisibility is the same mode that let 15 consecutive nightlies rot in CCE-127.

Observed in production twice on 2026-08-21 against
`theoju/claude-code-self-assessment`: runs 32460602658 and 32495019606 each
blocked a page on lint and still advanced. The second one advanced past the very
page the first one had stranded.

## The fix

Structural, not a new veto. The held-back set and `partition_deferrals` are now
computed unconditionally, and the cursor-walk branch is entered on
`time_truncated or held_back`. A run that holds pages back therefore takes the
same cursor-backed advance a truncated run takes: it advances only as far as the
last PR it actually documented, and only when doing so strands nothing behind
the cursor.

Two traps this deliberately avoids, both load-bearing:

1. **The obvious fix is wrong.** Extending `_should_advance_watermark` to refuse
   whenever `partial and not advance_cursor_backed` freezes the cursor on every
   `lint_block` and reinstates the CCE-109 doom loop that CCE-140 exists to
   prevent. Gating on `held_back` emptiness instead leaves clean runs on the
   plain window-HEAD advance, byte for byte.

2. **`partition_deferrals` had to be hoisted too, not just the read.** With
   `still_deferred` defaulting to `[]`, every non-truncated run silently CLEARED
   the deferral counts of the PRs it had held back, so no PR could ever
   accumulate enough deferrals to reach the skip threshold. Hoisting it arms
   that release valve, which is what stops a permanently-unlintable page from
   wedging the cursor forever.

## The decision CCE-151 left open

The ticket required the run to "exit non-zero **or** leave the watermark
unadvanced — decide which, explicitly, and record the reasoning."

**Resolved: leave the watermark unadvanced.** Exiting non-zero would fail the
nightly on a condition that is routine and self-healing — one page blocked, the
rest published — which trains operators to ignore red runs, the exact failure
CCE-127 was made of. Holding the cursor preserves the only property that
actually matters (the window stays re-readable next run) while
`partial_reasons` and the CCE-140 merge gate carry the visibility.

## Sibling test that had to change with this one

`test_state_advancement_invariant.py::test_partial_run_via_lint_block_holds_state_when_nothing_was_documented`
pinned the opposite — watermark MUST advance for `lint_block`, per CCE-40 §7 row
4. That case has the identical shape as this one (one PR admitted, zero pages
surviving, watermark advanced), so it was not a different scenario but the same
scenario with a different reason string. It moves in lockstep with this file.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

ORCH_RUNNER = Path(__file__).parent.parent.parent / "scripts" / "orchestrator_runner.py"
FAKES_DEGRADED = Path(__file__).parent / "fakes_degraded_advance"

SEEDED_BASELINE = "old_sha_000"


def _head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(repo: Path) -> subprocess.CompletedProcess:
    """No time budget pressure: the point is the NON-truncated path."""
    return subprocess.run(
        [
            sys.executable,
            str(ORCH_RUNNER),
            "--repo-root",
            str(repo),
            "--no-pr",
            "--dry-run-subagents",
            str(FAKES_DEGRADED),
        ],
        capture_output=True,
        text=True,
    )


def _authored_pages(repo: Path) -> list[str]:
    core = repo / "docs" / "site-src" / "core"
    return sorted(str(p.relative_to(repo)) for p in core.rglob("*.md"))


@pytest.fixture
def degraded_run(tmp_path, init_host, read_current_run):
    """Run the page-author-absent fixture set against a fresh host."""
    state_path = init_host(
        {"version": "1", "last_successful_run": {"head_sha": SEEDED_BASELINE}}
    )
    head = _head_sha(tmp_path)
    result = _run(tmp_path)
    return {
        "result": result,
        "head": head,
        "state": json.loads(state_path.read_text()),
        "current_run": read_current_run(state_path),
        "pages": _authored_pages(tmp_path),
    }


def test_degraded_non_truncated_run_holds_the_cursor_for_an_undocumented_pr(
    degraded_run,
):
    """The full shape of the fixed behavior, asserted field by field.

    This replaces the pre-fix characterization test. Every assertion is a
    statement about the contract CCE-151 established, so a regression that
    reintroduces the advance fails here rather than silently in production.
    """
    d = degraded_run
    cr = d["current_run"]

    # Still classified degraded, not blind — CCE-144 classifies page-stage
    # failures as degraded, and the fix must NOT have changed that. If this
    # flips to blind, the advance is being suppressed by the wrong mechanism
    # (`_should_advance_watermark`), which is the CCE-109 doom loop.
    assert cr["partial"] is True
    assert not cr.get("blind"), (
        "page_author_invalid must stay degraded; a blind classification here "
        "means the fix moved to _should_advance_watermark and reinstated the "
        f"CCE-109 doom loop. current_run={cr}"
    )
    assert any("page_author_invalid" in r for r in cr["partial_reasons"]), (
        f"expected page_author_invalid in reasons: {cr['partial_reasons']}"
    )

    # The PR was admitted and documented NOTHING.
    assert d["pages"] == [], (
        f"fixture is meant to produce no surviving page; got {d['pages']}"
    )

    # The run stays green. Blocking one page is routine and self-healing; the
    # visibility lives in partial_reasons and the CCE-140 merge gate, not in a
    # red nightly. See the module docstring for why this was chosen over exit 1.
    assert d["result"].returncode == 0, (
        f"expected a green exit; got {d['result'].returncode}: "
        f"{d['result'].stderr[-600:]}"
    )

    # The fix: the cursor stays put, so the window is re-readable next run.
    assert d["state"]["last_successful_run"]["head_sha"] == SEEDED_BASELINE, (
        "CCE-151: with every admitted PR held back, there is no documented PR "
        "to anchor a cursor-backed advance on, so the baseline must not move. "
        f"Found {d['state']['last_successful_run']['head_sha']}, expected "
        f"{SEEDED_BASELINE}"
    )
    assert d["state"]["last_successful_run"]["head_sha"] != d["head"], (
        "the window HEAD must not be reachable on this path at all — that "
        "assignment is what CCE-151 removed"
    )


def test_degraded_non_truncated_run_must_not_silently_consume_a_pr_invariant(
    degraded_run,
):
    """The property CCE-151 requires, stated independently of the mechanism.

    Deliberately written as the disjunction the ticket allowed rather than as
    an assertion about the watermark specifically. The test above pins the
    mechanism we chose; this one pins the property, so a future redesign that
    switches to the loud-exit option still satisfies it without a rewrite.
    """
    d = degraded_run
    advanced = d["state"]["last_successful_run"]["head_sha"] != SEEDED_BASELINE
    loud = d["result"].returncode != 0

    assert d["pages"] == [], "precondition: this run documented nothing"
    assert loud or not advanced, (
        "a run that consumed a PR and wrote no page must either exit non-zero "
        "or leave the cursor where it was. It did neither: exit="
        f"{d['result'].returncode}, watermark advanced to "
        f"{d['state']['last_successful_run']['head_sha'][:12]}. The PR is now "
        "outside every future collection window and its content is "
        "unrecoverable without a hand-written baseline rewind."
    )
