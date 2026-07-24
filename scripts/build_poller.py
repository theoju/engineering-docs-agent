"""CircleCI (and future non-GitHub) build-poll seam for the publish-verifier.

CCE-63 Option D': the GitHub publish-verify path stays in agents/publish-verifier.md
(the LLM-driven `gh` poll). This module is the Python seam for non-GitHub providers.

The real CircleCI poll is NOT implemented: there is no live CircleCI-publishing
host to validate the v2 API shape against (see the CCE-63 spec section 10). While
UNVALIDATED_AGAINST_LIVE_HOST is True, resolve_build_verdict degrades honestly
(a non-promoting verdict + a fixed 'modeled but unvalidated' partial reason)
instead of polling. poll_circleci / map_circleci_status are explicit
NotImplementedError stubs, reached only once the flag is flipped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

# Load-bearing honesty gate. While True, a non-github provider degrades instead
# of polling. Flip to False only once poll_circleci is implemented AND validated
# against a live CircleCI host (CCE-63 spec section 10).
UNVALIDATED_AGAINST_LIVE_HOST = True

# Fixed-literal partial reason. Never interpolates a token/response/header.
PROVIDER_UNVALIDATED_REASON = "circleci_provider_modeled_but_unvalidated"
TOKEN_MISSING_REASON = "circleci_token_missing"

# Non-success sentinel build_status for the honest-degrade verdict. Any value
# other than "success" is non-promoting per verify_runner's gate.
UNVALIDATED_BUILD_STATUS = "circleci_unvalidated"


class CircleCiTokenMissing(RuntimeError):
    """Raised when a circleci poll is attempted with no CIRCLECI_TOKEN."""


class BuildPoller(Protocol):
    """Documented contract for a provider build-poller (spec §5.2).

    The functional seam is the module-level ``poll_circleci`` below; this
    Protocol is the object-oriented form a future provider-poller class may
    implement. It is intentionally documentation-only for now — nothing
    implements it while the CircleCI poll is an unvalidated stub (§10), so it
    exists to name the contract, not to be enforced.
    Input: publishing config block, repo {owner,name}, merged PR number.
    Output: a build_status in {'success','failure','timeout'}.
    """

    def poll(self, publishing_config: dict, repo: dict, pr_number: int) -> str: ...


@dataclass
class CircleCiClient:
    """Real CircleCI v2 client skeleton. Reads CIRCLECI_TOKEN from the env and
    sends it ONLY as a `Circle-Token` request header — never a URL userinfo
    segment or query param — so it cannot leak via a logged URL.

    The API-walking methods (pipeline -> workflow -> job) are NotImplementedError
    stubs pending a validated API (CCE-63 spec section 10).
    """

    token: str | None = None

    def __post_init__(self) -> None:
        if self.token is None:
            self.token = os.environ.get("CIRCLECI_TOKEN")

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise CircleCiTokenMissing(TOKEN_MISSING_REASON)
        return {"Circle-Token": self.token}

    def pipeline_for_commit(self, repo: dict, revision: str) -> Any:
        raise NotImplementedError(
            "CircleCI v2 pipeline lookup unvalidated — see CCE-63 spec section 10"
        )


class FakeCircleCiClient:
    """Test double mirroring CircleCiClient. Canned status for the eventual poll
    implementation; today it only proves flag-flip routing and token handling.
    """

    def __init__(
        self, *, token: str | None = "fake-token", status: str = "success"
    ) -> None:
        self.token = token
        self._status = status

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise CircleCiTokenMissing(TOKEN_MISSING_REASON)
        return {"Circle-Token": self.token}


def map_circleci_status(status: str) -> str:
    """Collapse a CircleCI workflow status onto {'success','failure','timeout'}.

    NOT IMPLEMENTED — the status vocabulary mapping (esp. `on_hold`) is an open
    decision (CCE-63 spec section 10). Reached only once UNVALIDATED_AGAINST_LIVE_HOST
    is flipped.
    """
    raise NotImplementedError(
        "CircleCI status vocabulary mapping unvalidated — see CCE-63 spec section 10"
    )


def poll_circleci(
    client: Any, publishing_config: dict, repo: dict, pr_number: int
) -> str:
    """Poll a CircleCI build to a terminal build_status.

    NOT IMPLEMENTED — no live CircleCI-publishing host exists to validate the v2
    API shape (CCE-63 spec section 10). resolve_build_verdict never reaches here
    while UNVALIDATED_AGAINST_LIVE_HOST is True.
    """
    raise NotImplementedError("CircleCI poll unvalidated — see CCE-63 spec section 10")


def resolve_build_verdict(
    provider: str, publishing_config: dict, repo: dict, pr_number: int
) -> tuple[dict, list[str]]:
    """Return (verdict, reasons) for a non-github publish provider.

    Verdict shape matches the publish-verifier contract:
    {'verified': [...], 'failed': [...], 'build_status': str}.

    While UNVALIDATED_AGAINST_LIVE_HOST is True, degrade honestly: a non-promoting
    verdict (build_status != 'success', failed empty) plus a fixed 'modeled but
    unvalidated' partial reason. No crash, no hang, no live call. Once the flag is
    flipped, route into poll_circleci (which raises until the real poll ships).
    """
    if UNVALIDATED_AGAINST_LIVE_HOST:
        return (
            {"verified": [], "failed": [], "build_status": UNVALIDATED_BUILD_STATUS},
            [PROVIDER_UNVALIDATED_REASON],
        )
    client = CircleCiClient()
    status = poll_circleci(client, publishing_config, repo, pr_number)
    return (
        {"verified": [], "failed": [], "build_status": map_circleci_status(status)},
        [],
    )


# --- trigger seam (CCE-123) -------------------------------------------------

# Fixed-literal partial reason for the honest trigger degrade. Never interpolates
# a token/response (same discipline as PROVIDER_UNVALIDATED_REASON).
TRIGGER_UNVALIDATED_REASON = "circleci_trigger_modeled_but_unvalidated"


def trigger_circleci(client: Any) -> bool:
    """Real CircleCI v2 pipeline trigger. NOT IMPLEMENTED — no live CircleCI host
    exists to validate the trigger API (CCE-123; mirrors CCE-63 §10). Reached only
    once UNVALIDATED_AGAINST_LIVE_HOST is flipped."""
    raise NotImplementedError("CircleCI trigger unvalidated — see CCE-123")


def resolve_build_trigger(provider: str) -> tuple[bool, list[str]]:
    """Return (triggered, reasons) for a non-github provider's post-merge build
    trigger. While UNVALIDATED_AGAINST_LIVE_HOST is True, degrade honestly: no
    dispatch, a fixed 'modeled but unvalidated' reason. Once flipped, route into
    trigger_circleci (which raises until the real trigger ships). GitHub never
    routes here — it keeps its native gh.workflow_run dispatch in _maybe_auto_merge."""
    if UNVALIDATED_AGAINST_LIVE_HOST:
        return (False, [TRIGGER_UNVALIDATED_REASON])
    client = CircleCiClient()
    trigger_circleci(client)  # raises until the real trigger ships
    return (True, [])
