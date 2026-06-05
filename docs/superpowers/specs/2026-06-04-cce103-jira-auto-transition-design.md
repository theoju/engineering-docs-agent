# CCE-103 — auto-transition Jira to Done on PR merge

**Status:** approved 2026-06-04 (brainstorm + 3 locked decisions); implementation plan next.
**Jira:** CCE-103.
**Origin:** retrospective on the 2026-06-04 backlog-triage session. Five already-shipped CCE tickets (CCE-79, CCE-92, CCE-96, CCE-102, CCE-36) surfaced in the open queue because each PR merge required a manual Jira transition that nobody performed. The compounding hygiene cost — 10–30 minutes of `git log` / `gh pr view` rediscovery per ticket per triage — justifies a one-off automation that removes the manual step entirely.

---

## Why this exists

The CCE project has a strict convention: every branch and PR title carries the issue key (`feat/CCE-NN-slug`, `feat(CCE-NN): summary`). The Atlassian GitHub integration auto-links PRs to issues for visibility, but **never transitions the issue** — that step is left to the operator. Operators routinely forget. The result:

| Ticket  | Implementation PR             | PR merged    | Jira closed                                |
| ------- | ----------------------------- | ------------ | ------------------------------------------ |
| CCE-79  | #128                          | 2026-06-04\* | 2026-06-04 (during triage)                 |
| CCE-92  | superpowers#1688 + repo-local | 2026-06-04\* | 2026-06-04 (during triage)                 |
| CCE-96  | via CCE-82 PR                 | 2026-06-02\* | 2026-06-04 (during triage)                 |
| CCE-102 | server-side fix               | 2026-06-04   | 2026-06-04 (during triage)                 |
| CCE-36  | #48                           | 2026-05-28   | 2026-06-04 (during triage — **7-day gap**) |

\* dates approximate; the precise merge timestamps are in `gh pr view`.

The cost compounds: every nightly docs-agent cron run, every backlog scan, every "what's left to do this week" question gets answered against a polluted queue. Filing this ticket as CCE-103 IS the 6th already-shipped-risk if the workflow it specifies doesn't ship to catch itself.

## Scope

**In scope:** A repo-local hygiene workflow in `engineering-docs-agent` that closes its own Jira tickets when their implementing PRs merge to `main`.

**Out of scope (this iteration):**

- **Plugin generalization.** Other hosts that adopt the plugin do NOT get the workflow automatically. If demand materializes, file a follow-up to promote `scripts/jira_transition_on_merge.py` to the plugin's scaffolded surface (similar to how `docs-agent-nightly.yml` ships as a template). The current `JIRA_BASE_URL` is hardcoded; plugin promotion would read it from `.engineering-docs-agent/config.yml::sources.jira.base_url`.
- **PR body / commit message / branch name parsing.** The PR title is the single source of truth for "this PR closes ticket X". Body mentions are documentation and must not trigger transitions (the CCE-103 description itself mentions five other tickets in its evidence section — none should transition).
- **Workflow-state policy beyond Done.** The script always targets the `Done` workflow transition and does not handle "In Review" intermediates. If the Jira project workflow lacks a Done transition from the issue's current state, the script exits non-zero.
- **Retries beyond one 5xx absorption.** Network blips are absorbed; persistent failures fail loud.

## The hard constraint: stdlib-first runtime

Per `CLAUDE.md`: "Python: stdlib-first. New runtime deps require explicit justification in the spec." The Jira REST surface needed here is four endpoints (`GET /issue/{key}`, `GET /issue/{key}/transitions`, `POST /issue/{key}/transitions`, `POST /issue/{key}/comment`); `urllib.request` covers them. No `requests`, no `python-jira`.

## Locked decisions (from brainstorming)

