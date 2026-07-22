---
description: How the CCE-23 archive-index generator turns dated decision files into
  navigable, auto-maintained index pages.
source_files:
- scripts/archive_indexes.py
- scripts/orchestrator_runner.py
- scripts/site_structure.py
- scripts/state_io.py
- tests/fixtures/archive_indexes/**
- tests/orchestrator/test_archive_indexes.py
last_reviewed: '2026-05-27'
status: draft
doc_kind: architecture
---

# Decision Archive Index Generator (CCE-23)

The archive-index generator (`scripts/archive_indexes.py`) turns directories of date-prefixed Markdown files into navigable index pages. It is capability D of the docs-agent: a pure read-then-write step that runs on every nightly pass and always overwrites its output.

## How it fits into the pipeline

The orchestrator calls `generate_archive` after the page-authoring step. It reads the `site:` config block, locates every section whose `generator` is `archive-index`, and emits one index page per configured source directory into `<docs_dir>/<section.path>/`.

Generated pages carry an auto-generated banner:

```
_Auto-generated; N entries. Do not edit by hand — see `scripts/archive_indexes.py`._
```

Because the pages are always overwritten, you never need to touch them manually. Source files in the configured directories are the canonical input.

## Config shape

Add an `archive-index` section to your `site:` block:

```yaml
site:
  docs_dir: docs/site-src
  sections:
    - key: decisions
      title: Decisions
      path: decisions
      generator: archive-index
      sources:
        - docs/superpowers/specs
        - docs/superpowers/plans
      repo_url_base: https://github.com/org/repo/blob/main/
```

`sources` is a list of repo-relative directory paths. Each becomes one index page named after the directory's basename — e.g., `docs/superpowers/specs` → `decisions/specs.md`.

`repo_url_base` is optional. When present, every entry in the index links to its source file at that base URL. When absent, the generator derives the URL from `git remote get-url origin` plus the current branch (`detect_repo` in `scripts/orchestrator_runner.py`). If detection fails (unknown remote, detached HEAD), entries render as plain text with no link.

## Entry requirements

A file is included if and only if its name matches `YYYY-MM-DD-*.md`. Files without a date prefix are silently ignored. The generator reads two things from each matching file:

- **Title**: the first `# ` heading.
- **Summary**: the first non-blank, non-heading line after the title (truncated to 120 characters).
- **Status**: the `status` key from YAML frontmatter, rendered in a `Status` column.

Entries are grouped by ISO month (newest first) and rendered as a Markdown table.

## Graceful degradation

The generator never aborts mid-run. Each source is processed independently:

- **Missing directory**: logged as a warning to stderr; source is added to the `skipped` list.
- **No dated files**: same — a source with zero `YYYY-MM-DD-*.md` files is skipped rather than emitting an empty page.
- **Duplicate category**: two sources with the same basename (e.g., `team-a/specs` and `team-b/specs`) — the second is skipped to avoid overwriting the first page.
- **Read/path errors** (bad symlinks, `relative_to` failures): caught and skipped per-source.

`generate_archive` returns `{"written": [...], "skipped": [...]}` with repo-relative paths, so the orchestrator can log exactly what happened.

## Legacy lens-based path

Before CCE-23, the orchestrator called `regenerate(archive_root)` for any `lens_paths` entry flagged `archive_index: true`. That function still lives in `scripts/archive_indexes.py` and generates per-subdirectory `index.md` files with a plain bullet list.

The legacy path is retained until the orchestrator-integration step folds `lens_paths` entries into `site:` sections. New setups should use the `archive-index` generator instead.

## Running standalone

You can invoke the generator directly without the full orchestrator:

```bash
python scripts/archive_indexes.py \
  --repo-root . \
  --config .engineering-docs-agent/config.yml \
  --repo-url-base https://github.com/org/repo/blob/main/
```

The script prints a JSON summary of written and skipped paths to stdout. Warnings go to stderr. Exit code is `1` only on a config load error — individual source failures are non-fatal.
