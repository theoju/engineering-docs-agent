# tests/orchestrator/test_authoring_hard_cap_bounds.py
"""CCE-152: the branch-and-boundary contract of ``resolve_authoring_hard_cap``,
and the schema round-trip that makes its config key reachable at all.

The sibling ``test_pr_boundary_authoring_cut.py`` pins the behaviour the cap
produces inside the authoring loop. This module pins the number itself: which
values are refused, which are clamped, where the clamp turns into a squeeze,
and — the defect that made all of it invisible — whether a config carrying
``run.authoring_hard_cap_seconds`` survives the loader the nightly actually
uses.

That last point is the reason this file exercises ``load_config_validated``
rather than handing raw dicts to the resolver. The key was documented in the
resolver's docstring and read by the resolver, while ``templates/config.schema.json``
still declared the ``run`` block ``additionalProperties: false``. Every unit
test passed a dict the schema never saw, so nothing noticed that a host
following the documentation aborted its nightly at config validation
(``scripts/state_io.py:load_config_validated``) before the resolver was ever
called.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402
from state_io import ConfigError, load_config_validated  # noqa: E402


def _write_config(tmp_path: Path, base_yaml: str, run_block: dict) -> Path:
    """Serialise the shared host config with `run:` replaced by ``run_block``.

    Round-tripping through yaml rather than string-splicing so a value's Python
    type survives into the file — ``2415.5`` stays a float and ``True`` stays a
    bool, which is exactly what the schema's `integer` type is being asked
    about.
    """
    cfg = yaml.safe_load(base_yaml)
    cfg["run"] = run_block
    p = tmp_path / "config.yml"
    p.write_text(yaml.safe_dump(cfg))
    return p


# --------------------------------------------------------------------------
# The schema round-trip: the documented key has to reach the resolver.
# --------------------------------------------------------------------------


def test_the_documented_override_survives_the_real_loader(tmp_path, base_config_yaml):
    """A config carrying the documented key must LOAD, and its value must be
    the one the resolver returns.

    Two failures in one assertion chain, and they are different failures: the
    load is what the schema fix bought (before it, this raised ConfigError at
    ``$.run`` for an unevaluated property and the nightly exited 2), and the
    resolved value is what proves the key is still wired to the resolver rather
    than merely tolerated by the schema.
    """
    cfg_path = _write_config(
        tmp_path,
        base_config_yaml,
        {"time_budget_seconds": 2100, "authoring_hard_cap_seconds": 2415},
    )
    loaded = load_config_validated(cfg_path)
    assert loaded["run"]["authoring_hard_cap_seconds"] == 2415
    budget = runner.resolve_time_budget(loaded, None)
    assert budget == 2100
    # Not the 1.15 default (which is also 2415 at this budget — so use a
    # budget/cap pair the ratio cannot produce).
    assert runner.resolve_authoring_hard_cap(loaded, budget) == 2415


def test_a_loaded_override_beats_the_ratio(tmp_path, base_config_yaml):
    """Precedence, asserted on a value the ratio can never yield.

    ``2100 * 1.15`` is 2415; a config asking for 2200 must get 2200, not 2415.
    """
    cfg_path = _write_config(
        tmp_path,
        base_config_yaml,
        {"time_budget_seconds": 2100, "authoring_hard_cap_seconds": 2200},
    )
    loaded = load_config_validated(cfg_path)
    assert runner.resolve_authoring_hard_cap(loaded, 2100) == 2200
    assert int(2100 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO) != 2200


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("soon", id="string"),
        pytest.param(2415.5, id="float"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param(None, id="null"),
    ],
)
def test_the_loader_rejects_a_non_positive_integer_hard_cap(
    tmp_path, base_config_yaml, bad
):
    """The `integer` + `minimum: 1` types are load-bearing, not decoration.

    The resolver does an unguarded ``int(val)``: ``"soon"`` would raise
    ValueError out of ``run()``'s config guard as an exit 2 with a stack-shaped
    message, ``2415.5`` would silently truncate to 2415, and a key written and
    left blank (`null`) would silently resolve to the ratio default. The schema
    is where all four become one legible rejection naming the key.
    """
    cfg_path = _write_config(
        tmp_path, base_config_yaml, {"authoring_hard_cap_seconds": bad}
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config_validated(cfg_path)
    assert "authoring_hard_cap_seconds" in str(excinfo.value)


def test_the_run_block_did_not_become_permissive(tmp_path, base_config_yaml):
    """Adding one property must not have relaxed the block.

    The `run` block is `additionalProperties: false` on purpose: a misspelled
    knob that validates is a knob that silently does nothing all night. Pinning
    a near-miss of the NEW key specifically, since that is the spelling an
    operator copying it by hand gets wrong.
    """
    cfg_path = _write_config(
        tmp_path, base_config_yaml, {"authoring_hardcap_seconds": 2415}
    )
    with pytest.raises(ConfigError):
        load_config_validated(cfg_path)


# --------------------------------------------------------------------------
# The rejection boundary: cap <= budget is refused, cap == budget + 1 is not.
# --------------------------------------------------------------------------


def test_a_cap_one_second_above_the_budget_is_accepted_unchanged():
    """The other side of the rejection, which fixes the comparison at ``<=``.

    The refusal test pins ``cap == budget``. Without this one, tightening the
    guard to ``cap <= budget + N`` — or to any "give it some headroom"
    normalisation — would stay green while quietly overriding operators who
    asked for a small, deliberate overrun.
    """
    assert (
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": 2101}}, 2100
        )
        == 2101
    )


def test_a_cli_budget_override_participates_in_the_rejection():
    """Characterisation, and an operator-visible trap worth having written down.

    The budget the resolver compares against is the RESOLVED one, so
    ``--time-budget-seconds`` outranks the config's budget while the config's
    hard cap stays fixed. A host configured `2100 / 2415` that is re-run by
    hand with a 3000s budget therefore exits 2 before doing any work, on a
    config file nobody edited.

    That is the shipped precedence, not a claim about what it should be — if it
    is ever changed deliberately, this test is the record of what changed.
    """
    cfg = {"run": {"time_budget_seconds": 2100, "authoring_hard_cap_seconds": 2415}}
    budget = runner.resolve_time_budget(cfg, 3000)
    assert budget == 3000
    with pytest.raises(runner.ConfigError):
        runner.resolve_authoring_hard_cap(cfg, budget)
    # Without the override the same config is fine.
    assert (
        runner.resolve_authoring_hard_cap(cfg, runner.resolve_time_budget(cfg, None))
        == 2415
    )


def test_a_rejected_cap_names_both_numbers():
    """The message has to be actionable from the log line alone.

    ``run()`` catches this and returns 2 after emitting the message; the
    operator never sees a traceback, so the message is the entire diagnosis.
    """
    with pytest.raises(runner.ConfigError) as excinfo:
        runner.resolve_authoring_hard_cap(
            {"run": {"authoring_hard_cap_seconds": 1800}}, 2100
        )
    msg = str(excinfo.value)
    assert "1800" in msg and "2100" in msg


# --------------------------------------------------------------------------
# The TTL clamp, and the ceiling it is computed from.
# --------------------------------------------------------------------------


def test_the_ceiling_is_computed_from_this_hosts_own_merge_poll():
    """The poll term is read from config, not from the default constant.

    At budget 2800 the two paths diverge completely: on the default 900s poll
    the ceiling (2580) is below the budget and the host is squeezed flat, while
    on a 300s poll the ceiling is 3180 and the host keeps a real (clamped)
    overrun. A ceiling hardcoded to DEFAULT_CHECKS_TIMEOUT_SECONDS would give
    the second host the first host's answer.
    """
    fast_poll = {"merge": {"checks_timeout_seconds": 300}}
    ceiling = (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS - 300 - runner.AUTHORING_TTL_SAFETY_SECONDS
    )
    assert ceiling == 3180
    # The ratio product (3219) is above the ceiling, so the clamp is what answers.
    assert int(2800 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO) > ceiling
    assert runner.resolve_authoring_hard_cap(fast_poll, 2800) == ceiling
    # Same budget, default poll: no headroom at all.
    squeezed: list[str] = []
    assert runner.resolve_authoring_hard_cap({}, 2800, out_reasons=squeezed) == 2800
    assert squeezed


def test_a_manual_host_is_still_bounded_by_the_token():
    """Skipping the poll term is not skipping the clamp.

    A `policy: manual` host runs no merge poll, so it is charged nothing for
    one — but it still runs under the same installation token, and the tail
    reserve is still spent. A large override must land on TTL - tail, not on
    the override.
    """
    manual_big = {
        "merge": {"policy": "manual"},
        "run": {"authoring_hard_cap_seconds": 5000},
    }
    expected = runner.GITHUB_APP_TOKEN_TTL_SECONDS - runner.AUTHORING_TTL_SAFETY_SECONDS
    assert expected == 3480
    assert runner.resolve_authoring_hard_cap(manual_big, 2700) == expected


def test_a_malformed_merge_block_is_charged_the_poll_it_will_run():
    """`merge: nonsense` resolves to the auto default, so it pays for the poll.

    ``resolve_merge_settings`` treats a non-dict block as auto (default-ON), and
    the ceiling has to agree with it — reading a malformed block as "not auto"
    would hand the host the manual ceiling while it goes on running the poll,
    which is the one direction of this arithmetic that outlives the token.
    """
    reasons: list[str] = []
    assert (
        runner.resolve_authoring_hard_cap(
            {"merge": "nonsense"}, 2700, out_reasons=reasons
        )
        == 2700
    )
    assert reasons and reasons[0].startswith("authoring_hard_cap_squeezed:")
    # Identical to the well-formed auto host.
    auto: list[str] = []
    assert runner.resolve_authoring_hard_cap({}, 2700, out_reasons=auto) == 2700
    assert auto == reasons


# --------------------------------------------------------------------------
# The squeeze boundary: ceiling <= budget, and one second either side of it.
# --------------------------------------------------------------------------


def test_a_ceiling_exactly_at_the_budget_squeezes():
    """The `<=` in the squeeze test, pinned at the value that distinguishes it.

    A 1380s poll puts the ceiling at exactly 2100 for a 2100s host. Equal is a
    squeeze: the cap would be held at the budget either way, but a `<` here
    would take the ``min(cap, ceiling)`` path instead and return the same 2100
    with NO reason attached — the silent version of the degradation, which is
    the half the design forbids.
    """
    poll = (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS - runner.AUTHORING_TTL_SAFETY_SECONDS - 2100
    )
    assert poll == 1380
    reasons: list[str] = []
    cap = runner.resolve_authoring_hard_cap(
        {"merge": {"checks_timeout_seconds": poll}}, 2100, out_reasons=reasons
    )
    assert cap == 2100
    assert len(reasons) == 1 and reasons[0].startswith("authoring_hard_cap_squeezed:")


def test_a_ceiling_one_second_above_the_budget_does_not_squeeze():
    """One second of headroom is headroom: the cap clamps, quietly.

    This is what stops the squeeze predicate drifting to `ceiling <= budget + N`
    "for safety" — that would start emitting an advisory, and holding the cap
    flat, for hosts that do have room.
    """
    poll = (
        runner.GITHUB_APP_TOKEN_TTL_SECONDS - runner.AUTHORING_TTL_SAFETY_SECONDS - 2101
    )
    assert poll == 1379
    reasons: list[str] = []
    cap = runner.resolve_authoring_hard_cap(
        {"merge": {"checks_timeout_seconds": poll}}, 2100, out_reasons=reasons
    )
    assert cap == 2101
    assert reasons == []


def test_an_explicit_override_is_squeezed_too_and_the_reason_names_it():
    """The asymmetry the docstring claims, asserted.

    An override ABOVE the budget passes the rejection — so the operator's value
    is legal — and is then held at the budget anyway by a token nobody in this
    process controls. The reason must name the cap that was given up, or the
    operator reads a squeeze message that does not mention the number they set
    and concludes their config was ignored.
    """
    reasons: list[str] = []
    cap = runner.resolve_authoring_hard_cap(
        {"run": {"authoring_hard_cap_seconds": 3000}}, 2700, out_reasons=reasons
    )
    assert cap == 2700
    assert len(reasons) == 1
    assert "3000s" in reasons[0], reasons[0]


def test_the_squeeze_does_not_require_an_out_reasons_sink():
    """``out_reasons`` is optional, and the resolver still degrades correctly.

    Every caller in the tree passes a list today, so a missing `is not None`
    guard would only surface from a future caller — or from a unit test — as an
    AttributeError inside config resolution, i.e. as an exit 2 for a host whose
    config is fine.
    """
    assert (
        runner.resolve_authoring_hard_cap({}, runner.DEFAULT_TIME_BUDGET_SECONDS)
        == runner.DEFAULT_TIME_BUDGET_SECONDS
    )


def test_an_unlimited_budget_is_never_squeezed():
    """budget 0 means no deadline, so there is nothing to hold the cap at.

    ``run()`` turns a 0 budget into ``deadline=None`` and then
    ``authoring_hard_deadline=None``, so the cap is unused — but the resolver
    still runs, and `ceiling <= budget` must read False for it. An inverted or
    `<`-flipped comparison would hand every unlimited host a nightly advisory
    about a squeeze that cannot happen to it.
    """
    reasons: list[str] = []
    assert runner.resolve_authoring_hard_cap({}, 0, out_reasons=reasons) == 0
    assert reasons == []


# --------------------------------------------------------------------------
# The shared `run:` accessor (_run_cfg).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("nonsense", id="string"),
        pytest.param(None, id="null"),
        pytest.param([], id="list"),
        pytest.param(5, id="int"),
    ],
)
def test_every_run_resolver_survives_a_malformed_run_block(malformed):
    """One accessor, one behaviour: a non-dict `run:` resolves to defaults.

    ``resolve_time_budget`` used ``config.get("run") or {}``, which is a dict
    only by luck: any truthy non-mapping reached ``.get`` and raised
    AttributeError out of the resolver — uncaught, before the notifier, so the
    nightly died with a traceback and no digest. Its two siblings already
    treated the same block as absent. The extracted ``_run_cfg`` makes all
    three agree; this pins the agreement rather than the extraction, so an
    inlining later cannot regress one of them alone.
    """
    cfg = {"run": malformed}
    assert runner.resolve_time_budget(cfg, None) == runner.DEFAULT_TIME_BUDGET_SECONDS
    assert (
        runner.resolve_deferral_threshold(cfg) == runner.DEFAULT_DEFERRAL_SKIP_THRESHOLD
    )
    assert runner.resolve_authoring_hard_cap(cfg, 2100) == int(
        2100 * runner.DEFAULT_AUTHORING_HARD_CAP_RATIO
    )
    # The CLI override still wins over a malformed block rather than tripping on it.
    assert runner.resolve_time_budget(cfg, 120) == 120
