---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# description_quality lint rule

`description_quality` is the 8th Tier-1 default lint rule. It enforces that the `description` frontmatter field on agent-authored pages is a substantive sentence — not empty, not a copy of the page title, and not a placeholder ending in a colon.

The rule lives in `scripts/lint/description_quality.py` and is invoked by `lint_runner.py` along with the other seven Tier-1 rules whenever `lint.tier1: default` is set in your host config.

## Scope

The rule applies **only to agent-authored sections** — pages whose site section has `generator: agent-authored` in the host `config.yml`. For any other section generator, `check_path` returns `(True, "not agent-authored; skipped")` without reading the frontmatter. This keeps the rule a no-op for changelog, archive, and API pages that use a different required-field contract.

The section generator is resolved by `frontmatter_contract.section_generator_for` (`scripts/frontmatter_contract.py`), which matches on the longest path-prefix among all configured sections.

## What it checks

Given a page that passes the scope filter, the rule reads the page's `description` frontmatter field and applies three checks in cheapest-first order:

1. **`forbid_trailing_colon`** — description must not end with `:`. This catches partial sentences like `"Configures the output pipeline:"`.
2. **`forbid_equal_to_title`** — description must not duplicate the page's H1 heading (case-insensitive). The H1 is extracted from the page body via `archive_indexes.parse_title_and_summary`.
3. **`min_words`** — description must have at least N words after stripping whitespace.

All three checks default to `on`. The defaults are:

| Parameter | Default |
|---|---|
| `min_words` | `6` |
| `forbid_equal_to_title` | `true` |
| `forbid_trailing_colon` | `true` |

A frontmatter YAML parse error also fails the rule. This means `description_quality` surfaces the same gap-3 defects as the bootstrap verification path when you run it through `lint_runner` outside of bootstrap.

## Configuring thresholds

Override any default under `lint.tier1.description_quality` in your host config:

```yaml
lint:
  tier1:
    description_quality:
      min_words: 10
      forbid_equal_to_title: true
      forbid_trailing_colon: false
```

When `lint.tier1` is the string `"default"` (no dict), all three defaults apply and there are no overrides to read.

## Integration with the bootstrap pipeline

The bootstrap runner does not rely solely on the standalone lint script path. `run_bootstrap_core` in `scripts/orchestrator_runner.py` composes two verification steps into `dispatch_verified`:

1. **`parse_frontmatter_strict`** (`archive_indexes.py:59`) — re-reads the artifact the page-author subagent wrote and raises `yaml.YAMLError` on malformed YAML or `ValueError` on missing / structurally invalid frontmatter. This distinguishes parse failure from missing frontmatter so the progress log records distinct reasons.
2. **`description_quality.check_fm`** — runs the same three checks against the parsed frontmatter dict.

`dispatch_verified` is an additive wrapper around `dispatch_validated`. On failure it invokes a post-write callback that deletes the written file, so the existing skip-if-exists idempotency guard treats the absent file as not-yet-written on the next run. You get free retry-on-rerun without separate resume logic.

## Fixing violations

If `description_quality` blocks a page, the failure message tells you which check failed:

- `"missing or empty description"` — add a `description:` field to the frontmatter.
- `"forbid_trailing_colon: description ends in ':'"` — end the sentence with a period or rewrite it.
- `"forbid_equal_to_title: description == title ('...')"` — write a sentence that says something the title does not; the description should explain the *why* or *scope*, not restate the heading.
- `"min_words: N < 6"` — expand the description to at least six words.
- `"frontmatter YAML parse error"` — fix the YAML syntax. A `: ` inside a backtick span is a common trigger; wrap the value in double quotes or use a block scalar.

## Running the rule standalone

```bash
python scripts/lint/description_quality.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/**/*.md \
  --json
```

Or via the lint runner to see all Tier-1 results together:

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/**/*.md \
  --json
```

The lint runner exits `1` if any blocking rule fails; `description_quality` has `severity: block`.
