# SP-0: Nightly docs-agent cron — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trigger the `engineering-docs-agent` main authoring pipeline (`scripts/orchestrator_runner.py`) once daily at 07:00 UTC via a new GitHub Actions workflow, so PRs merged to `main` get a What's New entry + section authoring within ≤24h without manual intervention.

**Architecture:** A single self-contained scheduled workflow (`.github/workflows/docs-agent-nightly.yml`) — based on the auth + setup pattern in `.github/workflows/release.yml:7-32` — installs Python 3.11 + the Claude Code CLI, authenticates via `CLAUDE_CODE_OAUTH_TOKEN`, then runs `python3 scripts/orchestrator_runner.py`. The runner already handles state read, source-collector dispatch, page authoring, content validation, gap detection, What's New prepend, branch checkout, commit, push, and `gh pr create` (per the `engineering-docs-agent` skill's PR handling block). Partial runs open the PR anyway with `partial: true` (per spec §8). `workflow_dispatch:` is added for manual fires.

**Tech Stack:** GitHub Actions, Python 3.11, Claude Code CLI (`@anthropic-ai/claude-code`).

---

## Task 1: Author the cron workflow YAML

**Files:**

- Create: `.github/workflows/docs-agent-nightly.yml`

- [ ] **Step 1.1: Write the workflow file**

````yaml
name: docs-agent-nightly

on:
  schedule:
    # Daily at 07:00 UTC — early enough for the team to see results
    # before workday start in PT/ET. Off-minute 7 follows the GitHub
    # Actions guidance to avoid the :00 schedule pileup.
    - cron: "7 7 * * *"
  workflow_dispatch:
    inputs:
      reason:
        description: "Optional reason for manual fire (shown in run summary)"
        required: false
        default: "manual run"

permissions:
  contents: write # commit + push docs-agent/YYYY-MM-DD branch
  pull-requests: write # gh pr create + append-commit on existing PR
  issues: read # gap-detector reads linked issues (no writes)

concurrency:
  # One nightly authoring run at a time per branch. Manual fires queue
  # rather than parallelize so two runs don't race on the same
  # docs-agent/YYYY-MM-DD branch.
  group: docs-agent-nightly
  cancel-in-progress: false

jobs:
  author:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    env:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
      GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0 # full history so state.json window math sees all merges

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"

      - name: Install runtime dependencies
        # Matches release.yml — the flat scripts/ layout isn't pip-installable.
        run: |
          python -m pip install --upgrade pip
          python -m pip install pyyaml jsonschema

      - name: Install claude CLI
        run: |
          npm install -g @anthropic-ai/claude-code
          which claude || (echo "claude CLI not installed" && exit 1)

      - name: Assert OAuth token is configured
        # Same actionable-failure pattern as release.yml.
        run: '[ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || (echo "CLAUDE_CODE_OAUTH_TOKEN secret not configured" && exit 1)'

      - name: Configure git identity
        # The runner does `git commit` itself; without an identity it errors
        # out before reaching the PR step.
        run: |
          git config user.name "engineering-docs-agent[bot]"
          git config user.email "engineering-docs-agent@users.noreply.github.com"

      - name: Run nightly authoring
        # The runner reads .engineering-docs-agent/{config.yml,state.json},
        # computes the window vs HEAD, dispatches the pipeline, prepends
        # What's New, opens or append-commits to docs-agent/YYYY-MM-DD, and
        # writes state. Per spec §8: a partial run opens the PR anyway with
        # partial: true in the body — the workflow itself stays green so the
        # next nightly fire isn't suppressed by a red status.
        #
        # --repo-root is required by argparse; GITHUB_WORKSPACE is always set
        # by actions/checkout to the absolute path of the checked-out tree,
        # so no plumbing is needed beyond passing it through.
        run: python3 scripts/orchestrator_runner.py --repo-root "$GITHUB_WORKSPACE"

      - name: Run summary
        if: always()
        # workflow_dispatch.inputs.reason is user-controlled; the github.com
        # workflow-injection guidance is to pass it via env: and dereference
        # as a shell var rather than interpolating into the script body.
        env:
          TRIGGER: ${{ github.event_name }}
          REASON: ${{ inputs.reason }}
        run: |
          {
            echo "## docs-agent-nightly"
            echo ""
            echo "- **Run trigger:** \`$TRIGGER\`"
            if [ "$TRIGGER" = "workflow_dispatch" ]; then
              # Quote REASON so a value with spaces/newlines stays on one row.
              printf -- "- **Reason:** %s\n" "$REASON"
            fi
            echo "- **HEAD:** \`$(git rev-parse --short HEAD)\`"
            echo "- **State file (post-run):**"
            echo '  ```json'
            cat .engineering-docs-agent/state.json 2>/dev/null | sed 's/^/  /' || echo "  (no state)"
            echo '  ```'
          } >> "$GITHUB_STEP_SUMMARY"