| #   | Decision                                                                                          | Rationale                                                                                                                                                                                                 |
| --- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Repo-local hygiene workflow, not plugin capability                                                | Fastest to ship; no opt-in burden on other hosts; plugin promotion deferred until demand exists                                                                                                           |
| 2   | Thin GH Action workflow + `scripts/jira_transition_on_merge.py` Python helper + pytest unit tests | Matches `docs-agent-nightly.yml` + `scripts/orchestrator_runner.py` pattern; testable; stdlib-first                                                                                                       |
| 3   | Fail loud (workflow exits non-zero on Jira API failure)                                           | Whole point of the ticket is to NOT silently drop transitions; GH Actions notification + checks-tab red mark forces operator attention. The PR is already merged, so noisy failure cannot block delivery. |

## Architecture

Three artifacts, all repo-local:

```
.github/workflows/jira-transition.yml      # ~25 lines, thin shell
scripts/jira_transition_on_merge.py        # ~150 lines, stdlib-only, pure logic
tests/test_jira_transition_on_merge.py     # pytest, monkeypatched HTTP
```

**Trigger surface (workflow):**

- `pull_request: { types: [closed] }` — fires on every PR close; workflow conditional `if: github.event.pull_request.merged == true` gates so closed-without-merge is a clean no-op (job skipped, no helper invocation).
- `workflow_dispatch: { inputs: { pr_number: required, dry_run: bool default=true } }` — manual dispatch for development. Dry-run still calls the real Jira read endpoints (so transition discovery is exercised) but suppresses the comment + transition POSTs and prints what would have happened.

**Auth wiring (workflow → helper env):**

- `JIRA_API_TOKEN` ← `secrets.JIRA_API_TOKEN` (already configured 2026-05-29)
- `JIRA_EMAIL` ← `vars.JIRA_EMAIL` (already configured 2026-05-29; public identifier, not a credential)
- `JIRA_BASE_URL` ← hardcoded `https://designitright.atlassian.net` in the workflow
- `GITHUB_TOKEN` ← workflow default; used by `gh pr view` server-side fetch (so the helper does NOT trust `github.event.pull_request.title` from the trigger payload directly)

**Concurrency:**

```yaml
concurrency:
  group: jira-transition-${{ github.event.pull_request.number }}
  cancel-in-progress: false
```

Two events on the same PR (close → reopen → close) queue instead of race-condition the Jira API. Idempotency in the helper (`already_done` short-circuit) handles the duplicate run cleanly.

## Components

**CLI contract** (workflow → helper):

```
python3 scripts/jira_transition_on_merge.py \
  --pr-number 123 \
  --pr-title "feat(CCE-NN): foo" \
  --merge-sha abc123def \
  --merged-at 2026-06-04T20:00:00Z \
  --pr-url https://github.com/theoju/engineering-docs-agent/pull/123 \
  [--dry-run]
```

The workflow runs `gh pr view <N> --json title,number,mergeCommit,mergedAt,url` once and passes flat strings — the helper has zero GitHub API surface, which makes it pytest-able without faking `gh`.

**Internal module structure** (single file, named sections):

```python
# --- key extraction (pure) ---
def extract_keys(title: str) -> list[str]:
    """Return deduped CCE-\\d+ matches in title-occurrence order. [] if none."""

# --- Jira HTTP client (thin) ---
class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str): ...
    def get_issue(self, key: str) -> dict             # GET /rest/api/3/issue/{key}
    def get_transitions(self, key: str) -> list[dict] # GET .../transitions
    def transition(self, key: str, transition_id: str) -> None  # POST .../transitions
    def add_comment(self, key: str, body_markdown: str) -> None # POST .../comment

# --- comment formatting (pure) ---
def format_closure_comment(pr_number, pr_title, merge_sha, merged_at, pr_url) -> str

# --- transition selection (pure) ---
def find_done_transition_id(transitions: list[dict]) -> str | None
    # Match transition where to.statusCategory.key == "done"

# --- per-key flow ---
def process_key(key: str, client: JiraClient, pr_context: dict, dry_run: bool) -> dict

# --- aggregation + exit ---
def main(argv: list[str] | None = None) -> int
```

**`KeyResult` shape** (no new contracts.py entry — single dict literal):

```python
{"key": "CCE-103", "status": "transitioned|already_done|no_done_transition|failed", "detail": "..."}
```

