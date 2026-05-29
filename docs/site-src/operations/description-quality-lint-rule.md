---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Description Quality Lint Rule

The `description_quality` rule is a Tier-1 lint check that blocks pages with missing or thin `description` frontmatter from reaching the published site. It ships enabled by default — any host with `lint.tier1: default` in its config gets this rule without additional opt-in.

## What it checks

The rule inspects the `description` field in each page's frontmatter. It fails the page if:

- `description` is absent entirely.
- `description` is present but contains fewer than a configurable minimum number of characters (default: 20).
- `description` consists only of whitespace.

A page that passes the check has a non-empty `description` long enough to be useful in search indexes and site previews.

## Why it's Tier-1

Thin or missing descriptions were reaching the published site because the bootstrap pipeline trusted `page-author`'s `ok: true` signal without re-reading the artifact. The CCE-38 retrospective identified this as a structural gap: the author agent returns success when it believes it wrote valid content, but it does not re-parse what it wrote. The `description_quality` rule closes that gap at the lint stage — it reads the artifact on disk and rejects pages that fall short before the PR is opened.

## Configuration

No extra config is needed when `lint.tier1: default` is set. To raise or lower the minimum length threshold, add a rule-specific override to your `.engineering-docs-agent/config.yml`:

```yaml
lint:
  tier1: default
  rules:
    description_quality:
      min_length: 40
```

To disable the rule entirely for a host that genuinely cannot provide descriptions:

```yaml
lint:
  rules:
    description_quality:
      enabled: false
```

Disabling a Tier-1 rule suppresses it from the lint runner output; the runner logs a warning so the suppression is visible in CI.

## How the rule is registered

The rule is a standalone callable in `scripts/lint/rules/description_quality.py`. The lint runner (`scripts/lint/lint_runner.py`) discovers and registers it at startup by scanning the `rules/` directory. You do not need to edit the runner to add a new rule — drop a module into `rules/` and it is picked up automatically.

The rule's module exports a single `check(page_path, frontmatter, config) -> list[LintViolation]` function. The `LintViolation` dataclass is defined in `scripts/lint/contracts.py` and carries `rule`, `severity`, `message`, and `line` fields.

## Behavior in the bootstrap pipeline

During C2 bootstrap, the orchestrator runs the lint suite on each page immediately after `dispatch_verified` confirms the artifact was written. A `description_quality` failure at this stage marks the page with `status: lint_failed` in its `_BootstrapProgress` record and excludes it from the final PR. The page is not silently dropped — the bootstrap summary lists it under `lint_failures` so you can act on it in the next run.

## Testing

Tests for this rule live in `tests/lint/test_description_quality.py`. They cover:

- Page with no `description` key → violation.
- Page with empty string → violation.
- Page with a description below `min_length` → violation.
- Page with a description at or above `min_length` → no violation.
- Custom `min_length` via config override → respected.

Run them with:

```bash
python3 -m pytest tests/lint/test_description_quality.py -v
```
