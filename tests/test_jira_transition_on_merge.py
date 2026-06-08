"""Unit tests for scripts/jira_transition_on_merge.py (CCE-103).

Stdlib-first: the HTTP layer is exercised by monkeypatching urllib.request.urlopen
with a FakeUrlopen — no `responses`/`requests-mock` dependency. Each test declares
only the (method, url-suffix) calls it expects; an unmocked call fails loudly.

Test classes mirror the design's testability seams (one per section):
  TestExtractKeys / TestFormatClosureComment / TestFindDoneTransitionId  (pure)
  TestJiraClient                                                          (HTTP)
  TestProcessKey                                                          (per-key flow)
  TestMain                                                                (aggregation + exit)
"""

from __future__ import annotations

import base64
import json
import socket
import urllib.error
import urllib.request

import pytest

from scripts import jira_transition_on_merge as mod
from scripts.jira_transition_on_merge import (
    JiraAuthError,
    JiraClient,
    JiraNotFoundError,
    JiraServerError,
    extract_keys,
    find_done_transition_id,
    format_closure_comment,
)


# --- stdlib-only HTTP fake -------------------------------------------------
class _FakeResp:
    def __init__(self, status, body):
        self.status = status
        if isinstance(body, bytes):
            self._raw = body  # raw (possibly non-JSON) body, e.g. a CDN HTML page
        elif body is None:
            self._raw = b""
        else:
            self._raw = json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeUrlopen:
    """Routes keyed by (method, url-suffix) -> (status, body) | Exception.

    A value may be an Exception instance (raised) to simulate HTTPError/URLError.
    An unmocked (method, url) fails loudly so test pollution can't pass silently.
    """

    def __init__(self, routes):
        self.routes = routes
        self.calls = []  # (method, url, body_dict|None, auth_header)

    def __call__(self, req, timeout=None):
        method = req.get_method()
        url = req.full_url
        body = json.loads(req.data.decode()) if req.data else None
        self.calls.append((method, url, body, req.get_header("Authorization")))
        for (m, suffix), val in self.routes.items():
            if m == method and url.endswith(suffix):
                if isinstance(val, list):
                    # A SEQUENCED route: each call pops the next step, so a test can
                    # express fail-then-succeed — the retry-RECOVERY path that a
                    # fixed single-value route cannot exercise.
                    val = val.pop(0)
                if isinstance(val, Exception):
                    raise val
                return _FakeResp(*val)
        raise AssertionError(f"unmocked Jira call: {method} {url}")


@pytest.fixture
def fake_jira(monkeypatch):
    # Record backoff sleeps rather than performing them: unit tests stay instant AND
    # a test can assert the retry path actually paused (and for how long). Without
    # this, deleting the sleep or zeroing _RETRY_BACKOFF_S survives the suite.
    sleeps: list = []
    monkeypatch.setattr(mod.time, "sleep", sleeps.append)

    def install(routes):
        fake = FakeUrlopen(routes)
        fake.sleeps = sleeps
        monkeypatch.setattr(urllib.request, "urlopen", fake)
        return fake

    return install


def _http_error(code):
    return urllib.error.HTTPError("https://jira/x", code, "err", {}, None)


class TestExtractKeys:
    def test_empty_title_returns_empty(self):
        assert extract_keys("") == []

    def test_no_key_returns_empty(self):
        assert extract_keys("chore: bump deps") == []

    def test_single_key(self):
        assert extract_keys("feat(CCE-103): wire jira auto-transition") == ["CCE-103"]

    def test_multiple_keys_in_occurrence_order(self):
        assert extract_keys("feat(CCE-89): D1+D2 land (also closes CCE-77)") == [
            "CCE-89",
            "CCE-77",
        ]

    def test_duplicate_keys_collapse_preserving_first(self):
        assert extract_keys("CCE-1 then CCE-2 then CCE-1 again") == ["CCE-1", "CCE-2"]

    def test_lowercase_prefix_rejected(self):
        # CCE keys are uppercase by convention; a lowercase mention is not a key.
        assert extract_keys("cce-103: nope") == []

    def test_embedded_in_word_rejected(self):
        # Word boundaries: xCCE-1y is not a standalone key.
        assert extract_keys("xCCE-1y") == []

    def test_commit_style_space_suffix_extracts(self):
        # "feat(CCE-89 D2): foo" — the key is bounded by a space, so it matches.
        assert extract_keys("feat(CCE-89 D2): foo") == ["CCE-89"]


