---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/293
synthesized_into: []
doc_kind: decision
---

# Voice-sample loading skips an empty source instead of aborting

`load_voice_samples` in `scripts/state_io.py:load_voice_samples` now skips an empty voice source and keeps reading the sources behind it. Before PR #293 (CCE-176), one empty file silently discarded every remaining sample.

## What was wrong

The loop builds a source list in order: the optional `docs-agent-voice.md` override, each `voice.sample_paths` entry, then `CLAUDE.md`. For each source it slices `text[: max(0, cap - total)]` against a 20,000-character cap.

When that slice came back empty, the loop hit a `break`. It read like a budget guard, but it was not one. The loop already breaks at `total >= cap`, so `cap - total` is always positive when the slice runs. An empty snippet therefore means an empty file, never an exhausted budget.

The result: a 0-byte `docs-agent-voice.md` made the function return `[]` even with a populated `CLAUDE.md` present. The override leads the source list, so a single `touch docs-agent-voice.md` disabled every voice sample, and nothing was logged. The same happened with an empty entry in `sample_paths`: the sources after it were dropped.

## The decision

Change the `break` to `continue`. An empty source contributes nothing and is skipped. Later sources are still loaded.

The 20,000-character cap is unchanged. It is still enforced in two places the fix does not touch: the slice, and the `total >= cap` break that ends the walk once the budget is spent.

## Tests

`tests/contracts/test_state_io.py` pins the behavior:

- `test_load_voice_samples_empty_override_does_not_suppress_claude_md` — an empty override no longer hides `CLAUDE.md`.
- `test_load_voice_samples_empty_configured_sample_does_not_suppress_the_rest` — an empty `sample_paths` entry skips only itself.
- `test_load_voice_samples_still_stops_once_the_cap_is_reached` — a source behind one that exhausts the cap is excluded, so `continue` did not loosen the budget.

## Scope

This fixes only the empty-sample skip from CCE-176. CCE-183 (unbounded agent payloads) is linked but still in the backlog and is not addressed here.
