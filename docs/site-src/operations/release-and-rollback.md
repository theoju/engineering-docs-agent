---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/123
synthesized_into: []
---

# Release & Rollback Operations

This page covers the operational mechanics of cutting a version tag, understanding the two-stage release timeline, rolling back a bad release, and recovering from a tag-cut misfire. The full runbook source lives in `docs/runbooks/release-and-rollback.md` — maintainer-internal ops intentionally kept outside the published `docs_dir` to avoid `mkdocs --strict` cross-link hazards.

## The two-clock release model

Releasing a new version involves two independent clocks. Confusing them leads to premature "it's not working" conclusions.

**Clock 1 — release.yml validation (~5–10 min).** When you push a version tag, GitHub fires the `release.yml` workflow. This validates the tag format, runs release checks, and creates the GitHub Release object. If `release.yml` fails, the release is not published — see [Tag-cut misfire recovery](#tag-cut-misfire-recovery) below.

**Clock 2 — host pickup (up to ~24 h).** Tag-pinned host repos pick up the new version at their next scheduled nightly tick: 07:07 UTC by default. A host that installed at `v0.5.0` and has not bumped its config will not see `v0.6.0` until the nightly runs and the operator merges the resulting docs-agent PR. This is expected behavior, not a bug.

The Clock 2 window is driven entirely by the host's cron schedule. Do not cite a ~60 min SLA — the actual upper bound is ~24 h.

## Rolling back a bad release

Before you run anything, decide which rollback path applies:

| Host type | Effect of deleting the tag |
|---|---|
| Tag-pinned | Host reverts to previous pinned tag at its next nightly tick |
| Main-tracking | Host already follows HEAD; tag deletion has no effect on pickup |

For tag-pinned hosts, rolling back stops future propagation. Hosts that already picked up the bad tag need a follow-up patch release pointing to a known-good state — deleting the tag does not retroactively un-install it.

### Rollback command

```bash
gh release delete <tag> --cleanup-tag --yes
```

The `--cleanup-tag` flag deletes both the GitHub Release object and the underlying git tag. The `--yes` flag skips the interactive prompt — omit it if you want a confirmation step.

### Post-rollback hygiene

After deletion:

1. Verify the tag is gone: `git fetch --tags && git tag | grep <tag>` should return nothing.
2. For tag-pinned hosts that already picked up the bad tag, cut a patch release (`<major>.<minor>.<patch+1>`) pointing to the last known-good commit, then notify affected operators.
3. Update `CHANGELOG.md` with a retraction entry so the removal is discoverable in history.

## Tag-cut misfire recovery

A misfire is when `gh release create` exits 0 (the tag and GitHub Release exist) but `release.yml` subsequently fails — a partial release state.

This scenario was first observed on 2026-05-27 (PR #43): `release.yml` fires on `push: tags`, not on PR merge. A tag pushed before CI finished produced a Release object that pointed to an unvalidated commit.

**Recovery steps:**

1. Delete the release immediately: `gh release delete <tag> --cleanup-tag --yes`.
2. Identify and fix the root cause in `release.yml` or the tagged commit.
3. Re-cut the tag only after `release.yml` passes on a clean run against the fixed state.
4. Do not leave a partial release visible on the GitHub Releases page while investigating — it will be picked up by any host whose nightly runs during your investigation window.

## Related runbooks

The full internal runbooks are at:

- `docs/runbooks/release-and-rollback.md` — complete playbook with decision tables and edge cases
- `docs/runbooks/cce80-host-migration.md` — one-time CCE-80 host migration steps (cross-linked from the release runbook)
