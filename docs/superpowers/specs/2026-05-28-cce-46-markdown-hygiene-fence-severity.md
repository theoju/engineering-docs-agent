# CCE-46: split markdown_hygiene severity — warn on missing fence language, block on structural defects

**Ticket:** CCE-46
**Status:** Draft (awaiting user review)
**Related:** PR #59 (lost 2 authored pages to this issue)

## Problem

`scripts/lint/markdown_hygiene.py:14-16` declares a single module-level `SEVERITY = "block"` for the whole rule. The rule emits two kinds of findings:

1. **Opening fence missing a language tag** (e.g. ` ``` ` instead of ` ```python `). This is cosmetic — MkDocs still renders the block; only syntax highlighting is lost.
2. **Structural defects** (unpaired fence, heading hierarchy jumps). These genuinely break MkDocs render or produce malformed HTML.

Today both collapse to severity `block`, so `scripts/orchestrator_runner.py:1167-1226` drops the entire authored page on any finding from this rule. No retry, no partial save — the whole page reverts to HEAD (edit case) or is `unlink`-ed (create case). PR #59 lost two pages this way to three missing-language offsets, none of which would have broken the docs build.

`scripts/lint/lint_runner.py:84-139,156` consumes severity at the **rule-script level** via `out.get("severity")` (module-level), not per-finding. Existing `warn`-severity rules (`duplicate_content`, `reading_grade`, `sentence_variance`) all declare `SEVERITY = "warn"` at module scope and emit a single severity in their JSON output. The orchestrator's drop path also keys on per-finding `severity == "block"` (line 1168), but that severity is always copied from the rule's module-level constant via content-validator's aggregation. There is no precedent or runtime support for mixed-severity output from a single rule.

## Goal

A page authored with a missing fence language tag survives the validate→drop step. A page with an unpaired fence or a heading-jump still gets dropped. No new flags, no per-finding severity protocol, no orchestrator changes.

## Architecture

**Path chosen: B (split into two rule modules).**

Path A — single rule emitting per-finding severity — was rejected after reading `scripts/lint/lint_runner.py:84-139,156`. The runner keys on a single `severity` field at the rule-script JSON top level and aggregates `any_block_failed` per rule. Supporting mixed-severity output would require changes to:

- `lint_runner.py` (route per-finding severity into the aggregated result),
- the content-validator agent contract (`agents/content-validator.md`, `agents/schemas/content_validator.schema.json`) to specify how a single rule's mixed findings flatten,
- the orchestrator drop path (already keys on per-finding `severity`, but the `failed[]` array would need both severities preserved per-rule).

Path B mirrors the existing pattern of one module per severity level. Three Tier-1 rules already follow this single-severity-per-module convention; `duplicate_content` (warn), `reading_grade` (warn), and `sentence_variance` (warn) are the precedent.

### Changes

1. **`scripts/lint/markdown_hygiene.py`** becomes the structure-only block-severity rule:
   - `RULE_NAME = "markdown_hygiene_structure"` (renamed)
   - `SEVERITY = "block"` (unchanged)
   - `check_path` drops the no-language-tag detection; keeps unpaired-fence and heading-hierarchy detection.
2. **New `scripts/lint/markdown_hygiene_lang.py`** is the language-tag warn-severity rule:
   - `RULE_NAME = "markdown_hygiene_lang"`
   - `SEVERITY = "warn"`
   - `check_path` runs only the no-language-tag detection.
3. **`scripts/lint/lint_runner.py:21-30`** updates `TIER1_DEFAULT`: replace `"markdown_hygiene"` with two entries `"markdown_hygiene_lang"` and `"markdown_hygiene_structure"`. Order doesn't matter (Tier 1 default runs all). Total Tier-1 count goes from 8 to 9 (the list as written has 8 names; CHANGELOG.md says "Tier 1" without committing to a count).

> Rename note: the original module file `markdown_hygiene.py` is renamed in place (logic-pruned to structure-only) rather than deleted-and-recreated, so git tracks the move. The existing rule name `markdown_hygiene` is retired; nothing inside `agents/`, `skills/`, or runtime configs hardcodes the old name (verified via `grep`).