````

- [ ] **Step 1.2: Lint the YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/docs-agent-nightly.yml'))"`

Expected: no output (parse succeeds).

- [ ] **Step 1.3: Commit**

```bash
git add docs/superpowers/plans/2026-05-28-nightly-docs-agent-cron.md \
        .github/workflows/docs-agent-nightly.yml
git commit -m "$(cat <<'EOF'
feat(CCE-39): nightly docs-agent cron at 07:00 UTC

Adds the scheduled trigger the engineering-docs-agent main authoring
pipeline has been missing since v0.1.0. Daily at 07:00 UTC (cron `7 7 * * *`)
runs scripts/orchestrator_runner.py against the host; the runner itself
handles state read, pipeline dispatch, What's New prepend, commit, push,
and PR creation per spec §5.3.1.

Auth: CLAUDE_CODE_OAUTH_TOKEN (matches release.yml). Partial runs open
the PR anyway with partial: true per spec §8 — workflow stays green
so the next fire isn't suppressed by a red status. workflow_dispatch
input lets ops fire it manually with a reason logged to the run summary.

Concurrency group docs-agent-nightly prevents two runs racing on the
same docs-agent/YYYY-MM-DD branch.

Plan: docs/superpowers/plans/2026-05-28-nightly-docs-agent-cron.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Smoke-test via workflow_dispatch on the feature branch

**Files:** none

- [ ] **Step 2.1: Push the feature branch**

```bash
git push -u origin feat/CCE-39-nightly-docs-agent-cron
```

- [ ] **Step 2.2: Fire the workflow manually against the feature branch**

```bash
gh workflow run docs-agent-nightly.yml \
  --ref feat/CCE-39-nightly-docs-agent-cron \
  -f reason="SP-0 smoke test"
```

- [ ] **Step 2.3: Watch the run**

```bash
gh run watch
```

Expected outcomes (per spec §5.3.1 + §8):

- Workflow completes (green, or with the `partial: true` PR opened anyway).
- Either a new `docs-agent/YYYY-MM-DD` branch + PR appears, OR the existing one is append-committed.
- The PR's What's New entry references at least one of PRs #42 – #49 (those are the unprocessed merges since `bcfc489`).
- `state.json` on the docs-agent branch shows `current_run.head_sha` updated to the workflow's HEAD.

- [ ] **Step 2.4: Confirm the next scheduled fire is registered**

```bash
gh workflow view docs-agent-nightly.yml
```

Expected: the workflow shows up with the cron schedule active.

---

## Task 3: Update README with operational note

**Files:**

- Modify: `README.md` (add a one-paragraph note + the workflow_dispatch invocation)

- [ ] **Step 3.1: Find the Operations section in README**

Run: `grep -nE "^##? (Operations|Running|Usage)" README.md` — pick the closest section.

- [ ] **Step 3.2: Append the note**

```markdown
### Nightly authoring run

The agent's main authoring pipeline (`scripts/orchestrator_runner.py`) is
triggered automatically by `.github/workflows/docs-agent-nightly.yml` at
07:00 UTC daily. To fire it manually:

\`\`\`bash
gh workflow run docs-agent-nightly.yml -f reason="<your reason>"
gh run watch
\`\`\`

The runner opens or append-commits to a `docs-agent/YYYY-MM-DD` PR; a
partial run opens the PR anyway with `partial: true` in the body. The
workflow_dispatch input is a free-text reason surfaced in the run summary.
```

- [ ] **Step 3.3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(CCE-39): note the nightly docs-agent workflow + manual dispatch

Tells operators where the cron lives and how to fire it ad-hoc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage:**

- Daily 07:00 UTC cron ✓ (cron `7 7 * * *`)
- `CLAUDE_CODE_OAUTH_TOKEN` auth + assert step ✓ (Step 1.1)
- Partial-run PR-anyway behavior ✓ — workflow doesn't gate; the runner's own spec §8 logic carries the `partial` flag
- No `--explain` flag ✓ — out of scope per user choice
- `workflow_dispatch` for manual fires ✓ — with optional `reason` input
- Concurrency lock ✓ — one nightly per repo at a time

**Placeholder scan:** none.

**Type consistency:** Single YAML file + one README edit — no type surface.

**Risk notes (for execution time):**

- The `gh run watch` in Task 2.3 may take 5–15 minutes depending on what the runner finds in the window. If the run hangs, the workflow's `timeout-minutes: 60` will eventually cap it.
- If `CLAUDE_CODE_OAUTH_TOKEN` isn't set on the repo, Step 1.1's assert step gives the actionable failure and aborts before reaching the runner.
- The `engineering-docs-agent[bot]` git identity is a placeholder string, not a real GitHub App; commits will show as that author on the docs-agent PR but won't get a bot badge. Sufficient for v1.