class TestFormatClosureComment:
    CTX = dict(
        pr_number=123,
        pr_title="feat(CCE-103): wire jira auto-transition",
        merge_sha="abc123def",
        merged_at="2026-06-04T20:00:00Z",
        pr_url="https://github.com/theoju/engineering-docs-agent/pull/123",
    )

    def test_markdown_link_present(self):
        out = format_closure_comment(**self.CTX)
        assert (
            "[PR #123](https://github.com/theoju/engineering-docs-agent/pull/123)"
            in out
        )

    def test_sha_in_code_fence(self):
        out = format_closure_comment(**self.CTX)
        assert "`abc123def`" in out

    def test_timestamp_iso8601_present(self):
        out = format_closure_comment(**self.CTX)
        assert "2026-06-04T20:00:00Z" in out

    def test_long_title_not_truncated(self):
        long_title = "feat(CCE-1): " + ("x" * 300)
        out = format_closure_comment(**{**self.CTX, "pr_title": long_title})
        assert long_title in out

    def test_markdown_char_laden_title_embedded(self):
        nasty = "feat(CCE-1): *bold* _under_ `code` it"
        out = format_closure_comment(**{**self.CTX, "pr_title": nasty})
        assert nasty in out


class TestFindDoneTransitionId:
    @staticmethod
    def _t(tid, cat):
        return {"id": tid, "name": f"to-{cat}", "to": {"statusCategory": {"key": cat}}}

    def test_one_done_returns_its_id(self):
        assert find_done_transition_id([self._t("41", "done")]) == "41"

    def test_multiple_done_returns_first(self):
        ts = [
            self._t("11", "indeterminate"),
            self._t("41", "done"),
            self._t("42", "done"),
        ]
        assert find_done_transition_id(ts) == "41"

    def test_no_done_returns_none(self):
        ts = [self._t("11", "new"), self._t("21", "indeterminate")]
        assert find_done_transition_id(ts) is None

    def test_empty_list_returns_none(self):
        assert find_done_transition_id([]) is None

    def test_done_match_without_id_returns_none(self):
        # A malformed transition that matches the done category but carries no `id`
        # can't be POSTed — `.get("id")` must yield None (not KeyError), so the caller
        # reports no_done_transition and fails loud rather than crashing.
        assert (
            find_done_transition_id([{"to": {"statusCategory": {"key": "done"}}}])
            is None
        )