**Why not split into multiple files?** The helper is ~150 lines. The project's largest helper, `orchestrator_runner.py`, is ~600+ lines for comparison. Splitting now would be premature, and a single-file `scripts/*.py` matches the rest of the directory.

## Data flow

Happy path, single-key PR:

```
1. Operator merges PR #123 with title "feat(CCE-103): wire jira auto-transition" on main.
   ↓
2. GitHub fires `pull_request: closed` event with `merged: true`.
   ↓
3. .github/workflows/jira-transition.yml triggers.
   - if pull_request.merged != true → skip job (exit 0, helper never runs)
   - else → proceed
   ↓
4. Workflow runs `gh pr view 123 --json title,number,mergeCommit,mergedAt,url`,
   sets up Python 3.12, calls helper with flat CLI args.
   ↓
5. Helper main():
   a. extract_keys("feat(CCE-103): wire jira auto-transition") → ["CCE-103"]
   b. JiraClient.__init__(base_url, JIRA_EMAIL, JIRA_API_TOKEN)
   c. for key in keys: process_key(key, client, pr_context, dry_run=False)
   ↓
6. process_key("CCE-103", ...):
   a. issue = client.get_issue("CCE-103")
      - if status.statusCategory.key == "done" → return {status: "already_done"}, no POSTs
   b. transitions = client.get_transitions("CCE-103")
   c. done_id = find_done_transition_id(transitions)
      - if None → return {status: "no_done_transition", detail: "..."}, no POSTs
   d. client.add_comment("CCE-103", format_closure_comment(...))  ← comment BEFORE transition
   e. client.transition("CCE-103", done_id)
   f. return {status: "transitioned"}
   ↓
7. main() prints a one-line-per-key summary table; exit code:
   - 0 if every result ∈ {transitioned, already_done}, or no keys in title
   - 1 if ANY result ∈ {failed, no_done_transition}
   ↓
8. Workflow exit code surfaces in GH Actions UI:
   - Non-zero → red ✗ on PR's checks tab + email notification
   - Zero → green ✓ logged in Actions UI
```

**Multi-key PR** (e.g., `feat(CCE-89): D1+D2 land (also closes CCE-77)`):

- Step 5a returns `["CCE-89", "CCE-77"]` (regex dedup preserves first occurrence)
- Step 6 runs the whole per-key flow independently for each — failures are per-key, not all-or-nothing
- Step 7 exits non-zero if ANY key failed

**Dry-run mode** (`workflow_dispatch` with `dry_run: true`):

- Steps 6d and 6e are logged but not executed
- Steps 6a–c still call the real Jira read endpoints (transition discovery is exercised)
- The would-be comment text is printed to stdout
- All results report status as if the writes had happened, with `detail: "dry-run"` appended

**"Comment before transition" durability ordering:** if the transition POST fails after the comment posts, you get a "Closed by PR #N" comment on a still-Backlog ticket — visually inconsistent enough that the next triage will notice. The reverse ordering would silently transition with no audit trail if the comment POST failed.

## Error handling

The full exit-code matrix (each row is a pytest test case):

