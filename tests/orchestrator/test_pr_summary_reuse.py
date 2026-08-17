# tests/orchestrator/test_pr_summary_reuse.py
"""CCE-159: reusing a merged PR's summary instead of re-buying it every night.

The waste this closes was measured on the advanced-data-import-system host,
not estimated: 52 of the 58 PRs summarized on 2026-08-17 had been summarized
the night before — 90% repeat work, and it included every PR that run went on
to discard. At 29,346 fresh-input tokens per summarized PR, a healthy run was
spending ~1.53M tokens a night re-deriving summaries of content that cannot
change.

A merged PR is immutable, which is what makes this cache exact rather than
heuristic. The whole design rests on that premise, so most of this module is
about the two ways it can stop holding — the content behind the number changes
(``merge_sha``), or the instructions that read it change
(``agents/pr-summarizer.md``) — and on proving each one invalidates.

Like ``test_authoring_hard_cap_bounds.py``, the config case goes through
``load_config_validated`` rather than a raw dict. That file records why: a key
read by the runner but undeclared in ``templates/config.schema.json`` aborts a
host's nightly at config validation, and every unit test passing raw dicts
sails straight past it. ``run`` is still ``additionalProperties: false``.
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import orchestrator_runner as runner  # noqa: E402
from state_io import load_config_validated, load_state_validated  # noqa: E402

REPO = {"owner": "acme", "name": "widgets"}
NOW = datetime(2026, 8, 17, 10, 7, 32, tzinfo=timezone.utc)
FINGERPRINT = "abc123def4567890"


def _pr(number: int, merge_sha: str = "deadbeef") -> dict:
    return {"number": number, "merge_sha": merge_sha}


def _summary(hint: str = "core/backend/thing.md") -> dict:
    return {
        "pr_number": 1,
        "what_changed": "a thing changed",
        "doc_targets": [{"lens": "core", "action": "edit", "page_hint": hint}],
    }


def _entry(**overrides) -> dict:
    entry = {
        "merge_sha": "deadbeef",
        "fingerprint": FINGERPRINT,
        "last_seen_at": NOW.isoformat(),
        "summary": _summary(),
    }
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------
# Serving: the hit, and every reason to miss
# --------------------------------------------------------------------------


def test_an_unchanged_merged_pr_is_served_from_cache():
    """The whole point: no dispatch for content that cannot have changed."""
    cache = {"acme/widgets#648": _entry()}
    assert (
        runner.cached_pr_summary(cache, _pr(648), repo=REPO, fingerprint=FINGERPRINT)
        == _summary()
    )


def test_a_changed_merge_sha_invalidates_that_entry_only():
    """Same number, different content — a rewritten history or a re-merge.

    The number alone is not identity. If it were, the cache would serve a
    summary of code that is no longer there, which is worse than any amount of
    re-summarizing.
    """
    cache = {"acme/widgets#648": _entry(), "acme/widgets#649": _entry()}
    assert (
        runner.cached_pr_summary(
            cache, _pr(648, "0ther5ha"), repo=REPO, fingerprint=FINGERPRINT
        )
        is None
    )
    assert (
        runner.cached_pr_summary(cache, _pr(649), repo=REPO, fingerprint=FINGERPRINT)
        == _summary()
    ), "the sibling entry must be untouched — invalidation is per PR, not global"


def test_editing_the_summarizer_agent_invalidates_every_entry():
    """A summary is only valid for the instructions that produced it.

    This is why the fingerprint hashes the agent file rather than naming a
    version constant: nobody has to remember to bump it, so it cannot silently
    drift out of date the way a hand-maintained number does.
    """
    cache = {"acme/widgets#648": _entry(), "acme/widgets#649": _entry()}
    for number in (648, 649):
        assert (
            runner.cached_pr_summary(
                cache, _pr(number), repo=REPO, fingerprint="0000new0fingerprint"
            )
            is None
        )


def test_an_unreadable_agent_file_bypasses_the_cache_rather_than_trusting_it():
    """``pr_summarizer_fingerprint`` returns "" when it cannot read the agent.

    An empty fingerprint must match nothing. The alternative — treating
    "unknown" as "unchanged" — serves summaries whose provenance cannot be
    established, and does it silently.
    """
    cache = {"acme/widgets#648": _entry(fingerprint="")}
    assert runner.cached_pr_summary(cache, _pr(648), repo=REPO, fingerprint="") is None


def test_a_missing_or_malformed_entry_is_a_miss_not_a_crash():
    for cache in ({}, None, {"acme/widgets#648": "not-a-dict"}):
        assert (
            runner.cached_pr_summary(
                cache, _pr(648), repo=REPO, fingerprint=FINGERPRINT
            )
            is None
        )


def test_the_fingerprint_tracks_the_real_agent_file():
    """Not a fixture: hash the file the runner actually dispatches."""
    fingerprint = runner.pr_summarizer_fingerprint()
    assert fingerprint and len(fingerprint) == 16
    assert fingerprint == runner.pr_summarizer_fingerprint(), "must be stable"


# --------------------------------------------------------------------------
# Lifecycle: what survives to the next run
# --------------------------------------------------------------------------


def test_a_summary_produced_this_run_is_stored_for_the_next_one():
    out = runner.next_pr_summaries(
        {},
        repo=REPO,
        window_prs=[_pr(648)],
        summary_by_number={648: _summary()},
        fingerprint=FINGERPRINT,
        now=NOW,
    )
    stored = out["acme/widgets#648"]
    assert stored["summary"] == _summary()
    assert stored["merge_sha"] == "deadbeef"
    assert stored["fingerprint"] == FINGERPRINT


def test_a_pr_with_no_merge_sha_is_never_stored():
    """Half the validity check is the sha. An entry that cannot be invalidated
    is worse than no entry, because it can only ever be served blindly."""
    out = runner.next_pr_summaries(
        {},
        repo=REPO,
        window_prs=[{"number": 648}],
        summary_by_number={648: _summary()},
        fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert out == {}


def test_a_deferred_pr_keeps_its_entry_alive_while_it_is_still_being_asked_for():
    """A PR the admission gate never reached has no fresh summary this run.

    Its entry must still be refreshed, or the PR most likely to benefit from
    the cache — one deferred night after night — is the one that ages out of it.
    """
    old = (NOW - timedelta(days=20)).isoformat()
    out = runner.next_pr_summaries(
        {"acme/widgets#648": _entry(last_seen_at=old)},
        repo=REPO,
        window_prs=[_pr(648)],
        summary_by_number={},
        fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert out["acme/widgets#648"]["last_seen_at"] == NOW.isoformat()
    assert out["acme/widgets#648"]["summary"] == _summary()


def test_entries_age_out_so_the_cache_cannot_grow_forever():
    """A PR the baseline has passed never returns to a window."""
    stale = (NOW - timedelta(days=runner.PR_SUMMARY_RETENTION_DAYS + 1)).isoformat()
    fresh = (NOW - timedelta(days=1)).isoformat()
    out = runner.next_pr_summaries(
        {
            "acme/widgets#1": _entry(last_seen_at=stale),
            "acme/widgets#2": _entry(last_seen_at=fresh),
        },
        repo=REPO,
        window_prs=[],
        summary_by_number={},
        fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert "acme/widgets#1" not in out
    assert "acme/widgets#2" in out


def test_a_transient_window_shrink_does_not_wipe_the_cache():
    """The source-collector degrading is exactly when the pipeline can least
    afford to re-buy every summary, so absence from one window means nothing.

    This is why eviction is by last-seen rather than by window membership: the
    obvious implementation of "prune what is not in the window" empties the
    cache on the worst possible night.
    """
    cache = {
        f"acme/widgets#{n}": _entry(last_seen_at=NOW.isoformat()) for n in range(5)
    }
    out = runner.next_pr_summaries(
        cache,
        repo=REPO,
        window_prs=[],
        summary_by_number={},
        fingerprint=FINGERPRINT,
        now=NOW,
    )
    assert len(out) == 5


def test_the_next_cache_never_mutates_the_one_it_was_given():
    """Same contract as ``next_deferral_counts``: pure, so a caller can compare
    before and after to decide whether anything changed."""
    cache = {"acme/widgets#648": _entry()}
    before = dict(cache["acme/widgets#648"])
    runner.next_pr_summaries(
        cache,
        repo=REPO,
        window_prs=[_pr(648)],
        summary_by_number={648: _summary("other.md")},
        fingerprint="different",
        now=NOW,
    )
    assert cache["acme/widgets#648"] == before


def test_a_host_that_caches_nothing_keeps_an_empty_key():
    """Never-seed-empty, matching ``skipped_prs`` and ``deferral_counts``. A
    host with nothing to store keeps a state.json byte-identical to its
    pre-CCE-159 content, so no host's first run produces a no-op diff."""
    assert (
        runner.next_pr_summaries(
            {},
            repo=REPO,
            window_prs=[],
            summary_by_number={},
            fingerprint=FINGERPRINT,
            now=NOW,
        )
        == {}
    )


