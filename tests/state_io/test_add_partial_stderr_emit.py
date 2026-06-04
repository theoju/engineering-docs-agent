"""CCE-74: add_partial gains stderr emit on every call + redact-before-state.

Spec acceptance criteria #1 and #2:
  - Every add_partial call emits to stderr (not just newly-appended).
  - state.partial_reasons never carries raw credentials regardless of
    which call site recorded the reason.
"""

from __future__ import annotations

from scripts.state_io import add_partial


def _fresh_state() -> dict:
    return {
        "current_run": {
            "started_at": "2026-06-01T22:00:00+00:00",
            "head_sha": "abc",
            "partial": False,
            "partial_reasons": [],
        }
    }


# --- Acceptance Criterion #1: emit on every call ---------------------------


def test_add_partial_emits_partial_prefix_on_first_call(capsys):
    state = _fresh_state()
    add_partial(state, "checkout_failed: X")
    err = capsys.readouterr().err
    assert "docs-agent PARTIAL: checkout_failed: X" in err


def test_add_partial_emits_info_prefix_when_info_only(capsys):
    state = _fresh_state()
    add_partial(state, "source_map_failed: Y", info_only=True)
    err = capsys.readouterr().err
    assert "docs-agent INFO: source_map_failed: Y" in err


def test_add_partial_emits_on_every_call_not_just_first(capsys):
    """Retry-loop sequencing is the signal CCE-73 was built to preserve.
    State dedup at state_io.py:233 stays; stderr is unbounded."""
    state = _fresh_state()
    add_partial(state, "schema_invalid: X")
    add_partial(state, "schema_invalid: X")
    add_partial(state, "schema_invalid: X")
    err = capsys.readouterr().err
    assert err.count("docs-agent PARTIAL: schema_invalid: X") == 3
    # State still deduped (idempotent):
    assert state["current_run"]["partial_reasons"] == ["schema_invalid: X"]


def test_add_partial_state_dedup_preserved_with_three_distinct_reasons(capsys):
    state = _fresh_state()
    add_partial(state, "A")
    add_partial(state, "B")
    add_partial(state, "A")  # duplicate of first
    add_partial(state, "C")
    err = capsys.readouterr().err
    # 4 emissions — emit on every call, including the duplicate A:
    assert err.count("docs-agent PARTIAL: A") == 2
    assert err.count("docs-agent PARTIAL: B") == 1
    assert err.count("docs-agent PARTIAL: C") == 1
    # But state has 3 unique reasons:
    assert state["current_run"]["partial_reasons"] == ["A", "B", "C"]


# --- Acceptance Criterion #2: redact-before-state --------------------------


def test_add_partial_redacts_credentials_before_state_write(capsys):
    """The reason stored in state.partial_reasons MUST be redacted, not the
    raw input. Extends CCE-73's open_or_append_pr invariant to all 28
    add_partial sites."""
    state = _fresh_state()
    raw = "push_failed: https://x-access-token:ghs_SECRET@github.com/owner/repo.git"
    add_partial(state, raw)
    stored = state["current_run"]["partial_reasons"][0]
    assert "ghs_SECRET" not in stored
    assert "<redacted>" in stored
    err = capsys.readouterr().err
    assert "ghs_SECRET" not in err
    assert "<redacted>" in err


def test_add_partial_dedup_uses_redacted_form(capsys):
    """If two callers pass the same credential URL with different raw tokens,
    state dedup must compare the REDACTED form. Otherwise state.partial_reasons
    bloats with N variants that all look the same once redacted."""
    state = _fresh_state()
    add_partial(state, "push: https://x-access-token:ghs_AAAA@host/r")
    add_partial(state, "push: https://x-access-token:ghs_BBBB@host/r")
    # Both redact to the same string — dedup'd:
    assert state["current_run"]["partial_reasons"] == [
        "push: https://<redacted>@host/r"
    ]


# --- partial flag interaction (existing semantics preserved) ----------------


def test_add_partial_flips_partial_true_when_not_info_only():
    state = _fresh_state()
    add_partial(state, "X")
    assert state["current_run"]["partial"] is True


def test_add_partial_does_not_flip_partial_when_info_only():
    state = _fresh_state()
    add_partial(state, "X", info_only=True)
    assert state["current_run"]["partial"] is False
    assert state["current_run"]["partial_reasons"] == ["X"]


def test_add_partial_creates_current_run_when_missing(capsys):
    """When called on an empty state, add_partial must initialize
    current_run with partial=False + partial_reasons=[reason], then
    set partial=True (for default info_only=False)."""
    state: dict = {}
    add_partial(state, "X")
    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == ["X"]
    err = capsys.readouterr().err
    assert "docs-agent PARTIAL: X" in err


# --- OSError-survives semantics --------------------------------------------


def test_add_partial_state_mutation_survives_stderr_oserror(monkeypatch):
    """If sys.stderr is broken, the state mutation still happens (emit is
    best-effort). The redaction also still happens — it's a pure regex sub
    that never raises."""

    class _BrokenStream:
        def write(self, _s):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

    monkeypatch.setattr("sys.stderr", _BrokenStream())
    state = _fresh_state()
    # Must not raise:
    add_partial(state, "X")
    assert state["current_run"]["partial_reasons"] == ["X"]
    assert state["current_run"]["partial"] is True
