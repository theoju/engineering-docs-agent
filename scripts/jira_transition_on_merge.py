"""Auto-transition Jira CCE issues to Done when their implementing PR merges (CCE-103).

Repo-local hygiene helper. The GitHub workflow `.github/workflows/jira-transition.yml`
runs `gh pr view` once and passes flat CLI strings; this helper has zero GitHub API
surface (so it is pytest-able without faking `gh`) and a thin stdlib-only Jira client.

CLI contract:
  python3 scripts/jira_transition_on_merge.py \
    --pr-number 123 --pr-title "feat(CCE-NN): foo" --merge-sha abc123 \
    --merged-at 2026-06-04T20:00:00Z --pr-url https://github.com/.../pull/123 [--dry-run]

Exit codes:
  0  every key transitioned/already-done, or the title carries no CCE key
  1  any key failed / had no Done transition (the PR is already merged, so a
     loud non-zero failure forces operator attention without blocking delivery)
  2  startup error (missing JIRA_API_TOKEN env)

Stdlib-first per CLAUDE.md: urllib.request covers the four Jira endpoints needed.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

# CCE keys are uppercase and word-bounded; body/branch mentions are out of scope —
# the PR title is the single source of truth (see design doc, "Scope").
_KEY_RE = re.compile(r"\bCCE-\d+\b")


def extract_keys(title: str) -> list[str]:
    """Return deduped CCE-\\d+ matches in title-occurrence order. [] if none."""
    seen: dict[str, None] = {}
    for key in _KEY_RE.findall(title):
        seen.setdefault(key, None)
    return list(seen)


def format_closure_comment(
    pr_number: int,
    pr_title: str,
    merge_sha: str,
    merged_at: str,
    pr_url: str,
) -> str:
    """Markdown closure comment: a PR link, the merge SHA in a code fence, and the
    merge timestamp. The full title is embedded verbatim (never truncated)."""
    return (
        f"Closed by [PR #{pr_number}]({pr_url}): {pr_title}\n\n"
        f"Merged in `{merge_sha}` at {merged_at}."
    )


def find_done_transition_id(transitions: list[dict]) -> str | None:
    """Return the id of the first transition whose target is in the `done`
    statusCategory, else None. Matching on category (not name/id) survives a Jira
    workflow rename or transition-id renumber."""
    for t in transitions:
        if t.get("to", {}).get("statusCategory", {}).get("key") == "done":
            return t.get("id")
    return None


# --- Jira HTTP client (thin, stdlib-only) ----------------------------------
class JiraError(Exception):
    """Base for Jira client failures."""


class JiraAuthError(JiraError):
    """401/403 — credentials rejected."""


class JiraNotFoundError(JiraError):
    """404 — issue does not exist."""


class JiraServerError(JiraError):
    """5xx or network failure, after one retry."""


_TIMEOUT = 30
_RETRY_BACKOFF_S = 2  # one retry on 5xx/timeout absorbs a network blip; bounded


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._email = email
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._auth = f"Basic {token}"

    def _request(
        self, method: str, path: str, body: dict | None = None, api: str = "3"
    ) -> dict:
        url = f"{self.base_url}/rest/api/{api}/{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": self._auth,
            "Accept": "application/json",
            "User-Agent": "jira-transition-on-merge/1.0 (engineering-docs-agent)",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)

        attempts = 0
        while True:
            attempts += 1
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                # 4xx is permanent — never retry (it just bills the API for the same
                # answer). 5xx gets exactly one retry.
                if e.code in (401, 403):
                    # email is a vars. value (safe to surface); the token is NEVER logged.
                    raise JiraAuthError(
                        f"Jira auth failed ({e.code}) for {self._email}"
                    ) from None
                if e.code == 404:
                    raise JiraNotFoundError(f"{path} not found (404)") from None
                if 500 <= e.code < 600 and attempts == 1:
                    time.sleep(_RETRY_BACKOFF_S)
                    continue
                raise JiraServerError(
                    f"Jira server error ({e.code}) on {method} {path}"
                ) from None
            except json.JSONDecodeError:
                # A 2xx with a non-JSON body (e.g. a CDN HTML error page during a
                # partial incident) — surface as a per-key failure, never an uncaught
                # crash that would break multi-key isolation.
                raise JiraServerError(f"non-JSON response on {method} {path}") from None
            except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
                # A READ-phase timeout raises a bare TimeoutError / socket.timeout, which
                # is NOT a urllib.error.URLError — both must route through the same
                # one-retry-then-fail path (else they escape uncaught). socket.timeout is
                # an alias for TimeoutError on 3.10+; listed explicitly for <3.10 safety.
                if attempts == 1:
                    time.sleep(_RETRY_BACKOFF_S)
                    continue
                # reason/message only — never the Request (its headers carry the token).
                raise JiraServerError(
                    f"Jira network error on {method} {path}: {getattr(e, 'reason', e)}"
                ) from None

    def get_issue(self, key: str) -> dict:
        return self._request("GET", f"issue/{key}")

    def get_transitions(self, key: str) -> list[dict]:
        return self._request("GET", f"issue/{key}/transitions").get("transitions", [])

    def transition(self, key: str, transition_id: str) -> None:
        self._request(
            "POST",
            f"issue/{key}/transitions",
            body={"transition": {"id": transition_id}},
        )

    def add_comment(self, key: str, body_markdown: str) -> None:
        # v2 comment endpoint accepts a plain string body; v3 requires ADF (structured
        # JSON). The design's `body_markdown: str` maps cleanly to v2 — reads and the
        # transition POST stay on v3.
        self._request(
            "POST", f"issue/{key}/comment", body={"body": body_markdown}, api="2"
        )


# --- per-key flow ----------------------------------------------------------
def process_key(key: str, client: JiraClient, pr_context: dict, dry_run: bool) -> dict:
    """Run the full gate for one issue key. Returns a KeyResult dict:
    {"key", "status": transitioned|already_done|no_done_transition|failed, "detail"}.

    Reads (get_issue/get_transitions) always run — even in dry-run — so transition
    discovery is exercised. Writes (comment, then transition) are skipped in dry-run.
    Comment is posted BEFORE the transition: if the transition then fails, a "Closed
    by PR" comment on a still-open ticket is loud enough for the next triage to catch.
    """
    try:
        issue = client.get_issue(key)
        category = (
            issue.get("fields", {})
            .get("status", {})
            .get("statusCategory", {})
            .get("key")
        )
        if category == "done":
            return {"key": key, "status": "already_done", "detail": "already in Done"}

        done_id = find_done_transition_id(client.get_transitions(key))
        if done_id is None:
            current = issue.get("fields", {}).get("status", {}).get("name", "?")
            return {
                "key": key,
                "status": "no_done_transition",
                "detail": f"no Done transition from state '{current}'",
            }

        comment = format_closure_comment(**pr_context)
        if dry_run:
            print(
                f"[dry-run] {key}: would comment + transition to Done (id {done_id}):"
            )
            print(comment)
            return {"key": key, "status": "transitioned", "detail": "dry-run"}

        client.add_comment(key, comment)
    except JiraError as e:
        return {"key": key, "status": "failed", "detail": str(e)}

    # The comment is now posted; the transition is the durability-sensitive step.
    try:
        client.transition(key, done_id)
    except JiraError as e:
        return {
            "key": key,
            "status": "failed",
            "detail": f"comment posted but transition failed: {e}",
        }
    return {"key": key, "status": "transitioned", "detail": "transitioned to Done"}


# --- aggregation + exit ----------------------------------------------------
_DEFAULT_BASE_URL = "https://designitright.atlassian.net"
_OK_STATUSES = {"transitioned", "already_done"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Transition CCE Jira issues to Done when their PR merges (CCE-103)."
    )
    p.add_argument("--pr-number", required=True)
    p.add_argument("--pr-title", required=True, help="single source of truth for keys")
    p.add_argument("--merge-sha", required=True)
    p.add_argument("--merged-at", required=True)
    p.add_argument("--pr-url", required=True)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="exercise read endpoints but perform no comment/transition writes",
    )
    args = p.parse_args(argv)

    keys = extract_keys(args.pr_title)
    if not keys:
        print(f"No CCE keys in title {args.pr_title!r} — nothing to transition.")
        return 0

    token = os.environ.get("JIRA_API_TOKEN")
    if not token:
        print("ERROR: JIRA_API_TOKEN env is required.", file=sys.stderr)
        return 2
    email = os.environ.get("JIRA_EMAIL", "")
    base_url = os.environ.get("JIRA_BASE_URL", _DEFAULT_BASE_URL)

    client = JiraClient(base_url, email, token)
    pr_context = {
        "pr_number": args.pr_number,
        "pr_title": args.pr_title,
        "merge_sha": args.merge_sha,
        "merged_at": args.merged_at,
        "pr_url": args.pr_url,
    }

    results = [process_key(k, client, pr_context, args.dry_run) for k in keys]
    print(f"jira-transition: PR #{args.pr_number} → {len(keys)} key(s)")
    for r in results:
        print(f"  {r['key']}: {r['status']} — {r['detail']}")

    failed = [r for r in results if r["status"] not in _OK_STATUSES]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
