# tests/orchestrator/test_authoring_truncation_advance.py
"""Track A: an authoring-truncated run advances to the CCE-109 cursor, never
to the full window HEAD.

The PR-admission loop sets ``time_truncated`` when it hits the soft deadline
(orchestrator_runner.py:1491). The authoring loop truncates for the same reason
and historically set nothing, so ``advance_sha`` fell through to
``state["current_run"]["head_sha"]`` — the full window HEAD — and the run
persisted a baseline covering PRs whose pages it never authored.

Every fixture here places a NON-PR commit (``c4``) on top of the newest PR
merge commit (``c3``), so the cursor and HEAD are provably different shas.
Asserting ``advance == cursor`` alone would pass vacuously on a fixture whose
newest PR merge happens to BE head; the discriminating assertion — and the one
that would have caught the original fall-through — is ``advance != head``.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402

FAKES_MULTI = Path(__file__).parent / "fakes_multi"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fake_clock(values):
    """Monotonic values in order, then repeating the last. The first value is
    consumed by the deadline calc (same helper as test_time_budget.py)."""
    it = iter(values)
    last = values[-1]
    return lambda: next(it, last)


def _seed_window(repo: Path, state_path: Path, n: int) -> tuple[str, list[str]]:
    """Add n commits on top of the host's init commit and pin the baseline at
    that init commit, so last_sha..HEAD is a real n-commit window.
    Returns (base_sha, [c1..cn] oldest-first)."""
    base = _git(repo, "rev-parse", "HEAD")
    shas = []
    for i in range(1, n + 1):
        (repo / "f.txt").write_text(f"c{i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )
    return base, shas


def _pr(n: int, sha: str | None = None) -> dict:
    d = {"number": n, "title": f"PR {n}", "url": f"https://github.com/o/r/pull/{n}"}
    if sha:
        d["merge_sha"] = sha
    return d


def _fakes(dst: Path, prs: list[dict] | None, hints: list[str] | None) -> Path:
    """Copy fakes_multi, optionally overriding the collector's PRs and the
    summarizer's doc_targets (one batch per hint drives the authoring loop)."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in FAKES_MULTI.iterdir():
        (dst / f.name).write_text(f.read_text())
    if prs is not None:
        sc = json.loads((FAKES_MULTI / "fake_source_collector.json").read_text())
        sc["prs"] = prs
        (dst / "fake_source_collector.json").write_text(json.dumps(sc))
    if hints is not None:
        summ = json.loads((FAKES_MULTI / "fake_pr_summarizer.json").read_text())
        summ["doc_targets"] = [
            {"lens": "core", "action": "create", "page_hint": h} for h in hints
        ]
        (dst / "fake_pr_summarizer.json").write_text(json.dumps(summ))
    return dst


THREE_HINTS = ["connectors/alpha.md", "connectors/beta.md", "connectors/gamma.md"]
# deadline=100; admission gates at 10 and 20 admit all 3 PRs; authoring batch 0
# is unconditional, batch 1's gate sees 150 → the authoring loop truncates.
AUTHORING_TRUNCATION_CLOCK = [0, 10, 20, 150]


def test_authoring_truncation_advances_to_cursor_not_head(tmp_path, init_host):
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {"head_sha": "s"}})
    base, (c1, c2, c3, c4) = _seed_window(repo, state_path, 4)
    # c4 is a direct (non-PR) commit, so HEAD is strictly ahead of the newest
    # PR merge — cursor and head can never coincide in this fixture.
    fakes = _fakes(
        tmp_path.parent / f"trackA_cursor_{tmp_path.name}",
        [_pr(1, c1), _pr(2, c2), _pr(3, c3)],
        THREE_HINTS,
    )
    rc = runner.run(
        repo,
        dry_run_dir=fakes,
        no_pr=True,
        time_budget_seconds=100,
        now_monotonic=_fake_clock(AUTHORING_TRUNCATION_CLOCK),
    )
    assert rc == 0
    core = repo / "docs" / "site-src" / "core" / "connectors"
    # Precondition: the run really was cut inside the authoring loop.
    assert (core / "alpha.md").exists()
    assert not (core / "beta.md").exists()
    assert not (core / "gamma.md").exists()
    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    head = _git(repo, "rev-parse", "HEAD")
    assert head == c4
    # THE assertion: the bug was a fall-through to head, so the negative is
    # what discriminates. Keep it even though the positive below implies it.
    assert advance != head, written["last_successful_run"]
    assert advance == c3, written["last_successful_run"]
    # A truncated run also stamps the window it covered for the CCE-43 guard.
    assert written["last_successful_run"].get("window_head_sha") == c4, written[
        "last_successful_run"
    ]