class TestJiraClient:
    BASE = "https://designitright.atlassian.net"

    def _client(self):
        return JiraClient(self.BASE, "me@x.com", "tok")

    def test_base_url_trailing_slash_stripped(self):
        # A configured base URL with a trailing slash must not double the slash in the
        # request path (".../net//rest/api/...") — rstrip it once at construction.
        assert JiraClient(self.BASE + "/", "me@x.com", "tok").base_url == self.BASE

    def test_get_issue_parses_and_returns(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): (200, {"key": "CCE-1", "fields": {}})})
        assert self._client().get_issue("CCE-1") == {"key": "CCE-1", "fields": {}}

    def test_get_transitions_returns_list(self, fake_jira):
        body = {
            "transitions": [{"id": "41", "to": {"statusCategory": {"key": "done"}}}]
        }
        fake_jira({("GET", "issue/CCE-1/transitions"): (200, body)})
        assert self._client().get_transitions("CCE-1") == body["transitions"]

    def test_transition_posts_correct_body(self, fake_jira):
        fake = fake_jira({("POST", "issue/CCE-1/transitions"): (204, None)})
        self._client().transition("CCE-1", "41")
        method, url, body, _auth = fake.calls[-1]
        assert (method, body) == ("POST", {"transition": {"id": "41"}})
        assert "/rest/api/3/" in url

    def test_add_comment_posts_string_body_via_v2(self, fake_jira):
        fake = fake_jira({("POST", "issue/CCE-1/comment"): (201, {"id": "9"})})
        self._client().add_comment("CCE-1", "hello world")
        method, url, body, _auth = fake.calls[-1]
        assert (method, body) == ("POST", {"body": "hello world"})
        assert "/rest/api/2/" in url  # v2 accepts a plain string body; v3 needs ADF

    def test_auth_header_is_basic_base64(self, fake_jira):
        fake = fake_jira({("GET", "issue/CCE-1"): (200, {})})
        self._client().get_issue("CCE-1")
        expected = "Basic " + base64.b64encode(b"me@x.com:tok").decode()
        assert fake.calls[-1][3] == expected

    def test_401_raises_auth_error(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(401)})
        with pytest.raises(JiraAuthError):
            self._client().get_issue("CCE-1")

    def test_403_raises_auth_error(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(403)})
        with pytest.raises(JiraAuthError):
            self._client().get_issue("CCE-1")

    def test_404_raises_not_found(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(404)})
        with pytest.raises(JiraNotFoundError):
            self._client().get_issue("CCE-1")

    def test_500_retries_once_then_raises_server_error(self, fake_jira):
        fake = fake_jira({("GET", "issue/CCE-1"): _http_error(500)})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")
        assert len(fake.calls) == 2  # initial + one retry
        # The retry MUST back off — a deleted sleep or _RETRY_BACKOFF_S=0 is a defect.
        assert fake.sleeps == [2]

    def test_timeout_retries_once_then_raises_server_error(self, fake_jira):
        fake = fake_jira({("GET", "issue/CCE-1"): urllib.error.URLError("timed out")})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")
        assert len(fake.calls) == 2

    def test_read_timeout_TimeoutError_retries_then_server_error(self, fake_jira):
        # A Jira READ-phase timeout surfaces as a bare TimeoutError, NOT a URLError —
        # it must still retry once then raise JiraServerError (not crash uncaught).
        fake = fake_jira({("GET", "issue/CCE-1"): TimeoutError("read timed out")})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")
        assert len(fake.calls) == 2
        assert fake.sleeps == [2]  # the network-error branch backs off too

    def test_socket_timeout_retries_then_server_error(self, fake_jira):
        # socket.timeout is distinct from TimeoutError on Python <3.10 — cover both.
        fake = fake_jira({("GET", "issue/CCE-1"): socket.timeout("read timed out")})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")
        assert len(fake.calls) == 2

    def test_non_json_2xx_body_raises_server_error(self, fake_jira):
        # A 2xx with a non-JSON body (CDN HTML during a partial incident) must surface
        # as JiraServerError (caught per-key), not an uncaught JSONDecodeError.
        fake_jira({("GET", "issue/CCE-1"): (200, b"<html>edge error</html>")})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")

    def test_500_then_200_recovers_on_retry(self, fake_jira):
        # The POINT of the retry is recovery, not just a second doomed attempt. A
        # transient 5xx followed by a 200 must return the parsed body — proving the
        # success-on-retry branch, which fixed single-value routes can't reach.
        fake = fake_jira(
            {("GET", "issue/CCE-1"): [_http_error(500), (200, {"key": "CCE-1"})]}
        )
        assert self._client().get_issue("CCE-1") == {"key": "CCE-1"}
        assert len(fake.calls) == 2  # failed once, recovered on the retry
        assert fake.sleeps == [2]

    def test_timeout_then_200_recovers_on_retry(self, fake_jira):
        # Same recovery, via the network-error branch (bare TimeoutError → retry → 200).
        fake = fake_jira(
            {("GET", "issue/CCE-1"): [TimeoutError("blip"), (200, {"key": "CCE-1"})]}
        )
        assert self._client().get_issue("CCE-1") == {"key": "CCE-1"}
        assert len(fake.calls) == 2
        assert fake.sleeps == [2]

    def test_400_raises_server_error_without_retry(self, fake_jira):
        # A non-handled 4xx (e.g. 400/409) is permanent — map to JiraServerError and
        # NEVER retry. Locks the `5xx-only` retry guard against a widening mutation.
        fake = fake_jira({("GET", "issue/CCE-1"): _http_error(400)})
        with pytest.raises(JiraServerError):
            self._client().get_issue("CCE-1")
        assert len(fake.calls) == 1  # no retry on a client error
        assert fake.sleeps == []  # and therefore no backoff

    def test_auth_error_message_excludes_token(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(401)})
        with pytest.raises(JiraAuthError) as ei:
            self._client().get_issue("CCE-1")
        assert "tok" not in str(ei.value)  # token must never surface
        assert "me@x.com" in str(ei.value)  # email IS safe to log (a vars. value)


