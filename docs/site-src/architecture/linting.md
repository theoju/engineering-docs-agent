---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Linting

The agent ships a tiered lint system that runs in CI and inside the bootstrap verification loop. Rules are grouped into three tiers: Tier-1 blocks a page from being accepted; Tier-2 and Tier-3 are opt-in per host.

The entry point is `scripts/lint/lint_runner.py`. You can run it directly:

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The runner reads your host config, resolves which rules are enabled, dispatches each rule script as a subprocess, and aggregates the results into a single JSON object. An overall exit code of `1` means at least one blocking rule failed.

## Tiers

### Tier-1 (default)

Set `lint.tier1: default` in your host config to enable all nine Tier-1 rules. The full default list, defined at `scripts/lint/lint_runner.py:21`, is:

| Rule | What it checks |
|---|---|
| `frontmatter_schema` | Required frontmatter keys are present and correctly typed |
| `internal_links` | Internal markdown links resolve to existing files |
| `markdown_hygiene_lang` | Code fences carry a language tag |
| `markdown_hygiene_structure` | Headings follow a valid hierarchy |
| `footnotes` | Footnote references are defined and used |
| `diagrams` | Diagram blocks are valid |
| `framework_build` | The docs framework builds without error |
| `stub_redirect` | Stub pages carry a redirect target |
| `description_quality` | `description` frontmatter is substantive and non-trivial |

Every Tier-1 rule reports `"severity": "block"`. A failure stops the page from being published.

### Tier-2 (opt-in)

Tier-2 rules are enabled per-key under `lint.tier2` in your host config. Each accepts a truthy value to turn it on, or a config object to tune it.

| Config key | Rule | What it checks |
|---|---|---|
| `banned_phrases` | `banned_phrases` | Phrases you've flagged as disallowed in `lint.tier2.banned_phrases` |
| `ai_tells` | `ai_tells` | Common AI-generated filler phrases |
| `terminology_glossary` | `terminology` | Terms that must match your glossary |
| `second_person_consistency` | `second_person` | Consistent use of second person |
| `paragraph_max_words` | `paragraph_length` | Paragraphs exceeding your word limit |

### Tier-3 (opt-in)

Tier-3 rules are enabled per-key under `lint.tier3`. They are more expensive and stylistic.

| Config key | Rule | What it checks |
|---|---|---|
| `reading_grade_range` | `reading_grade` | Reading grade falls within your target band |
| `sentence_variance` | `sentence_variance` | Sentence length varies enough to avoid monotony |
| `duplicate_detection` | `duplicate_content` | Content duplicated across pages |

## Rule script contract

Each rule is a standalone script under `scripts/lint/`. The runner calls it as a subprocess (`scripts/lint/lint_runner.py:101`):

```
python <rule>.py --config <path> --paths <file1> [<file2>...] --json
```

The script must exit `0` (all passed), `1` (at least one failure), or `2` (invocation error). On `--json`, it writes a single JSON object to stdout:

```json
{
  "rule": "description_quality",
  "severity": "block",
  "results": [
    { "path": "docs/site-src/foo.md", "ok": true, "message": "ok" }
  ]
}
```

The runner parses this; anything with `"severity": "block"` and a failing result sets the overall exit code to `1`.

## `description_quality` rule

Added in PR #50 (CCE-38). It applies only to `agent-authored` pages — the generator check at `scripts/lint/description_quality.py:107` calls `frontmatter_contract.section_generator_for(path, config)` and silently passes non-agent-authored pages. This keeps the rule from firing on human-written docs that don't carry a `description` field.

For agent-authored pages, the rule enforces three constraints (defaults at `scripts/lint/description_quality.py:29`):

- **`min_words: 6`** — the description must contain at least six words after whitespace split.
- **`forbid_equal_to_title: true`** — the description must not be identical to the page's H1, compared case-insensitively after stripping whitespace.
- **`forbid_trailing_colon: true`** — the description must not end in `:`.

All three are `"severity": "block"`. The check order is cheapest-first: trailing colon, equal-to-title, then word count. A file that fails the first check is rejected without doing the remaining work.

You can tune the defaults per-host by adding a dict under `lint.tier1.description_quality`:

```yaml
lint:
  tier1: default
  # Override description_quality defaults:
  # lint.tier1 must stay "default" for the string sentinel to enable all rules;
  # per-rule config is read separately via _resolve_config.
```

Wait — `lint.tier1` must be the string `"default"` to enable the rule set. Per-rule overrides under `lint.tier1.description_quality` are only read when `lint.tier1` is a dict. If you need custom thresholds, change `lint.tier1` to a dict that includes all nine rule names and add your overrides there. The sentinel `"default"` and the dict form are mutually exclusive.

## Running in CI

The lint runner is a standalone script with no external dependencies beyond `yaml` (already in the plugin's environment). Add it to your CI pipeline after the docs build step:

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths $(find docs -name "*.md") \
  --json | tee lint-results.json
```

A non-zero exit code from the runner means a blocking rule failed. The JSON output identifies which paths and rules are responsible.

## Relationship to bootstrap verification

The bootstrap fail-fast layer (see [Bootstrap fail-fast verification](bootstrap-fail-fast.md)) calls `description_quality.check_path` directly during the `dispatch_verified` callback rather than via `lint_runner`. This lets the bootstrap loop reject a page immediately after the `page-author` subagent writes it, before the page enters the skip-if-exists idempotency check. The net effect is that running the full lint suite in CI catches the same class of defects that the bootstrap callback already caught at authoring time — both paths share the same rule logic.
