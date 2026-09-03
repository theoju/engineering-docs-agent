---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/223
synthesized_into: []
doc_kind: decision
---

# CCE-150: the blind-run-detection abandon call, reversed nine minutes later

> **This page is a decision-history record, not a description of current behavior.** If you want the actual, currently-shipped design for blind-run detection, read the CCE-144 entry in `CLAUDE.md` and its spec at `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`. Nothing below describes what the runner does today.

## What happened

On 2026-08-14 an operator instructed a session to abandon the unmerged `feat/CCE-144-blind-run-detection` branch, on the premise that its work was stranded and unreachable. PR #223 archived the CCE-144 plan and spec under that premise, stamping them as abandoned and closing ticket CCE-150.

The premise was wrong. The branch had in fact been pushed, and its commits were not unreachable. The operator reversed the abandon decision almost immediately — within nine minutes of PR #223 merging — and the CCE-144 implementation itself merged to `main` as PR #224. PR #223's own title and body flag this explicitly: every factual claim below its warning banner is marked false as of 2026-08-14T07:25:23Z, superseded by PR #224.

So the sequence, in order, was:

1. PR #223 merges, archiving the blind-run-detection design as abandoned and closing CCE-150.
2. Nine minutes later, PR #224 merges the same implementation to `main`.

Everything PR #223 asserted about the design being unimplemented was true only for those nine minutes, and false for the entire time since.

## Why this page exists

PR #223 is now only a historical artifact: a record of a call that got made and then unmade almost immediately. Anyone who finds PR #223 or ticket CCE-150 by searching history, without also finding PR #224, would reasonably conclude that blind-run detection was never built. It was — under CCE-144, on `main`, since 2026-08-14.

This page exists to close that gap for future readers. It does not add architecture or operations content of its own: the CCE-144 behavior it would otherwise describe is already covered by the CLAUDE.md CCE-144 entry and by `docs/superpowers/specs/2026-08-13-cce144-blind-run-detection-design.md`, both of which are current.

## What to do if you land here

Don't treat PR #223's body, or the archived plan/spec it points at, as authoritative for what the docs-agent runner does. Go to the CCE-144 spec and the CLAUDE.md entry instead — those describe the shipped `blind` vs. `degraded` split, the three consumers that read the flag, and the incident that motivated it. Treat CCE-150 as closed-in-error: the ticket is done, but not for the reason its closure said.