PR_CTX = dict(
    pr_number=116,
    pr_title="feat(CCE-1): wire it",
    merge_sha="deadbeef",
    merged_at="2026-06-08T00:00:00Z",
    pr_url="https://github.com/theoju/engineering-docs-agent/pull/116",
)


def _issue(category, name="Backlog"):
    return (
        200,
        {"fields": {"status": {"name": name, "statusCategory": {"key": category}}}},
    )


def _transitions(*cats):
    return (
        200,
        {
            "transitions": [
                {"id": str(40 + i), "to": {"statusCategory": {"key": c}}}
                for i, c in enumerate(cats)
            ]
        },
    )


class TestProcessKey:
    def _client(self):
        return JiraClient("https://designitright.atlassian.net", "me@x.com", "tok")

    def test_already_done_no_posts(self, fake_jira):
        fake = fake_jira({("GET", "issue/CCE-1"): _issue("done", "Done")})
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=False)
        assert r["status"] == "already_done"
        assert [c[0] for c in fake.calls] == [
            "GET"
        ]  # no transitions/comment/transition

    def test_happy_path_comment_then_transition(self, fake_jira):
        fake = fake_jira(
            {
                ("GET", "issue/CCE-1"): _issue("indeterminate", "In Progress"),
                ("GET", "issue/CCE-1/transitions"): _transitions(
                    "indeterminate", "done"
                ),
                ("POST", "issue/CCE-1/comment"): (201, {"id": "9"}),
                ("POST", "issue/CCE-1/transitions"): (204, None),
            }
        )
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=False)
        assert r["status"] == "transitioned"
        posts = [c for c in fake.calls if c[0] == "POST"]
        # comment BEFORE transition (durability ordering)
        assert posts[0][1].endswith("comment")
        assert posts[1][1].endswith("transitions")
        assert posts[1][2] == {"transition": {"id": "41"}}

    def test_no_done_transition_no_comment(self, fake_jira):
        fake = fake_jira(
            {
                ("GET", "issue/CCE-1"): _issue("new", "Backlog"),
                ("GET", "issue/CCE-1/transitions"): _transitions(
                    "new", "indeterminate"
                ),
            }
        )
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=False)
        assert r["status"] == "no_done_transition"
        assert [c[0] for c in fake.calls] == ["GET", "GET"]  # no POSTs

    def test_transition_fails_after_comment(self, fake_jira):
        fake_jira(
            {
                ("GET", "issue/CCE-1"): _issue("indeterminate"),
                ("GET", "issue/CCE-1/transitions"): _transitions("done"),
                ("POST", "issue/CCE-1/comment"): (201, {}),
                ("POST", "issue/CCE-1/transitions"): _http_error(500),
            }
        )
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=False)
        assert r["status"] == "failed"
        assert "comment posted but transition failed" in r["detail"]

    def test_read_failure_marks_failed(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(404)})
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=False)
        assert r["status"] == "failed"

    def test_dry_run_no_posts_prints_comment(self, fake_jira, capsys):
        fake = fake_jira(
            {
                ("GET", "issue/CCE-1"): _issue("indeterminate"),
                ("GET", "issue/CCE-1/transitions"): _transitions("done"),
            }
        )
        r = mod.process_key("CCE-1", self._client(), PR_CTX, dry_run=True)
        assert r["status"] == "transitioned"
        assert r["detail"] == "dry-run"
        assert [c[0] for c in fake.calls] == ["GET", "GET"]  # reads only, no writes
        assert "deadbeef" in capsys.readouterr().out  # would-be comment surfaced


