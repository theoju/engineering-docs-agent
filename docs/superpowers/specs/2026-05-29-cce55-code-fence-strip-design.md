# CCE-55 — Strip benign code-fence wrappers before strict JSON parse

## Background

Subagents (`pr-summarizer`, `gap-detector`, `source-collector`) are instructed in two places to return raw JSON only — once in their agent contract `.md` file (e.g. `agents/pr-summarizer.md:71` and again at `agents/pr-summarizer.md:159` as a forbidden output), and once in the orchestrator's execution-framing prompt at `scripts/orchestrator_runner.py:119-126`. Despite this, the model wraps the JSON in a markdown code fence (` ```json ... ``` `) about 19% of the time. Forensics from the docs-agent-nightly run that produced PR #69 captured 16 schema-bearing dispatches; 3 of them (2 pr-summarizer, 1 gap-detector) wrapped in fences.

When the wrap happens, `scripts/orchestrator_runner.py:475` raises `json.JSONDecodeError`, the orchestrator falls through to `_rescue_json_object` at line 480, brace-balanced extraction recovers the JSON byte-equal to the fence contents, all rescued outputs validate against their schema, and the orchestrator appends `prose_contamination_rescued: <name>` to `partial_reasons`. The PR opens with a `WARNING — Partial run` banner enumerating the rescue events.

The diagnostic on PR #69's forensics artifact (Option D) verified byte-equality between fence contents and rescued JSON for all 3 contaminated dispatches. Content is preserved. The banner is signal-noise.

## Problem

Every non-trivial nightly run trips the partial banner because of fence wrapping. Operators learn to ignore the banner because the underlying content is fine. That defeats the purpose of `partial_reasons` — the banner should surface runs where something operationally meaningful went wrong, not runs where the model added decorative whitespace around its JSON output.

The contamination class matters:

- **Markdown code fence wrap** — known, benign, byte-equal recoverable. Common. Should be silently normalized.
- **Prose preamble** (e.g. the original CCE-15 `★ Insight` preamble injected by a SessionStart hook) — anomalous, may be lossy in pathological cases, indicates upstream contamination escaping the `--setting-sources project,local` defense. Should keep raising `prose_contamination_rescued`.

## Goal

Recognize the markdown code-fence wrap as a known benign output shape. Strip it before strict `json.loads`. Suppress the `partial_reasons` banner for this class. Keep `_rescue_json_object` intact as the second-line defense for genuinely anomalous contamination.

## Non-goals

- Tightening agent prompts. The instruction is already there, twice per agent, plus once in the orchestrator framing. The model ignores it ~19% of the time anyway. This is a known LLM failure mode, not a prompt-engineering problem.
- Removing `_rescue_json_object`. It still earns its keep for the residual contamination class (prose preambles, post-fence trailing prose, etc.).
- Forcing 100% clean dispatches. Partial-mode remains the operational visibility surface for runs where something genuinely degraded.

## Design

### New helper

````python
def _strip_code_fence(text: str) -> str:
    """If text is exactly a markdown code fence wrap around JSON, return
    the inner content. Otherwise return text unchanged.

    Matched shape (optional outer whitespace, optional language tag):
        \\s* ``` (json|JSON|<empty>)? \\n
        <inner>
        \\n ``` \\s*

    The match is whole-string. Mid-string fences (prose then fenced JSON
    then more prose) do not match — those fall through to
    _rescue_json_object as anomalous contamination.
    """
````

Implementation: a single `re.match` against `^\s*```[A-Za-z0-9]*\s*\n(.*)\n```\s*$` with `re.DOTALL`. On match: return group(1). On miss: return the original text.

### Pipeline integration

In `dispatch_subagent` (`scripts/orchestrator_runner.py:471-485`):

