# tests/orchestrator/test_degraded_advance_non_truncated.py
"""CCE-151: a degraded run advances the watermark on the NON-truncated path.

`deferred_pages_by_pr` is only read inside `if time_truncated:`. The `else`
branch assigns `advance_sha = state["current_run"]["head_sha"]` — the full
window HEAD — without consulting it, so a run that admitted a PR, wrote no page
for it, and was never truncated still walks the cursor past that PR. The cursor
is consume-once: the window is never re-read and the content is lost for good.

The run exits 0, so no failure signal fires and nobody investigates. That
invisibility is the same mode that let 15 consecutive nightlies rot in CCE-127.

Observed in production twice on 2026-08-21 against
`theoju/claude-code-self-assessment`: runs 32460602658 and 32495019606 each
blocked a page on lint and still advanced. The second one advanced past the
very page the first one had stranded.

## Two tests, on purpose

`test_..._characterization` PASSES today. It pins the defect's exact shape so a
future change cannot alter it silently — including a change that "fixes" it
without noticing the blast radius.

`test_..._invariant` is `xfail(strict=True)`: the property CCE-151 says must
hold, which does not hold yet. Strict is what makes this self-cleaning — the
day the fix lands, this file turns RED and forces whoever fixed it to drop the
marker rather than leaving a stale xfail behind.

## Read this before "fixing" it

Two traps, both load-bearing:

1. **The obvious fix is wrong.** Extending `_should_advance_watermark` to refuse
   when `partial and not advance_cursor_backed` freezes the cursor on every
   `lint_block` and reinstates the CCE-109 doom loop that CCE-140 exists to
   prevent. CCE-151 records the structural fix instead: hoist the held-back set
   out of `if time_truncated:` and populate `deferred_pages_by_pr` on the
   non-truncated path too.

2. **A sibling test pins the OPPOSITE and is green.**
   `test_state_advancement_invariant.py::test_partial_run_via_lint_block_advances_state`
   asserts the watermark MUST advance for `lint_block`, per CCE-40 §7 row 4 and
   reaffirmed by CCE-144. That case has the identical shape as this one — one PR
   admitted, zero pages surviving, watermark advanced — so it is not a different
   scenario, it is the same scenario with a different reason string. Whichever
   way CCE-151 is resolved, BOTH tests change together or the suite contradicts
   itself.

CCE-151 leaves one decision explicitly open: the reproduction must "exit
non-zero **or** leave the watermark unadvanced — decide which, explicitly, and
record the reasoning." The invariant below is written as that disjunction, so it
does not pre-empt the choice: either fix satisfies it.
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


def test_degraded_non_truncated_run_advances_past_an_undocumented_pr_characterization(
    degraded_run,
):
    """Pins the defect exactly as it stands. Expected to PASS until CCE-151.

    Every assertion here is a statement about today's behavior, not about
    desired behavior. When CCE-151 lands, this test must be rewritten in the
    same commit — it is the inventory of what that fix changes.
    """
    d = degraded_run
    cr = d["current_run"]

    # The run is degraded, not blind — CCE-144 classifies page-stage failures
    # as degraded, which is what routes it past _should_advance_watermark.
    assert cr["partial"] is True
    assert not cr.get("blind"), (
        "page_author_invalid is classified degraded, so `blind` must be falsy; "
        "if this fails, the classification changed and the advance gate moved "
        f"with it. current_run={cr}"
    )
    assert any("page_author_invalid" in r for r in cr["partial_reasons"]), (
        f"expected page_author_invalid in reasons: {cr['partial_reasons']}"
    )

    # The PR was admitted and documented NOTHING.
    assert d["pages"] == [], (
        f"fixture is meant to produce no surviving page; got {d['pages']}"
    )

    # And the run is green, so nothing alerts anyone.
    assert d["result"].returncode == 0, (
        f"expected a green exit today; got {d['result'].returncode}: "
        f"{d['result'].stderr[-600:]}"
    )

    # The defect: the cursor walks to full window HEAD anyway.
    assert d["state"]["last_successful_run"]["head_sha"] == d["head"], (
        "CCE-151: the non-truncated branch assigns advance_sha = window HEAD "
        "without consulting deferred_pages_by_pr, so the cursor moves past a PR "
        "that produced no documentation. Found "
        f"{d['state']['last_successful_run']['head_sha']}, expected {d['head']}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CCE-151 unfixed: a degraded non-truncated run consumes a PR, writes no "
        "page, exits 0, and still advances the consume-once cursor past it. "
        "Remove this marker in the commit that fixes it."
    ),
)
def test_degraded_non_truncated_run_must_not_silently_consume_a_pr_invariant(
    degraded_run,
):
    """The property CCE-151 requires. Written as a disjunction on purpose.

    CCE-151's acceptance leaves the mechanism open — "exits non-zero **or**
    leaves the watermark unadvanced — decide which, explicitly". Asserting the
    disjunction means this test passes under either resolution and does not
    quietly decide it here.

    The invariant itself is not negotiable in either form: a window whose PR
    produced no page must remain re-readable, or the run must be loud enough
    that a human looks before the branch is merged.
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