def _argv(title):
    return [
        "--pr-number",
        "116",
        "--pr-title",
        title,
        "--merge-sha",
        "deadbeef",
        "--merged-at",
        "2026-06-08T00:00:00Z",
        "--pr-url",
        "https://github.com/theoju/engineering-docs-agent/pull/116",
    ]


def _ok_routes(key):
    return {
        ("GET", f"issue/{key}"): _issue("indeterminate"),
        ("GET", f"issue/{key}/transitions"): _transitions("done"),
        ("POST", f"issue/{key}/comment"): (201, {}),
        ("POST", f"issue/{key}/transitions"): (204, None),
    }


class TestMain:
    @pytest.fixture(autouse=True)
    def _creds(self, monkeypatch):
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        monkeypatch.setenv("JIRA_EMAIL", "me@x.com")

    def test_no_keys_exits_0(self):
        assert mod.main(_argv("chore: bump deps, no key here")) == 0

    def test_no_keys_exits_0_even_without_token(self, monkeypatch):
        # Ordering invariant: a keyless title is a clean 0 BEFORE the token check —
        # a no-op PR must never fail CI just because the Jira secret is unset.
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        assert mod.main(_argv("chore: bump deps, no key here")) == 0

    def test_single_happy_exits_0(self, fake_jira):
        fake_jira(_ok_routes("CCE-1"))
        assert mod.main(_argv("feat(CCE-1): wire it")) == 0

    def test_single_failed_exits_1(self, fake_jira):
        fake_jira({("GET", "issue/CCE-1"): _http_error(404)})
        assert mod.main(_argv("feat(CCE-1): wire it")) == 1

    def test_multi_key_all_ok_exits_0(self, fake_jira):
        fake_jira({**_ok_routes("CCE-1"), **_ok_routes("CCE-2")})
        assert mod.main(_argv("feat(CCE-1): land (also closes CCE-2)")) == 0

    def test_multi_key_partial_failure_exits_1(self, fake_jira):
        routes = {**_ok_routes("CCE-1"), ("GET", "issue/CCE-2"): _http_error(404)}
        fake_jira(routes)
        assert mod.main(_argv("feat(CCE-1): land (also closes CCE-2)")) == 1

    def test_no_done_transition_exits_1(self, fake_jira):
        fake_jira(
            {
                ("GET", "issue/CCE-1"): _issue("new", "Backlog"),
                ("GET", "issue/CCE-1/transitions"): _transitions("new"),
            }
        )
        assert mod.main(_argv("feat(CCE-1): wire it")) == 1

    def test_missing_token_exits_2(self, monkeypatch):
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        assert mod.main(_argv("feat(CCE-1): wire it")) == 2

    def test_timeout_on_first_key_does_not_block_second(self, fake_jira):
        # Per-key isolation: a read timeout on CCE-1 must mark it failed but still
        # process CCE-2 to completion (exit 1 overall).
        routes = {
            ("GET", "issue/CCE-1"): TimeoutError("read timed out"),
            **_ok_routes("CCE-2"),
        }
        fake = fake_jira(routes)
        assert mod.main(_argv("feat(CCE-1): land (also closes CCE-2)")) == 1
        # CCE-2 was processed through to its transition POST despite CCE-1 crashing-class error
        assert any(
            c[0] == "POST" and c[1].endswith("issue/CCE-2/transitions")
            for c in fake.calls
        )
