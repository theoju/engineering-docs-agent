# Release & Rollback Runbook

Version-agnostic operational guide for cutting, validating, rolling back, and
recovering a release of the engineering-docs-agent plugin. Examples use `v0.5.0`
(cut 2026-06-04) as the worked case.

For the one-time CCE-80 host-migration steps, see
[`cce80-host-migration.md`](cce80-host-migration.md).

## The two release clocks

Cutting a release starts two independent clocks. Operators repeatedly conflate
them — do not. "The release passed" (Clock 1) does not mean "the hosts have it"
(Clock 2).

| Clock                      | What you are waiting on                                                                                                    | Typical duration                   | How to check                                                                   |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------ |
| **1 — release validation** | `release.yml` live-tests run after the tag is pushed                                                                       | ~5–10 min                          | `gh run watch --workflow release.yml`                                          |
| **2 — host pickup**        | Hosts run the new code on their next nightly tick — automatically if main-tracking, only after a pin-bump PR if tag-pinned | up to ~24h once the ref is current | `gh run list --repo theoju/<host> --workflow docs-agent-nightly.yml --limit 1` |

Notes:

- **A tag-pinned host does NOT auto-upgrade.** Its plugin checkout is frozen at
  whatever `ref: vX.Y.Z` its `.github/workflows/docs-agent-nightly.yml` carries (the
  template default in `templates/workflow-run.yml` is a pinned tag). It keeps running
  that version every nightly until someone merges a **pin-bump PR** changing `ref:` to
  the new tag. The cron only governs _when_ an already-current pin runs — it never
  changes the pin. So for a tag-pinned host, Clock 2 = pin-bump PR + the next 07:07 UTC
  tick, not the tick alone.
- **A main-tracking host auto-upgrades.** A host whose checkout uses `ref: main` (or
  that was installed via `claude plugin update`) picks up the latest `main` commit on
  its next nightly with no pin change — Clock 2 is then purely the cron wait. The
  currently-onboarded hosts (`advanced-data-import-system`, `claude-code-self-assessment`)
  are configured this way, so they pick up a release automatically once it lands on `main`.
- **Clock 2 is daily, not hourly.** The nightly cron is `7 7 * * *` (07:07 UTC) in
  `templates/workflow-run.yml` — worst case ~24h from a current ref to the run.

**Worked example — v0.5.0:**

- Tag pushed `2026-06-04T15:33Z`; `release.yml` went green ~30s later — Clock 1
  closed in under a minute on that cut (the ~5–10 min figure is the upper bound when
  the live-tests exercise the full matrix).
- The onboarded hosts track `main`, so they picked up the released commit at the next
  07:07 UTC tick — Clock 2. (A tag-pinned host would instead have needed a pin-bump PR
  to `v0.5.0` first.)

## Rollback playbook

Use when a cut release is bad enough that hosts must not pick it up.

### Decide first: roll back vs. cut a forward patch

| Situation                                                                 | Action                                                                                          |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Tag is broken and **no host has picked it up yet** (still within Clock 2) | **Roll back** — delete the tag before the next 07:07 UTC tick.                                  |
| Hosts have **already** picked it up, or the fix is small                  | **Cut a forward patch** (e.g. `v0.5.1`). Rolling back a consumed tag strands hosts mid-version. |

### Roll back a tag

```bash
gh release delete <tag> --cleanup-tag --yes   # e.g. gh release delete v0.5.0 --cleanup-tag --yes
gh release view <tag> || echo "confirmed deleted"  # deleted: exits non-zero, "release not found" on stderr
```

`--cleanup-tag` deletes the underlying git tag as well as the GitHub release; `--yes`
skips the confirmation prompt.

### Post-rollback hygiene

- **Main-tracking hosts** self-heal: their next nightly pulls `main`, which no longer
  references the deleted tag. No action needed.
- **Tag-pinned hosts** need a **downgrade PR** re-pinning `ref:` in their
  `.github/workflows/docs-agent-nightly.yml` to the prior good tag. Until that lands,
  their plugin-vendoring checkout step fails (the tag is gone).
- **Post a comment on the closing Jira ticket** recording the rollback and the reason.

## Tag-cut-misfire recovery

The misfire: `gh release create` **succeeds**, but `release.yml` then **fails** (for
example, live-tests red). The tag exists; the release is unvalidated.

Real precedent: the 2026-05-27 misfire during the PR #43 release attempt — the `v*`
tag push triggered a `release.yml` run (it runs `on: push: tags`) that failed this
way. (v0.5.0 itself did not — its run was green ~30s after the tag.)

Recovery:

1. **Leave the tag in place.** Do not reflexively delete it — deleting mid-validation
   destroys the audit trail and confuses any host that already polled.
2. **Post the partial state on the closing Jira ticket:** "Tag `<tag>` cut at
   `<time>`; `release.yml` run `<id>` failed at `<step>`. Validation incomplete." This
   leaves the next triager a visible breadcrumb on a still-open concern.
3. **Decide by severity:**
   - Live-tests red for an **environmental/flaky** reason → re-run `release.yml`
     (`gh run rerun <id>`); no new tag needed.
   - Live-tests red for a **real defect** → cut a forward patch with the fix
     (`v0.5.1`), or roll back per the playbook above if no host has picked up yet.