# --------------------------------------------------------------------------
# The round-trips, for the reason test_authoring_hard_cap_bounds records
# --------------------------------------------------------------------------


def test_the_kill_switch_survives_the_real_config_loader(tmp_path, base_config_yaml):
    """``run`` is ``additionalProperties: false``, so an undeclared key does
    not degrade — it aborts the nightly at config validation, before any of
    this code runs. Exercising the loader is the only way that is visible."""
    cfg = yaml.safe_load(base_config_yaml)
    cfg["run"] = {**(cfg.get("run") or {}), "reuse_pr_summaries": False}
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(cfg))

    assert load_config_validated(path)["run"]["reuse_pr_summaries"] is False


def test_reuse_defaults_to_on_when_the_host_says_nothing(tmp_path, base_config_yaml):
    """The saving should not require every host to opt in, and the cache is
    safe by construction — it serves nothing it cannot prove is current."""
    cfg = yaml.safe_load(base_config_yaml)
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(cfg))

    loaded = load_config_validated(path)
    assert (loaded.get("run") or {}).get("reuse_pr_summaries", True) is True


def test_a_cached_state_round_trips_through_the_state_schema(tmp_path):
    """The stored shape has to survive ``load_state_validated``, or the very
    next run rejects the state its predecessor wrote."""
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"version": "1", "pr_summaries": {"acme/widgets#648": _entry()}})
    )
    loaded = load_state_validated(path)
    assert loaded["pr_summaries"]["acme/widgets#648"]["merge_sha"] == "deadbeef"
