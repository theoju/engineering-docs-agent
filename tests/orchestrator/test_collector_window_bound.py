# tests/orchestrator/test_collector_window_bound.py
"""CCE-199: the window bound must reach the source-collector's inputs.

CCE-169 bounded the window on the wrong side of the agent boundary. Its cut
runs at `resolve_window_cap(config)` *after* `dispatch_validated(
"source-collector", ...)` has returned, so it bounds what the run ADMITS and
nothing bounds what the collector EMITS. A host whose baseline has fallen far
enough behind hands the collector a window it cannot fit in one output; the
agent improvises `error: "output_size_limit: N of M in-window PRs returned"`,
which no call site handles, so it lands in the generic `sources.get("error")`
branch as `degraded=False` -- blind. A blind run exits non-zero, skips
auto-merge and freezes the watermark, so the window is one day wider tomorrow
and the next run fails identically.

Measured on the ADIS host, run 37493982560 (2026-10-06): baseline pinned at a
2026-09-09 commit while `completed_at` read 2026-10-05, 173 in-window PRs, 12
returned, `auto_merge_skipped: blind_run`, exit 1. Five failures in six nights.

`max_detail_prs` bounds DETAIL, not membership: the collector still returns
every in-window PR, emitting a metadata-only anchor past the bound. That
distinction is the whole safety argument -- see
`test_the_contract_bounds_detail_without_dropping_prs`.

Plan: docs/superpowers/plans/2026-10-06-cce199-collector-window-bound.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from test_window_cap import _seed_capped_host  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]


class _StopRun(RuntimeError):
    """Abort `run()` once the collector inputs have been captured."""


def _capture_sc_inputs(monkeypatch, tmp_path, init_host, base_config_yaml, cap):
    """Drive `run()` far enough to observe the source-collector's inputs.

    Captured at the dispatch seam rather than asserted on a rendered reason:
    the value has no downstream signal of its own, so a change that resolves
    the cap and then forgets to put it in `sc_inputs` is invisible everywhere
    else in the suite.
    """
    _state_path, _base, _shas, fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=cap
    )
    captured: dict = {}
    real = orun.dispatch_validated

    def spy(name, inputs, **kwargs):
        if name == "source-collector":
            captured.update(inputs)
            raise _StopRun
        return real(name, inputs, **kwargs)

    monkeypatch.setattr(orun, "dispatch_validated", spy)
    try:
        orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    except _StopRun:
        pass
    return captured


def test_collector_inputs_carry_the_window_bound(
    monkeypatch, tmp_path, init_host, base_config_yaml
):
    """`max_detail_prs` must be present and equal to the resolved cap.

    THE WHOLE POINT OF CCE-199. Without it the collector has no way to know
    the window is bounded, so it details the entire window and overflows.
    """
    captured = _capture_sc_inputs(
        monkeypatch, tmp_path, init_host, base_config_yaml, cap=2
    )
    assert "max_detail_prs" in captured, sorted(captured)
    assert captured["max_detail_prs"] == 2, captured["max_detail_prs"]


def test_the_bound_tracks_the_config_key_not_a_literal(
    monkeypatch, tmp_path, init_host, base_config_yaml
):
    """A hardcoded `10` satisfies the test above on a default host.

    This is the test that distinguishes `resolve_window_cap(config)` from a
    literal, so it must use a cap that is not the default.
    """
    captured = _capture_sc_inputs(
        monkeypatch, tmp_path, init_host, base_config_yaml, cap=7
    )
    assert captured["max_detail_prs"] == 7, captured["max_detail_prs"]
    assert captured["max_detail_prs"] != orun.DEFAULT_WINDOW_PR_CAP


def test_zero_reaches_the_collector_as_zero(
    monkeypatch, tmp_path, init_host, base_config_yaml
):
    """`0` is CCE-169's advertised unlimited opt-out and must survive transit.

    `resolve_window_cap(config) or DEFAULT` would rewrite an explicit opt-out
    into the default and silently bound a host that asked not to be bounded --
    the same `is None` versus truthiness trap `resolve_window_cap` is itself
    written to avoid.
    """
    captured = _capture_sc_inputs(
        monkeypatch, tmp_path, init_host, base_config_yaml, cap=0
    )
    assert captured["max_detail_prs"] == 0, captured["max_detail_prs"]


def test_the_contract_documents_max_detail_prs_and_demands_oldest_first():
    """OLDEST-FIRST IS A CORRECTNESS REQUIREMENT, not a preference.

    The orchestrator only ever sees the PRs the collector chose to detail, so a
    newest-first payload is indistinguishable from an oldest-first one. The
    cursor would advance across the detailed set and every older PR in the
    window would fall permanently behind the baseline, outside every future
    window. An ADIS run was observed emitting "the 9 most recent", so this is
    observed agent behaviour and not a hypothetical.

    Pinned as a contract assertion because the agent is a prompt: there is no
    code path to unit-test, and the prompt is the only place the guarantee can
    live.
    """
    contract = (_REPO_ROOT / "agents" / "source-collector.md").read_text()
    assert "`max_detail_prs`" in contract, "max_detail_prs is absent from the contract"
    after = contract[contract.index("`max_detail_prs`") :].lower()
    assert "oldest" in after, (
        "the max_detail_prs contract must require oldest-first detail; without "
        "it a bounded payload can strand older PRs behind the baseline"
    )


def test_the_contract_bounds_detail_without_dropping_prs():
    """The bound must not become a membership filter.

    This is the distinction between CCE-199 as designed and the unsafe variant
    it replaced. If the collector may omit the tail entirely, the orchestrator
    never learns those PRs exist: `held_back` is empty, CCE-151's walk is
    skipped, and the advance reaches full window HEAD. The contract therefore
    has to say that every in-window PR is still returned, anchor-shaped past
    the bound.
    """
    contract = (_REPO_ROOT / "agents" / "source-collector.md").read_text()
    after = contract[contract.index("`max_detail_prs`") :]
    # CCE-202 narrowed HOW the tail is reported without changing THAT it is.
    # Asserted on the accounting identity rather than on the word "anchor":
    # the rewritten contract still contains "anchor", inside a sentence that
    # REJECTS per-PR anchors, so the old substring check now passes for the
    # opposite of the reason it was written.
    assert "held_back_count" in after, (
        "the contract must require the tail to be reported as a count; a "
        "payload that simply ends early reads as a complete window"
    )
    assert "len(prs) + held_back_count" in after, (
        "the contract must state the accounting identity the orchestrator "
        "checks, or the agent cannot know what makes a payload complete"
    )
    assert "payload_bounded" in contract, (
        "a bounded payload needs a CONTRACTED reason; an invented string is "
        "what sent run 37493982560 down the blind path"
    )


def test_the_schema_accepts_an_anchor_shaped_pr():
    """An anchor must validate, or the orchestrator rejects the whole payload.

    `additionalProperties: false` stays, so this is about `required` being
    satisfiable by the four anchor fields rather than about loosening the
    object.
    """
    import jsonschema

    schema = json.loads(
        (_REPO_ROOT / "agents" / "schemas" / "source_collector.schema.json").read_text()
    )
    anchor = {
        "prs": [
            {
                "number": 4242,
                "url": "https://example.invalid/pull/4242",
                "merge_sha": "0" * 40,
                "merged_at": "2026-01-01T00:00:00Z",
            }
        ],
        "jira_issues": [],
        "partial": True,
        "error": "payload_bounded: 10 of 173",
    }
    jsonschema.validate(anchor, schema)


def test_a_payload_that_drops_prs_is_flagged_incomplete(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The guard that makes an anchored payload safe to trust.

    `payload_bounded: <d> of <t>` is the collector's own claim about how wide
    the window was. If fewer than `<t>` PRs arrive, the tail was DROPPED rather
    than anchored, and nothing downstream can recover it: an absent PR reaches
    neither `window_capped` nor `_deferred_all`, so `held_back` stays empty,
    CCE-151's walk is skipped, and the advance reaches full window HEAD. The
    window is consume-once, so that tail is never documented by anyone and
    nothing goes red.

    Asserted end-to-end rather than by grepping the source: a text assertion
    cannot catch a `NameError` in the guard, a regex that never matches, or an
    off-by-one in the comparison -- all of which leave the dangerous path live
    while the test stays green.
    """
    state_path, _base, _shas, fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    sc_path = fakes / "fake_source_collector.json"
    sc = json.loads(sc_path.read_text())
    # The fixture carries 3 PRs; claim a 99-PR window so 96 are unaccounted.
    sc["partial"] = True
    sc["error"] = "payload_bounded: 2 of 99"
    sc_path.write_text(json.dumps(sc))

    orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    reasons = read_current_run(state_path).get("partial_reasons") or []
    assert any("collector_payload_incomplete" in r for r in reasons), reasons


