---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
  - https://github.com/theoju/engineering-docs-agent/pull/131
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

The `page-author` subagent produces a `description` field but does not re-parse its own output. A plausible-looking value can still be too short, a copy of the page title, or end in a trailing colon — all of which degrade search-index quality and site previews. The `description_quality` rule closes this gap at the lint stage: it reads every agent-authored artifact on disk and rejects pages that fall short before the PR is opened. Because a bad `description` is silent and always wrong — not a matter of style or preference — the rule carries `severity: block`, not warn.

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

When the lint runner dispatches `description_quality` against an agent-authored page and the check fails, `lint_runner` (`scripts/lint/lint_runner.py`) aggregates the block-severity failure and exits with code 1. A non-zero exit signals the orchestrator that the page is not ready to land in the PR. The rule itself does not unlink files or mutate state; that responsibility belongs to the caller. Because `severity` is `block` and not `warn`, the failure gates the whole run — there is no partial-PR path for a page that fails this check.

## Testing

Tests live in `tests/lint/test_description_quality.py`. They cover:

- Missing `description` field → violation.
- Description below `min_words` threshold → violation; substantial description → pass.
- Description equal to the page title (case-insensitive) → violation.
- `title=None` passed to `check_fm` → equal-to-title comparison skipped, other checks still apply.
- Trailing colon → violation.
- Config overrides for `min_words`, `forbid_trailing_colon`, and `forbid_equal_to_title` individually → respected.
- Non-agent-authored lens (no `generator: agent-authored`) → rule returns `ok=True, "skipped"`.
- CLI emits JSON matching the rule contract and exits 1 on failure.
- `lint_runner.enabled_rules` includes `description_quality` when `lint.tier1: default`.

Run them with:

```bash
python3 -m pytest tests/lint/test_description_quality.py -v
```
