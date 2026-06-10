---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/132
synthesized_into: []
doc_kind: architecture
---

# framework: none — host onboarding

`framework: none` tells the agent your repo has no language framework the plugin detects automatically. Set it explicitly in `.engineering-docs-agent/config.yml`:

```yaml
site:
  framework: none
```

The agent runs its full generic pipeline on this setting. No capability errors — each one detects what it needs and skips cleanly when that prerequisite is absent.

## What runs

Every item here requires only git history and the docs tree. No package manifest, no OpenAPI schema, and no spec/plan directory are needed.

- **Nightly diff window** — the runner reads `state.json.last_successful_run.head_sha` and collects merged PRs since that SHA. Git is the only requirement.
- **PR summarizer** — runs on every merged PR in the window; produces the structured summary that the page-author and gap-detector consume.
- **Page author** — writes or edits docs pages from PR summaries. Voice-matching uses the `voice_samples` list in your config.
- **What's New entry** — appended to your changelog page each run.
- **Gap detector** — flags non-trivial PRs with no corresponding spec or plan. When no `docs/superpowers/specs` tree exists, the spec-lookup branch skips; the gap detector still runs against PR titles and descriptions.
- **`citation_exists`** — a Tier-1 lint rule that verifies every cited source in a page resolves to a real URL or file path. Requires only git and citation metadata embedded in frontmatter. Runs normally on framework-none hosts.
- **Fact-checker** — the factual-accuracy guard. It reads cited pages, cross-references claims against source content, and emits warnings when a claim can't be grounded. Requires only git and citation metadata. Runs normally on framework-none hosts. Zero fact-checker warnings is one of the three auto-merge eligibility criteria.
- **Publish verification** — polls the configured `publishing.build_workflow` after the docs PR merges and confirms pages are live.

## What doesn't run

These capabilities require detection signals a `framework: none` host won't provide. They skip cleanly — no errors, no empty artifacts.

- **OpenAPI extractor** — skipped when no `openapi_schema` path is configured.
- **Python package scanner** — skipped when no `pyproject.toml` or `setup.py` is found.
- **Jira extractor** — skipped when no `jira.project_keys` are configured.

## Auto-merge behavior

`framework: none` does not affect merge eligibility. The auto-merge gate checks three conditions: non-partial run, zero fact-checker warnings, no human commits on the PR. All three are available to framework-none hosts.

Absent `merge:` config defaults to `auto`. Opt out with:

```yaml
merge:
  policy: manual
```

## Minimal config reference

```yaml
site:
  framework: none
  docs_dir: docs/

docs:
  lens_paths:
    core: docs/site-src/
  agent_editable_paths:
    - docs/site-src/**

merge:
  policy: auto
```

Every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The config loader validates this at startup and rejects any lens path with no matching editable glob.
