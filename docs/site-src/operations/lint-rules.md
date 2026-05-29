---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Lint rules

The lint runner (`scripts/lint/lint_runner.py`) applies rules in three tiers. Tier-1 rules run by default when `lint.tier1: default` is set in your host config. Tier-2 and Tier-3 rules are opt-in per rule.

Rules are standalone scripts under `scripts/lint/`. The runner dispatches each script with `--config`, `--paths`, and `--json`, collects the JSON output, and exits 1 if any `block`-severity rule found a failure.

## Tier-1 default rules

Setting `lint.tier1: default` in `.engineering-docs-agent/config.yml` enables the full default set. As of PR #50, nine rules are registered:

| Rule script | What it checks |
|---|---|
| `frontmatter_schema.py` | Required frontmatter fields are present and correctly typed |
| `internal_links.py` | Internal markdown links resolve to existing pages |
| `markdown_hygiene_lang.py` | Fenced code blocks carry a language tag |
| `markdown_hygiene_structure.py` | Document structure (single H1, heading hierarchy) |
| `footnotes.sh` | Footnote references have matching definitions |
| `diagrams.py` | Mermaid and other diagram blocks are syntactically valid |
| `framework_build.py` | The docs framework (MkDocs) builds without error |
| `stub_redirect.py` | Stub pages carry a valid redirect target |
| `description_quality.py` | Frontmatter `description` is substantive, not a placeholder |

## `description_quality` rule

`description_quality` was added in PR #50 (CCE-38) to close a failure mode where the bootstrap loop accepted pages with missing or thin `description` fields and those pages reached the published site undetected.

### Scope

The rule is a no-op for non-agent-authored sections. It applies only to pages whose containing site section has `generator: agent-authored` in the host config's `site.sections` list. `frontmatter_contract.section_generator_for` resolves the generator for any given path.

If the page's section is not `agent-authored`, the rule returns `(True, "not agent-authored; skipped")` and the runner treats it as a pass.

### What it checks

Three sub-checks run in order (cheapest first):

1. **Present and non-empty.** `description` must exist in frontmatter and must not be blank. Fails with `missing or empty description`.
2. **No trailing colon.** Placeholder descriptions often end in `:` (e.g. `"Overview:"` copied from a template). Fails with `forbid_trailing_colon: description ends in ':'`.
3. **Not equal to the page title.** If the page has an H1 heading and `description` matches it (case-insensitive), the description adds no signal. Fails with `forbid_equal_to_title: description == title ('…')`.
4. **Minimum word count.** Descriptions shorter than `min_words` (default: 6) are too thin to be useful. Fails with `min_words: N < 6`.

Severity is `block`: any failure causes the lint runner to exit 1.

### Configuration

Override defaults under `lint.tier1.description_quality` in your host config:

```yaml
lint:
  tier1:
    description_quality:
      min_words: 8                # default: 6
      forbid_equal_to_title: true # default: true
      forbid_trailing_colon: true # default: true
```

Unrecognised keys are ignored. Keys absent from your override keep their defaults.

### Running standalone

```bash
python scripts/lint/description_quality.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/**/*.md \
  --json
```

JSON output shape:

```json
{
  "rule": "description_quality",
  "severity": "block",
  "results": [
    { "path": "docs/site-src/core/connectors.md", "ok": true,  "message": "ok" },
    { "path": "docs/site-src/core/lint-rules.md",  "ok": false, "message": "min_words: 3 < 6" }
  ]
}
```

### Per-page suppression

There is no per-page suppression mechanism. If a page is in an `agent-authored` section, the rule always applies. To exclude a page, move it to a non-agent-authored section or update its section's `generator` in the site config.

## Tier-2 and Tier-3 rules

Tier-2 and Tier-3 rules are enabled by adding keys under `lint.tier2` or `lint.tier3` in your host config. Each key maps to a rule script:

**Tier-2:**

| Config key | Rule script |
|---|---|
| `banned_phrases` | `banned_phrases.py` |
| `ai_tells` | `ai_tells.py` |
| `terminology_glossary` | `terminology.py` |
| `second_person_consistency` | `second_person.py` |
| `paragraph_max_words` | `paragraph_length.py` |

**Tier-3:**

| Config key | Rule script |
|---|---|
| `reading_grade_range` | `reading_grade.py` |
| `sentence_variance` | `sentence_variance.py` |
| `duplicate_detection` | `duplicate_content.py` |

`voice_consistency` is intentionally absent from the runner. It is handled by the `content-validator` subagent using LLM-based evaluation, not a standalone script.
