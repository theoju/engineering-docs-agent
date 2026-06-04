# CCE-80 — Refresh `templates/workflow-run.yml` to match dogfood's nightly

**Status:** Spec — pending plan
**Jira:** CCE-80 ([link](https://designitright.atlassian.net/browse/CCE-80))
**Author:** Theo Jungeblut (Claude Opus 4.7, brainstorming workflow + 3-validator panel)
**Date:** 2026-06-01
**Brainstorm artifacts:** workflow `wfo9fr3y2` (context sweep), workflow `wb60kpder` (Approach A adversarial validation), workflow `wi8wa16cg` (spec adversarial validation)
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

|                                     | Decision                                                                                                                | Rationale                                                                                                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| D1 — Scope                          | All 16 STALE in one PR                                                                                                  | Closes the 7-commit gap in one motion; eliminates drift in one merge.                                                      |
| D2 — CLI auth                       | OAuth-primary (`CLAUDE_CODE_OAUTH_TOKEN`); drop `ANTHROPIC_API_KEY`                                                     | Matches what the `claude` CLI in CI actually reads; API-key-only hosts work in dev but silently fail in CI.                |
| D3 — App token                      | Opt-in via `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''` with `\|\|` fallback to `secrets.GITHUB_TOKEN`                     | Best balance: power-users get full CI, low-friction hosts still onboard.                                                   |
| D4 — `pull_request: closed` trigger | KEEP (TEMPLATE-ONLY divergence)                                                                                         | Real-time docs update on merge for hosts; self-loop guard prevents recursion.                                              |
| D5 — Adjacent gaps                  | Bundle CCE-73 stdout echo (separate commit, same PR); defer CCE-69 mkdocs to follow-up                                  | CCE-73 modifies the same Run-summary step; CCE-69 is a new feature deserving its own design.                               |
| MIG — Existing-host migration       | Hard cutover + explicit runbook for ADIS, CCSA, data-importer                                                           | Simplest template (single auth model); operator burden bounded to 3 known hosts.                                           |
| PIN — Plugin `ref:`                 | Pin to release tag `v0.5.0` inline (PR author cuts immediately post-merge, <5 min SLA)                                  | Closes supply-chain risk window today; sets release-tagging cadence going forward.                                         |
| FN — Workflow filename              | Update template header AND `SKILL.md:33` to `.github/workflows/docs-agent-nightly.yml`                                  | Matches dogfood + all 3 known hosts; one-line header edit + one SKILL.md edit.                                             |
| SLK — `SLACK_WEBHOOK_URL`           | KEEP with rationale comment                                                                                             | `agents/notifier.md` consumes it via `slack_config.webhook_url`; setup-guide.md documents it as opt-in (verified by grep). |
| **CO-EDIT** — Dogfood scope         | **Co-edit `.github/workflows/docs-agent-nightly.yml` in the same PR** for the items dogfood lacks (CCE-73 stdout echo). | Lets §6.1 parity test enable at merge time without an xfail follow-up.                                                     |
| **ADIS-69** — ADIS mkdocs           | Per-host carve-out in §8 runbook: after re-scaffold, manually re-apply the mkdocs install step                          | Don't block CCE-80 on CCE-69; document the one-block diff ADIS keeps until CCE-69 lands.                                   |
| **OAUTH-VAR** — Opt-out variable    | Keep `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT` (broad-semantic single-purpose boolean)                                        | Simpler than per-check rename; no migration cost since the var is new for CCE-80.                                          |

## 4. Architecture

### 4.1 Approach

**Approach A** (selected from 3 considered options): direct in-place edit of `templates/workflow-run.yml` + co-edit `.github/workflows/docs-agent-nightly.yml` for the same-PR items + **live-dogfood parity test** (no snapshot fixture) + setup-skill changes for deterministic per-host cron randomization. Validators converged on this over Approach B (parameterized renderer — too heavy for absorbing 16 commits we already understand) and Approach C (envelope-invariant test suite — over-engineering until it earns its keep).

### 4.2 Generic-first considerations (per CLAUDE.md)

- **Inline literally:** Bot identity `engineering-docs-agent[bot]` (plugin name, not host's).
- **Parameterize via `vars.*`:** `JIRA_EMAIL`, `DOCS_AGENT_APP_CLIENT_ID` (CCE-66 made this call deliberately — email and client ID are public-coordinate-style metadata, not credentials).
- **Parameterize via `secrets.*`:** `JIRA_API_TOKEN`, `DOCS_AGENT_APP_PRIVATE_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, `SLACK_WEBHOOK_URL` (all credentials).
- **Setup-skill discovery output (NOT hardcoded):** cron minute offset — picking dogfood's `7 7` literally creates a `:07` pileup across every host. Setup skill rewrites the cron line at scaffold time via a deterministic per-host hash.
- **Keep HOST-SPECIFIC:** orchestrator entrypoint path (`python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .` template vs `python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"` dogfood). The template's vendored-plugin path is correct for arbitrary hosts.
- **JIRA_EMAIL / SLACK_WEBHOOK_URL empty-string handling:** orchestrator must treat empty-string `JIRA_EMAIL` identically to missing-key (both skip with `jira_auth_missing`); notifier.md must respect `config.notifications.slack.enabled` regardless of secret presence. Verified during plan task §11.4 below.

## 5. Production changes

### 5.1.0 Final template step list (numbered, dogfood-cited)

The post-absorption `templates/workflow-run.yml` has the following ordered structure. Each step cites its dogfood source line and absorbs that step verbatim (modulo `id:` additions noted, plus the host-specific orchestrator entrypoint).

1. **Header comment block** (TEMPLATE-ONLY) — instructs operator to drop into `.github/workflows/docs-agent-nightly.yml` (FN); documents the `pull_request: closed` trigger + plugin-vendoring step + opt-in `vars.*`/`secrets.*` matrix.
2. **`name: docs-agent run`** (preserved from current template; cosmetic).
3. **`on:`** triggers — schedule (cron `7 7 * * *` — rewritten per-host by setup-skill, see §5.3.1), `workflow_dispatch.inputs.reason` (default `"manual run"`, dogfood lines 7–14), `pull_request.types: [closed]` (TEMPLATE-ONLY, paired with self-loop guard).
4. **`permissions:`** `contents: write`, `pull-requests: write`, `issues: read` (dogfood line 19).
5. **`concurrency:`** `group: docs-agent-nightly`, `cancel-in-progress: false` (dogfood lines 21–24).
6. **`jobs.run:`** `runs-on: ubuntu-latest`, `timeout-minutes: 60` (dogfood lines 30–31), job-level `if:` self-loop guard (TEMPLATE-ONLY).
7. **Job-env block** — `CLAUDE_CODE_OAUTH_TOKEN`, `JIRA_API_TOKEN`, `JIRA_EMAIL`, `GH_TOKEN` (placeholder; overridden at step-env for App-token wiring), `SLACK_WEBHOOK_URL` (TEMPLATE-ONLY).
8. **Step — Generate GitHub App installation token** (`id: app-token`, dogfood lines 44–66; opt-in via `if:`).
9. **Step — Checkout host repo** (`id: checkout-host`, dogfood lines 68–74; `token:` uses `||` fallback).
10. **Step — Check out engineering-docs-agent plugin** (`id: checkout-plugin`, TEMPLATE-ONLY; `ref: v0.5.0` per §5.4).
11. **Step — Install Python deps** (`python -m pip install --upgrade pip && python -m pip install pyyaml jsonschema`, dogfood lines 77–82).
12. **Step — Install claude CLI** (`npm install -g @anthropic-ai/claude-code` + `which claude` verify, dogfood lines 84–87).
13. **Step — Assert OAuth token** (four-arm case, dogfood lines 89–110; gated by `vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true'`).
14. **Step — Configure git identity** (`id: git-identity`, dogfood lines 112–117).
15. **Step — Run docs-agent** (`id: docs-agent`, step-env scope for `GH_TOKEN`, `DOCS_AGENT_DEBUG_DIR`; entrypoint is HOST-SPECIFIC: template uses vendored path).
16. **Step — Upload subagent forensics** (`if: always()`, dogfood lines 143–159).
17. **Step — Run summary** (`if: always()`, dogfood lines 161–197; CCE-73 bundled — see §5.1.2).
18. **Step — Print partial-run reasons** (`if: always()`, CCE-73 — see §5.1.2).

The plan's first task verifies this list against the current dogfood by line-range so any drift between writing the spec and writing the plan is caught.

### 5.1.1 Commit sequence (5 commits within the PR)

Each commit leaves `actionlint` clean and the parity test in a defined state (passing OR xfailed with rationale).

| #   | Commit                                                                | Body summary                                                                                                               |
| --- | --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 1   | `feat(CCE-80): absorb CCE-39 baseline (steps 1–7, 11–12, 14, 17)`     | Triggers, permissions, concurrency, timeout, job-env, install steps, identity, run-summary base. Adds parity test xfailed. |
| 2   | `feat(CCE-80): absorb CCE-45 + CCE-66 App-token plumbing (steps 8–9)` | App-token step + checkout token wiring + step-env GH_TOKEN. Lifts xfail for App-token shape asserts.                       |
| 3   | `feat(CCE-80): absorb CCE-49 OAuth four-arm assert (step 13)`         | Plus enterprise opt-out gate. Lifts xfail for substring asserts.                                                           |
| 4   | `feat(CCE-80): absorb CCE-41 forensics + DEBUG_DIR (steps 15–16)`     | DOCS_AGENT_DEBUG_DIR + upload-artifact. Lifts xfail for forensics asserts.                                                 |
| 5   | `feat(CCE-80): bundle CCE-73 stdout echo (step 18, dogfood co-edit)`  | Adds `Print partial-run reasons` step to BOTH template AND dogfood. Lifts the final parity-test xfail.                     |

Plus dedicated commits for setup-skill (`feat(CCE-80): scaffold_workflow.py helper + SKILL.md cron-rewrite`), tests (`test(CCE-80): parity + scaffold-workflow tests`), runbook (`docs(CCE-80): host-migration runbook`), and CONTRIBUTING gate (`docs(CCE-80): contributing note for dogfood↔template parity`). Total: ~9 commits.

### 5.1.2 Dogfood co-edits (`.github/workflows/docs-agent-nightly.yml`)

Same PR. Two changes:

1. **NEW step "Print partial-run reasons"** — immediately after "Run summary", `if: always()`, body:
   ```yaml
   - name: Print partial-run reasons
     if: always()
     shell: bash
     run: |
       state=".docs-agent-cache/state.json"
       if [ -f "$state" ]; then
         jq -r '.current_run.partial_reasons[]? // empty' "$state" || true
       fi
   ```
   Null-safe via `// empty`; `|| true` so a malformed state.json doesn't fail the run-summary stage.
2. **No structural reorders** in dogfood. The 16 STALE items already exist in dogfood — that's the point. Only the CCE-73 addition is new on the dogfood side.

### 5.1.3 `templates/workflow-run.yml` — absorb all 16 STALE divergences

Each item references its STALE number from the divergence map (`wfo9fr3y2`).

**Triggers / metadata**

- **#2** Cron `0 7 * * *` → `7 7 * * *`. **Rationale comment on the LINE ABOVE the cron entry** (NOT trailing — keeps the §5.3.1 regex anchor strict):
  ```yaml
  schedule:
    # 07:07 UTC off-minute default; setup-skill rewrites per-host so 100 hosts don't pileup at :07
    - cron: "7 7 * * *"
  ```
- **#4** Add `workflow_dispatch.inputs.reason` (default `"manual run"`).

**Permissions / job-level**

- **#5** Add `permissions.issues: read`.
- **#6** Replace `concurrency: { group: docs-agent-${{ github.ref }}, cancel-in-progress: true }` with `concurrency: { group: docs-agent-nightly, cancel-in-progress: false }`. Document in PR description: changes manual-fire UX (queue not cancel).
- **#7** Add `timeout-minutes: 60` at job scope.

**Job-env**

- **#8** Swap `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` → `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`.
- **#9** Add `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}` (note: `vars`, not `secrets` — per CCE-66).

**App-token step (D3 opt-in)** — note `client-id:` (not `app-id:`); this is the CCE-66 v3 deprecation:

- **#11/#12/#19** Add full `Generate GitHub App installation token` step with `id: app-token`, gated by `if: vars.DOCS_AGENT_APP_CLIENT_ID != ''`:
  ```yaml
  # Without DOCS_AGENT_APP_CLIENT_ID set, this step is skipped and the workflow falls back
  # to secrets.GITHUB_TOKEN. CONSEQUENCE: docs-agent PRs will NOT trigger your host CI
  # (push/pull_request workflows). To enable host CI on docs-agent PRs, register a GitHub
  # App and set vars.DOCS_AGENT_APP_CLIENT_ID + secrets.DOCS_AGENT_APP_PRIVATE_KEY.
  - name: Generate GitHub App installation token
    id: app-token
    if: vars.DOCS_AGENT_APP_CLIENT_ID != ''
    uses: actions/create-github-app-token@v3
    with:
      client-id: ${{ vars.DOCS_AGENT_APP_CLIENT_ID }} # CCE-66: v3 deprecated app-id; use client-id
      private-key: ${{ secrets.DOCS_AGENT_APP_PRIVATE_KEY }}
  ```
- Wire checkout token to `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}`. GHA semantics: skipped-step outputs evaluate to empty string, so the `||` resolves to the fallback. Documented in §9.3 + the inline comment above.
- Wire authoring-step env `GH_TOKEN: ${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` at **step-env scope** (job-env rejects `steps.*` references per the CCE-45 follow-up `9d81929`).

**Install / verify**

- **#14** Swap `pip install pyyaml jsonschema` → `python -m pip install --upgrade pip && python -m pip install pyyaml jsonschema`.
- **#15** Add `which claude || (echo "claude CLI not installed" && exit 1)` after the npm install.

**OAuth pre-flight four-arm assert (STALE #16)**

- Full step envelope:
  ```yaml
  - name: Assert OAuth token (sk-ant-oat*, len ≥ 32)
    id: assert-oauth
    if: vars.DOCS_AGENT_SKIP_OAUTH_ASSERT != 'true'
    shell: bash # explicit; lets shellcheck lint the block
    run: |
      if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
        echo "::error::CLAUDE_CODE_OAUTH_TOKEN is empty. Set it in repo secrets."
        exit 1
      fi
      case "$CLAUDE_CODE_OAUTH_TOKEN" in
        sk-ant-oat*)  : ;;
        sk-ant-api*)  echo "::error::CLAUDE_CODE_OAUTH_TOKEN looks like a console API key (sk-ant-api*). Paste an OAuth token (sk-ant-oat*) instead."; exit 1 ;;
        *)            echo "::error::CLAUDE_CODE_OAUTH_TOKEN has unexpected prefix. Expected sk-ant-oat*."; exit 1 ;;
      esac
      if [ ${#CLAUDE_CODE_OAUTH_TOKEN} -lt 32 ]; then
        echo "::error::CLAUDE_CODE_OAUTH_TOKEN is too short (<32 chars)."
        exit 1
      fi
  ```
  Env inherits from job-env (no step-env duplication). Acceptance gate: `actionlint` + `shellcheck` clean on this block.

**Identity / authoring / forensics**

- **#17** Git identity step (`id: git-identity`, `engineering-docs-agent[bot]` / `engineering-docs-agent@users.noreply.github.com`).
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

**Run summary step (STALE #22)**

- Base step from CCE-39 (dogfood lines 161–197) — markdown trigger/reason/HEAD/state.json with `jq -e` safe fallback, written to `$GITHUB_STEP_SUMMARY`.
- **`if: always()`** on the step itself (partial/failed runs MUST render summary).
- CCE-73 stdout echo lives in a SEPARATE STEP (§5.1.2 bullet 1) for review clarity.

### 5.2 `templates/workflow-run.yml` — preserve TEMPLATE-ONLY items (do not absorb)

- **#3** `pull_request: closed` trigger.
- **#23** Job-level `if: github.event_name == 'schedule' || (github.event.pull_request.merged == true && !startsWith(github.head_ref, 'docs-agent/'))` (self-loop guard, only meaningful with #3).
- **#13** Plugin-vendoring `actions/checkout@v5` step (note `id: checkout-plugin` — used by the parity test to discriminate from the host-checkout step):
  ```yaml
  - name: Check out engineering-docs-agent plugin
    id: checkout-plugin
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

**Copy this verbatim into the plan's task** — do not re-derive:

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

# Loosened anchor (C5): tolerates trailing whitespace / inline comment on the cron line,
# in case a future edit adds one. The rewrite preserves whatever tail was present.
_CRON_PATTERN = re.compile(r'^(\s+- cron: ")7 7 (\* \* \*")(.*)$', re.MULTILINE)


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
    new_text, n = _CRON_PATTERN.subn(rf'\g<1>{minute} 7\g<2>\g<3>', text)
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

**5.3.2 SKILL.md edits at step 6**

In `skills/engineering-docs-agent-setup/SKILL.md`, find the sub-bullet beginning:

> `Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json`(initial),`.github/workflows/docs-agent-run.yml`, ...`

Replace the workflow-write sub-bullet with:

> Render the workflow with a deterministic per-host cron minute:
>
> ```bash
> python <plugin_root>/scripts/scaffold_workflow.py \
>     --owner "$OWNER" --repo "$REPO" \
>     --out .github/workflows/docs-agent-nightly.yml
> ```
>
> where `OWNER` / `REPO` come from `discovery["git"]["owner"]` and `discovery["git"]["repo"]` (see §5.3.5). The helper is deterministic — re-scaffolding the same host always produces the same cron minute; no operator-visible diff churn.

Also update the parenthetical `(CCE-57)` reference to read `(CCE-57, CCE-80)`.

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

| Name                           | Type        | Required                                 | Purpose                                             |
| ------------------------------ | ----------- | ---------------------------------------- | --------------------------------------------------- |
| `CLAUDE_CODE_OAUTH_TOKEN`      | `secrets.*` | ✅                                       | Claude CLI auth in CI                               |
| `JIRA_API_TOKEN`               | `secrets.*` | If Jira enrichment                       | Atlassian API auth                                  |
| `JIRA_EMAIL`                   | `vars.*`    | If Jira enrichment                       | Atlassian basic-auth email half                     |
| `DOCS_AGENT_APP_CLIENT_ID`     | `vars.*`    | Opt-in (host CI on docs-agent PRs)       | GitHub App client ID                                |
| `DOCS_AGENT_APP_PRIVATE_KEY`   | `secrets.*` | Opt-in (paired with above)               | GitHub App private key                              |
| `SLACK_WEBHOOK_URL`            | `secrets.*` | Opt-in (Slack notifications)             | Incoming-webhook URL                                |
| `DOCS_AGENT_SKIP_OAUTH_ASSERT` | `vars.*`    | Opt-in (enterprise/Bedrock/Vertex hosts) | Set to `true` to skip the sk-ant-oat\* prefix check |

**5.3.5 NEW: `setup_discover.discover()` emits `{owner, repo}` (C4)**

The new helper needs the host's `owner` and `repo`. `setup_discover` currently does not emit these. Add to `scripts/setup_discover.py`:

```python
import re
import subprocess

_REMOTE_PATTERN = re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?/?$")


def discover_git_origin(repo_root: Path) -> dict | None:
    """Return {owner, repo} parsed from `git remote get-url origin`, or None.

    Returns None if no `origin` remote exists, or the URL doesn't match the
    github.com pattern. Caller (SKILL.md) falls back to AskUserQuestion.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    m = _REMOTE_PATTERN.search(result.stdout.strip())
    if not m:
        return None
    return {"owner": m.group(1), "repo": m.group(2)}
```

Wire `discover_git_origin` into `discover()` under a new key `discovery["git"]` (alongside the existing keys); update `discovery["git"]` to include `owner`, `repo`, and the existing `host: github` field. Test additions: `tests/setup/test_setup_discover.py` adds 3 cases (SSH URL, HTTPS URL, missing remote → None).

SKILL.md step 6 references `discovery["git"]["owner"]`/`discovery["git"]["repo"]` — fall back to `AskUserQuestion("What is the GitHub owner/repo for this host?", header="Repo", options=[...])` if either is None.

**5.3.6 NEW: Pre-merge plugin-tree clarification**

Adding to SKILL.md (or `docs/runbooks/cce80-host-migration.md` — see §8) the following operator-facing note for the migration runbook:

> The migration runbook §8 re-runs the setup skill on each host **before** CCE-80 merges. The setup skill uses the plugin tree that `claude` resolves at invocation time. By default, this is the `~/.claude/plugins/engineering-docs-agent/` clone, which tracks the plugin's `main` branch. The CCE-80 changes are not on `main` yet — they live on the feature branch.
>
> To use the CCE-80 branch's setup skill, run:
>
> ```bash
> # From the plugin repo on the CCE-80 feature branch:
> claude plugin add --local /Users/theo/Projects/engineering-docs-agent
> ```
>
> before re-scaffolding any host. After CCE-80 merges, `claude plugin update engineering-docs-agent` returns each operator to the standard main-tracking install.

### 5.4 Release-tagging (PIN) — strict post-merge sequence (C2)

The template pins `actions/checkout@v5 ref: v0.5.0` for plugin vendoring. The tag must exist before any host re-scaffolds (otherwise host nightly fails at the plugin-vendoring checkout step). Strict sequence at PR-merge time:

| Step                         | Owner                      | Window                | Verification                                                                                                                                                                                               |
| ---------------------------- | -------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Merge CCE-80 PR to `main` | PR author                  | T+0                   | `gh pr view 99 --json mergedAt`                                                                                                                                                                            |
| 2. Cut tag from main HEAD    | PR author                  | T+5 min max           | `gh release create v0.5.0 --target main --title "v0.5.0 — CCE-80 template refresh" --notes-file - <<< "$(cat <<EOF\nTemplate absorbs 16 STALE divergences from dogfood nightly. See CCE-80 spec.\nEOF\n)"` |
| 3. Verify tag exists         | PR author                  | T+6 min               | `gh release view v0.5.0` returns success                                                                                                                                                                   |
| 4. Begin host migration §8   | PR author or runbook owner | After step 3 verifies | Per-host gh CLI commands per §8                                                                                                                                                                            |

Removed the "(or coordinated immediately-post-merge PR)" hedge from earlier draft — a tag is not a PR. If the post-merge tag cut fails for any reason, halt host migrations and surface the issue; do not proceed with `ref: v0.5.0` references unresolved.

**Future plugin releases:** cut a tag with every plugin release; document the cadence in CONTRIBUTING.md (out of scope for this PR, captured as §10 follow-up).

## 6. Testing strategy

### 6.1 NEW `tests/templates/test_workflow_run_parity.py`

Live-dogfood parity test. No snapshot fixture (validators flagged the snapshot as self-defeating). Eight named test functions match the eight assertion categories (precedent: `tests/ci/test_workflow_pages_template.py`).

**Library:** `ruamel.yaml` (not PyYAML). Rationale: PyYAML's `SafeLoader` collapses YAML 1.1 booleans, so the top-level `on:` key parses as `True`. Validators flagged this as a silent test escape. `ruamel.yaml` preserves string keys and respects YAML 1.2 semantics. **Dependency home:** add `ruamel.yaml>=0.18` to a new `requirements-dev.txt` (NOT `templates/docs-requirements.txt` — that ships to hosts).

**Allowlist + key grammar** — top-of-file:

```python
"""Parity test for templates/workflow-run.yml ↔ .github/workflows/docs-agent-nightly.yml.

Key grammar (the strings used in _ALLOWLIST and matcher logic):
  uses:<action>@<ver>              — matches step by uses: signature only (no id required)
  uses:<action>@<ver>#<id>         — matches step by uses: AND id: (disambiguates duplicates)
  with.<key>==<value>              — matches a step whose with: key has the given literal value
  env.<NAME>                       — matches a job-env or step-env key
  pull_request.types==[<list>]     — matches an `on.pull_request.types` literal
  if:<expression>                  — matches a step- or job-level if: (substring match on the expression)
  run:<prefix>                     — matches a step whose run: scalar starts with the prefix (first line, normalized whitespace)
"""

_ALLOWLIST = {
    # Template-only divergences (D4 — pull_request.closed self-loop affordance):
    "uses:actions/checkout@v5#checkout-plugin":
        "Template-only: plugin vendoring step (id: checkout-plugin discriminates from host checkout)",
    "pull_request.types==['closed']":
        "Template-only trigger: real-time docs update on merge for hosts (D4)",
    "if:github.event_name == 'schedule'":
        "Template-only job-level guard: paired with pull_request.closed trigger (D4 self-loop)",
    "with.path==.docs-agent-plugin":
        "Template-only: vendored-plugin checkout target (paired with checkout-plugin step)",
    "run:python .docs-agent-plugin/scripts/orchestrator_runner.py":
        "HOST-SPECIFIC: vendored entrypoint (divergence #20; template uses .docs-agent-plugin path)",
    "env.SLACK_WEBHOOK_URL":
        "Template-only opt-in: consumed by agents/notifier.md when notifications.slack.enabled: true",
}

_WITH_KEY_CONTRACT = {
    "actions/checkout@v5":                  {"token"},                        # App-token wiring (when used by host-checkout)
    "actions/create-github-app-token@v3":   {"client-id", "private-key"},     # CCE-66: v3 deprecated app-id
    "actions/upload-artifact@v6":           {"name", "path", "retention-days", "if-no-files-found"},
}
```

**Eight assertion test functions** (one per category):

1. `test_step_signature_parity()` — for each step in dogfood, the template has a step with the same `uses:` or `run:` first-line signature, modulo `_ALLOWLIST`. Step `name:` is diagnostic only; match on signature + `id:` (where present).
2. `test_with_key_contract()` — for each step that uses an action listed in `_WITH_KEY_CONTRACT`, the documented `with:` keys are present. **Policy:** extra `with:` keys not in the contract are ALLOWED if present in BOTH files (so dogfood can add a future `with:` without breaking parity until template absorbs).
3. `test_high_value_substring_asserts()`:
   - OAuth pre-flight step body contains `sk-ant-oat` AND `sk-ant-api` (locks four-arm case).
   - CLI install step body contains `which claude`.
   - Git identity step body contains `engineering-docs-agent[bot]`.
   - Run-summary step body contains `partial_reasons` (locks CCE-73 echo step presence).
   - Substring checks run on the **parsed ruamel.yaml `run:` scalar** (not raw bytes) — eliminates quoting/escaping false-positives.
4. `test_literal_equals_shape_contract()`:
   - `concurrency.group == "docs-agent-nightly"`
   - `concurrency.cancel-in-progress == False`
   - `jobs.<id>.timeout-minutes == 60`
   - `permissions` keys ⊇ `{contents, pull-requests, issues}`
   - Job-env keys ⊇ `{CLAUDE_CODE_OAUTH_TOKEN, JIRA_API_TOKEN, JIRA_EMAIL}`
   - Triggers include `schedule` AND `workflow_dispatch`; `pull_request.types == [closed]` is template-only (allowlist).
   - `on.pull_request.branches == [main]` (template-only).
5. `test_app_token_conditional_shape()`:
   - App-token step has `if:` substring `vars.DOCS_AGENT_APP_CLIENT_ID != ''`.
   - Checkout step's `with.token` value matches the AST-normalized form `{{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` (parser strips whitespace/quoting; compares normalized expression).
   - Authoring step's step-env `GH_TOKEN` matches the same normalized form.
6. `test_stale_allowlist_entries()`:
   - Every `_ALLOWLIST` key matches at least one step in dogfood OR template. Orphans fail with `stale allowlist entry "X" — no matching step in dogfood or template. Delete or update.`
   - **Redundant-allowlist guard:** every `_ALLOWLIST` key must NOT match a step that's present in BOTH dogfood AND template. Such entries indicate the template absorbed something that didn't need an allowlist. Fail with `redundant allowlist entry "X" — present in both files; remove from allowlist`.
7. `test_run_summary_if_always()` — Run summary step has `if:` expression starting with `always()` (matches both literal `always()` and extended `always() && <cond>` per validator I6).
8. `test_on_key_regression()` — asserts top-level `on:` parsed correctly under `ruamel.yaml` (regression guard for the PyYAML escape route — if a future maintainer swaps in `yaml.safe_load`, this test catches `on:` → `True`).

**Assertion order** is locked: tests run in numeric order (`test_01_step_signature_parity` ... `test_08_on_key_regression`) so failure output is predictable.

**Failure messages.** Each assertion wraps its error with:

```
Diverged: <key>
Dogfood:  .github/workflows/docs-agent-nightly.yml:<line or "?">
Template: templates/workflow-run.yml:<line or "?">
Action:   Absorb into template, OR add to _ALLOWLIST in tests/templates/test_workflow_run_parity.py with rationale.
```

Line numbers are **best-effort**: `getattr(node, 'lc', None) and node.lc.line + 1` guard; if absent (ruamel didn't preserve LC info for that scalar), print `"?"` and direct the operator to the relevant step `name:` for grep.

### 6.2 NEW `tests/setup/test_scaffold_workflow.py`

Tests the new helper at `scripts/scaffold_workflow.py` (§5.3.1). Lives under `tests/setup/` to match the existing setup-discover test placement.

1. **Determinism:** `deterministic_cron_minute("theoju", "adis")` twice → same value.
2. **Distinct distribution:** assert exact equality against pre-computed SHA-256 values for 4+ known fixtures (`theoju/adis`, `theoju/ccsa`, `theoju/data-importer`, `theoju/dogfood`). Pre-compute these via `python -c "import hashlib; print(int(hashlib.sha256(b'theoju/adis').hexdigest(), 16) % 51 + 5)"` at plan-write time; bake the integers into the test.
3. **Bounds:** minute ∈ `[5, 55]` across the fixed sweep.
4. **Anchor sanity:** `rewrite_cron(text_without_cron_line, ...)` raises `RuntimeError("found 0")`; `rewrite_cron(text_with_two_cron_lines, ...)` raises `RuntimeError("found 2")`. Fixture construction: in-test multiline string with `0` and `2` `- cron: "7 7 * * *"` occurrences.
5. **Round-trip on real template:** read the current `templates/workflow-run.yml`, call `rewrite_cron("theoju", "dogfood")`, assert (a) output differs from input by exactly the cron line, (b) parses cleanly under `ruamel.yaml`, (c) passes `actionlint` (subprocess invocation; `pytest.skip` with clear reason if `actionlint` binary not on PATH).
6. **CLI smoke:** invoke `scripts/scaffold_workflow.py` via `subprocess.run` with `--owner theoju --repo dogfood` and assert stdout starts with `# Drop into the host repo at .github/workflows/docs-agent-nightly.yml` (FN header) and contains the expected cron minute.

**xfail discipline during commit sequence (§5.1.1):** parity tests xfail-marked during commits 1–4 (where the template is partial); commit 5 lifts the xfails.

### 6.3 NEW `tests/skills/test_setup_skill_md.py`

Grep-style integration test for the SKILL.md edits (validator I8). Asserts:

1. `skills/engineering-docs-agent-setup/SKILL.md` references `.github/workflows/docs-agent-nightly.yml` (FN).
2. SKILL.md does NOT reference `docs-agent-run.yml` anywhere (catches incomplete edits).
3. SKILL.md references `scripts/scaffold_workflow.py` at the workflow-write sub-step (locks §5.3.2).
4. SKILL.md step 8 references `DOCS_AGENT_APP_CLIENT_ID` and `host CI` (catches if the §5.3.3 warning is dropped).

### 6.4 Existing tests

No existing tests should break. Smoke run: full `python3 -m pytest` green (baseline today: 726 passed + 3 skipped per CCE-74 merge).

## 7. Acceptance criteria

- [ ] All 16 STALE divergences absorbed; parity test (§6.1) passes against current `.github/workflows/docs-agent-nightly.yml` with the 6-entry allowlist.
- [ ] All App-token conditional shape asserts + run-summary `always()` assert pass.
- [ ] All substring asserts (`sk-ant-oat`, `sk-ant-api`, `which claude`, `engineering-docs-agent[bot]`, `partial_reasons`) pass.
- [ ] `actionlint` clean on edited `templates/workflow-run.yml` AND on edited `.github/workflows/docs-agent-nightly.yml`.
- [ ] `shellcheck` clean on the OAuth-assert step body.
- [ ] Full `python3 -m pytest` green (baseline + ~14 new tests across §6.1, §6.2, §6.3).
- [ ] Setup-skill regression: generated workflow lints + parses + has randomized cron in `[5, 55]`.
- [ ] §5.3.3 SKILL.md step-8 conditional warning is emitted when `vars.DOCS_AGENT_APP_CLIENT_ID` is unset (verified by §6.3 integration test).
- [ ] `setup_discover.discover_git_origin()` covered by tests in `tests/setup/test_setup_discover.py` (SSH URL, HTTPS URL, missing-remote None paths).
- [ ] Release tag `v0.5.0` cut by PR author within 5 min of merge per §5.4 strict sequence; verified before any host migration begins.
- [ ] Migration runbook at `docs/runbooks/cce80-host-migration.md` executed on the 3 known hosts (ADIS, CCSA, data-importer); manual nightly dispatch verifies on each.
- [ ] ADIS-specific carve-out (mkdocs install step) re-applied after re-scaffold per §8 step 6.
- [ ] PR description includes:
  - `cancel-in-progress: false` UX change (queue not cancel)
  - `JIRA_EMAIL` reads from `vars.*` not `secrets.*` (CCE-66)
  - **~500–600 lines added** (template ~145 + helper ~80 + parity test ~150 + helper test ~80 + SKILL.md/setup-guide.md edits ~50)
  - Concurrency-rename merge-window note
- [ ] PR-template / CONTRIBUTING.md note added under a "Dogfood ↔ Template Parity" heading:
  > Edits to `.github/workflows/docs-agent-nightly.yml` require either (a) corresponding update to `templates/workflow-run.yml`, or (b) an explicit entry added to `_ALLOWLIST` in `tests/templates/test_workflow_run_parity.py` with rationale.
- [ ] Merge window respected: outside 07:00–08:00 UTC (avoids concurrency-group rename collision with in-flight nightly).

## 8. Migration runbook

**Home:** `docs/runbooks/cce80-host-migration.md` (NEW file, committed in the same PR). Below is the runbook content the plan should write into that file.

### Pre-merge checklist

- [ ] CCE-80 PR is open, all checks green.
- [ ] Operator has the plugin tree checked out at the CCE-80 feature branch and has run `claude plugin add --local /path/to/engineering-docs-agent` (see §5.3.6) — required because re-scaffolding before merge uses the feature branch's SKILL.md + scripts.

### For each of ADIS, CCSA, data-importer (in this order):

1. **Provision new secrets in the host's repo:**

   ```bash
   gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo theoju/<host> --body "$OAUTH_TOKEN"
   ```

   - (Optional, recommended) Register a GitHub App `engineering-docs-agent`, install it on the host repo, then:
     ```bash
     gh variable set DOCS_AGENT_APP_CLIENT_ID --repo theoju/<host> --body "$CLIENT_ID"
     gh secret set DOCS_AGENT_APP_PRIVATE_KEY --repo theoju/<host> --body-file path/to/private-key.pem
     ```
   - (Optional, enterprise hosts only) `gh variable set DOCS_AGENT_SKIP_OAUTH_ASSERT --repo theoju/<host> --body "true"`
   - **Verification:** `gh secret list --repo theoju/<host>` shows `CLAUDE_CODE_OAUTH_TOKEN`; `gh variable list --repo theoju/<host>` shows new vars if set.

2. **Re-run setup skill on the host** (using the feature-branch plugin tree per the pre-merge checklist):

   ```bash
   cd /path/to/host && claude
   > /engineering-docs-agent-setup
   ```

   - **Verification:** `.github/workflows/docs-agent-nightly.yml` exists (note new filename if previously `docs-agent-run.yml` — old file should be deleted by the operator); contains `client-id:`, OAuth-assert step, forensics step, run-summary step, Print-partial-reasons step.
   - **Verification (cron):** `grep -E '^\s+- cron: "[0-9]+ 7 \* \* \*"' .github/workflows/docs-agent-nightly.yml` returns a single line with a minute in `[5, 55]`.

3. **(ADIS only) Re-apply mkdocs install carve-out** (ADIS-69 — see §3 locked decision):
   - Insert the following step IMMEDIATELY AFTER the "Install Python deps" step (between steps 11 and 12 per §5.1.0 ordering):
     ```yaml
     - name: Install mkdocs (ADIS-specific; CCE-69 follow-up will absorb)
       run: python -m pip install mkdocs mkdocs-material
     ```
   - Commit the manual edit on the ADIS repo with subject `chore(ADIS-DOCS): CCE-80 carve-out — restore mkdocs install pending CCE-69`.
   - **Verification:** `actionlint .github/workflows/docs-agent-nightly.yml` clean.

4. **Verify with manual dispatch:**

   ```bash
   gh workflow run docs-agent-nightly.yml --repo theoju/<host> -f reason="post-CCE-80 migration verify"
   gh run watch --repo theoju/<host>
   ```

   - **Verification:** OAuth pre-flight passes (no `sk-ant-api*` complaint), App-token step runs (or cleanly skips), forensics artifact uploads visible in `gh run view --log`, run-summary renders.
   - **Rollback if failure:** see step 4 rollback below.

5. **Remove legacy secret** post-verification:

   ```bash
   gh secret delete ANTHROPIC_API_KEY --repo theoju/<host>
   ```

   - **Verification:** `gh secret list --repo theoju/<host>` no longer shows `ANTHROPIC_API_KEY`.
   - Confirm the next scheduled nightly succeeds (24h waiting period). Document this verification step's completion when satisfied.

6. **Document migration completion** in the host's `docs-agent/` PR (or in Jira CCE-80 comments) so the migration audit is traceable.

### Step 4 rollback

If the manual dispatch fails:

1. Restore `ANTHROPIC_API_KEY` secret if it was already deleted.
2. Revert the workflow file on the host:
   ```bash
   git revert <re-scaffold-commit-sha>
   git push
   ```
3. File a follow-up CCE ticket with the failure mode; halt remaining-host migrations until root cause is understood.

### Post-merge cleanup

After ALL hosts have completed step 5 and confirmed nightly success:

- [ ] Operator runs `claude plugin update engineering-docs-agent` to switch back to main-tracking plugin install.
- [ ] CCE-80 ticket transitioned to Done.

## 9. Risk surface

Each risk is tagged `[in-PR]` (mitigated by code/test changes in this PR) or `[operator-runtime]` (requires operator action at migration time).

### 9.1 Concurrency-group rename mid-flight `[operator-runtime]`

Switching from `docs-agent-${{ github.ref }}` to `docs-agent-nightly` mid-flight could collide with an in-progress run on a host that started under the old group name. Mitigations:

- Merge CCE-80 outside the 07:00–08:00 UTC window (when nightly cron typically fires).
- The `pull_request: closed` trigger fires the new template immediately on merge — but only on the dogfood host (others won't have the new template until they re-scaffold). Low real-world probability.

### 9.2 Existing hosts not in the runbook `[operator-runtime]`

The 3 known hosts (ADIS, CCSA, data-importer) are covered by §8. Any other host instantiated from the stale template will see the same `ANTHROPIC_API_KEY` → `CLAUDE_CODE_OAUTH_TOKEN` hard-fail on the next setup re-scaffold. Mitigation: setup-guide.md update calls out the breaking change in the "Migrating from earlier plugin versions" section.

### 9.3 App-token opt-out silently suppresses host CI `[in-PR]`

GHA: `steps.app-token.outputs.token` is `""` when the step is skipped via `if:`, so `${{ steps.app-token.outputs.token || secrets.GITHUB_TOKEN }}` resolves to `secrets.GITHUB_TOKEN`. GHA suppresses `push` / `pull_request` triggers on commits/PRs made by `GITHUB_TOKEN`. Net: hosts that opt out get the workflow running, but their downstream CI doesn't fire on docs-agent PRs. Mitigation: prominent template comment (§5.1) + setup-skill onboarding warning (§5.3.3, locked by §6.3 integration test).

### 9.4 Plugin pin causes update lag `[operator-runtime]`

After CCE-80 merges, the template's `ref: v0.5.0` means future plugin releases require either re-scaffold or manual `ref:` bump on each host. Mitigation: cut a tag with every plugin release (set the cadence in CONTRIBUTING.md); document the bump procedure in setup-guide.md.

### 9.5 CCE-69 mkdocs deferral failure mode `[operator-runtime]`

Hosts using mkdocs (ADIS) currently install mkdocs in their host workflow (CCE-69). The refreshed template does NOT install mkdocs. Mitigation in this PR: ADIS migration step §8.3 applies the carve-out manually. Long-term: file CCE-69 follow-up ticket with a 1-line failure-mode note for the next implementer.

### 9.6 PyYAML escape route (test brittleness) `[in-PR]`

If someone replaces `ruamel.yaml` with PyYAML's `SafeLoader` in `test_workflow_run_parity.py` (or in any setup-skill code that reads the template), `on:` → `True` silently breaks trigger-related assertions. Mitigation: regression test in §6.1.8.

### 9.7 OAuth opt-out trade-off `[operator-runtime]`

`vars.DOCS_AGENT_SKIP_OAUTH_ASSERT=true` disables the entire OAuth pre-flight assert step. Trade-off: convenience for enterprise/Bedrock/Vertex hosts vs. catching the most common misconfiguration. If a non-enterprise host accidentally sets this var, they lose the four-arm assert and any future OAuth-related validation we add. Mitigation: setup-guide.md documents the var with explicit "enterprise hosts only" guidance; setup-skill step 8 prints a warning if the var is set on a host whose detected toolchain doesn't match an enterprise pattern (e.g., no Bedrock/Vertex env vars).

### 9.8 JIRA_EMAIL / SLACK_WEBHOOK_URL empty-string handling `[in-PR]`

When a generic host doesn't set `vars.JIRA_EMAIL`, the workflow expands `JIRA_EMAIL: ${{ vars.JIRA_EMAIL }}` to an empty string (not unset). The orchestrator's source-collector must handle empty-string identically to missing-key (both skip with `jira_auth_missing`). Similarly for `SLACK_WEBHOOK_URL`. Plan task §11.4 below verifies + adds tests if the existing code path doesn't already handle this.

### 9.9 Fork host collision (low) `[operator-runtime]`

The deterministic cron rewrite uses `sha256(owner/repo)`. If a host is a fork of another (`owner-a/foo` and `owner-b/foo` are distinct fixtures), the minutes are independent — no collision. If the SAME owner runs TWO docs-agent workflows in the same repo (would be unusual but possible via `.github/workflows/docs-agent-*.yml` siblings), they collide on minute. Not in scope; surface as a known limitation.

## 10. Out of scope

- Approach B (parameterized renderer with Jinja2 / string.Template) — future ticket if the parameterization surface grows.
- Approach C (envelope-invariant test suite) — current parity + shape contracts are sufficient.
- CCE-69 mkdocs framework branch — deferred to a separate ticket; this spec files §9.5 follow-up.
- Retroactive auto-refresh of host workflows on plugin update — hosts opt in via re-running setup skill.
- Release-tag cadence enforcement (a tag cut with every plugin release) — captured in CONTRIBUTING.md as a follow-up after CCE-80.
- `actionlint` setup-skill smoke (currently runs against `.github/workflows/`; extending to `templates/*.yml` is a one-line CI change captured in §7).
- `setup_discover.discover_git_origin()` for non-GitHub remotes (GitLab, Gitea) — only GitHub today.

## 11. References

- Brainstorm context-sweep workflow: `wfo9fr3y2` (16-STALE divergence map + ticket-impact analysis)
- Approach A validation workflow: `wb60kpder` (3-validator panel + synthesized verdict)
- Spec validation workflow: `wi8wa16cg` (3-validator panel + synthesized verdict)
- CCE-39, CCE-41, CCE-45, CCE-49, CCE-53, CCE-54, CCE-66, CCE-73, CCE-74, CCE-75 (history of dogfood-only changes)
- CCE-66 spec: `docs/superpowers/specs/2026-05-31-cce66-auth-tier-migration.md` (vars/secrets discipline)
- CCE-57 spec: `docs/superpowers/specs/2026-05-29-cce57-onboarding-prep.md` (last template touch context)
- CLAUDE.md "Generic plugin — runs on ANY host repo" — load-bearing for the generic-first decisions in §4.2
- GHA: skipped-step output semantics — [GitHub Actions docs / contexts / steps](https://docs.github.com/en/actions/learn-github-actions/contexts#steps-context)
- GHA: `actions/create-github-app-token@v3` — [CCE-66 deprecation note](https://github.com/actions/create-github-app-token/releases/tag/v3.0.0)
- `agents/notifier.md` — consumer of `SLACK_WEBHOOK_URL`
- `templates/workflow-run.yml` (current, 52 lines)
- `.github/workflows/docs-agent-nightly.yml` (current, 198 lines)
- `skills/engineering-docs-agent-setup/SKILL.md` (setup skill — step 6 at line 33 to update)
- `tests/ci/test_workflow_pages_template.py` (existing template-test pattern; precedent for §6.1 structure)
- `scripts/preflight_host.py:25` (`_WORKFLOW_TEMPLATE` constant; check whether it needs to track the new filename)
- `scripts/setup_discover.py` (extend with `discover_git_origin()` per §5.3.5)
