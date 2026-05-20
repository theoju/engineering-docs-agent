# engineering-docs-agent — Session Kickoff

> **Read this first when starting a new Claude Code session in this folder.**
> This document captures decisions, open questions, and reference pointers
> from the brainstorming session that originated this project.
> Origin: 2026-05-19, in the ADIS worktree right after merging PR #371 (ADIS-235).

---

## 1. The idea, in one paragraph

A reusable Claude Code plugin that watches a host repository's engineering
artifacts (Git commits, merged PRs, Jira issues, ADRs, specs, plans) and on a
configurable schedule (default: nightly) opens a PR against the host's docs
site containing:

1. **What's New** — a dated entry summarizing changes since the last successful
   run, prepended to a maintained `WHATS-NEW.md` (or a configurable history
   page).
2. **Doc updates** — new or modified pages in the host's docs site reflecting
   the identified changes (new APIs, changed behavior, new ADRs/specs that need
   weaving in, etc.).
3. **Notifications** — email and/or Slack summary of the run: what changed,
   what the agent updated, link to the PR.
4. **Gap detection** — flag PRs and Jira issues that look "non-trivial" but
   have no associated ADR/spec/plan, so humans can decide whether one is
   needed.

The plugin is **not ADIS-specific**. ADIS is consumer #1 and the reference
implementation, but the plugin must work for any project that follows the same
broad documentation pattern (audience lenses over a canonical core, with an
archive for ADRs/specs/plans).

---

## 2. Decisions made so far

### 2.1. Location & distribution → **Option A**

The plugin lives in **its own repository** (this one:
`~/Projects/engineering-docs-agent/`), distributed as a **Claude Code plugin**
(same model as `superpowers`, `pr-review-toolkit`, etc.). ADIS installs the
plugin and dogfoods it; ADIS does NOT host the plugin code.

- **Rejected: Option B** (build inside ADIS, extract later) — high risk of
  accidental ADIS-coupling; extraction would be painful.
- **Rejected: Option C** (own repo, but reference ADIS paths) — worst of both
  worlds; no plugin distribution, still hard-coded paths.

### 2.2. Authority model → **PR mode**

Every nightly run pushes to a branch (e.g. `docs-agent/2026-05-20`) and opens
a PR against the host repo's docs. **Humans review and merge.** No commit-direct
mode. The agent never mutates the docs main branch on its own.

- **Rejected: commit-direct mode** — unreviewed runs can rot the canonical
  site silently.
- **Rejected: hybrid (small mechanical → direct, prose → PR)** — added
  complexity (classifier) for marginal speed win; PR mode is fast enough when
  the PR auto-passes CI and humans batch-review.

### 2.3. MVP scope → **deferred**

The session ended before settling MVP scope. See open question Q1 below.

---

## 3. Open questions to resolve in the new session

These were going to be the next clarifying questions in the brainstorming flow.
Resume by re-invoking `/superpowers:brainstorming` and walking through them in
roughly this order:

### Q1. MVP scope (the next question to ask)

Which of the four outputs (§1 above) ship in v1?

- **Minimal (recommended):** What's New + doc updates only (2.1 + 2.3). Smallest
  end-to-end loop you can dogfood and iterate on. Email/Slack and gap
  detection ship in v2.
- **Minimal + notifications:** add email/Slack (2.2). Argument: notifying humans
  is what makes the PR usable in practice; without it, PRs pile up.
- **Full:** all four in v1. Bigger build, slower to first run; gap-detection
  heuristics ("non-trivial") often need real-run tuning.

### Q2. Source integrations scope for v1

- Git only (GitHub + GitLab? GitHub only?)
- Git + Jira
- Make Jira an opt-in plugin within the plugin (so non-Jira projects work)

### Q3. State storage

Where does "last successful run" state live? Options:

- A state file in the host repo (e.g. `.engineering-docs-agent/state.json`,
  committed). Pros: portable, auditable. Cons: every run touches state.
- A GitHub branch (e.g. `docs-agent/state`). Pros: no main-repo churn.
  Cons: another moving piece.
- Derived from the most recent What's New entry. Pros: zero state file.
  Cons: fragile if a run partially fails.

### Q4. Trigger model

- Pure cron (GitHub Actions scheduled workflow).
- Event-driven (webhook on PR merge to main).
- Both (cron baseline, event for "instant nightly").

### Q5. Setup-skill UX

The plugin ships with a one-time setup skill (the user explicitly asked for
this) that runs in the host repo and produces a config. Two flavors:

- **Interactive Q&A** — the skill asks the user questions and writes the
  config. Aligns with `superpowers:brainstorming` pattern.
- **Auto-discovery + propose** — the skill inspects the repo (looks for
  `.github/`, `pyproject.toml`, `mkdocs.yml`, Jira config in CI env, etc.),
  proposes a config, user reviews. Less typing; risk of wrong guesses.

### Q6. Gap-detection heuristics for "non-trivial"

What counts as a change that "should have" a spec/plan?