| Situation                                | Detection point                                          | Action                                                     | Exit        | Operator artifact                                                     |
| ---------------------------------------- | -------------------------------------------------------- | ---------------------------------------------------------- | ----------- | --------------------------------------------------------------------- |
| `merged: false` on close event           | Workflow conditional                                     | Skip job before Python runs                                | 0           | No Actions run for this job                                           |
| No `CCE-\d+` in title                    | `extract_keys() is []`                                   | Log "no CCE keys", return                                  | 0           | Green ✓, single-line log                                              |
| Issue already `statusCategory: done`     | `get_issue().fields.status.statusCategory.key == "done"` | Skip comment + transition                                  | 0           | Green ✓, no duplicate Jira comment                                    |
| No Done transition from current state    | `find_done_transition_id() is None`                      | Log key + current Jira state name                          | 1           | Red ✗, stderr surfaces state name                                     |
| Auth failure (401/403)                   | `JiraClient` HTTP layer                                  | Raise `JiraAuthError`, mark `failed`                       | 1           | Red ✗, stderr includes `JIRA_EMAIL` (safe — public var) NOT the token |
| Issue not found (404)                    | `get_issue` returns 404                                  | Mark `failed: "CCE-NN not found"`                          | 1           | Red ✗                                                                 |
| Network timeout / 5xx                    | `urllib.error.URLError`                                  | Mark `failed` after one retry                              | 1           | Red ✗, retry via Actions UI re-run                                    |
| Comment posted, transition fails         | Between 6d and 6e                                        | Mark `failed: "comment posted but transition failed: ..."` | 1           | Red ✗ + Jira comment on still-Backlog ticket → next triage catches    |
| Multi-key partial failure (1 of N fails) | aggregator                                               | Process all keys, exit 1                                   | 1           | Red ✗, per-key results in log                                         |
| Duplicate events on same PR              | Workflow `concurrency:` group                            | Queue rather than parallel                                 | (per-event) | `already_done` short-circuits the second run                          |
| Missing `JIRA_API_TOKEN` env             | `main()` startup                                         | Print error, exit 2                                        | 2           | Red ✗ before any API call                                             |

**Credential safety:**

- `JIRA_API_TOKEN` is never logged. Helper takes it via env var, passes to `JiraClient.__init__`, never echoes.
- Caught `urllib.error.URLError` is reformatted to strip the `Authorization:` header before stderr-printing (defensive — `urllib` tends to scrub but not guaranteed across Python versions).
- `JIRA_EMAIL` IS logged on auth failure for debuggability (it's a `vars.` value, not a secret).

**HTTP layer specifics:**

- `urllib.request.Request` + `urllib.request.urlopen` with `timeout=30`.
- Auth: HTTP Basic with `{JIRA_EMAIL}:{JIRA_API_TOKEN}` base64-encoded.
- `User-Agent: jira-transition-on-merge/1.0 (engineering-docs-agent)` so Atlassian rate-limit logs identify the caller.
- No retries on 4xx (permanent state — retry just bills the API for the same answer).
- One retry on 5xx / timeout with 2-second backoff (network blip absorption). Bounded so workflow run-time stays predictable.

## Testing

**File:** `tests/test_jira_transition_on_merge.py` — pytest, matches existing `tests/test_*.py` naming.

**Fixture strategy** (stdlib-first, no `responses` / `requests-mock` dep):

- Single `monkeypatch_urlopen` fixture replaces `urllib.request.urlopen` with a `FakeUrlopen` callable.
- `FakeUrlopen` is constructed with a `dict[tuple[str, str], Response]` keyed by `(method, url_suffix)` — each test declares only the calls it expects.
- `Response` is `(status_code, json_body)` — the fake returns a context-manager object whose `.read()` yields JSON-encoded bytes.
- Unexpected calls raise `AssertionError("unmocked Jira call: METHOD URL")` so test pollution can't pass silently. A test that accidentally widens the helper's API surface will fail loudly.

**Test classes** (one per testability seam):

| Class                      | Coverage                                                                                                                                                                                                                                                                                                                                                    |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TestExtractKeys`          | empty title; single key; multiple keys; duplicate keys collapse to dedup; case-insensitive match → reject (CCE keys are uppercase); embedded-in-word (`xCCE-1y`) → reject (`\b` boundaries); commit-style `feat(CCE-89 D2): foo` → extracts `CCE-89`                                                                                                        |
| `TestFormatClosureComment` | all fields populated → markdown link present, SHA in code fence, timestamp in ISO-8601; long PR title → not truncated; markdown-char-laden title (`*`, `_`, `` ` ``) → safely embedded                                                                                                                                                                      |
| `TestFindDoneTransitionId` | one Done transition → returns its id; multiple Done-category transitions → returns first; no Done-category → returns `None`; empty list → returns `None`                                                                                                                                                                                                    |
| `TestJiraClient`           | `get_issue`/`get_transitions` parse + return; `transition`/`add_comment` POST correct body; 401 raises `JiraAuthError`; 404 raises `JiraNotFoundError`; 500 retries once then raises `JiraServerError`; timeout raises `JiraServerError`; auth header is `Basic <base64>`                                                                                   |
| `TestProcessKey`           | already-done → `{status: already_done}`, no POSTs; happy path → comment + transition, `{status: transitioned}`; no Done transition → `{status: no_done_transition}`, no comment; transition fails after comment → `{status: failed, detail: comment posted but transition failed: ...}`; dry_run=True → no POSTs, `{status: transitioned, detail: dry-run}` |
| `TestMain`                 | no keys → exit 0; single happy → exit 0; single failed → exit 1; multi-key all-OK → exit 0; multi-key partial → exit 1; missing `JIRA_API_TOKEN` env → exit 2                                                                                                                                                                                               |