## Failure modes

| Mode                                                                | Behavior                                                                             |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Opening fence missing language tag                                  | `markdown_hygiene_lang` emits warn; orchestrator's drop loop **skips** (not `block`) |
| Unpaired fence (odd fence count)                                    | `markdown_hygiene_structure` emits block; orchestrator drops the page                |
| Heading hierarchy jump (h1 → h3)                                    | `markdown_hygiene_structure` emits block; orchestrator drops the page                |
| Both kinds in same file                                             | Two findings emitted by two rules; only structure finding triggers drop              |
| Missing file path                                                   | Both rules return `(False, "file not found")` with their respective severities       |
| Pre-existing config references the old rule name `markdown_hygiene` | No config references exist (verified); nothing to migrate                            |

## Testing strategy

Two test files:

1. **`tests/lint/test_markdown_hygiene.py`** (updated) — covers the new `markdown_hygiene_structure` rule. Tests for unpaired-fence and heading-hierarchy are kept and updated to assert `out["rule"] == "markdown_hygiene_structure"` and `out["severity"] == "block"`. The `test_no_lang` test is **moved** to the new test file (see below) because the structure rule no longer flags missing-language fences.
2. **`tests/lint/test_markdown_hygiene_lang.py`** (new) — covers `markdown_hygiene_lang`. Asserts: (a) a fixture with a missing-language fence returns rc=1 with message containing "language", `out["severity"] == "warn"`, `out["rule"] == "markdown_hygiene_lang"`; (b) a clean fixture (`good.md`) passes rc=0; (c) a fixture with a structural defect (unpaired fence) does **not** fail this rule (it's the structure rule's job).
3. **`tests/lint/test_lint_runner.py`** (updated) — `test_runs_tier1_default` asserts both `markdown_hygiene_lang` and `markdown_hygiene_structure` appear in `rules_run`. The old `assert "markdown_hygiene" in rules_run` is removed.

Fixtures from `tests/fixtures/markdown_hygiene/` are reused as-is. No new fixtures needed.

All tests use the fixture-driven dry-run path; the production Claude CLI dispatch is monkeypatched in unit tests (existing convention).

## Acceptance criteria

1. `scripts/lint/markdown_hygiene.py` `RULE_NAME` is `markdown_hygiene_structure`; `check_path` no longer flags missing-language fences; `SEVERITY` stays `block`.
2. `scripts/lint/markdown_hygiene_lang.py` exists with `RULE_NAME = "markdown_hygiene_lang"`, `SEVERITY = "warn"`, and only the missing-language detection.
3. `scripts/lint/lint_runner.py` `TIER1_DEFAULT` lists both `markdown_hygiene_lang` and `markdown_hygiene_structure`; the old `markdown_hygiene` entry is removed.
4. `tests/lint/test_markdown_hygiene.py` reflects the structure-only rule and passes.
5. `tests/lint/test_markdown_hygiene_lang.py` exists, asserts severity `warn`, and passes.
6. `tests/lint/test_lint_runner.py::test_runs_tier1_default` asserts both new rule names and passes.
7. `python3 -m pytest` is fully green.
8. No code outside `scripts/lint/` and `tests/lint/` is touched (no orchestrator change, no contract change, no skill update — orchestrator already does the right thing once the severities arrive correctly).

## Out of scope

- **Per-finding severity protocol** in `lint_runner.py` and the content-validator contract. A future ticket can introduce this if more rules need mixed severities; today only `markdown_hygiene` would have benefited.
- **Auto-fix of missing language tags.** The warn-severity finding still appears in the docs PR's lint summary so authors can backfill tags. Auto-inserting a language guess is a separate ticket.
- **Tier-2/Tier-3 promotion of `markdown_hygiene_lang`.** It stays in Tier-1 default so authors still see the warning; only the drop behavior changes.
- **CHANGELOG entry.** Internal rule split; CHANGELOG is for release-facing changes.
