"""CCE-144: every blocking add_partial call site must be explicitly classified.

The runtime default for a blocking reason is BLIND (fail-safe). This test
forbids *relying* on that default: a call site that passes neither
`info_only` nor `degraded` has been classified by nobody, and would inherit
red-or-green by accident. Adding a bare add_partial call fails this test.

Deliberately not a registry of site->classification: keys built from the
enclosing function plus reason token collide in verify_runner, where three
separate reason loops share a key but not a classification, and a registry
decays as sites move. Requiring explicitness at the call site cannot decay.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED_MODULES = ("scripts/orchestrator_runner.py", "scripts/verify_runner.py")


def _add_partial_calls(path: Path):
    """Yield (lineno, enclosing_function, keyword_names) per add_partial call."""
    tree = ast.parse(path.read_text())
    enclosing: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    enclosing.setdefault(child.lineno, node.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "add_partial":
            continue
        yield (
            node.lineno,
            enclosing.get(node.lineno, "<module>"),
            {kw.arg for kw in node.keywords if kw.arg},
        )


@pytest.mark.parametrize("rel", GUARDED_MODULES)
def test_every_add_partial_call_is_explicitly_classified(rel):
    path = REPO_ROOT / rel
    unclassified = [
        f"{rel}:{lineno} in {fn}()"
        for lineno, fn, kwargs in _add_partial_calls(path)
        if not ({"info_only", "degraded"} & kwargs)
    ]
    assert not unclassified, (
        "add_partial call sites with no explicit classification:\n  "
        + "\n  ".join(unclassified)
        + "\n\nPass degraded=True if the run HELD BACK the work it could not "
        "process (self-healing, stays green), degraded=False if the run "
        "CONSUMED input it could not process (blind, turns the nightly red), "
        "or info_only=True if the reason is advisory. See the Classification "
        "section of the CCE-144 spec."
    )


def test_the_guard_actually_detects_a_bare_call(tmp_path):
    """Meta-test: exercise _add_partial_calls on an isolated probe, so a green
    result above means "all sites classified" and never "the walk found
    nothing".

    Deliberately does NOT read the guarded modules: a probe appended to their
    source would count every still-unclassified call alongside it, so the test
    could only pass after the classification landed — failing at the TDD red
    gate with a message blaming the walk, which is the one part that works.
    Reading a fixture instead makes it order-independent and lets it exercise
    the `.attr` branch, which no real call site currently covers.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def f(state):\n"
        "    add_partial(state, 'bare')\n"
        "    add_partial(state, 'degraded', degraded=True)\n"
        "    add_partial(state, 'advisory', info_only=True)\n"
        "    mod.add_partial(state, 'attribute-style')\n"
    )
    calls = list(_add_partial_calls(probe))
    assert len(calls) == 4, f"walk found {len(calls)} calls, expected 4"
    unclassified = [
        fn for _lineno, fn, kwargs in calls if not ({"info_only", "degraded"} & kwargs)
    ]
    assert len(unclassified) == 2, (
        "the walk must flag the bare call AND the attribute-style call; "
        f"it flagged {len(unclassified)}"
    )