def test_an_accounted_bounded_payload_is_not_flagged(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The guard must not fire on the healthy case it exists to permit.

    A collector that anchors its tail returns every in-window PR, so the count
    matches its claimed total. Without this test the guard could be written as
    "any payload_bounded is incomplete", which would make the fix it belongs to
    useless -- every bounded run would stall exactly as it does today.
    """
    state_path, _base, _shas, fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=2
    )
    sc_path = fakes / "fake_source_collector.json"
    sc = json.loads(sc_path.read_text())
    # 3 PRs returned, 3 claimed in window: 2 detailed + 1 anchored.
    sc["partial"] = True
    sc["error"] = "payload_bounded: 2 of 3"
    sc_path.write_text(json.dumps(sc))

    orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    reasons = read_current_run(state_path).get("partial_reasons") or []
    assert not any("collector_payload_incomplete" in r for r in reasons), reasons


# --------------------------------------------------------------------------
# CCE-199 Task 4: route a bounded payload degraded, keep everything else blind.
#
# Tasks 1-3 made the payload FIT -- the collector now anchors its tail instead
# of overflowing. They did not make the night pass: `sources.get("error")` is
# classified `degraded=False` for every value, so the contracted
# `payload_bounded` reason lands blind exactly where the invented
# `output_size_limit` did, and a blind run exits non-zero, skips auto-merge and
# freezes the watermark. The stall would have survived its own fix.
#
# `blind` is monotonic within a run (`state_io.add_partial`), so there are TWO
# sites to route, not one: the error AND `source_collector_partial: true`,
# which the contract requires a bounded payload to set. Routing only the first
# leaves the second to blind the run on its own --
# `test_partial_true_does_not_blind_a_bounded_run_on_its_own` is the case that
# catches that, and it is why these tests assert the SITE and not only the
# outcome.
# --------------------------------------------------------------------------


def _seed_bounded(
    tmp_path, init_host, base_config_yaml, *, cap, error, prs=None, partial=True
):
    """A capped host whose collector reports `error` with an optional payload.

    `prs=None` keeps the fixture's three PRs, so `payload_bounded: <d> of 3` is
    an ACCOUNTED claim and `<d> of 99` is not.
    """
    state_path, base, shas, fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=cap
    )
    sc_path = fakes / "fake_source_collector.json"
    sc = json.loads(sc_path.read_text())
    sc["partial"] = partial
    sc["error"] = error
    if prs is not None:
        sc["prs"] = prs
    sc_path.write_text(json.dumps(sc))
    return state_path, base, shas, fakes


def test_a_bounded_payload_that_accounts_for_its_window_advances(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """THE TICKET. A bounded payload must behave like the cap it already is.

    Asserted as an advance rather than as a flag, because the flag is not what
    was broken -- the frozen watermark is. The advance must land on the CAP
    BOUNDARY (`c2`, the last admitted PR) and not on head: the anchored tail is
    real work still owed, held out by CCE-169's admission cut, and an advance
    past it would be the silent permanent loss the anchor contract exists to
    prevent. `test_a_capped_run_advances_to_the_cap_boundary_and_says_so` pins
    the same boundary for an unbounded payload; this is that invariant
    surviving a collector that had to bound its own output.
    """
    state_path, _base, (_c1, c2, c3), fakes = _seed_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, error="payload_bounded: 2 of 3"
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0, "an accounted bounded payload is held-back work, not a blind run"

    cr = read_current_run(state_path)
    assert cr.get("blind") is not True, cr
    # Degraded, NOT info_only: a run that could not detail its whole window is
    # not a clean run, and `partial` is what withholds the non-cursor-backed
    # advance.
    assert cr.get("partial") is True, cr
    assert any("payload_bounded" in r for r in cr.get("partial_reasons", [])), cr

    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != c3, "advanced past the anchored tail"


def test_partial_true_does_not_blind_a_bounded_run_on_its_own(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The second call site, which a one-line fix to the first would miss.

    The contract requires a bounded payload to set `partial: true` as well as
    the error. `source_collector_partial: true` is its own `add_partial` call
    with its own classification, and `blind` is monotonic -- so routing only the
    error leaves this site to freeze the watermark by itself, with a digest that
    names a reason the operator has just been told is benign.
    """
    state_path, _base, _shas, fakes = _seed_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, error="payload_bounded: 2 of 3"
    )
    orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    blind = read_current_run(state_path).get("blind_reasons", [])
    assert not any("source_collector_partial" in r for r in blind), blind