**TDD order:** pure functions first (`extract_keys`, `format_closure_comment`, `find_done_transition_id`), then `JiraClient` HTTP cases, then `process_key` integration, then `main`. Each class red→green before the next.

**Manual integration test** (one-time, before turning on dry-run-off mode):

1. `workflow_dispatch` against `pr_number: 48` (CCE-36 — already in Done) with `dry_run: true` → expect `{key: CCE-36, status: already_done}`, exit 0. Validates the read path with zero side-effect risk.
2. `workflow_dispatch` against a real merged PR pointing to a still-Backlog ticket with `dry_run: true` → expect `{status: transitioned, detail: dry-run}`. Confirms transition discovery works against live workflow.
3. Only after both pass does the operator merge the `pull_request: closed` automatic trigger live.

**No workflow-level pytest integration tests.** Real `gh` and Jira calls require fixtures the project doesn't have (sandbox Jira instance, throwaway PRs). The matrix above plus the two manual dispatches give the same confidence.

## Acceptance criteria

- [ ] New CCE PR merges to `main` → matching Jira issue transitions to **Done** within 60s of merge, with a closure comment linking the merge commit + PR.
- [ ] PRs without `CCE-NN` in the title are no-ops (no errors, no spurious comments, green ✓).
- [ ] PRs with multiple `CCE-NN` keys in title transition all of them; per-key failures don't block other keys.
- [ ] Idempotent — running the workflow twice against the same merged PR produces zero duplicate comments and zero duplicate transitions.
- [ ] Dry-run mode (`workflow_dispatch` with `dry_run: true`) exercises read endpoints but performs no writes.
- [ ] On Jira API failure: workflow exits non-zero, GH Actions surfaces the failure to operator (email + red ✗ on checks tab).
- [ ] `pytest tests/test_jira_transition_on_merge.py` passes; all 6 test classes covered.
- [ ] CLAUDE.md "Plugin conventions" section documents the workflow's existence so future operators know it's there.
- [ ] **Self-validation:** when the implementing PR for CCE-103 itself merges, the workflow transitions CCE-103 to Done — no manual close needed.

## Notes / future work

- **Plugin promotion path.** If this proves useful enough that other host repos want it, the script is straightforwardly plugin-portable: replace the hardcoded `JIRA_BASE_URL` with a config read from `.engineering-docs-agent/config.yml::sources.jira.base_url` and `sources.jira.project_keys[0]` for the regex prefix; ship the workflow as a template via `templates/workflow-jira-transition.yml`; add a scaffold step to `engineering-docs-agent-setup`. File as a separate ticket when demand materializes.
- **Cron reconciler safety net.** A weekly Python script that queries Jira for open CCE issues whose dev-status panel (`customfield_10000.json.cachedValue.summary.pullrequest.overall.state == "MERGED"`) reports a merged PR would catch any PRs that merged while the workflow was broken / disabled / not-yet-installed. Filed as future work; not blocking this iteration.
- **Done transition id `41`.** Discovered at design time but never hardcoded — the script always calls `GET /transitions` and matches on `statusCategory.key == "done"`. This means a future Jira workflow change that renumbers transitions doesn't break the script.
