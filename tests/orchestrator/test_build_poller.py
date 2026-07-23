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
    reason="publish-trigger is GitHub-only: orchestrator_runner._maybe_auto_merge "
    "dispatches gh.workflow_run(build_workflow) unconditionally (~line 2886). "
    "Provider-aware dispatch for ci_provider: circleci is tracked by the CCE-63 "
    "sibling trigger ticket. This strict-xfail flips to a hard failure the moment "
    "that seam learns about ci_provider, forcing the implementer to update it.",
    strict=True,
)
def test_publish_trigger_is_provider_aware():
    # AC6: the post-merge publish TRIGGER (distinct from this ticket's verify
    # seam) is the second GitHub-only seam. It lives in orchestrator_runner's
    # _maybe_auto_merge, NOT build_poller — so the fence must anchor THERE, or
    # it never fires when the gap actually closes. DESIRED future state: the
    # trigger dispatch branches on ci_provider. Today it does not (github-only).
    import inspect

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner

    trigger_src = inspect.getsource(orchestrator_runner._maybe_auto_merge)
    assert "ci_provider" in trigger_src
