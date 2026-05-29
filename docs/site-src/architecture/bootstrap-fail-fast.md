---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Bootstrap Fail-Fast

The bootstrap pipeline now rejects pages that cannot be parsed, lack frontmatter, or carry thin descriptions. When verification fails, the runner deletes the written file so the next run retries the page through the existing skip-if-exists idempotency guard — no new resume logic required.

## Root cause

Before PR #50, `run_bootstrap_core` trusted the `page-author` subagent's `ok: true` flag without re-reading the artifact it wrote. This allowed three classes of bad output to reach the published site:

- **Bad YAML** — a `: ` inside a backtick span in a description broke frontmatter parsing.
- **Absent frontmatter** — a page written with no `---` block at all.
- **Thin descriptions** — one- or two-word `description:` values that passed `ok: true` but were useless to readers.

All three required manual rewriting after the CCE-15/CCE-36 release. The fix adds verification at the dispatch layer rather than trusting the subagent flag.

## New components

### `parse_frontmatter_strict` (`archive_indexes.py`)

`parse_frontmatter_strict` is a strict variant of the existing `parse_frontmatter` helper. It distinguishes two failure modes:

- `yaml.YAMLError` — the frontmatter block exists but is not valid YAML.
- `ValueError` — no frontmatter block is present at all.

Callers can branch on exception type to produce different error messages or retry strategies.

### `dispatch_verified` (`orchestrator_runner.py`)

`dispatch_verified` is an additive wrapper around `dispatch_validated`. After the subagent write succeeds, it invokes a caller-supplied post-write callback (the verification step). If the callback raises, `dispatch_verified` deletes the target file before re-raising, leaving the path clean for the next run.

`run_bootstrap_core` composes `parse_frontmatter_strict` and `description_quality` into that callback. The callback runs in this order:

1. Parse frontmatter strictly — fails fast on bad YAML or absent block.
2. Run `description_quality` — checks word count, title equality, and trailing colon.

### `description_quality` lint rule

`description_quality` is the 8th Tier-1 default lint rule. It ships with three configurable checks:

| Parameter | Default | Effect |
|---|---|---|
| `min_words` | 5 | Fails if `description` has fewer words than this. |
| `forbid_equal_to_title` | `true` | Fails if `description` duplicates the page title verbatim. |
| `forbid_trailing_colon` | `true` | Fails if `description` ends with `:`. |

Hosts that enabled `lint.tier1: default` before PR #50 get `description_quality` automatically. To opt out of a specific check without disabling the whole rule, override its parameter in your config.

### `_BootstrapProgress` helper

`_BootstrapProgress` atomically writes `.engineering-docs-agent/bootstrap.progress.json` on every page transition. External observers (CI dashboards, the nightly workflow's post-run summary) read this file to distinguish an in-flight bootstrap from a crashed one. The file is gitignored; it persists only for the duration of the bootstrap run.

## Failure handling and retry

When `dispatch_verified` deletes a failed page, the path reverts to "not yet written." The bootstrap's skip-if-exists check treats that path as pending on the next invocation. No extra state tracking is needed — the rollback makes the page invisible to the idempotency guard, so the run just retries it.

If your bootstrap run terminates mid-flight (process kill, timeout), `_BootstrapProgress` records the last-known state. Pages that were written but not yet verified are also rolled back by the file-delete step inside `dispatch_verified`, so they re-enter the pending queue on the next run.

## Test coverage

PR #50 adds 34 new tests, growing the suite from 559 to 593. The new tests cover:

- `parse_frontmatter_strict` for valid YAML, bad YAML, and absent frontmatter.
- `dispatch_verified` success path, callback failure with file-delete, and callback failure when the file was already gone.
- `description_quality` for each configurable check, default-enabled behavior under `tier1: default`, and opt-out via per-parameter override.
- `_BootstrapProgress` atomic write and read-back under concurrent-write conditions.
