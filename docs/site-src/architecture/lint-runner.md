---
description: "The lint runner lives at scripts/lint/lint_runner.py."
source_files:
  - scripts/lint/lint_runner.py
last_reviewed: '2026-06-09'
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/89
synthesized_into: []
---

# Lint Runner

The lint runner lives at `scripts/lint/lint_runner.py`. It reads the host config, resolves which rules are enabled, and dispatches each rule as a subprocess — collecting JSON output and aggregating it into a single pass/fail verdict.

## Rule tiers

Rules are organized into three tiers. The tier a rule belongs to determines whether it's enabled automatically or requires explicit opt-in.

**Tier 1** is the default suite. Set `lint.tier1: default` in your host config to enable all rules in `TIER1_DEFAULT` (defined at `scripts/lint/lint_runner.py:21`). Do not hardcode the count — read it from that list.

**Tier 2** rules are opt-in per rule. Each Tier-2 rule maps from a config key to a rule script name via `TIER2_CONFIG_KEYS` (`scripts/lint/lint_runner.py:35`). For example, setting `lint.tier2.banned_phrases: [...]` enables the `banned_phrases` rule. A falsy or absent value keeps the rule off.

**Tier 3** rules are also opt-in and follow the same key-to-script mapping via `TIER3_CONFIG_KEYS` (`scripts/lint/lint_runner.py:43`). These are the most expensive rules (reading grade, sentence variance, duplicate detection) and are off by default.

## Rule script contract

Every rule script follows a uniform CLI contract:

- Exit `0` — all paths passed.
- Exit `1` — at least one path failed. The `severity` field in the JSON output determines whether the lint runner itself exits `1`.
- Exit `2` — invocation error (bad args, missing config, unhandled exception).

The runner calls each script with `--config <path> --paths <files...> --json`. The `footnotes` rule is the one exception: it's a bash script invoked as `bash footnotes.sh --json <files...>` with no `--config` argument.

If a rule script is missing from disk or produces empty or unparseable output, the runner synthesizes a block-severity failure result rather than silently skipping the rule.

## Severity and blocking

Only `severity: block` failures cause the runner to exit `1`. Warn-severity results are collected and surfaced in the JSON output but do not block the pipeline.

The two markdown hygiene rules split on this axis deliberately: `markdown_hygiene_structure` is block-severity (unpaired fences and heading hierarchy jumps break MkDocs render), while `markdown_hygiene_lang` is warn-severity (a missing language tag loses syntax highlighting but the page still renders).

## Fenced code block masking (CCE-68)

Before PR #89, the heading rules fired on `#`-prefixed lines inside fenced code blocks. A YAML comment like `# key: value` inside a ` ```yaml ``` ` block would trip `HEADING_CASE` or `HEADING_ENDS_PERIOD`, producing false-positive failures on structurally correct documents.

The fix pairs fence delimiters greedily and masks any heading match whose offset falls inside a fenced region. In `markdown_hygiene_structure.py`, the `_in_fence()` helper at line 47 checks each heading match offset against the list of `(start, end)` pairs computed from paired backtick fences. Heading matches inside a fence are skipped entirely. The same masking pattern applies to tilde-delimited fences.

Four tests cover the fix: one per false-positive trigger (backtick, tilde, multi-block, and nested content).

## Output format

The runner emits a single JSON object to stdout when `--json` is passed:

```json
{
  "version": "1",
  "results": [
    {
      "rule": "internal_links",
      "severity": "block",
      "results": [
        { "path": "docs/site-src/core/index.md", "ok": true, "message": "ok" }
      ]
    }
  ]
}
```

Each entry in `results` is the raw JSON output from the rule script. The runner does not transform or filter rule output — it passes it through as-is.

## Adding a new rule

1. Write a script at `scripts/lint/<rule_name>.py` implementing the CLI contract above.
2. Add the rule name to `TIER1_DEFAULT` (if it should be on by default) or add a config-key mapping to `TIER2_CONFIG_KEYS` or `TIER3_CONFIG_KEYS`.
3. If the rule should fire on content outside fenced code blocks only, use the `_in_fence` masking pattern from `markdown_hygiene_structure.py:47` — do not apply heading or content rules to fenced regions.
4. Add tests under `tests/lint/` using the fixture-driven dry-run path.
