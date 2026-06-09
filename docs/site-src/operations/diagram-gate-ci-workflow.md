---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/110
synthesized_into: []
---

# Diagram-gate CI workflow: in-job filter pattern

## The problem with workflow-level `paths:` filters on required checks

If a GitHub required status check lives in a workflow that carries a top-level `paths:` filter, every PR that touches none of those paths causes GitHub to **skip the workflow entirely**. GitHub never posts a status for a skipped workflow. The PR's `mergeStateStatus` stays `BLOCKED` forever.

This is not a transient failure — it is a permanent block. No amount of re-running the checks resolves it, because the workflow never runs to post any result.

CCE-91 hit this with `diagram-gate`: `docs.yml` had a `paths:` filter scoped to docs files, so any non-docs PR triggered a permanent merge block. The emergency fix (CCE-91 stage-1) removed `diagram-gate` from required checks. PR #110 is the durable fix that allows restoring it.

The same root cause appeared in CCE-59 with `actionlint.yml`. The invariant is now recorded in `CLAUDE.md`: **required status checks must never carry a workflow-level `paths:` filter.**

## The fix: in-job filter

Move the path-scoping logic out of the workflow trigger and into the job itself. The job always runs — so GitHub always posts a conclusive status — but expensive steps execute only when relevant files changed.

The pattern in `.github/workflows/docs.yml`:

```yaml
on:
  pull_request:
    # NO paths: filter here

jobs:
  diagram-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: filter
        id: filter
        run: |
          BASE="${{ github.event.pull_request.base.sha }}"
          CHANGED=$(git diff --name-only "$BASE" HEAD)
          if echo "$CHANGED" | grep -qE '^(docs/|\.github/workflows/docs\.yml)'; then
            echo "relevant=true" >> "$GITHUB_OUTPUT"
          else
            echo "relevant=false" >> "$GITHUB_OUTPUT"
          fi

      - name: install-chromium
        if: steps.filter.outputs.relevant == 'true'
        run: npx playwright install chromium

      - name: mkdocs-build
        if: steps.filter.outputs.relevant == 'true'
        run: mkdocs build --strict

      - name: render-gate
        if: steps.filter.outputs.relevant == 'true'
        run: python3 scripts/render_gate.py

      - name: skip-ok
        if: steps.filter.outputs.relevant == 'false'
        run: echo "No diagram-relevant changes. Skipping render gate."
```

The `skip-ok` step is what makes this safe. When `relevant=false`, the job completes successfully via the no-op step. GitHub sees a green status and unblocks the PR.

## What `git diff --name-only` checks against

The filter uses `github.event.pull_request.base.sha` as the diff base — the merge-base of the PR branch against the target. This is available as an environment variable via the GitHub Actions context.

Do not use `HEAD~1` or `origin/main`. Those are fragile on merge commits and force-pushes. `base.sha` is the authoritative anchor for what this PR actually changes.

## Regression tests

PR #110 added two tests to `tests/test_docs_workflow.py`:

- `test_docs_workflow_has_no_pull_request_paths_filter` — asserts the `on.pull_request` trigger in `docs.yml` contains no `paths:` key.
- `test_docs_workflow_gates_heavy_steps_on_in_job_filter` — asserts that Playwright install, mkdocs build, and render-gate steps all carry an `if: steps.filter.outputs.relevant == 'true'` condition.

Run them with:

```bash
python3 -m pytest tests/test_docs_workflow.py -v
```

If you add a new expensive step to `docs.yml`, add it to the assertion in `test_docs_workflow_gates_heavy_steps_on_in_job_filter` at the same time.

## Restoring `diagram-gate` as a required check

After merging PR #110, restore the branch-protection rule via the GitHub API:

```bash
gh api \
  -X PATCH \
  repos/{owner}/{repo}/branches/main/protection/required_status_checks \
  --input - <<'EOF'
{
  "strict": true,
  "contexts": ["diagram-gate"]
}
EOF
```

Then verify the fix with a synthetic non-docs PR. Open a PR that touches only a file outside the `docs/` tree (e.g., a comment in a Python script). Confirm that:

1. `docs.yml` runs.
2. The `filter` step outputs `relevant=false`.
3. The `skip-ok` step runs.
4. The `diagram-gate` check shows green.
5. `mergeStateStatus` is not `BLOCKED`.

If any of those fail, the branch-protection PATCH did not land or the `paths:` filter was reintroduced.

## Applying this pattern elsewhere

Any workflow that hosts a required status check must follow this pattern. The rule is simple:

- Remove all `paths:` and `branches:` filters from `on.pull_request`.
- Add an in-job `filter` step as the first step in the job.
- Gate every non-trivial step on the filter output.
- Add a `skip-ok` no-op step for the false branch.

If a workflow runs multiple jobs and only some are required checks, apply the filter only to the jobs that are required. Jobs that are not required checks can keep workflow-level filters if needed for cost control — they will not block PRs when skipped.