def test_orchestrator_has_the_expected_call_site_population():
    """Tripwire on the audit's scope. Not a hard contract — if this fails
    because sites were legitimately added or removed, re-audit the new ones
    against the spec's Classification section and update the number here in
    the same commit that adds them."""
    calls = list(_add_partial_calls(REPO_ROOT / "scripts/orchestrator_runner.py"))
    assert len(calls) == 42, (
        f"expected 42 add_partial calls, found {len(calls)}; re-audit and "
        "update this count deliberately"
    )
    # 42 -> 42: CCE-141 revision 3 made the feature DETECTION ONLY. The page is
    # never rewritten, so `_repair_citation_paths` became
    # `_diagnose_citation_paths` and both of its sites were replaced, one for
    # one — `citation_repair_declined` and `citation_path_repaired` out,
    # `citation_shortening_suspected` and `citation_diagnosis_failed` in. The
    # count is unchanged; the CLASSIFICATION is not, and that is the part worth
    # recording.
    #
    # Classification: both new sites are info_only=True.
    #
    # The finding line was degraded=True as `citation_repair_declined`, on the
    # reasoning that a decline meant a page did not ship. That reasoning is
    # gone. Nothing the diagnostic does affects whether the page ships: the
    # page blocks because `citation_exists` blocks it, and that block already
    # arrives here as `lint_block` with its own degraded=True. A second
    # degraded reason would double-count one failure — and would cost the run
    # auto-merge through CCE-140's `partial and not advance_cursor_backed`
    # gate for a line that is pure advice about a block someone else already
    # reported. Advisory is not silent: add_partial appends an info_only
    # reason to `partial_reasons` and emits it to stderr like any other.
    #
    # The failure line (`citation_diagnosis_failed`) is the broad-catch arm
    # that keeps a malformed `mkdocs.yml` — a top-level YAML list or bare
    # scalar raises AttributeError on `.get` — from taking down an unattended
    # nightly through the missing top-level handler in run()/main(). It is
    # info_only for the same reason the findings are: a broken advisory has no
    # bearing on page correctness, so it must not flip `partial`. It is
    # recorded at all because a diagnostic that silently stopped working is
    # indistinguishable from one with nothing to report.
    # 41 -> 42: CCE-141 revision 2 added `citation_repair_declined` in
    # `_repair_citation_paths`. Corroboration is now the ENTRY CONDITION for a
    # repair, so the repairer has a second outcome: a unique suffix candidate
    # that no source outside the authoring agent vouches for is refused. The
    # site reports each refusal with the cited token, the candidate it refused,
    # and why.
    #
    # Classification: degraded=True — explicitly NOT info_only. A decline is not
    # a rescue; it is a page that does not ship. The unresolvable citation
    # survives, `citation_exists` blocks it, the lint-block revert discards the
    # page and CCE-140 holds its PRs out of the advance cursor, so the next run
    # re-authors it. That is exactly the shape the sibling test's assertion
    # message calls held-back-and-self-healing, and it is the same
    # classification the `lint_block` site it feeds already carries. Silence
    # here would reproduce the very harm this revision exists to fix, one band
    # narrower: block -> deferral -> forgiveness -> the page is never written
    # and nothing in the digest ever says so. It is emphatically not blind
    # (degraded=False): the run JUDGED this citation and rejected it.
    # 40 -> 41: CCE-141 added `citation_path_repaired` in the new
    # `_repair_citation_paths`, called beside `_enforce_agent_frontmatter` for
    # every authored page. It reports each citation path the deterministic
    # repairer rewrote from an unresolvable relative path to a resolvable one.
    #
    # Classification: info_only=True. A repair is a successful rescue, not a
    # degradation — nothing was lost, so `partial` must not flip. Flipping it
    # would veto auto-merge for a self-correction through CCE-140's `partial
    # and not advance_cursor_backed` gate, punishing the run for fixing the
    # very problem it fixed. It is recorded at all because the digest line is
    # the only signal that would ever justify revisiting the author prompt
    # that produced the shortened citation in the first place.
    # 39 -> 40: CCE-159 added `pr_summaries_reused` in run(), reporting how
    # many PRs were served from the summary cache instead of re-dispatched.
    #
    # Classification: info_only=True. It reports work the run did NOT have to
    # do, so it is the opposite of a degradation — nothing was held back and
    # nothing was consumed unprocessed. Flipping `partial` on a successful
    # saving would also cost auto-merge every night through CCE-140's
    # `partial and not advance_cursor_backed` gate, turning the optimization
    # into an outage. It is recorded at all because a saving nobody can see is
    # indistinguishable from a feature that silently stopped working.
    # 38 -> 39: CCE-152 added one site on net. The authoring truncation gained a
    # second reason — a deferral to the next PR boundary versus a hard-cap cut
    # inside a PR's group — but they share one `add_partial`, since only the
    # parenthetical and the trailing clause differ. The site that actually
    # arrived is `authoring_hard_cap_squeezed` in run(), recorded when the App
    # token's TTL leaves the host no overrun to grant.
    #
    # Classification, per the mapping the sibling test's assertion message
    # states: the truncation site is degraded=True because the run HELD BACK
    # the page batches it could not reach — they stay owed, `held_back` names
    # them, and the next run re-authors them, which is the self-healing case.
    # (It is emphatically not the blind case: a run that CONSUMED input it
    # could not process is one that walked past the work without recording it.)
    # The squeeze site is info_only=True: it describes the host's configuration
    # rather than this run's work, and flipping `partial` on it would cost a
    # default-budget host auto-merge every night via CCE-140's
    # `partial and not advance_cursor_backed` gate.