def test_an_empty_bounded_payload_stays_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """A bound is only trustworthy when something came back under it.

    `payload_bounded: 0 of 173` is not a collector holding work back, it is a
    collector that returned nothing while claiming a 173-PR window -- there is
    no detailed prefix to advance to, so the only safe reading is blind.
    """
    state_path, base, _shas, fakes = _seed_bounded(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        error="payload_bounded: 0 of 173",
        prs=[],
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 1, "an empty payload cannot be degraded"
    assert read_current_run(state_path).get("blind") is True
    assert json.loads(state_path.read_text())["last_successful_run"]["head_sha"] == base


def test_a_bounded_claim_the_payload_cannot_account_for_stays_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """Degrading on the claim alone would hand the cursor a short window.

    Three PRs arrive against a claimed 99, so 96 are unaccounted: the tail was
    dropped rather than anchored. Task 3's guard records that independently;
    this asserts the CLASSIFIER refuses it too, so the two agree instead of one
    relying on the other.
    """
    state_path, base, _shas, fakes = _seed_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, error="payload_bounded: 2 of 99"
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 1, "an unaccounted payload cannot be degraded"
    assert read_current_run(state_path).get("blind") is True
    assert json.loads(state_path.read_text())["last_successful_run"]["head_sha"] == base


def test_the_invented_overflow_string_from_the_incident_is_still_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The exact string run 37493982560 emitted must not become benign.

    `output_size_limit` is not in the contract -- the agent improvised it. An
    older plugin version, or an agent that ignores the new contract, can still
    produce it, and it carries no accounting, so there is nothing to verify a
    cursor against. CCE-144: an unclassified failure mode is loud, not silent.
    """
    state_path, _base, _shas, fakes = _seed_bounded(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        error="output_size_limit: 12 of 173 in-window PRs returned",
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 1, "an unrecognised collector error must stay blind"
    assert read_current_run(state_path).get("blind") is True


def test_a_contracted_tool_failure_is_still_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """Only `payload_bounded` is held-back; the other contracted errors are not.

    `git_rate_limit` means the collector could not LOOK, so the window it
    returned is not a judgement about that window -- the distinction CCE-144 is
    built on. Without this test the fix could be written as "any error with a
    non-empty payload is degraded", which would quietly advance across a
    rate-limited half-window.
    """
    state_path, _base, _shas, fakes = _seed_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, error="git_rate_limit"
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 1, "a tool failure must stay blind"
    assert read_current_run(state_path).get("blind") is True


# --------------------------------------------------------------------------
# The classification rule itself. The six cases above drive `run()`, which is
# what proves the wiring; these pin the boundaries the wiring cannot reach --
# an exact-count payload, a zero-detail payload, and the two string shapes a
# looser regex would wrongly accept.
# --------------------------------------------------------------------------


def test_an_exactly_accounted_payload_is_held_back():
    """`len(prs) == total` is the healthy anchored case, not an off-by-one.

    This is the boundary a `>` would break: an anchored payload returns exactly
    as many PRs as it claims, so a strict comparison would refuse every correct
    payload and leave the stall in place.
    """
    assert orun.collector_error_is_held_back("payload_bounded: 2 of 3", [1, 2, 3])


def test_a_payload_longer_than_its_claim_is_held_back():
    """More PRs than claimed is still fully accounted.

    Not a shape the contract asks for, but `>=` means an agent that
    miscounts its own total low cannot turn a complete payload into a stall.
    """
    assert orun.collector_error_is_held_back("payload_bounded: 2 of 3", [1, 2, 3, 4])


def test_a_short_payload_is_not_held_back():
    assert not orun.collector_error_is_held_back("payload_bounded: 2 of 99", [1, 2, 3])


def test_a_zero_detail_payload_is_not_held_back():
    """Anchors alone give the cursor nothing to stop on.

    A collector that anchored all three PRs and detailed none has returned a
    complete window, so the accounting check passes -- but there is no detailed
    prefix, and admitting anchors would hand the authoring stage PRs with no
    body or files. Accounting is necessary and not sufficient.
    """
    assert not orun.collector_error_is_held_back("payload_bounded: 0 of 3", [1, 2, 3])


def test_an_empty_payload_is_not_held_back():
    assert not orun.collector_error_is_held_back("payload_bounded: 0 of 0", [])


def test_a_non_string_error_is_not_held_back():
    assert not orun.collector_error_is_held_back(None, [1, 2, 3])


def test_the_reason_must_be_the_whole_error_not_a_substring():
    """A compound error is a different event and stays blind.

    `git_rate_limit; payload_bounded: 2 of 3` says the collector BOTH bounded
    its output and hit a rate limit -- the second clause makes the window
    untrustworthy whatever the first claims. The match is anchored so a
    substring cannot launder a blind error into a degraded one.
    """
    assert not orun.collector_error_is_held_back(
        "git_rate_limit; payload_bounded: 2 of 3", [1, 2, 3]
    )


def test_trailing_commentary_is_not_held_back():
    """An agent that decorates the reason has left the contract.

    Refusing it is the fail-safe reading: the decoration may be reporting
    something the accounting does not capture.
    """
    assert not orun.collector_error_is_held_back(
        "payload_bounded: 2 of 3 (body omitted)", [1, 2, 3]
    )


# --------------------------------------------------------------------------
# CCE-202: the anchored tail does not fit either.
#
# CCE-199 bounded DETAIL and contracted one metadata anchor per held-back PR.
# Measured on the ADIS window (200 in-window PRs, 2026-10-07): the contracted
# anchor shape is 186 bytes, so the tail alone is 37,203 bytes and the agent's
# actual emission was 48,563 -- reproducing the 49.6KB the runner spilled. The
# payload is O(window), which is the one variable the bound existed to make
# irrelevant, so the cliff merely moved to ~161 PRs and the window was already
# 173 when the fix was written. It could never have cleared that host's stall.
#
# The tail's per-PR anchors are only ever consumed by `advance_cursor_list` to
# walk PAST a held-back PR, which an overflowing window must never do. So the
# tail collapses to a count plus ONE stop-marker, which is O(1):
#
#   held_back_count:  how many anchorable in-window PRs went undetailed
#   held_back_oldest: {number, merge_sha} -- the oldest of them, and the only
#                     one the cursor walk needs to break on
#
# A count WITHOUT a stop-marker is the catastrophic shape, not a lesser one:
# `held_back` stays empty, the advance branch takes its `else`, and the run
# advances to full window HEAD -- CCE-144's consume-once loss, green. Hence
# `test_a_positive_count_without_a_stop_marker_stays_blind`.
# --------------------------------------------------------------------------


def _seed_count_bounded(
    tmp_path,
    init_host,
    base_config_yaml,
    *,
    cap,
    detailed,
    stop_marker="derive",
    count="derive",
    error="derive",
):
    """A capped host whose collector bounded its tail to a count + marker.

    Keeps the oldest `detailed` fixture PRs in `prs` and replaces the rest with
    `held_back_count` plus `held_back_oldest`. `stop_marker` and `count`
    default to the shapes the contract requires; pass an explicit value (or
    `None`) to seed a malformed payload.
    """
    state_path, base, shas, fakes = _seed_capped_host(
        tmp_path, init_host, base_config_yaml, cap=cap
    )
    sc_path = fakes / "fake_source_collector.json"
    sc = json.loads(sc_path.read_text())
    kept, dropped = sc["prs"][:detailed], sc["prs"][detailed:]
    sc["prs"] = kept
    if count == "derive":
        count = len(dropped)
    if stop_marker == "derive":
        stop_marker = (
            {"number": dropped[0]["number"], "merge_sha": dropped[0]["merge_sha"]}
            if dropped
            else None
        )
    if error == "derive":
        error = f"payload_bounded: {detailed} of {detailed + len(dropped)}"
    sc["partial"] = True
    sc["error"] = error
    if count is not None:
        sc["held_back_count"] = count
    if stop_marker is not None:
        sc["held_back_oldest"] = stop_marker
    sc_path.write_text(json.dumps(sc))
    return state_path, base, shas, fakes


def test_a_count_bounded_payload_advances_to_the_detailed_prefix(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """THE TICKET. An O(1) tail must advance exactly where anchors did.

    Pins the same boundary as
    `test_a_bounded_payload_that_accounts_for_its_window_advances`, which
    proves the collapse from M anchors to one stop-marker changed the payload
    SIZE and not the cursor SEMANTICS. The advance must reach `c2` -- the last
    detailed PR -- and never `c3`, which is real work still owed.
    """
    state_path, _base, (_c1, c2, c3), fakes = _seed_count_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, detailed=2
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0, "a count-bounded payload is held-back work, not a blind run"

    cr = read_current_run(state_path)
    assert cr.get("blind") is not True, cr
    assert cr.get("partial") is True, cr

    written = json.loads(state_path.read_text())
    advance = written["last_successful_run"]["head_sha"]
    assert advance == c2, written["last_successful_run"]
    assert advance != c3, "advanced past the held-back tail"


def test_the_held_back_count_is_reported_not_just_the_stop_marker(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """The reason must name the real count, not the one synthesized PR.

    The stop-marker enters the cursor machinery as a single element, so a
    reason rendered from `len(window_capped)` would read "1 of 3" on a window
    holding back 190. An operator reading that figure is the only signal the
    drain is not keeping up.
    """
    state_path, _base, _shas, fakes = _seed_count_bounded(
        tmp_path, init_host, base_config_yaml, cap=3, detailed=1
    )
    orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    reasons = read_current_run(state_path).get("partial_reasons", [])
    assert any("held_back_collector_bounded: 2 of 3" in r for r in reasons), reasons


def test_a_positive_count_without_a_stop_marker_stays_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """THE CATASTROPHIC SHAPE. A count alone must never advance.

    With no stop-marker `held_back` is empty, so the advance branch falls to
    its `else` and reaches full window HEAD -- consuming a window whose tail
    nobody documented, with no red anywhere. That is strictly worse than
    today's loud stall, so an unstoppable claim is blind by construction.
    """
    state_path, base, _shas, fakes = _seed_count_bounded(
        tmp_path, init_host, base_config_yaml, cap=2, detailed=2, stop_marker=None
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc != 0, "a tail the cursor cannot stop on must fail loudly"
    assert read_current_run(state_path).get("blind") is True

    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, "watermark moved"


def test_a_stop_marker_without_a_merge_sha_stays_blind(
    tmp_path, init_host, base_config_yaml, read_current_run
):
    """An unanchored stop-marker cannot be re-anchored by a later window.

    `_last_processed_merge_sha` skips a PR with no sha, so a marker without one
    stops the walk but leaves the cursor unable to name where it stopped.
    """
    state_path, base, _shas, fakes = _seed_count_bounded(
        tmp_path,
        init_host,
        base_config_yaml,
        cap=2,
        detailed=2,
        stop_marker={"number": 999},
    )
    rc = orun.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc != 0, rc
    assert read_current_run(state_path).get("blind") is True
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, "watermark moved"


# --- predicate units ------------------------------------------------------


_MARKER = {"number": 3, "merge_sha": "a" * 40}


def test_a_count_closes_the_accounting_gap():
    """`len(prs) + held_back_count` is the new accounting identity."""
    assert orun.collector_error_is_held_back(
        "payload_bounded: 2 of 3", [1, 2], held_back_count=1, held_back_oldest=_MARKER
    )


def test_a_count_that_does_not_close_the_gap_is_not_held_back():
    assert not orun.collector_error_is_held_back(
        "payload_bounded: 2 of 99", [1, 2], held_back_count=1, held_back_oldest=_MARKER
    )


def test_a_positive_count_without_a_stop_marker_is_not_held_back():
    assert not orun.collector_error_is_held_back(
        "payload_bounded: 2 of 3", [1, 2], held_back_count=1, held_back_oldest=None
    )


def test_a_stop_marker_without_a_merge_sha_is_not_held_back():
    assert not orun.collector_error_is_held_back(
        "payload_bounded: 2 of 3",
        [1, 2],
        held_back_count=1,
        held_back_oldest={"number": 3},
    )


def test_a_zero_count_falls_back_to_the_anchored_rule():
    """Backward compatibility, pinned.

    The anchored contract satisfies `len(prs) + 0 >= total`, so the default
    `held_back_count=0` must reduce the predicate to exactly CCE-199's rule --
    which is what keeps every CCE-199 test above meaningful rather than
    accidentally passing.
    """
    assert orun.collector_error_is_held_back("payload_bounded: 2 of 3", [1, 2, 3])
    assert not orun.collector_error_is_held_back("payload_bounded: 2 of 3", [1, 2])


def test_the_contract_documents_the_count_bounded_tail():
    """The agent is a prompt, so the prompt is the only place this can live."""
    t = (_REPO_ROOT / "agents" / "source-collector.md").read_text()
    assert "held_back_count" in t, "the count field is not contracted"
    assert "held_back_oldest" in t, "the stop-marker is not contracted"
    lo = t.index("held_back_oldest")
    assert "oldest" in t[lo - 600 : lo + 600].lower()


def test_the_schema_accepts_a_count_bounded_payload():
    import jsonschema

    schema = json.loads(
        (_REPO_ROOT / "agents" / "schemas" / "source_collector.schema.json").read_text()
    )
    jsonschema.validate(
        {
            "prs": [
                {
                    "number": 1,
                    "title": "t",
                    "url": "https://example.test/1",
                    "merged_at": "2026-01-01T00:00:00Z",
                    "merge_sha": "b" * 40,
                }
            ],
            "jira_issues": [],
            "partial": True,
            "error": "payload_bounded: 1 of 3",
            "held_back_count": 2,
            "held_back_oldest": {"number": 2, "merge_sha": "c" * 40},
        },
        schema,
    )
