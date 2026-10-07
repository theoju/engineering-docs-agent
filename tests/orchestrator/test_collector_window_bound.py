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
    captured = _capture_sc_inputs(monkeypatch, tmp_path, init_host, base_config_yaml, cap=2)
    assert "max_detail_prs" in captured, sorted(captured)
    assert captured["max_detail_prs"] == 2, captured["max_detail_prs"]


def test_the_bound_tracks_the_config_key_not_a_literal(
    monkeypatch, tmp_path, init_host, base_config_yaml
):
    """A hardcoded `10` satisfies the test above on a default host.

    This is the test that distinguishes `resolve_window_cap(config)` from a
    literal, so it must use a cap that is not the default.
    """
    captured = _capture_sc_inputs(monkeypatch, tmp_path, init_host, base_config_yaml, cap=7)
    assert captured["max_detail_prs"] == 7, captured["max_detail_prs"]
    assert captured["max_detail_prs"] != orun.DEFAULT_WINDOW_PR_CAP


def test_zero_reaches_the_collector_as_zero(monkeypatch, tmp_path, init_host, base_config_yaml):
    """`0` is CCE-169's advertised unlimited opt-out and must survive transit.

    `resolve_window_cap(config) or DEFAULT` would rewrite an explicit opt-out
    into the default and silently bound a host that asked not to be bounded --
    the same `is None` versus truthiness trap `resolve_window_cap` is itself
    written to avoid.
    """
    captured = _capture_sc_inputs(monkeypatch, tmp_path, init_host, base_config_yaml, cap=0)
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
    after = contract[contract.index("`max_detail_prs`") :].lower()
    assert "anchor" in after, "the contract must describe the metadata anchor shape"
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
    import json

    import jsonschema

    schema = json.loads(
        (
            _REPO_ROOT / "agents" / "schemas" / "source_collector.schema.json"
        ).read_text()
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
    import json

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
    import json

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
