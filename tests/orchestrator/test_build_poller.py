from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import build_poller  # noqa: E402


def test_flag_is_load_bearing_and_true_by_default():
    assert build_poller.UNVALIDATED_AGAINST_LIVE_HOST is True


def test_resolve_degrades_honestly_while_unvalidated():
    verdict, reasons = build_poller.resolve_build_verdict(
        "circleci", {"base_url": "https://x"}, {"owner": "o", "name": "r"}, 42
    )
    assert verdict["failed"] == []
    assert verdict["build_status"] != "success"  # non-promoting
    assert reasons == ["circleci_provider_modeled_but_unvalidated"]


def test_flag_flip_routes_into_poll_circleci(monkeypatch):
    # AC4: flipping the flag routes the fork into the unimplemented live poll.
    monkeypatch.setattr(build_poller, "UNVALIDATED_AGAINST_LIVE_HOST", False)
    with pytest.raises(NotImplementedError):
        build_poller.resolve_build_verdict(
            "circleci", {}, {"owner": "o", "name": "r"}, 42
        )


def test_poll_and_map_are_stubs():
    with pytest.raises(NotImplementedError):
        build_poller.poll_circleci(build_poller.FakeCircleCiClient(), {}, {}, 1)
    with pytest.raises(NotImplementedError):
        build_poller.map_circleci_status("on_hold")


def test_circleci_client_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("CIRCLECI_TOKEN", "envtok")
    client = build_poller.CircleCiClient()
    assert client.auth_headers() == {"Circle-Token": "envtok"}


def test_circleci_client_missing_token_raises_typed_error(monkeypatch):
    monkeypatch.delenv("CIRCLECI_TOKEN", raising=False)
    client = build_poller.CircleCiClient()
    with pytest.raises(build_poller.CircleCiTokenMissing):
        client.auth_headers()


def test_token_never_appears_in_reason_strings():
    # The degrade reason is a fixed literal — never interpolates a token.
    _, reasons = build_poller.resolve_build_verdict("circleci", {}, {}, 1)
    assert all(
        r == "circleci_provider_modeled_but_unvalidated" or "token" not in r
        for r in reasons
    )


@pytest.mark.xfail(
    reason="publish-trigger is GitHub-only (orchestrator_runner.py workflow_run); "
    "provider-aware dispatch tracked by the CCE-63 sibling trigger ticket",
    strict=True,
)
def test_publish_trigger_is_provider_aware():
    # AC6: DESIRED future behavior — a circleci host's post-merge publish is
    # triggered via a CircleCI pipeline, not gh.workflow_run. Not built yet;
    # this strict-xfail flips to a hard failure the moment it is, forcing the
    # implementer to remove the marker.
    assert hasattr(build_poller, "trigger_circleci_publish")