- LOC threshold (e.g. >200 lines)?
- Files touched (e.g. >5 files)?
- Subsystem heuristic (e.g. anything touching `backend/connectors/` or
  `backend/storage/` always counts)?
- LLM judgment per PR (most flexible, most expensive)?
- Combination?

### Q7. Doc-update authoring fidelity

When the agent writes new pages or edits prose, what guardrails keep voice
consistent with the host site?

- Read N recent pages from the same lens as voice samples?
- Read the host's `.claude/CLAUDE.md` for project conventions?
- Maintain a `docs-agent-voice.md` that the host project authors once?

### Q8. Notification channel design (when 2.2 lands)

- Email via what? (SES, SendGrid, plain SMTP from CI?)
- Slack via what? (Webhook URL stored as host-repo secret, or Slack app?)
- Per-recipient routing or single channel?

### Q9. Distribution mechanics

- Plugin registered with which Claude Code plugin marketplace?
- Versioning scheme (semver, calver)?
- Public vs private (start private, open-source if it stabilizes)?

---

## 4. Reference implementation: what to mine from ADIS-235

The plugin should generalize patterns from the ADIS work, not copy them.
These artifacts have generalizable value:

| Artifact                                                                                    | Location in ADIS                                                                      | Generalize as                                                                                                    |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| YAML front-matter schema (`status`, `sources`, `synthesized_into`)                          | `docs/site-src/archive/adrs/*.md` headers                                             | A spec the plugin enforces on archive pages                                                                      |
| Auto-index generator                                                                        | `scripts/generate_archive_indexes.py`                                                 | Plugin script, host config supplies promoted-slugs list                                                          |
| Footnote integrity verifier                                                                 | `scripts/verify_footnotes.sh`                                                         | Plugin-shipped script, host wires into its CI                                                                    |
| Playwright diagram verifier                                                                 | `scripts/verify_docs_diagrams.py`                                                     | Plugin-shipped (already generic-ish; needs host site-dir/source-dir as args, which it already accepts)           |
| Redirect-stub pattern                                                                       | 15 originating files replaced with 3-line stubs                                       | Plugin documents the pattern + provides a "promote ADR/spec" helper script                                       |
| Synthesized-into admonition (the mkdocs `!!! info` block injected at top of promoted pages) | Python snippet in PR #371, commit `24e001d`                                           | Plugin-shipped, runs on every nightly to keep breadcrumbs in sync                                                |
| Lens-over-canonical-core IA                                                                 | `docs/site-src/{portfolio,future-me,core,onboarding,archive}/`                        | Plugin templates/ directory provides a starter IA the setup skill can scaffold                                   |
| What's New entry format                                                                     | (not built yet in ADIS)                                                               | Plugin v1 deliverable; ADIS becomes consumer #1                                                                  |
| Doc-source map / drift hook                                                                 | `.claude/hooks/doc_drift.py` + `scripts/build_doc_source_map.py` from ADIS-228 design | Plugin generalizes: the hook fires when source files change, the agent reads accumulated drift state on next run |

**Read these for full context before implementing:**

- `/Users/theo/Projects/advanced-data-importer/docs/superpowers/specs/2026-05-19-adis-architecture-docs-historical-merge-design.md` — the historical-insight merge spec
- `/Users/theo/Projects/advanced-data-importer/docs/superpowers/plans/2026-05-19-adis-architecture-docs-historical-merge.md` — the 138-step implementation plan
- `/Users/theo/Projects/advanced-data-importer/docs/superpowers/specs/2026-05-18-adis-architecture-documentation-design.md` — the original architecture-docs spec (ADIS-228), with the lens-over-canonical-core IA design and the doc-drift-hook design
- ADIS PR #371 — the merged historical-insight merge work
- ADIS PR #370 — placeholder-prose removal (the immediate predecessor)

---

## 5. Out of scope (explicit)

To prevent scope creep when starting fresh:

- **Not a publishing platform.** The plugin opens PRs against the host's
  existing docs site (mkdocs, Docusaurus, whatever). It does not host or
  build the site itself — that's the host repo's job.
- **Not a docs linter.** Drift detection and footnote integrity are
  pre-existing tools the plugin reuses; new linters are out of scope unless
  required by a specific output.
- **Not a Jira/GitHub mirror.** The plugin reads from these systems but does
  not store or sync their data beyond what's needed for one run.
- **No content rewriting of pages the agent didn't author.** Human-authored
  pages are read-only unless explicitly listed in the config as
  "agent may edit."

---

## 6. How to resume in this folder

```bash
cd ~/Projects/engineering-docs-agent
claude
```

Opening message to Claude:

> "Resume the engineering-docs-agent brainstorming. Read KICKOFF.md first.
> The next question to settle is Q1 (MVP scope). Use the
> `/superpowers:brainstorming` skill to continue from there."

Once design questions are settled, the flow is:

1. `/superpowers:brainstorming` → write design spec to
   `docs/superpowers/specs/YYYY-MM-DD-engineering-docs-agent-design.md`.
2. `/superpowers:writing-plans` → write implementation plan.
3. `/superpowers:subagent-driven-development` → execute.
