---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/50
  - https://github.com/theoju/engineering-docs-agent/pull/135
synthesized_into: []
doc_kind: architecture
description: The four CCE-38 bootstrap safeguards that catch bad authored artifacts — strict frontmatter parsing, prose-contamination detection, post-write validation, and checklist-bypass recovery.
source_files:
  - scripts/orchestrator_runner.py
last_reviewed: "2026-06-22"
---

# Bootstrap fail-fast mechanisms

The C2 bootstrap pipeline (CCE-38) adds four structural safeguards that catch bad artifacts before they reach the published site. Before this work, the pipeline trusted `page-author`'s `ok: true` signal without independently verifying the written file — allowing bad YAML, missing frontmatter, and thin descriptions to slip through undetected.

Three uncaptured intervention patterns from the CCE-15/CCE-36 release retrospective drove this work: checklist-bypass recovery, prose-contamination detection, and post-write artifact validation. CCE-38 formalises each as a structural check rather than an ad-hoc retry.

## parse_frontmatter_strict

`scripts/orchestrator_runner.py` previously treated a YAML parse failure the same as absent frontmatter — both returned `None` and the pipeline continued silently. `parse_frontmatter_strict` raises a distinct `FrontmatterParseError` on malformed YAML, so the orchestrator surfaces the exact failure instead of masking it as a missing-header case.

The distinction matters operationally: absent frontmatter is often recoverable (the agent writes a fresh header block on retry), but a YAML parse error means the artifact is corrupt and re-running without a fix produces the same broken output.

## description_quality lint rule

A new `description_quality` rule is registered as a Tier-1 default alongside the existing six rules. It blocks any page where the `description` frontmatter field is absent, empty, or below a configurable minimum token count.

The rule fires during the post-write lint pass — after `dispatch_verified` confirms the artifact exists but before the PR is opened. Pages that fail are added to the partial-reasons list and flagged in the Slack/email digest rather than published silently with a thin description.

Because it is Tier-1, it is **on by default**. Hosts that need to disable it must explicitly set `lint.tier1.description_quality: false` in their config.

## dispatch_verified

`dispatch_verified` wraps `dispatch_validated` with a post-write check callback. After `page-author` returns `ok: true`, the orchestrator invokes the callback — by default, it reads the written file and confirms the frontmatter parses cleanly and is non-empty.

This closes the gap where `page-author` could report success while writing prose-contaminated YAML or an otherwise unloadable artifact. The callback is injectable: unit tests substitute a lightweight in-memory checker without touching the filesystem, keeping the test suite fast and fully mocked.

## \_BootstrapProgress

`_BootstrapProgress` writes an atomic per-page progress file to a `.bootstrap-progress/` directory under the run's working tree. Each record is written after a successful per-page dispatch and checked at startup on re-entry.

If the same run hour is re-entered — for example, after a transient CI failure — the orchestrator skips pages that already have a completed progress record rather than re-dispatching them. This makes same-hour re-runs safe and enables mid-run recovery without duplicating work or overwriting a correctly-authored page.

Progress files are ephemeral and gitignored. The docs-agent PR contains only the authored pages; the `.bootstrap-progress/` directory never appears in the branch.

## Failure modes addressed

The four mechanisms together close the patterns identified in the CCE-15/CCE-36 retrospective:

| Pattern                        | Mechanism                               |
| ------------------------------ | --------------------------------------- |
| Checklist-bypass recovery      | `_BootstrapProgress` re-run safety      |
| Prose-contamination detection  | `dispatch_verified` post-write callback |
| Post-write artifact validation | `parse_frontmatter_strict`              |
| Thin-description bypass        | `description_quality` Tier-1 rule       |

None of these are breaking changes. Existing hosts gain the `description_quality` rule in their Tier-1 set automatically; all other behaviour is additive.