1. Compute `stripped = _strip_code_fence(canonical_text)`.
2. If `stripped != canonical_text`, the wrap was present. Attempt `json.loads(stripped)`.
   - On success: return the parsed dict. Do NOT append to `out_reasons`. The wrap is a known benign shape.
   - On failure: fall through to step 4 (the strip didn't help; treat as anomalous).
3. If `stripped == canonical_text`, no wrap was present. Attempt `json.loads(canonical_text)`. On success: return. On failure: fall to step 4.
4. Fall through to `_rescue_json_object` (existing behavior). On success: return rescued dict AND append `prose_contamination_rescued: <name>` to `out_reasons`. On failure: return None.

### Telemetry preservation

The forensics dir already captures `<ts>-<name>.stdout.txt` (the contaminated text) and `<ts>-<name>.stream.jsonl` (the raw stream). After this change, an operator investigating a future contamination can still see the fence wrap in the artifact — only the partial banner is suppressed, not the forensics.

If we later want to surface fence-wrap frequency as a separate diagnostic (without breaking partial-mode), a counter like `state.current_run.code_fence_strips` could land in a follow-up. Out of scope for this spec.

## Test plan

New tests in `tests/orchestrator/test_strip_code_fence.py`:

- `test_strip_unwraps_json_lang_fence` — `"```json\n{}\n```"` → `"{}"`.
- `test_strip_unwraps_no_lang_fence` — `"```\n{}\n```"` → `"{}"`.
- `test_strip_unwraps_trailing_whitespace` — `"```json\n{}\n```\n\n"` → `"{}"`.
- `test_strip_unwraps_leading_whitespace` — `"\n  ```json\n{}\n```"` → `"{}"`.
- `test_strip_preserves_clean_json` — `'{"a":1}'` → `'{"a":1}'` (no change).
- `test_strip_does_not_match_prose_around_fence` — `"prose\n```json\n{}\n```\nmore"` → unchanged (this is anomalous contamination, must fall through to rescue).
- `test_strip_does_not_match_mid_string_braces` — `"see `code` not fence"` → unchanged.
- `test_strip_real_fixture_pr_summarizer` — load the PR #69 forensics fixture (1640-byte ` ```json ` wrapped output), strip, json.loads succeeds, schema validates.

New tests in `tests/orchestrator/test_dispatch_rescue.py` (extending the existing rescue test module):

- `test_dispatch_fence_wrapped_emits_no_partial_reason` — monkeypatched subprocess returns ` ```json\n{"prs":[]}\n``` `; dispatch returns `{"prs":[]}`; `out_reasons` stays empty.
- `test_dispatch_anomalous_prose_still_emits_rescue_reason` — monkeypatched subprocess returns `"★ Insight\n{prose}\n{\"prs\":[]}"`; dispatch returns `{"prs":[]}`; `out_reasons` has `prose_contamination_rescued: <name>`.

Existing tests in `test_dispatch_rescue.py` and `test_dispatch_validated.py`: confirm they still pass. The `prose_contamination_rescued` assertion in `test_dispatch_subagent_appends_rescue_reason_to_out_reasons` uses an `★ Insight` prefix — that pattern is anomalous, not a fence wrap, so it must still flow through the rescue path with the reason emitted.

## Behavior matrix

| Subagent output shape              | Existing behavior                             | Behavior after CCE-55                                    |
| ---------------------------------- | --------------------------------------------- | -------------------------------------------------------- |
| Raw `{...}`                        | parse success, no banner                      | parse success, no banner                                 |
| ` ```json\n{...}\n``` `            | rescue + `prose_contamination_rescued` banner | strip + parse success, no banner                         |
| ` ```\n{...}\n``` ` (no lang tag)  | rescue + banner                               | strip + parse, no banner                                 |
| `★ Insight\n...\n{...}`            | rescue + banner                               | rescue + banner (unchanged)                              |
| `prose\n```json\n{...}\n```\nmore` | rescue + banner                               | rescue + banner (unchanged — strip is whole-string only) |
| Unparseable garbage                | None returned, schema_invalid reason          | None returned, schema_invalid reason (unchanged)         |

## Files changed

- `scripts/orchestrator_runner.py` — add `_strip_code_fence`, wire it into `dispatch_subagent` between `canonical_text` extraction and `json.loads`.
- `tests/orchestrator/test_strip_code_fence.py` (new) — 8 unit tests for the helper.
- `tests/orchestrator/test_dispatch_rescue.py` — add 2 integration tests for the dispatch pipeline.
- `tests/fixtures/cce55/` (new) — capture the actual PR #69 contaminated fixture for the fixture-based unit test (lifted from `/tmp/cce55-fx-v2/20260529T155357-pr-summarizer.stdout.txt`).

No changes to:

- Agent contract `.md` files (the existing instructions are already correct; the model just ignores them sometimes)
- `agents/schemas/*` (no schema change)
- `scripts/contracts.py` (no dataclass change)
- Workflow YAMLs

## Risk

- **Regression on the existing rescue path**: mitigated by keeping `_rescue_json_object` intact and gating the strip on whole-string match. Anything that isn't exactly a fence wrap still falls through.
- **False positive on a legitimate string that happens to look like a fence**: the whole-string match (`^\s*```...\n.*\n```\s*$`) cannot match a JSON object whose first character is `{`, because `{` doesn't start with backticks. The strip is invisible to clean dispatches.
- **Sonnet emits a fence with extra trailing prose**: doesn't match whole-string strip; falls through to `_rescue_json_object`; existing behavior preserved.

## Out of scope

- Source-collector dispatches that exhibit other contamination patterns. The CCE-15 work covered the `★ Insight` SessionStart-hook class. If new patterns show up in forensics, they'll get their own ticket.
- Banner-suppression for non-pr-summarizer/gap-detector agents. The fix applies uniformly to all dispatches that go through `dispatch_subagent`.
- Telemetry counter for fence-strip frequency. If we want to know how often the model wraps in fences, the forensics artifacts already let us count post-hoc.
