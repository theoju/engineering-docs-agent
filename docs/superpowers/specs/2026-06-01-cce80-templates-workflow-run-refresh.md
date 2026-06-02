# CCE-80 — Refresh `templates/workflow-run.yml` to match dogfood's nightly

**Status:** Spec — pending plan
**Jira:** CCE-80 ([link](https://designitright.atlassian.net/browse/CCE-80))
**Author:** Theo Jungeblut (Claude Opus 4.7, brainstorming workflow + 3-validator panel)
**Date:** 2026-06-01
**Brainstorm artifacts:** workflow `wfo9fr3y2` (context sweep), workflow `wb60kpder` (Approach A adversarial validation)
**Folds local task:** #383

---

## 1. Why

The plugin's `templates/workflow-run.yml` is the generic GitHub Actions workflow that the `engineering-docs-agent-setup` skill installs into a host repo's `.github/workflows/` at onboarding time. Since CCE-39 (foundational dogfood nightly creation, 2026-05-22), the dogfood host's `.github/workflows/docs-agent-nightly.yml` has accumulated **9 commits worth of features and fixes** that were never backported to the template. New hosts onboarded today receive a workflow that silently lacks:

| Missing                                                                | Origin                                       | Operator impact                                                                                                                                     |
| ---------------------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| App-token plumbing                                                     | CCE-45, CCE-66                               | Docs-agent PRs **silently suppress downstream CI** on every host (default `GITHUB_TOKEN` can't trigger `push`/`pull_request` from its own commits). |
| OAuth pre-flight four-arm assert                                       | CCE-39, CCE-49                               | Misconfigured auth fails deep in orchestrator with cryptic errors instead of at step 6 with `::error::` annotations.                                |
| Forensics upload + `DOCS_AGENT_DEBUG_DIR`                              | CCE-41 (explicitly deferred template absorb) | Failed runs leave **no post-mortem trail** on host runners.                                                                                         |
| Run-summary step                                                       | CCE-39, refined by CCE-73                    | No `$GITHUB_STEP_SUMMARY` audit trail; no stdout echo of `partial_reasons`.                                                                         |
| `JIRA_EMAIL` env                                                       | CCE-53, moved to `vars.*` by CCE-66          | Source-collector silently skips Jira enrichment with `jira_auth_missing`.                                                                           |
| Concurrency policy (`docs-agent-nightly`, `cancel-in-progress: false`) | CCE-39                                       | Two runs can race on the same `docs-agent/YYYY-MM-DD` branch.                                                                                       |
| Git identity step                                                      | CCE-39                                       | Orchestrator's commit step errors before the PR step.                                                                                               |
| `timeout-minutes: 60`                                                  | CCE-39                                       | Runaway runs aren't bounded; paired with App-token's 1h lifetime.                                                                                   |
| `permissions.issues: read`                                             | CCE-39                                       | Gap-detector silently degrades (can't read linked issues).                                                                                          |
| Plus 7 lower-impact items                                              | CCE-39, CCE-53, CCE-54                       | `python -m pip` form, `which claude` install verify, workflow_dispatch `reason` input, off-minute cron, etc.                                        |

**CCE-66** is the only ticket whose own body explicitly names `templates/workflow-run.yml` as needing the same change — it's the smoking-gun template-absorb directive. CCE-41 (SP-1 forensics) explicitly deferred template absorption. This ticket lands the absorption.

## 2. Current-state evidence

|                  | Template                       | Dogfood nightly                            |
| ---------------- | ------------------------------ | ------------------------------------------ |
| Path             | `templates/workflow-run.yml`   | `.github/workflows/docs-agent-nightly.yml` |
| Last commit      | `bfb412f` (CCE-57, 2026-05-29) | `91e9b6c` (CCE-66, 2026-06-01)             |
| Line count       | 52                             | 198                                        |
| Byte count       | 1,764                          | 10,085                                     |
| Lifetime commits | 3                              | 9 (last 30 days)                           |

**Divergence map** (from brainstorm workflow `wfo9fr3y2`): **16 STALE, 1 HOST-SPECIFIC, 4 TEMPLATE-ONLY, 2 EQUIVALENT** (24 numbered divergences).

**Dogfood-only commit set** (never backported):

- `036adf8` CCE-39 — Foundational nightly cron (11 of 16 STALE items)
- `ddd6aab` CCE-41 — Subagent forensics CI (2 STALE items)
- `3089fbb`, `9d81929` CCE-45 — App-token swap (3 STALE items)
- `60496f5` CCE-53 — JIRA_EMAIL wiring (1 STALE item)
- `74c242c` CCE-54 — actions/\* Node-24 bumps (version floor)
- `91e9b6c` CCE-66 — app-id → client-id, JIRA_EMAIL → vars (1 STALE item; explicit template-absorb directive)

## 3. Locked decisions

|                                     | Decision                                                                               | Rationale                                                                                                                  |
| ----------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------ |
| D1 — Scope                          | All 16 STALE in one PR                                                                 | Closes the 7-commit gap in one motion; eliminates drift in one merge.                                                      |
| D2 — CLI auth                       | OAuth-primary (`CLAUDE_CODE_OAUTH_TOKEN`); drop `ANTHROPIC_API_KEY`                    | Matches what the `claude` CLI in CI actually reads; API-key-only hosts work in dev but silently fail in CI.                |
| D3 — App token                      | **Opt-in via `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''`** with `                        |                                                                                                                            | `fallback to`secrets.GITHUB_TOKEN` | Best balance: power-users get full CI, low-friction hosts still onboard. |
| D4 — `pull_request: closed` trigger | KEEP (TEMPLATE-ONLY divergence)                                                        | Real-time docs update on merge for hosts; self-loop guard prevents recursion.                                              |
| D5 — Adjacent gaps                  | Bundle CCE-73 stdout echo (separate commit, same PR); defer CCE-69 mkdocs to follow-up | CCE-73 modifies the same Run-summary step; CCE-69 is a new feature deserving its own design.                               |
| MIG — Existing-host migration       | **Hard cutover + explicit runbook** for ADIS, CCSA, data-importer                      | Simplest template (single auth model); operator burden bounded to 3 known hosts.                                           |
| PIN — Plugin `ref:`                 | **Pin to release tag `v0.5.0`** inline (cut at CCE-80 merge time)                      | Closes supply-chain risk window today; sets release-tagging cadence going forward.                                         |
| FN — Workflow filename              | Update template header to `.github/workflows/docs-agent-nightly.yml`                   | Matches dogfood + all 3 known hosts; one-line header edit.                                                                 |
| SLK — `SLACK_WEBHOOK_URL`           | KEEP with rationale comment                                                            | `agents/notifier.md` consumes it via `slack_config.webhook_url`; setup-guide.md documents it as opt-in (verified by grep). |

## 4. Architecture

### 4.1 Approach

**Approach A** (selected from 3 considered options): direct in-place edit of `templates/workflow-run.yml` + a **live-dogfood parity test** (no snapshot fixture) + setup-skill changes for deterministic per-host cron randomization. Validators converged on this over Approach B (parameterized renderer — too heavy for absorbing 16 commits we already understand) and Approach C (envelope-invariant test suite — over-engineering until it earns its keep).

### 4.2 Generic-first considerations (per CLAUDE.md)

- **Inline literally:** Bot identity `engineering-docs-agent[bot]` (plugin name, not host's).
- **Parameterize via `vars.*`:** `JIRA_EMAIL`, `DOCS_AGENT_APP_CLIENT_ID` (CCE-66 made this call deliberately — email and client ID are public-coordinate-style metadata, not credentials).
- **Parameterize via `secrets.*`:** `JIRA_API_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `SLACK_WEBHOOK_URL` (all credentials).
- **Setup-skill discovery output (NOT hardcoded):** cron minute offset — picking dogfood's `7 7` literally creates a `:07` pileup across every host. Setup skill rewrites the cron line at scaffold time via a deterministic per-host hash.
- **Keep HOST-SPECIFIC:** orchestrator entrypoint path (`python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .` template vs `python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"` dogfood). The template's vendored-plugin path is correct for arbitrary hosts.

## 5. Production changes

### 5.1 `templates/workflow-run.yml` — absorb all 16 STALE divergences

Each item references its STALE number from the divergence map (`wfo9fr3y2`).

**Triggers / metadata**

- **#2** Cron `0 7 * * *` → `7 7 * * *` with rationale comment (dogfood line 6).
  - **NOTE:** the literal value `7 7` gets rewritten per-host by setup-skill (§5.2) — the template ships with `7 7` as the canonical "off-minute" default that survives scaffold-skipping hosts.
- **#4** Add `workflow_dispatch.inputs.reason` (default `"manual run"`).

**Permissions / job-level**

- **#5** Add `permissions.issues: read`.
- **#6** Replace `concurrency: { group: docs-agent-${{ github.ref }}, cancel-in-progress: true }` with `concurrency: { group: docs-agent-nightly, cancel-in-progress: false }`. Document in PR description: changes manual-fire UX (queue not cancel).
- **#7** Add `timeout-minutes: 60` at job scope.

**Job-env**

- **#8** Swap `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` → `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`.
- **#9** Add `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}` (note: `vars`, not `secrets` — per CCE-66).

**App-token step (D3 opt-in)**

- **#11/#12/#19** Add full `Generate GitHub App installation token` step with `id: app-token`, gated by `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''`:
  ```yaml
  - name: Generate GitHub App installation token
    id: app-token
    if: vars.DOCS_AGENT_APP_CLIENT_ID != ''
    uses: actions/create-github-app-token@v3
    with:
      app-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }} # NOTE: GHA action calls it app-id, but value is the Client ID per CCE-66
      private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
  ```
- Wire checkout token to `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}`. GHA semantics: skipped-step outputs evaluate to empty string, so the `||` resolves to the fallback. Document this in the spec's risk-surface (§9.3) and in the template comment block.
- Wire authoring-step env `GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` at step-env scope (job-env rejects `steps.*` references per the CCE-45 follow-up `9d81929`).
- **Prominent template comment immediately above the App-token step:**
  ```yaml
  # Without DOCS_AGENT_APP_CLIENT_ID set, this step is skipped and the workflow falls back
  # to secrets.GITHUB_TOKEN. CONSEQUENCE: docs-agent PRs will NOT trigger your host CI
  # (push/pull_request workflows). To enable host CI on docs-agent PRs, register a GitHub
  # App and set vars.DOCS_AGENT_APP_CLIENT_ID + secrets.DOCS_AGENT_APP_PRIVATE_KEY.
  ```

**Install / verify**

- **#14** Swap `pip install pyyaml jsonschema` → `python -m pip install --upgrade pip && python -m pip install pyyaml jsonschema`.
- **#15** Add `which claude || (echo "claude CLI not installed" && exit 1)` after the npm install.

**OAuth pre-flight four-arm assert (STALE #16)**

- Add the full four-arm case from dogfood lines 89–110:
  ```bash
  if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    echo "::error::CLAUDE_CODE_OAUTH_TOKEN is empty. Set it in repo secrets."
    exit 1
  fi
  case "$CLAUDE_CODE_OAUTH_TOKEN" in
    sk-ant-oat*)  : ;;  # pass
    sk-ant-api*)  echo "::error::CLAUDE_CODE_OAUTH_TOKEN looks like a console API key (sk-ant-api*). Paste an OAuth token (sk-ant-oat*) instead."; exit 1 ;;
    *)            echo "::error::CLAUDE_CODE_OAUTH_TOKEN has unexpected prefix. Expected sk-ant-oat*."; exit 1 ;;
  esac
  if [ ${#CLAUDE_CODE_OAUTH_TOKEN} -lt 32 ]; then
    echo "::error::CLAUDE_CODE_OAUTH_TOKEN is too short (<32 chars)."
    exit 1
  fi
  ```
- **Gate the entire step** with `if: vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true'` so enterprise / Bedrock / Vertex hosts (different prefix conventions) can opt out.

**Identity / authoring / forensics**

- **#17** Add git identity step (`engineering-docs-agent[bot]` / `<engineering-docs-agent@users.noreply.github.com>`).
- **#18** Add `DOCS_AGENT_DEBUG_DIR: ${{ runner.temp }}/docs-agent-debug` to authoring step env (read by `scripts/orchestrator_runner.py:357`).
- **#21** Add `actions/upload-artifact@v6` forensics step:
  ```yaml
  - name: Upload subagent forensics
    if: always()
    uses: actions/upload-artifact@v6
    with:
      name: docs-agent-debug-${{ github.run_id }}
      path: ${{ runner.temp }}/docs-agent-debug/
      retention-days: 14
      if-no-files-found: warn
  ```

**Run summary step (STALE #22 + CCE-73 bundled as a separate commit)**

- Base step from CCE-39 (dogfood lines 161–197) — markdown trigger/reason/HEAD/state.json with `jq -e` safe fallback, written to `$GITHUB_STEP_SUMMARY`.
- **`if: always()`** on the step itself (validators flagged this as a critical defect — without it, partial/failed runs render no summary, defeating CCE-73's bundling rationale).
- **CCE-73 bundle (separate commit in the same PR):** echo `current_run.partial_reasons` to stdout (in addition to the `$GITHUB_STEP_SUMMARY` write), so operators see partial-failure context in the run log without expanding the summary.

### 5.2 `templates/workflow-run.yml` — preserve TEMPLATE-ONLY items (do not absorb)

- **#3** `pull_request: closed` trigger.
- **#23** Job-level `if: github.event_name == 'schedule' || (github.event.pull_request.merged == true && !startsWith(github.head_ref, 'docs-agent/'))` (self-loop guard, only meaningful with #3).
- **#13** Plugin-vendoring `actions/checkout@v5` step:
  ```yaml
  - name: Check out engineering-docs-agent plugin
    uses: actions/checkout@v5
    with:
      repository: theoju/engineering-docs-agent
      ref: v0.5.0 # PIN — see §5.4 release-tagging
      path: .docs-agent-plugin
  ```
- **#10** `SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}` env (with rationale comment: "consumed by agents/notifier.md when notifications.slack.enabled: true").
- **#20** Orchestrator entrypoint `python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .` (HOST-SPECIFIC; template's vendored-plugin path is correct, do not "fix" to dogfood's path).
- **FN** Header comment updated to instruct `.github/workflows/docs-agent-nightly.yml` (was `docs-agent-run.yml` — matches dogfood + all 3 known hosts).

### 5.3 Setup-skill changes

**Ground truth (confirmed during self-review):** The setup skill is markdown-driven (`skills/engineering-docs-agent-setup/SKILL.md`). At step 6 (SKILL.md:33), Claude reads `templates/workflow-run.yml` and writes it to the host. There is NO Python scaffold script for the workflow file. The existing `scripts/setup_scaffold.py` is for the docs _site_ (invoked at SKILL.md step 7), not the workflow. So the cron-randomization needs a small new helper that the markdown skill invokes.

**5.3.1 NEW helper: `scripts/scaffold_workflow.py`** (stdlib-only)

```python
"""Render templates/workflow-run.yml for a host repo.

Rewrites the cron line to a deterministic per-host minute so 100 hosts
don't all hit :07 UTC. Everything else is byte-for-byte copy.

Usage:
    python scripts/scaffold_workflow.py --owner OWNER --repo REPO \\
        [--template PATH] [--out PATH]

--template defaults to the plugin's templates/workflow-run.yml; "-" reads stdin.
--out defaults to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

_CRON_PATTERN = re.compile(r'^(\s+- cron: ")7 7 (\* \* \*")$', re.MULTILINE)


def deterministic_cron_minute(owner: str, repo: str) -> int:
    """Stable per-host cron minute in [5, 55].

    Same owner/repo → same minute (no diff churn on re-scaffold).
    SHA-256 mod 51 over distinct owner/repo strings is uniform across [0, 50];
    offset to [5, 55] to keep within GitHub off-minute guidance.
    """
    digest = hashlib.sha256(f"{owner}/{repo}".encode()).hexdigest()
    return int(digest, 16) % 51 + 5


def rewrite_cron(text: str, owner: str, repo: str) -> str:
    """Replace `cron: "7 7 * * *"` with the deterministic per-host minute.

    Anchored substitution. Raises if the template has zero or more than one
    matching line (structural drift guard).
    """
    minute = deterministic_cron_minute(owner, repo)
    new_text, n = _CRON_PATTERN.subn(rf'\g<1>{minute} 7\g<2>', text)
    if n != 1:
        raise RuntimeError(
            f"Expected exactly 1 cron line matching the anchor; found {n}. "
            "Template structure changed — update scripts/scaffold_workflow.py "
            "or its tests."
        )
    return new_text


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--template", default=None,
                        help='Template path; "-" for stdin; default plugin templates/workflow-run.yml')
    parser.add_argument("--out", default=None, help="Output path; default stdout")
    args = parser.parse_args()

    if args.template == "-":
        text = sys.stdin.read()
    elif args.template:
        text = Path(args.template).read_text()
    else:
        plugin_root = Path(__file__).resolve().parent.parent
        text = (plugin_root / "templates" / "workflow-run.yml").read_text()

    rendered = rewrite_cron(text, args.owner, args.repo)

    if args.out:
        Path(args.out).write_text(rendered)
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
```

Properties: **deterministic** (same input → same minute), **uniformly distributed** ([0, 50] mod 51), **anchored** (structural drift fails loud), **stdlib-only**.

**5.3.2 SKILL.md edits at step 6 (line 33)**

Two changes to the existing step:

1. **Filename:** `.github/workflows/docs-agent-run.yml` → `.github/workflows/docs-agent-nightly.yml` (FN decision; matches dogfood + all 3 known hosts).
2. **Cron-rewrite invocation** — replace the verbatim "write the workflow file" sub-step with:
   > Render the workflow with a deterministic per-host cron minute:
   >
   > ```bash
   > python <plugin_root>/scripts/scaffold_workflow.py \
   >     --owner "$OWNER" --repo "$REPO" \
   >     --out .github/workflows/docs-agent-nightly.yml
   > ```
   >
   > where `OWNER` / `REPO` come from discovery (or the user-confirmed override). The helper is deterministic — re-scaffolding the same host always produces the same cron minute; no operator-visible diff churn.

**5.3.3 SKILL.md additions at step 8 ("next steps" summary)**

Append a conditional warning to step 8's output when `vars.DOCS_AGENT_APP_CLIENT_ID` is unset on the host:

> If `vars.DOCS_AGENT_APP_CLIENT_ID` is unset, the workflow falls back to `secrets.GITHUB_TOKEN`. CONSEQUENCE: docs-agent PRs will NOT trigger your host CI (`push` / `pull_request` workflows). To enable host CI on docs-agent PRs:
>
> 1. Register a GitHub App named `engineering-docs-agent` with `Contents: write`, `Pull requests: write`, `Issues: read` permissions.
> 2. Install it on this repository.
> 3. Set `vars.DOCS_AGENT_APP_CLIENT_ID` (the App's Client ID) and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` (the App's private key, PEM form).
> 4. Re-scaffold via this skill (no-op for cron; activates the App-token step).

**5.3.4 Documentation: `docs/site-src/setup-guide.md`**

Document the `vars.*` / `secrets.*` provisioning matrix:
| Name | Type | Required | Purpose |
|---|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `secrets.*` | ✅ | Claude CLI auth in CI |
| `JIRA_API_TOKEN` | `secrets.*` | If Jira enrichment | Atlassian API auth |
| `JIRA_EMAIL` | `vars.*` | If Jira enrichment | Atlassian basic-auth email half |
| `DOCS_AGENT_APP_CLIENT_ID` | `vars.*` | Opt-in (host CI on docs-agent PRs) | GitHub App client ID |
| `DOCS_AGENT_APP_PRIVATE_KEY` | `secrets.*` | Opt-in (paired with above) | GitHub App private key |
| `SLACK_WEBHOOK_URL` | `secrets.*` | Opt-in (Slack notifications) | Incoming-webhook URL |
| `DOCS_AGENT_SKIP_OAUTH_ASSERT` | `vars.*` | Opt-in (enterprise/Bedrock/Vertex hosts) | Set to `true` to skip the sk-ant-oat\* prefix check |

### 5.4 Release-tagging (PIN)

Cut release tag `v0.5.0` at CCE-80 merge time on `main`. The template's plugin-vendoring `ref:` references this tag. Future plugin releases require either:

1. Re-scaffold via setup-skill (picks up new template with new tag), OR
2. Manual `ref:` bump in the host's workflow file.

Acceptance gate (§7) requires the tag exists before / immediately after merge.

## 6. Testing strategy

### 6.1 NEW `tests/templates/test_workflow_run_parity.py`

Live-dogfood parity test. No snapshot fixture (validators flagged the snapshot as self-defeating).

**Library:** `ruamel.yaml` (not PyYAML). Rationale: PyYAML's `SafeLoader` collapses YAML 1.1 booleans, so the top-level `on:` key parses as `True`. Validator code-quality flagged this as a silent test escape. `ruamel.yaml` preserves string keys and respects YAML 1.2 semantics.

**Allowlist** — top-of-file dict `{step_signature: rationale}`:

```python
ALLOWLIST = {
    # Template-only divergences (D4 — pull_request.closed self-loop affordance):
    "uses:actions/checkout@v5#vendor-plugin": "Template-only: plugin vendoring step; dogfood IS the plugin",
    "pull_request.types==['closed']":        "Template-only trigger: real-time docs update on merge for hosts (D4)",
    "if:github.event_name == 'schedule' || ...!startsWith(github.head_ref, 'docs-agent/')":
                                              "Template-only job-level guard: paired with pull_request.closed trigger",
    "with.path==.docs-agent-plugin":         "Template-only: vendored-plugin checkout target",
    "run:python .docs-agent-plugin/scripts/orchestrator_runner.py": "HOST-SPECIFIC: vendored entrypoint (item #20)",
    "env.SLACK_WEBHOOK_URL":                 "Template-only opt-in: consumed by agents/notifier.md",
}
```

**Assertions:**

1. **Step-signature parity.** For each step in dogfood, the template has a step with the same signature (`uses:<action>@<ver>` or first-line of `run:`), modulo allowlist. Step `name:` is treated as diagnostic only — match on signature + `id:` (where present).
2. **`with:` key contract.** For each step that uses an action listed in `WITH_KEY_CONTRACT`:
   ```python
   WITH_KEY_CONTRACT = {
       "actions/checkout@v5":            {"token"},               # App-token wiring
       "actions/create-github-app-token@v3": {"app-id", "private-key"},
       "actions/upload-artifact@v6":     {"name", "path", "retention-days", "if-no-files-found"},
   }
   ```
   Assert documented keys are present.
3. **Substring asserts on high-value steps:**
   - OAuth pre-flight step body contains `sk-ant-oat` AND `sk-ant-api` (locks the four-arm case).
   - CLI install step body contains `which claude`.
   - Git identity step body contains `engineering-docs-agent[bot]`.
   - Run-summary step body contains `partial_reasons` (locks the CCE-73 bundle).
4. **Literal-equals shape contract:**
   - `concurrency.group == "docs-agent-nightly"`
   - `concurrency.cancel-in-progress == False`
   - `jobs.<id>.timeout-minutes == 60`
   - `permissions` keys ⊇ `{contents, pull-requests, issues}`
   - Job-env keys ⊇ `{CLAUDE_CODE_OAUTH_TOKEN, JIRA_API_TOKEN, JIRA_EMAIL}`
   - Triggers include `schedule` AND `workflow_dispatch`; `pull_request.types == [closed]` is template-only (allowlist).
5. **3 App-token conditional shape asserts:**
   - App-token step has `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''`.
   - Checkout step's `with.token` is the `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` fallback expression.
   - Authoring step's step-env `GH_TOKEN` is the same fallback expression.
6. **Stale-allowlist-entry assertion.** Every allowlist key matches at least one step in dogfood or template. Orphans fail with:
   > `stale allowlist entry "X" — no matching step in dogfood or template. Delete or update.`
7. **Run-summary `if: always()` assertion.** Locked separately because it's load-bearing for CCE-73 bundling.
8. **`on:` key regression test.** Asserts the triggers block parsed correctly under `ruamel.yaml` (regression guard for the PyYAML escape route).

**Failure messages.** Each assertion wraps its error with:

```
Diverged: <key>
Dogfood:  .github/workflows/docs-agent-nightly.yml:<line>
Template: templates/workflow-run.yml:<line>
Action:   Absorb into template, OR add to ALLOWLIST in tests/templates/test_workflow_run_parity.py with rationale.
```

### 6.2 NEW `tests/setup/test_scaffold_workflow.py`

Tests the new helper at `scripts/scaffold_workflow.py` (§5.3.1). Lives under `tests/setup/` to match the existing setup-discover test placement (`tests/setup/test_setup_discover.py`).

1. **Determinism:** `deterministic_cron_minute("theoju", "adis")` twice → same value.
2. **Distinct distribution:** `deterministic_cron_minute("theoju", "adis")` ≠ `deterministic_cron_minute("theoju", "ccsa")`. Pre-compute the expected SHA-256 minutes for these and one or two other known fixtures so the test is fully deterministic; assert exact equality.
3. **Bounds:** minute ∈ `[5, 55]` across a fixed sweep of 20 fixture inputs.
4. **Anchor sanity:** `rewrite_cron("cron: \"0 7 * * *\"" + ...)` raises `RuntimeError("found 0")`; `rewrite_cron(text_with_two_cron_lines, ...)` raises `RuntimeError("found 2")`.
5. **Round-trip on real template:** read the current `templates/workflow-run.yml`, call `rewrite_cron("theoju", "dogfood")`, assert the output differs from input by exactly the cron line, parses cleanly under `ruamel.yaml`, and passes `actionlint` (subprocess invocation; skip the test with a clear message if `actionlint` binary not on PATH).
6. **CLI smoke:** invoke `scripts/scaffold_workflow.py` via `subprocess.run` with `--owner theoju --repo dogfood` and assert stdout starts with `# Drop into the host repo at .github/workflows/docs-agent-nightly.yml` and contains the expected cron minute.

### 6.3 Existing tests

No existing tests should break. Smoke run: full `python3 -m pytest` green (baseline today: 726 passed + 3 skipped per CCE-74 merge).

## 7. Acceptance criteria

- [ ] All 16 STALE divergences absorbed; parity test (§6.1) passes against current `.github/workflows/docs-agent-nightly.yml` with the 6-entry allowlist.
- [ ] All 5 App-token conditional shape asserts + run-summary `if: always()` assert pass.
- [ ] All 4 substring asserts (`sk-ant-oat`, `sk-ant-api`, `which claude`, `engineering-docs-agent[bot]`, `partial_reasons`) pass.
- [ ] `actionlint` clean on edited `templates/workflow-run.yml`.
- [ ] Full `python3 -m pytest` green (baseline + 8+ new tests).
- [ ] Setup-skill regression: generated workflow lints + parses + has randomized cron in `[5, 55]`.
- [ ] Release tag `v0.5.0` cut on main (or in a coordinated immediately-post-merge PR).
- [ ] Migration runbook (§8) executed on the 3 known hosts (ADIS, CCSA, data-importer); manual nightly dispatch verifies on each.
- [ ] PR description preempts the operator-visible changes: `cancel-in-progress: false` UX, `JIRA_EMAIL` from vars, ~145-line delta, concurrency-rename merge-window note.
- [ ] PR-template / CONTRIBUTING.md note added: "edits to `.github/workflows/docs-agent-nightly.yml` require corresponding template or allowlist update".
- [ ] Merge window respected: outside 07:00–08:00 UTC (avoids concurrency-group rename collision with in-flight nightly).

## 8. Migration runbook (existing hosts: ADIS, CCSA, data-importer)

**Before the CCE-80 PR merges**, for each of the 3 known hosts:

1. **Provision new secrets in the host's repo:**
   - Add secret `CLAUDE_CODE_OAUTH_TOKEN` (sk-ant-oat\*) — same token used for the dogfood host's CI.
   - (Optional, recommended) Register a GitHub App for the docs-agent, add var `DOCS_AGENT_APP_CLIENT_ID` and secret `DOCS_AGENT_APP_PRIVATE_KEY`. Install the App on the host repo.
   - (Optional) Set `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT=true` if the host uses an enterprise auth model.

2. **Re-run setup skill** on the host:
   - Invoke `/engineering-docs-agent-setup` in the host's CWD.
   - Verify the scaffolded `.github/workflows/docs-agent-nightly.yml` matches the new template structure.
   - Verify the cron line was rewritten to a host-specific minute in `[5, 55]`.

3. **Verify with manual dispatch:**
   - Trigger the workflow via `workflow_dispatch` with `reason: "post-CCE-80 migration verify"`.
   - Confirm: OAuth pre-flight passes, App-token step runs (or cleanly skips), forensics artifact uploads, run-summary renders.

4. **Remove legacy secret** post-verification:
   - Delete `ANTHROPIC_API_KEY` from the host's repo secrets.
   - Confirm the next scheduled nightly succeeds.

5. **Document migration completion** in the host's `docs-agent/` PR (or in Jira CCE-80 comments) so the migration audit is traceable.

## 9. Risk surface

### 9.1 Concurrency-group rename mid-flight

Switching from `docs-agent-${{ github.ref }}` to `docs-agent-nightly` mid-flight could collide with an in-progress run on a host that started under the old group name. Mitigations:

- Merge CCE-80 outside the 07:00–08:00 UTC window (when nightly cron typically fires).
- The `pull_request: closed` trigger fires the new template immediately on merge — but only on the dogfood host (others won't have the new template until they re-scaffold). Low real-world probability.

### 9.2 Existing hosts not in the runbook

The 3 known hosts (ADIS, CCSA, data-importer) are covered by §8. Any other host instantiated from the stale template will see the same `ANTHROPIC_API_KEY` → `CLAUDE_CODE_OAUTH_TOKEN` hard-fail on the next setup re-scaffold. Mitigation: setup-guide.md update calls out the breaking change in the "Migrating from earlier plugin versions" section.

### 9.3 App-token opt-out silently suppresses host CI

GHA: `steps.app-token.outputs.token` is `""` when the step is skipped via `if:`, so `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` resolves to `secrets.GITHUB_TOKEN`. GHA suppresses `push` / `pull_request` triggers on commits/PRs made by `GITHUB_TOKEN`. Net: hosts that opt out get the workflow running, but their downstream CI doesn't fire on docs-agent PRs. Mitigation: prominent template comment (§5.1) + setup-skill onboarding warning (§5.3.2).

### 9.4 Plugin pin causes update lag

After CCE-80 merges, the template's `ref: v0.5.0` means future plugin releases require either re-scaffold or manual `ref:` bump on each host. Mitigation: cut a tag with every plugin release (set the cadence in CONTRIBUTING.md); document the bump procedure in setup-guide.md.

### 9.5 CCE-69 mkdocs deferral failure mode

Hosts using mkdocs (e.g., ADIS) currently install mkdocs in their host workflow (CCE-69). The refreshed template does NOT install mkdocs. If a future mkdocs-host onboards via the refreshed template without manual edit, the orchestrator's mkdocs build step gets `mkdocs: command not found` or produces an unbuilt `docs/` tree. Mitigation: file CCE-69 follow-up ticket with a 1-line failure-mode note. Out of scope for CCE-80 PR.

### 9.6 PyYAML escape route (test brittleness)

If someone replaces `ruamel.yaml` with PyYAML's `SafeLoader` in `test_workflow_run_parity.py` (or in any setup-skill code that reads the template), `on:` → `True` silently breaks trigger-related assertions. Mitigation: regression test in §6.1.8.

## 10. Out of scope

- Approach B (parameterized renderer with Jinja2 / string.Template) — future ticket if the parameterization surface grows.
- Approach C (envelope-invariant test suite) — current parity + shape contracts are sufficient.
- CCE-69 mkdocs framework branch — deferred to a separate ticket; this spec files §9.5 follow-up.
- Retroactive auto-refresh of host workflows on plugin update — hosts opt in via re-running setup skill.
- New plugin releases on a fixed cadence — covered by CONTRIBUTING.md cadence doc as a follow-up.
- `actionlint` setup-skill smoke (currently runs against `.github/workflows/`; extending to `templates/*.yml` is a one-line CI change and lives outside this ticket's scope but is captured in §7).

## 11. References

- Brainstorm context-sweep workflow: `wfo9fr3y2` (16-STALE divergence map + ticket-impact analysis)
- Approach A validation workflow: `wb60kpder` (3-validator panel + synthesized verdict)
- CCE-39, CCE-41, CCE-45, CCE-49, CCE-53, CCE-54, CCE-66, CCE-73, CCE-74, CCE-75 (history of dogfood-only changes)
- CCE-66 spec: `docs/superpowers/specs/2026-05-31-cce66-auth-tier-migration.md` (vars/secrets discipline)
- CCE-57 spec: `docs/superpowers/specs/2026-05-29-cce57-onboarding-prep.md` (last template touch context)
- CLAUDE.md "Generic plugin — runs on ANY host repo" — load-bearing for the generic-first decisions in §4.2
- GHA: skipped-step output semantics — [GitHub Actions docs / contexts / steps](https://docs.github.com/en/actions/learn-github-actions/contexts#steps-context)
- `agents/notifier.md` — consumer of `SLACK_WEBHOOK_URL`
- `templates/workflow-run.yml` (current, 52 lines)
- `.github/workflows/docs-agent-nightly.yml` (current, 198 lines)
- `skills/engineering-docs-agent-setup/SKILL.md` (setup skill — line 33 step to update)
