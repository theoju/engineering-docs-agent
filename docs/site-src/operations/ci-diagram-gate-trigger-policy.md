---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/107
synthesized_into: []
doc_kind: architecture
---

# CI Diagram-Gate Trigger Policy

The `diagram-gate` job in `.github/workflows/docs.yml` validates that every page reachable from the published mkdocs site builds cleanly under strict mode. It is intentionally scoped to paths that affect the published output — running it on unrelated directories produces CI noise with no diagnostic value.

## Path triggers

The workflow's `on.pull_request.paths` block limits `diagram-gate` to changes under paths that influence the published site. As of PR #107, two directories are explicitly excluded:

- `docs/runbooks/**` — operator playbooks; consumed by humans, not by mkdocs.
- `docs/superpowers/**` — work-tracking artifacts (specs, plans, SDDs); also not published.

A PR that touches only files under either of these trees will not enqueue `diagram-gate`. All other paths in the repo retain their pre-existing trigger behavior.

If you add a new top-level directory that is also not published, add it to the `paths-ignore` block in `.github/workflows/docs.yml` before merging. Do not rely on the absence of an `on.push` trigger — `paths-ignore` is the correct knob for PR-scoped jobs.

## Docstring lint guard (CCE-87)

The CCE-80 release cycle surfaced a class of mkdocs-autorefs regressions: bare CLI flag syntax (`--FLAG VALUE` or `[--FLAG VALUE]`) in `scripts/*.py` docstrings causes WARNING-on-strict-build failures when mkdocs interprets the brackets as cross-reference anchors.

The new pytest lint at `tests/ci/test_docstring_flag_value_lint.py` catches this pattern at test time. It rejects any `scripts/*.py` docstring that contains bare flag syntax outside:

- Fenced code blocks (` ``` `).
- Inline backticks.
- reST `Usage::` literal blocks.

The test ships with a synthetic regression fixture and a self-check test so the rule cannot silently degrade. If you add a new CLI script under `scripts/`, wrap flag references in backticks or a `Usage::` block. The lint will tell you on the first `pytest` run if you miss one.

## Ordering constraint

CCE-84 promotes `diagram-gate` to a required branch-protection check via `gh api PUT`. CCE-84 must be applied **after** PR #107 is merged. Applying the branch-protection rule before the narrowed path triggers land means the gate would be required on runbook PRs that no longer enqueue it, producing permanently-blocked branches. The committed spec and plan under `docs/superpowers/` record this ordering explicitly.

CCE-88 upgrades the `/ship -f` regex in `~/.claude/skills/ship/lib/validate-git-cmd.sh` and is a separate follow-up unrelated to the trigger policy.

## Related tickets

| Ticket | Scope |
|--------|-------|
| CCE-85 | Narrow `diagram-gate` path triggers (this change) |
| CCE-87 | Docstring flag-syntax lint guard (this change) |
| CCE-84 | Promote `diagram-gate` to required branch-protection check (follow-up) |
| CCE-88 | `/ship -f` regex upgrade (follow-up, unrelated) |
