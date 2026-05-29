---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
synthesized_into: []
---

# Bootstrap fail-fast verification

The bootstrap orchestrator previously trusted the `page-author` subagent's `ok: true` reply without re-reading the artifact it wrote to disk. Bad YAML frontmatter, absent frontmatter, and thin descriptions could reach the published site undetected. PR #50 (CCE-38) closes that gap with a fail-fast verification layer wired into `run_bootstrap_core`.

## Root cause

`run_bootstrap_core` used `ok: true` in the subagent JSON response as the acceptance signal. The subagent controls that field — if it misformatted the file and still returned `ok: true`, the orchestrator moved on. The CCE-15 and CCE-36 retrospectives identified three recurring intervention patterns all traceable to this single trust assumption.

## What changed

### `parse_frontmatter_strict` (`archive_indexes.py`)

A stricter sibling of the existing `parse_frontmatter` that distinguishes two distinct failure modes: absent frontmatter (no `---` delimiter at all) and present-but-invalid YAML (delimiters present, content malformed). Callers that need only the lenient parse continue using the original; the verification layer calls the strict variant so it can log the right error and route the retry correctly.

### `dispatch_verified` (`scripts/orchestrator_runner.py`)

A wrapper around the existing `dispatch_validated` that accepts a caller-supplied post-write callback. After dispatch completes, the callback reads the target file and runs the verification checks. If verification fails, `dispatch_verified` deletes the target file before returning an error. Because `run_bootstrap_core` already skips pages whose target path exists (`if target_path.exists(): skip`), deleting on failure gives free retry semantics — a subsequent run picks up the page as if it were never attempted.

The dry-run guard is respected: in dry-run mode the callback is not invoked and the file is never deleted.

### `description_quality` lint rule (Tier-1)

A new Tier-1 rule added to `scripts/lint/`. It enforces two constraints:

- The `description` frontmatter field must meet a minimum word count (currently five words).
- The `description` value must not be identical to the page title.

Both constraints fire as lint errors, not warnings, so they block a page from passing the Tier-1 gate. The rule is enabled by default on any host with `lint.tier1: default`.

### `_BootstrapProgress` (`scripts/orchestrator_runner.py`)

A small dataclass that atomically writes a per-page state record to `.engineering-docs-agent/bootstrap.progress.json` on every state transition (started, verified, skipped, failed). Writes are atomic: the helper writes to a temp file in the same directory then `os.replace`s it so a crash mid-write never leaves a partial JSON file. The progress file is gitignored and intended for operational visibility — you can `cat` it during a long bootstrap run to see which pages are in-flight and which have been accepted.

Three early-exit paths that can cause an under-count in the progress file are tracked as follow-up work and are not fixed in this PR.

## Verification sequence

For each candidate page, `run_bootstrap_core` now follows this sequence:

1. Check `target_path.exists()` — skip if true (idempotency, unchanged).
2. Call `dispatch_verified` with the page-author payload and a verification callback.
3. The callback calls `parse_frontmatter_strict` on the written file. Failure → delete file, return error.
4. The callback runs `description_quality` checks. Failure → delete file, return error.
5. On success, `_BootstrapProgress` records `verified` for the page.

Steps 3 and 4 run in the callback, inside `dispatch_verified`, before control returns to `run_bootstrap_core`. The orchestrator sees a clean success or a clean failure — it never sees a partially-accepted page.

## Test coverage

PR #50 added 34 tests, growing the suite from 559 to 593 passing. The new tests cover:

- `parse_frontmatter_strict` distinguishing absent vs. malformed frontmatter.
- `dispatch_verified` deleting the target file when the callback raises.
- `dispatch_verified` leaving the target file intact when the callback passes.
- `description_quality` triggering on short and title-equal descriptions.
- `_BootstrapProgress` atomic write behavior under simulated mid-write crash.

All tests use the fixture-driven dry-run path; the real Claude CLI dispatch is monkeypatched.

## Relationship to existing helpers

`parse_frontmatter` in `archive_indexes.py` is unchanged and continues to serve all callers that do not need error-mode discrimination. Before calling the strict variant anywhere else, `grep -rn parse_frontmatter_strict` to confirm you are reaching for the right function — the two have different return shapes on failure.
