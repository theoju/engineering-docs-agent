---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/111
synthesized_into: []
doc_kind: architecture
---

# Diagram-Gate CI Workflow

The `diagram-gate` workflow validates that documentation diagrams render correctly before a PR can merge. It runs Playwright-driven screenshot tests and an `mkdocs build --strict` check. Because these steps take ~3 minutes, the workflow uses a path filter to skip them entirely when a PR touches only non-docs files.

## Filter logic

On every PR, the workflow runs a `filter` job first. That job compares the changed file paths against a set of `include` patterns. If no changed file matches an include pattern, the job sets `relevant=false` and the workflow exits immediately.

The include patterns cover files that can affect rendered diagrams or docs structure — for example, source pages under `docs/site-src/`, the `mkdocs.yml` config, and diagram source files. Files like `CHANGELOG.md`, Python scripts, and workflow YAML are not included; a PR that only touches those paths triggers the skip path.

## Skip-path behavior

When `relevant=false`, the workflow:

1. Skips the Playwright browser install step.
2. Skips the `mkdocs build` step.
3. Skips the render-gate comparison step.
4. Reports the required `diagram-gate` status check as **SUCCESS** in ~10 seconds.

The required check still reports — it just exits early with a green status. This matters because GitHub branch protection requires the check to pass regardless of whether any diagrams were touched. Without the skip path, every CHANGELOG or script-only PR would block on a 3-minute run that tests nothing relevant.

## CCE-91 fix context

Before CCE-91 (landed in PR #110, commit `a71a2a7`), the filter step was absent. Every PR ran the full Playwright suite even when no docs-adjacent file changed. This caused two problems: unnecessary CI time on non-docs PRs, and a deadlock risk if the required check queued behind a slow Playwright run on a branch that only updated a README.

The fix added Option A: a path-filter job at the top of the workflow that gates all downstream steps. PR #111 validated the fix end-to-end by touching only `CHANGELOG.md` — a file deliberately excluded from the include patterns — and confirming the gate reported SUCCESS without invoking any Playwright or mkdocs step.

## Updating the include patterns

The include patterns live in the workflow file (`.github/workflows/diagram-gate.yml`). When you add a new file category that can affect rendered output, add its path glob to the `include` block of the filter job. When you add a file that should never trigger the gate (config, scripts, metadata), verify it is absent from all include globs.

Do not broaden the include patterns speculatively. A pattern that is too wide defeats the skip path and restores the 3-minute penalty on unrelated PRs. Add patterns only when you have a concrete file type that, when changed, can cause a diagram rendering difference.
