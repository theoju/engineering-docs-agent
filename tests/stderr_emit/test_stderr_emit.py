"""CCE-74: stderr_emit module — emit helpers + redaction.

Tests the leaf module that all stderr writes route through. Side effects:
emit_stderr writes one prefixed redacted line; emit_log writes one raw
line; both swallow OSError so a closed/broken stderr cannot crash the
orchestrator.
"""

from __future__ import annotations

import pytest

from scripts.stderr_emit import (
    _OBSERVABILITY_FLUSH,
    _redact_credentials,
    emit_log,
    emit_stderr,
)


# --- _redact_credentials ----------------------------------------------------


def test_redact_credentials_replaces_https_user_token_with_marker():
    raw = "push_failed: https://x-access-token:ghs_AAAA@github.com/owner/repo.git"
    assert (
        _redact_credentials(raw)
        == "push_failed: https://<redacted>@github.com/owner/repo.git"
    )


def test_redact_credentials_replaces_http_too():
    raw = "fetch http://user:secret@example.com/r"
    assert _redact_credentials(raw) == "fetch http://<redacted>@example.com/r"


def test_redact_credentials_passes_through_when_no_url():
    assert (
        _redact_credentials("checkout_failed: fatal: not a git repository")
        == "checkout_failed: fatal: not a git repository"
    )


def test_redact_credentials_is_idempotent():
    once = _redact_credentials("push: https://x-access-token:ghs_xxx@host/r")
    twice = _redact_credentials(once)
    assert once == twice


# --- header-form secrets (CCE-63) -------------------------------------------


def test_redact_credentials_masks_circle_token_header():
    assert (
        _redact_credentials("Circle-Token: abc123SECRET") == "Circle-Token: <redacted>"
    )


def test_redact_credentials_masks_authorization_bearer():
    assert (
        _redact_credentials("Authorization: Bearer abc123SECRET")
        == "Authorization: Bearer <redacted>"
    )


def test_redact_credentials_header_masking_is_case_insensitive():
    assert _redact_credentials("circle-token: xyz") == "circle-token: <redacted>"


def test_redact_credentials_header_masking_is_idempotent():
    once = _redact_credentials("Circle-Token: abc123SECRET")
    assert _redact_credentials(once) == once


def test_redact_credentials_masks_single_quoted_dict_repr():
    # str({"Circle-Token": token}) — the canonical leak vector when a header
    # dict is logged or lands in an HTTP-client exception (CCE-63 review).
    assert (
        _redact_credentials("{'Circle-Token': 'abc123SECRET'}")
        == "{'Circle-Token': '<redacted>'}"
    )


def test_redact_credentials_masks_double_quoted_dict_repr():
    assert (
        _redact_credentials('headers {"Circle-Token": "abc123SECRET", "X": "y"}')
        == 'headers {"Circle-Token": "<redacted>", "X": "y"}'
    )


def test_redact_credentials_masks_authorization_basic():
    assert (
        _redact_credentials("Authorization: Basic dXNlcjpwYXNzSECRET")
        == "Authorization: Basic <redacted>"
    )


def test_redact_credentials_masks_actual_auth_headers_repr():
    # The exact str() a leak would produce from CircleCiClient.auth_headers().
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    from build_poller import CircleCiClient

    leaked = f"request failed with {CircleCiClient(token='sk_live_REALSECRET').auth_headers()}"
    out = _redact_credentials(leaked)
    assert "sk_live_REALSECRET" not in out
    assert "<redacted>" in out


# --- emit_stderr ------------------------------------------------------------


def test_emit_stderr_writes_partial_prefix_when_not_info_only(capsys):
    emit_stderr("checkout_failed: X")
    err = capsys.readouterr().err
    assert err == "docs-agent PARTIAL: checkout_failed: X\n"


def test_emit_stderr_writes_info_prefix_when_info_only(capsys):
    emit_stderr("source_map_failed: Y", info_only=True)
    err = capsys.readouterr().err
    assert err == "docs-agent INFO: source_map_failed: Y\n"


def test_emit_stderr_redacts_credentials(capsys):
    emit_stderr("push: https://x-access-token:ghs_secret@github.com/r/r")
    err = capsys.readouterr().err
    assert "ghs_secret" not in err
    assert "<redacted>" in err


def test_emit_stderr_survives_oserror(monkeypatch):
    """A closed/broken stderr must not crash the orchestrator."""

    class _BrokenStream:
        def write(self, _s):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

    monkeypatch.setattr("sys.stderr", _BrokenStream())
    # Should not raise:
    emit_stderr("X")


# --- emit_log ---------------------------------------------------------------


def test_emit_log_writes_raw_text_no_prefix(capsys):
    emit_log("bootstrap.progress.json write failed: PermissionError")
    err = capsys.readouterr().err
    assert err == "bootstrap.progress.json write failed: PermissionError\n"


def test_emit_log_does_not_redact(capsys):
    """emit_log is for non-partial-reason diagnostics where the caller
    decides whether redaction is needed. Locks the non-redacting contract."""
    emit_log("debug: http://user:secret@host/r")
    err = capsys.readouterr().err
    assert "secret" in err


def test_emit_log_survives_oserror(monkeypatch):
    class _BrokenStream:
        def write(self, _s):
            raise OSError("stream closed")

        def flush(self):
            raise OSError("stream closed")

    monkeypatch.setattr("sys.stderr", _BrokenStream())
    emit_log("hello")


# --- _OBSERVABILITY_FLUSH invariant -----------------------------------------


def test_observability_flush_constant_is_true():
    """Module-level invariant: flush=True for every stderr write.
    Prevents a future contributor from copy-pasting flush=False code."""
    assert _OBSERVABILITY_FLUSH is True
