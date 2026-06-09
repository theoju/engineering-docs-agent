---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/107
synthesized_into: []
doc_kind: decision
---

# Decision: Docstring lint guard for bare CLI flag syntax (CCE-87)

**Date:** 2026-06-04
**Tickets:** CCE-85, CCE-87
**PR:** [#107](https://github.com/theoju/engineering-docs-agent/pull/107)

## Context

During the CCE-80 release cycle, `mkdocs build --strict` started emitting autorefs warnings on docstrings that contained bare CLI flag syntax — patterns like `--FLAG VALUE` or `[--FLAG VALUE]` outside any code context. These are not valid mkdocs-autorefs cross-references; the build treats them as broken links and fails in strict mode.

The problem was caught at build time, not test time. That meant a developer could write a docstring, push, and only discover the regression when CI ran the full site build.

The same cycle also revealed that `diagram-gate` was firing on PRs that touched only `docs/runbooks/**` or `docs/superpowers/**` — directories that hold operator playbooks and work-tracking artifacts with no effect on the published mkdocs site. Every such PR produced unnecessary CI noise.

## Decision

**Proactively reject the docstring syntax pattern at pytest time, not mkdocs build time.**

A new lint test (`tests/ci/test_docstring_flag_value_lint.py`) scans every `scripts/*.py` docstring and fails if it finds `--FLAG VALUE` or `[--FLAG VALUE]` outside a fenced code block, inline backtick, or reST `Usage::` literal block. The rule is paired with:

- A synthetic regression fixture that deliberately contains the banned pattern, so the rule cannot go green on an empty scanner.
- A self-check test that asserts the fixture is caught, so the rule cannot silently degrade if the pattern-matching logic is later weakened.

**Narrow the `diagram-gate` path filter** in `.github/workflows/docs.yml` to exclude `docs/runbooks/**` and `docs/superpowers/**`. Those directories do not affect the published site, so triggering the gate on them is pure noise.

## Why this approach

Catching the pattern at test time is cheaper than at build time. `pytest` runs in seconds; `mkdocs build --strict` against a full site takes longer and requires the full mkdocs dependency chain. The earlier the catch, the shorter the feedback loop.

The synthetic fixture + self-check pair is a guard against rule rot. A lint rule without a failing fixture is just documentation — it can silently stop matching without any test going red. Both guards must pass for the rule to be considered active.

The path filter fix is mechanical. The `diagram-gate` job exists to catch broken links and diagram regressions in the published site; `docs/runbooks/` and `docs/superpowers/` are not published paths, so they should never have been in scope.

## What this does not cover

**CCE-84** (promoting `diagram-gate` to a required branch-protection check via `gh api PUT`) and **CCE-88** (`/ship -f` regex upgrade in `~/.claude/skills/ship/lib/validate-git-cmd.sh`) are explicit follow-ups. They are tracked in the committed spec/plan docs under `docs/superpowers/` and are not part of this change.

This PR must be merged before CCE-84 is applied — CCE-84 promotes `diagram-gate` to required, and the narrowed trigger must be in place first so that runbook-only PRs are not blocked by a required check they can never satisfy.

## Files changed

- `.github/workflows/docs.yml` — path trigger exclusions for `docs/runbooks/**` and `docs/superpowers/**`
- `tests/ci/test_docstring_flag_value_lint.py` — new lint rule, synthetic fixture, self-check
- `docs/superpowers/` — consolidating spec and implementation plan for the CCE-77/CCE-80 cycle
