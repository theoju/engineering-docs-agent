---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/61
synthesized_into: []
---

# Linting Rules

The docs-agent runs a tiered linting pipeline against every page it authors or edits. Rules are grouped into three tiers — Tier 1 (enabled by default), Tier 2, and Tier 3 (both opt-in). Each rule has a severity: `warn` lets the PR through with a note; `block` fails the lint stage and prevents the page from landing.

## Tier 1: Default rules

The host repo's `lint.tier1: default` setting enables all seven Tier-1 rules. You do not need to list them individually — they activate as a group.

## Markdown hygiene rules (split as of PR #61)

Before PR #61, a single `markdown_hygiene` rule covered all markdown structural issues at a uniform `block` severity. That caused a page with only a missing language tag — a cosmetic omission by the `page-author` agent — to be fully rejected from the docs site.

PR #61 split that single rule into two:

### `markdown_hygiene_lang` (severity: `warn`)

Flags code-fence opening lines that are missing a language tag (e.g., a bare ` ``` ` instead of ` ```python `). The page still lands; the warning surfaces in the lint summary so the issue is visible without being fatal.

Use this rule to surface probabilistic slip-ups by the `page-author` agent without blocking delivery.

### `markdown_hygiene_structure` (severity: `block`)

Catches defects that genuinely break MkDocs rendering:

- Unpaired fences (an opening ` ``` ` with no matching closing fence).
- Heading jumps (e.g., an `h4` immediately after an `h2` with no `h3` in between).

These defects corrupt the rendered page, so they remain `block`. If `lint_runner.py` returns a `block` violation for this rule, the page is not included in the docs-agent PR.

### Registering both rules

Both rules are registered in `TIER1_DEFAULT` in `scripts/lint/lint_runner.py`. The script-path derivation maps rule name to file using the same convention as all other Tier-1 rules: `scripts/lint/<rule_name>.py`. Three tests cover the split:

- `test_markdown_hygiene_lang` — verifies warn-only on a bare fence.
- `test_markdown_hygiene_structure` — verifies block on an unpaired fence and on a heading jump.
- `test_runner_registration` — verifies both rule names appear in the runner's registered rule set.

## Configuration reference

```yaml
lint:
  tier1: default        # enables all 7 Tier-1 rules, including both markdown_hygiene_* rules
  tier2: []             # opt-in, empty by default
  tier3: []             # opt-in, empty by default
```

To disable a specific Tier-1 rule, list it under `lint.tier1.disabled`:

```yaml
lint:
  tier1:
    disabled:
      - markdown_hygiene_lang   # suppress warn-level language-tag checks
```

Disabling `markdown_hygiene_structure` is not recommended — unpaired fences and heading jumps will silently corrupt rendered output.

## Running the linter locally

```bash
python scripts/lint/lint_runner.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/**/*.md \
  --json
```

The `--json` flag outputs structured results per file. Each entry includes `rule`, `severity`, `line`, and `message`. A non-zero exit code means at least one `block`-severity violation was found.
