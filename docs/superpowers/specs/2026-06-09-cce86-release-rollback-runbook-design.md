---
title: "CCE-86 — release-ops runbook polish (rollback, two-clock SLA, misfire recovery)"
status: approved
date: 2026-06-09
ticket: CCE-86
---

# CCE-86 — release-ops runbook polish

## Problem

The v0.5.0 release execution surfaced operational knowledge that lives nowhere durable:

- Operators repeatedly **conflate two distinct release clocks** — the `release.yml`
  validation run (minutes) and the host-pickup latency (a full nightly cycle).
- There is no documented **rollback playbook** for a release tag, so a bad cut has
  no rehearsed recovery.
- There is no **tag-cut-misfire recovery** procedure for the case where
  `gh release create` succeeds but `release.yml` then fails.

CCE-86 was filed to add these to `docs/runbooks/cce80-host-migration.md`. But three
of the four asks are **release-process-generic** — they recur on every version cut —
while that runbook is a spent, one-time CCE-80/v0.5.0 migration artifact named after
a job that is already done. Parking reusable release knowledge there strands it where
no future release operator will look.

## Goal

Put the reusable release-day knowledge in a durable, version-agnostic home; add only
the migration-specific CHANGELOG step to the CCE-80 runbook; make the new runbook
discoverable; and ground every example in the actual v0.5.0 release.

## Locked decisions

1. **Scope = hybrid.** A new durable release runbook holds the three reusable
   sections (rollback, two-clock SLA, tag-cut-misfire recovery). The CCE-80 runbook
   gets the migration-specific CHANGELOG-update step plus a cross-link. (Chosen over
   "all four sections literally into the CCE-80 file" and "everything generic.")
2. **Location = `docs/runbooks/` + discoverability pointer.** The new runbook is a
   sibling of `cce80-host-migration.md` (maintainer-internal release ops; outside
   `docs_dir`, so no frontmatter contract, no Tier-1 lint, no `mkdocs --strict`
   gating). A one-line pointer in `CLAUDE.md`'s conventions makes it findable.
   (Chosen over publishing into `docs/site-src/operations/`, which would reproduce
   the documented ADIS cross-link `--strict` break, add lint friction on
   command-dense prose, and put maintainer-internal content in a user-facing site.)
3. **Verification = lightweight link-resolution test.** One pytest asserts the
   cross-links resolve (CCE-80 runbook → new runbook; CLAUDE.md pointer → new
   runbook; new runbook exists). Plus `mkdocs build --strict` for AC3 and the full
   suite. (Chosen over manual-only and over adding section-presence assertions.)

## Grounding facts (verified 2026-06-09)

- `release.yml` exists — it is **Clock 1** (release validation).
- v0.5.0 tag pushed `2026-06-04T15:33Z`; its `release.yml` run went green ~30s later.
  v0.5.0 itself did **not** misfire.
- Real **misfire precedent**: the `2026-05-27` `release.yml` run (PR #43 release
  attempt) **failed** — cited as the worked example for misfire recovery.
- Nightly cron is `7 7 * * *` (daily, 07:07 UTC) in both `templates/workflow-run.yml`
  and `.github/workflows/docs-agent-nightly.yml`. Therefore **Clock 2** (tag-pinned
  host pickup) is **up to ~24h**, the next daily tick — **not the "~60 min" stated in
  the ticket**. This spec corrects that figure; accuracy is the entire point of the
  two-clock section.

## Design

Four touch points. No runtime code; documentation plus one guard test.

### 1. New file — `docs/runbooks/release-and-rollback.md`

Generic, version-agnostic release-ops runbook. Three sections:

**Two-clock SLA framing.** Names the two waits operators conflate:

- _Clock 1 — release validation:_ `release.yml` live-tests, ~5–10 min after tag push.
- _Clock 2 — host pickup:_ tag-pinned hosts pick up the new ref at the next daily
  07:07 UTC nightly tick → up to ~24h. Main-tracking hosts pick up on their next
  nightly with no tag dependency.
- _Worked example (v0.5.0):_ tag pushed `2026-06-04T15:33Z`; `release.yml` green ~30s
  later (Clock 1); tag-pinned hosts eligible at the next 07:07 UTC tick (Clock 2).

**Rollback playbook.** `gh release delete <tag> --cleanup-tag --yes`, with:

- _Preconditions:_ when to roll back vs. cut a forward patch.
- _Post-rollback hygiene:_ main-tracking hosts self-heal on the next nightly;
  tag-pinned hosts need a downgrade PR (re-pin to the prior tag).
- v0.5.0 used as the concrete tag in examples.

**Tag-cut-misfire recovery.** When `gh release create` succeeds but `release.yml`
then fails: leave the tag in place, post a comment on the closing Jira ticket
describing the partial state for the next triage, and decide patch-vs-rollback by
severity. Cites the `2026-05-27` failure as the real precedent.

### 2. Edit — `docs/runbooks/cce80-host-migration.md`

In the post-merge gate area, add a **CHANGELOG-update step**: call out the
`CHANGELOG.md` entry as a release-day artifact, with a fill-in template line an
operator completes. Add a one-line cross-link: for rollback, SLA, and misfire
recovery, see `release-and-rollback.md` (same-directory relative link).

### 3. Edit — `CLAUDE.md`

One-line pointer in the release/merge conventions area to
`docs/runbooks/release-and-rollback.md` — the Option-C discoverability hook.

### 4. New test — `tests/docs/test_runbook_links.py`

Assert the cross-links resolve:

- `docs/runbooks/release-and-rollback.md` exists.
- The cross-link target referenced from `cce80-host-migration.md` resolves to an
  existing file.
- The `CLAUDE.md` pointer path resolves to an existing file.

Guards the one realistic long-term regression: a rename rotting the links.

## Verification

- The link-resolution pytest passes.
- `mkdocs build --strict` exits 0 (AC3 — trivially green; nothing enters the site).
- Full `python3 -m pytest` green.

## Acceptance-criteria mapping

- **AC1** (four operator-actionable sections) → the CHANGELOG step in the CCE-80 runbook plus the three sections in the new runbook.
- **AC2** (references the actual v0.5.0 release as a worked example) → the grounding
  facts above (tag timestamps, the green v0.5.0 run, the 2026-05-27 misfire
  precedent, the corrected ~24h Clock 2).
- **AC3** (`mkdocs build --strict` still passes) → verification step.

## Scope-outs (YAGNI)

- No release-runbook "framework" or templating.
- No changes to `release.yml` or any workflow.
- No per-host automation.
- Not published to the docs site (per locked decision 2).
- The CCE-80 runbook's existing per-host migration steps are untouched; only the
  CHANGELOG step and the cross-link are added.
