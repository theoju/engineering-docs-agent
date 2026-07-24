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


def test_publish_trigger_is_provider_aware():
    # CCE-123: the post-merge publish TRIGGER (distinct from CCE-63's verify seam)
    # forks on ci_provider inside orchestrator_runner._maybe_auto_merge.
    import inspect

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    import orchestrator_runner

    trigger_src = inspect.getsource(orchestrator_runner._maybe_auto_merge)
    assert "ci_provider" in trigger_src
    # Guard the ROUTING, not just the signature token: a wrong impl that keeps
    # the ci_provider param but drops the non-github fork must fail here. The
    # bare `"ci_provider" in src` check was vacuous — reverting the whole fork
    # left the param token in the signature and this test still passed
    # (CCE-123 adversarial-validation finding).
    assert "resolve_build_trigger" in trigger_src
    assert "pages_dispatch_skipped" in trigger_src


# --- trigger seam (CCE-123) -------------------------------------------------


def test_resolve_build_trigger_degrades_honestly_while_unvalidated():
    triggered, reasons = build_poller.resolve_build_trigger("circleci")
    assert triggered is False  # no dispatch performed
    assert reasons == ["circleci_trigger_modeled_but_unvalidated"]


def test_resolve_build_trigger_flag_flip_routes_into_trigger_circleci(monkeypatch):
    # Once the honesty gate flips, the fork routes into the unimplemented trigger.
    monkeypatch.setattr(build_poller, "UNVALIDATED_AGAINST_LIVE_HOST", False)
    with pytest.raises(NotImplementedError):
        build_poller.resolve_build_trigger("circleci")


def test_trigger_circleci_is_a_stub():
    with pytest.raises(NotImplementedError):
        build_poller.trigger_circleci(build_poller.FakeCircleCiClient())


def test_trigger_unvalidated_reason_is_fixed_literal():
    _triggered, reasons = build_poller.resolve_build_trigger("circleci")
    # Pin the concrete literal VALUE (not the constant against itself) so a
    # rename of the string is caught here — asserting `reasons ==
    # [TRIGGER_UNVALIDATED_REASON]` alone stayed green under a value mutation
    # (CCE-123 adversarial-validation finding).
    assert (
        build_poller.TRIGGER_UNVALIDATED_REASON
        == "circleci_trigger_modeled_but_unvalidated"
    )
    assert reasons == ["circleci_trigger_modeled_but_unvalidated"]
    assert "token" not in build_poller.TRIGGER_UNVALIDATED_REASON
