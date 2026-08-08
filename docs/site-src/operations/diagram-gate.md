---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/110
  - https://github.com/theoju/engineering-docs-agent/pull/111
synthesized_into: []
doc_kind: architecture
---

# Diagram-Gate CI Workflow

The `diagram-gate` job validates that documentation diagrams render correctly before a PR can merge. It runs a Playwright-driven render gate and an `mkdocs build --strict` check. Those steps take ~3 minutes, so the job detects whether a PR touches diagram-relevant files and skips the expensive work when it does not.

The job lives in `.github/workflows/docs.yml`. There is no separate `diagram-gate.yml` workflow — the workflow is named `docs`, and `diagram-gate` is the single job inside it.

## Filter logic

Detection happens in a **step**, not a separate job. The `diagram-gate` job's first real step is named `Detect diagram-relevant changes` and carries `id: filter`. It diffs the changed files against the PR base SHA (on `pull_request`) or the previous commit (on `push`), then matches each path with a bash `case` statement.

Exclusions are tested first and short-circuit the match:

```bash
case "$f" in
  docs/runbooks/*|docs/superpowers/*)
    continue
    ;;
esac
case "$f" in
  docs/*|scripts/verify_diagrams.py|tests/diagrams/*|tests/fixtures/diagrams/render/*|requirements-docs.txt|.github/workflows/docs.yml)
    relevant=true
    break
    ;;
esac
```

These are shell glob patterns, so `*` spans slashes — `docs/*` matches any page nested under `docs/`, including this one at `docs/site-src/operations/diagram-gate.md`. The step writes `relevant=true` or `relevant=false` to `$GITHUB_OUTPUT`, and every expensive step downstream gates on `steps.filter.outputs.relevant == 'true'`.

Note that Python scripts and workflow YAML are **not** categorically excluded: `scripts/verify_diagrams.py` and `.github/workflows/docs.yml` both trigger the gate, because a change to either can alter the gate's own behavior. `CHANGELOG.md` and the runbook and superpowers trees are the paths that reliably skip.

When the base SHA is missing or all-zeroes — a first push to a new branch, or an unrecognized event — the step defaults to `relevant=true`. The gate fails safe: it would rather run needlessly than silently skip.

## Skip-path behavior

When `relevant=false`, the job skips the Python setup, the docs-tooling install, the Chromium install, the render tests, the `mkdocs build`, and the render gate. A `No-op success` step runs on the inverse condition and logs why the gate did nothing.

The job does not exit early — it runs to ground and reports success in ~10 seconds. That distinction is the entire point. `diagram-gate` is a required branch-protection check, so it must report a status on every PR. A job that terminated without reporting would leave the check pending and block the merge.

## CCE-91 fix context

The original workflow carried a `paths:` filter on its `push` and `pull_request` triggers. That filter did not merely save CI time — it caused a permanent deadlock. On any PR that touched none of the listed paths, GitHub skipped the workflow entirely, the required `diagram-gate` check never reported, and `mergeStateStatus` stayed `BLOCKED` forever. PR #108 hit this on every non-docs check.

CCE-91 (PR #110, commit `a71a2a7`) inverted the skip surface. It removed `paths:` from both triggers so the workflow always fires, and moved path detection into the in-job `filter` step described above. Non-docs PRs now pay ~5 seconds of detection instead of either a 3-minute Playwright run or a permanent block. This is the same lesson `.github/workflows/actionlint.yml` records under CCE-59: never put a `paths:` filter on a workflow that backs a required status check.

Two tests in `tests/diagrams/test_packaging.py` encode the contract from both sides: `tests/diagrams/test_packaging.py:test_docs_workflow_has_no_pull_request_paths_filter` guards against re-introducing the workflow-level filter, and `tests/diagrams/test_packaging.py:test_docs_workflow_gates_heavy_steps_on_in_job_filter` guards against dropping the in-job gating that keeps non-docs PRs fast.

## Updating the path patterns

The patterns live in the `Detect diagram-relevant changes` step of `.github/workflows/docs.yml`, not in a reusable filter action. To add a file category that can affect rendered output, add its glob to that step's include `case` arm. To make a path stop triggering the gate, add it to the exclusion `case` arm above it — remember the exclusions are evaluated first.

Do not add a `paths:` filter at the workflow level to achieve the same effect. It reintroduces the CCE-91 deadlock.

Do not broaden the include patterns speculatively either. A pattern that is too wide defeats the skip path and restores the 3-minute penalty on unrelated PRs. Add patterns only when you have a concrete file type that, when changed, can cause a diagram rendering difference.
