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

- `description` is absent or only whitespace.
- `description` has fewer than a configurable minimum number of words (`min_words`, default 6).
- `description` merely repeats the page title (`forbid_equal_to_title`, default on).
- `description` ends with a trailing colon (`forbid_trailing_colon`, default on).

A page that passes the check has a substantive `description` useful in search indexes and site previews.

## Why it's Tier-1

Thin or missing descriptions were reaching the published site because the bootstrap pipeline trusted `page-author`'s `ok: true` signal without re-reading the artifact. The CCE-38 retrospective identified this as a structural gap: the author agent returns success when it believes it wrote valid content, but it does not re-parse what it wrote. The `description_quality` rule closes that gap at the lint stage — it reads the artifact on disk and rejects pages that fall short before the PR is opened.

## Configuration

No extra config is needed when `lint.tier1: default` is set. Overrides live under `lint.tier1` as a dict carrying rule subkeys (the `_resolve_config` helper in `scripts/lint/description_quality.py` merges them over the defaults):

```yaml
lint:
  tier1:
    description_quality:
      min_words: 10
      forbid_equal_to_title: true
      forbid_trailing_colon: true
```

Note the trade-off: `lint.tier1` is either the sentinel string `default` (full Tier-1 set, rule defaults) or a dict (which is also how per-rule keys such as `stub_paths` are carried). Only the three keys above are recognized; unknown keys are ignored.

## How the rule is registered

The rule is a standalone script at `scripts/lint/description_quality.py`, registered by name in the `TIER1_DEFAULT` list in `scripts/lint/lint_runner.py`. Registration is explicit — adding a rule means adding the script and appending its name to the tier list (or a tier-2/3 config-key mapping).

Every rule script shares one CLI contract: `--config <path> --paths <p...> --json`, exit 0 all-pass / 1 any-fail / 2 invocation error, emitting `{"rule", "severity", "results": [{"path", "ok", "message"}]}`. The runner aggregates per-rule JSON and exits 1 if any block-severity rule failed.

## Behavior in the bootstrap pipeline

During C2 bootstrap, `dispatch_verified` runs a post-write check against the artifact the page-author produced. A failing page is unlinked so the next bootstrap run retries it (the existing skip-if-exists idempotency is the retry mechanism), and the rejection reasons land in the run ledger. The per-page progress file `bootstrap.progress.json` (a runtime artifact under `.engineering-docs-agent/`) records the page under its `failed` list, and the run digest surfaces the reasons under `lint_failures` — the page is not silently dropped.

## Testing

Tests for this rule live in `tests/lint/test_description_quality.py`. They cover:

- Missing `description` field → violation.
- Description below `min_words` → violation; substantial description → pass.
- Description equal to the page title → violation (and skipped when no title).
- Trailing colon → violation.
- Config overrides for `min_words`, `forbid_trailing_colon`, `forbid_equal_to_title` → respected.
- Non-agent-authored lenses skipped; CLI JSON output and Tier-1 registration.

Run them with:

```bash
python3 -m pytest tests/lint/test_description_quality.py -v
```
