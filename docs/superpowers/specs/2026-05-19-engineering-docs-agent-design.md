---
status: approved
date: 2026-05-19
sources:
  - KICKOFF.md
  - Brainstorming session 2026-05-19
synthesized_into: []
---

# engineering-docs-agent — Design Spec

## 1. Summary

A reusable Claude Code plugin that watches a host repository's engineering
artifacts (Git commits, merged PRs, Jira issues, ADRs, specs, plans) and on a
cron + event-driven cadence opens a PR against the host's docs site
containing:

1. **What's New** — a dated entry summarizing changes since the last
   successful run, prepended to a configurable history page.
2. **Doc updates** — new or modified pages reflecting identified changes.
3. **Notifications** — Slack and/or email digest of each run.
4. **Gap detection** — flags PRs/Jira issues that look "non-trivial" but have
   no associated ADR/spec/plan.
5. **Publish verification** — after a docs-agent PR merges, verifies the
   host's downstream build pipeline succeeded and pages are live.

The plugin is **not host-specific**. ADIS
(`~/Projects/advanced-data-importer`) is consumer #1 and the reference
implementation; the plugin must work for any project following the same
broad documentation pattern (audience lenses over a canonical core, with an
archive for ADRs/specs/plans).

## 2. Goals

- **Atomic correctness.** State and content advance together. The agent
  never claims to have covered changes humans haven't seen.
- **Cost discipline.** LLM tokens spent only where judgment is required.
- **Testability.** Every subagent has a structured output schema; every
  lint rule is a standalone script with unit tests.
- **Adoption friction = zero new files required.** A host installs the
  plugin, runs the setup skill, gets a working nightly run.
- **Context-rot resistance.** Each subagent has a narrow tool allowlist
  and a focused input/output contract.

## 3. Non-goals (out of scope for v1)

- Owning the docs publishing pipeline. Host's existing `mkdocs build`,
  Docusaurus deploy, etc. continues to run on PR merge.
- Mirroring Jira/GitHub data. The plugin reads from these systems each run;
  it does not persist them beyond per-run cursors.
- Rewriting human-authored pages. The agent edits only paths declared as
  agent-editable in config, or pages it created itself.

## 4. Decisions (from brainstorming)

| #    | Question         | Decision                                                                                                                                                       |
| ---- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1   | MVP scope        | Full (What's New + doc updates + notifications + gap detection + publish verification)                                                                         |
| Q2   | Sources          | Git always-on; Jira opt-in module                                                                                                                              |
| Q3a  | State storage    | Committed `.engineering-docs-agent/state.json`, advances in the same PR as doc changes                                                                         |
| Q3b  | Open-PR handling | Append commits to existing open PR; state advances on merge                                                                                                    |
| Q4   | Trigger          | Cron + `pull_request.closed` event hybrid, debounced via Actions concurrency group                                                                             |
| Q5   | Setup UX         | Hybrid setup skill: auto-discover what's inferable, ask what isn't                                                                                             |
| Q6   | Gap heuristic    | Tiered: subsystem allowlist → size filter → LLM judgment; dismissed-flag memory in state                                                                       |
| Q7   | Voice            | Layered: few-shot from lens (always) + `.claude/CLAUDE.md` (always, if present) + `docs-agent-voice.md` override (optional)                                    |
| Q8a  | Transports       | Slack webhook + email SMTP, independently configurable                                                                                                         |
| Q8b  | Routing          | Single channel/recipient per transport                                                                                                                         |
| Q9a  | Distribution     | Self-hosted marketplace from this repo                                                                                                                         |
| Q9b  | Versioning       | Semver, starting at `v0.1.0`                                                                                                                                   |
| Q9c  | Visibility       | Private at launch; open-source when stable                                                                                                                     |
| Lint | Lint rules       | Tier 1 default-on (block page on fail), Tier 2 opt-in (block page on fail), Tier 3 advisory (warn only); standalone scripts hosts can also run in their own CI |
| Pub  | Publish          | Agent opens PR; host pipeline builds/deploys on merge; agent verifies post-merge via separate workflow                                                         |

## 5. Architecture

### 5.1. Plugin layout

```
engineering-docs-agent/
├── .claude-plugin/
│   └── plugin.json
├── marketplace.json
├── agents/
│   ├── source-collector.md
│   ├── pr-summarizer.md
│   ├── gap-detector.md
│   ├── page-author.md
│   ├── content-validator.md
│   ├── publish-verifier.md
│   └── notifier.md
├── skills/
│   ├── engineering-docs-agent/
│   │   └── SKILL.md            # Runtime orchestrator
│   └── engineering-docs-agent-setup/
│       └── SKILL.md            # One-time host-side setup
├── templates/
│   ├── workflow-run.yml        # Main authoring workflow
│   ├── workflow-verify.yml     # Post-merge verification workflow
│   ├── config.example.yml      # Example host config
│   ├── glossary.example.yml    # Example terminology glossary
│   └── lens-ia/                # Starter lens IA scaffold
├── scripts/
│   ├── lint/
│   │   ├── frontmatter_schema.py
│   │   ├── internal_links.py
│   │   ├── markdown_hygiene.py
│   │   ├── footnotes.sh        # Reused from ADIS
│   │   ├── diagrams.py         # Reused from ADIS
│   │   ├── framework_build.py
│   │   ├── stub_redirect.py
│   │   ├── banned_phrases.py
│   │   ├── ai_tells.py
│   │   ├── terminology.py
│   │   ├── second_person.py
│   │   ├── paragraph_length.py
│   │   ├── reading_grade.py
│   │   ├── sentence_variance.py
│   │   ├── duplicate_content.py
│   │   └── lint_runner.py
│   └── archive_indexes.py      # Reused from ADIS, generalized
├── tests/
│   ├── lint/                   # Per-rule unit tests
│   ├── orchestrator/           # Pipeline integration tests with fake source-collector
│   └── fixtures/               # Sample host repos, PRs, config files
└── docs/
    └── superpowers/
        ├── specs/
        └── plans/
```

### 5.2. Subagents (7 total)

Each subagent is defined as `agents/<name>.md` with frontmatter declaring its
tool allowlist and a structured input/output contract.

| Subagent            | Job                                                                                                                                                       | Tools                                         | Returns                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- | --------------------------------------------------------------------------- |
| `source-collector`  | Given `(last_sha..HEAD)` window and host config, fetch merged PRs (title, body, files, stats, linked Jira keys); fetch linked Jira issues if Jira enabled | Bash (`gh`), WebFetch (Jira API), Read        | `{ prs: [...], jira_issues: [...] }`                                        |
| `pr-summarizer`     | Given one PR + its Jira context, summarize the change                                                                                                     | Read                                          | `{ what_changed, why, breaking, doc_targets: [{lens, action, page_hint}] }` |
| `gap-detector`      | Given one PR + config (allowlist, size thresholds, dismissed-flag set), judge if spec/plan should exist                                                   | Read                                          | `{ needs_spec: bool, reasoning, confidence }`                               |
| `page-author`       | Given lens, action, page hint, input summaries, voice samples, write or edit page content                                                                 | Read (voice samples, target page), Write/Edit | `{ path, diff_summary }`                                                    |
| `content-validator` | Run lint suite (Tier 1 default + Tier 2 opt-in + Tier 3 advisory) on authored/edited pages per host config                                                | Bash, Read                                    | `{ passed: [...], failed: [{ path, rule, message, severity }] }`            |
| `publish-verifier`  | After docs-agent PR merges, poll host's build workflow, then fetch changed URLs and verify content is live                                                | Bash (`gh`, `curl`), WebFetch                 | `{ verified: [...], failed: [...] }`                                        |
| `notifier`          | Given run digest (and optionally a verification digest), compose and post Slack message + email                                                           | Bash (`curl`, SMTP action)                    | `{ slack_ok, email_ok, errors }`                                            |

### 5.3. Pipelines

#### 5.3.1. Main authoring pipeline (cron + `pull_request.closed`)

```
[engineering-docs-agent orchestrator skill, invoked by Actions]
  load .engineering-docs-agent/state.json + .engineering-docs-agent/config.yml
       │
       ▼
  window = (state.last_successful_run.head_sha .. HEAD)
       │
       ▼
  ┌─[ source-collector ]──────► { prs, jira_issues }
  │
  ▼
  ┌─[ pr-summarizer × N (parallel) ]──────► [ summaries ]
  │
  ▼
  aggregate doc_targets → per-lens authoring batches
       │
       ▼
  ┌─[ page-author × batches (parallel across lenses, serial within lens) ]──► [ written files ]
  │
  ▼
  ┌─[ content-validator ]──────► { passed, failed }
  │   on Tier 1 fail: drop that page change, log, surface in notification
  ▼
  ┌─[ gap-detector × N (parallel, skip dismissed) ]──────► [ verdicts ]
  │
  ▼
  prepend What's New entry → update state.json
       │
       ▼
  open or append-commit to docs-agent/YYYY-MM-DD PR
       │
       ▼
  ┌─[ notifier ]──────► Slack post + email
```

Concurrency notes:

- `pr-summarizer`, `gap-detector`, `page-author` (cross-lens) fan out in parallel.
- `page-author` within a single lens serializes (avoid two authors editing the same page).
- `state.json` write, PR ops, and `notifier` are serial after fan-in.
- Actions concurrency group: `docs-agent-${branch}` cancels in-progress runs when a newer event fires (debouncing).
- Recursion prevention: the main workflow's `pull_request.closed` trigger filters out branches matching `docs-agent/*`, so a docs-agent PR merging does not itself trigger a new authoring run.

#### 5.3.2. Verify pipeline (on `pull_request.closed` of `docs-agent/*` with `merged=true`)

```
[verify-publish workflow]
  parse merged PR → list of changed page paths
       │
       ▼
  poll host build workflow → wait for "success" or timeout
       │
       ▼
  ┌─[ publish-verifier ]──────► { verified, failed }
  │
  ▼
  ┌─[ notifier ]──────► ✅ Published / ⚠️ Discrepancy follow-up
```

The two workflows are decoupled: the main authoring run completes when the
PR is opened, regardless of how long humans take to review. The verify
workflow is a separate, idempotent unit triggered by the merge event.

### 5.4. Configuration shape

`.engineering-docs-agent/config.yml` in the host repo, produced by the setup
skill, committed alongside the docs.

```yaml
docs:
  framework: mkdocs # auto-discovered
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: # paths the agent may edit
    - docs/site-src/core/**
    - docs/site-src/archive/**
    - docs/site-src/whats-new.md
  lens_paths:
    core: docs/site-src/core
    archive: docs/site-src/archive
    onboarding: docs/site-src/onboarding

sources:
  git:
    host: github
  jira:
    enabled: true
    project_keys: [ADIS]
    base_url: https://acme.atlassian.net

trigger:
  cron: "0 7 * * *"
  on_pr_merge: true

gap_detection:
  allowlist_paths:
    - backend/connectors/**
    - backend/storage/**
  size_filter:
    min_loc: 50
    min_files: 3

voice:
  custom_voice_file: docs-agent-voice.md # optional

lint:
  tier1: default # all default-on
  tier2:
    banned_phrases: ["simply", "obviously", "just"]
    ai_tells: true
    voice_consistency: true
    terminology_glossary: docs-agent-glossary.yml # optional file
    second_person_consistency: true
    paragraph_max_words: 150
  tier3:
    reading_grade_range: [8, 12]
    sentence_variance: true
    duplicate_detection: true

publishing:
  base_url: https://docs.acme.com
  build_workflow: deploy-docs.yml
  url_map_rule: standard # path → URL convention
  verify_timeout_seconds: 600

notifications:
  slack:
    enabled: true
    webhook_url_secret: SLACK_WEBHOOK_URL
  email:
    enabled: true
    smtp_server_secret: SMTP_SERVER
    smtp_user_secret: SMTP_USER
    smtp_password_secret: SMTP_PASSWORD
    from_address: docs-agent@acme.com
    recipients: [docs@acme.com]
```

### 5.5. State shape

`.engineering-docs-agent/state.json`, committed in each docs PR.

```json
{
  "version": "1",
  "last_successful_run": {
    "completed_at": "2026-05-19T07:03:21Z",
    "head_sha": "abc123...",
    "pr_number": 142
  },
  "current_run": {
    "started_at": "2026-05-20T07:00:00Z",
    "head_sha": "def456...",
    "partial": false,
    "partial_reasons": []
  },
  "dismissed_gap_flags": {
    "owner/repo#138": "dismissed by @theo 2026-05-15: refactor, no behavior change"
  },
  "cursors": {
    "jira_last_updated": "2026-05-19T06:58:00Z"
  }
}
```

## 6. Lint rules

### 6.1. Tier 1 — Default-on, blocks page on failure

| Rule                 | What it checks                                                                                     |
| -------------------- | -------------------------------------------------------------------------------------------------- |
| `frontmatter_schema` | Required YAML fields present (`status`, `sources`, `synthesized_into`); types valid                |
| `internal_links`     | All internal Markdown and wiki-style links resolve to files; anchors resolve                       |
| `markdown_hygiene`   | Code fences have language tags; heading hierarchy valid (no h3 without h2); no trailing whitespace |
| `footnotes`          | All `[^n]` refs have definitions, no orphans (reused: `verify_footnotes.sh`)                       |
| `diagrams`           | Mermaid/Playwright diagrams parse and render (reused: `verify_docs_diagrams.py`)                   |
| `framework_build`    | `mkdocs build --strict` (or Docusaurus equivalent) succeeds for changed pages                      |
| `stub_redirect`      | Promoted-archive pages keep the 3-line stub format per config                                      |

### 6.2. Tier 2 — Opt-in, blocks page on failure

| Rule                | What it checks                                                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------------ |
| `banned_phrases`    | Configurable list per host                                                                                   |
| `ai_tells`          | Em-dash density above threshold; filler words ("robust", "comprehensive", "seamless"); list-of-three overuse |
| `voice_consistency` | LLM check: page matches voice samples from the same lens                                                     |
| `terminology`       | Configurable glossary enforces canonical terms                                                               |
| `second_person`     | If `you` appears, page consistently second-person                                                            |
| `paragraph_length`  | Configurable max paragraph word count                                                                        |

### 6.3. Tier 3 — Advisory, warns only

| Rule                | What it checks                                      |
| ------------------- | --------------------------------------------------- |
| `reading_grade`     | Flesch-Kincaid grade level outside configured range |
| `sentence_variance` | Pages with overly uniform sentence lengths          |
| `duplicate_content` | Cross-page near-duplicates                          |

### 6.4. Integration

Each rule is a standalone script in `scripts/lint/<rule>.py` (or `.sh`) with
a uniform CLI:

```
scripts/lint/<rule>.py --config <path> --paths <file>... [--json]
```

Exit code 0 = pass; 1 = block-severity failure; 2 = warn-severity failure.
JSON output (when `--json` set) emits `{ rule, severity, results: [...] }`.

`scripts/lint/lint_runner.py` reads `config.yml`, selects enabled rules,
runs them, aggregates results into the schema returned by
`content-validator`. Hosts can also invoke `lint_runner.py` directly in
their own CI on human-authored PRs.

## 7. Setup skill UX

`engineering-docs-agent-setup` is a Claude Code skill installed with the
plugin. The user runs it once in their host repo. Behavior:

1. **Auto-discover** (no LLM cycles):
   - Docs framework: presence of `mkdocs.yml` / `docusaurus.config.js` / `package.json`.
   - Docs source dir: framework convention (`docs/`, `docs/site-src/`, etc.).
   - CI provider: presence of `.github/workflows/` / `.gitlab-ci.yml`.
   - Jira: presence of `JIRA_*` env vars in CI configs or `.env.example`.
   - Lens IA: scan `docs/site-src/*` for top-level directories.
   - Allowlist candidates: directories matching `backend/`, `core/`, `auth/` heuristics.
2. **Ask the user only** (multiple-choice where possible):
   - Slack webhook secret name (skip if Slack disabled).
   - Email SMTP secret names + recipient list (skip if email disabled).
   - Voice preferences: use few-shot only / add CLAUDE.md / create voice file.
   - Tier 2 lint rules to enable (opt-in per rule).
   - Terminology glossary file: skip / create blank / point to existing.
3. **Propose config**: emit `.engineering-docs-agent/config.yml` and show diff.
4. **Write files** on user confirmation:
   - `config.yml`
   - Empty `state.json` with `version: "1"`.
   - `.github/workflows/docs-agent-run.yml` (from template).
   - `.github/workflows/docs-agent-verify.yml` (from template).
   - `docs-agent-glossary.yml` if requested.

The skill ships with a `--dry-run` flag that emits the proposed config to
stdout without writing.

## 8. Error handling

| Failure mode                                 | Behavior                                                                                                                                                              |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Subagent crash/timeout                       | Orchestrator catches; marks `state.current_run.partial=true` with a `partial_reasons` entry; continues independent steps; PR body shows "⚠️ Partial run" with details |
| Source API rate limit                        | Exponential backoff inside `source-collector`; if exhausted, return partial set and add reason                                                                        |
| Page-author content fails Tier 1 lint        | Drop that page change, surface in notification; PR continues without that page                                                                                        |
| Page-author content fails Tier 2 lint        | Drop that page change, surface in notification; PR continues                                                                                                          |
| Page-author content fails Tier 3 lint        | Include page; emit warning in notification                                                                                                                            |
| PR create/update fails                       | Hard fail; `state.json` not advanced; next run retries the same window                                                                                                |
| Notification fails                           | Log only; do not fail the run; surface in next run's notification                                                                                                     |
| State file merge conflict                    | Append-commit semantics prevent this; if it happens, run aborts with human-actionable error                                                                           |
| Publish-verifier build never succeeds        | Timeout after `verify_timeout_seconds`; notify ⚠️ "Build did not complete within timeout"                                                                             |
| Publish-verifier finds 404 on a verified URL | Notify ⚠️ "Build succeeded but URL X returned 404"                                                                                                                    |

## 9. Testing strategy

- **Subagent prompts** — golden-file tests: fixture input → assert returned JSON conforms to schema (structure, not exact text). Located in `tests/agents/`.
- **Lint scripts** — standard unit tests per rule: known-good and known-bad fixtures, assert exit code and JSON output. Located in `tests/lint/`.
- **Orchestrator** — integration tests with a fake `source-collector` returning canned PR data; assert end state (PR opened with expected files, state.json advanced, lint failures surfaced). Located in `tests/orchestrator/`.
- **Setup skill** — `--dry-run` mode emits config to stdout; tested against fixture host repos (mkdocs + Docusaurus + bare). Located in `tests/setup/`.
- **Reused scripts** (`footnotes.sh`, `diagrams.py`, `archive_indexes.py`) — existing ADIS tests carry over.
- **End-to-end** — a fixture host repo with seeded PRs walks through the full main + verify pipelines against a mocked Git/Jira layer.

Coverage target: every Tier 1 lint rule has at least one known-good and one
known-bad fixture; every subagent has at least one happy-path golden test
and one error-path test; orchestrator has at least one partial-run test.

## 10. Distribution

- `marketplace.json` at repo root lists the `engineering-docs-agent` plugin.
- Hosts add this repo as a marketplace, install the plugin, run the setup skill.
- Versioning: semver. First dogfoodable release tagged `v0.1.0`.
- Visibility: private at launch; flip to public marketplace after stabilization.

## 11. Implementation phases (high-level — detailed plan in `writing-plans`)

Suggested build order, optimized for early dogfooding:

1. **Plugin scaffolding** — `plugin.json`, `marketplace.json`, repo layout.
2. **Reused ADIS scripts** — lift `verify_footnotes.sh`, `verify_docs_diagrams.py`, `generate_archive_indexes.py`; generalize.
3. **Tier 1 lint rules** — `frontmatter_schema`, `internal_links`, `markdown_hygiene`, `framework_build`, `stub_redirect`. Standalone, fully tested.
4. **`lint_runner.py`** — aggregates rules, reads config.
5. **Subagent definitions** — all 7 agents authored as `.md` with input/output schemas.
6. **Orchestrator skill** — pipeline implementation.
7. **Setup skill** — auto-discover + ask + write.
8. **Workflow templates** — main + verify.
9. **Configuration & state schemas** — JSON schema files for validation.
10. **Tier 2 lint rules** — `banned_phrases`, `ai_tells`, `voice_consistency`, `terminology`, `second_person`, `paragraph_length`.
11. **Tier 3 lint rules** — `reading_grade`, `sentence_variance`, `duplicate_content`.
12. **End-to-end test** — fixture host repo through both pipelines.
13. **Documentation** — README, plugin description, setup guide.
14. **Dogfood on ADIS** — install the plugin, run setup, do a first nightly. This is the v0.1.0 release gate.

Phases 3, 5, 10, and 11 are heavily parallelizable across independent subagent
dispatches. Phases 2, 4, 6, 7, 8, 9 should be serial (each depends on the
previous).

## 12. Reused ADIS artifacts

From `~/Projects/advanced-data-importer`:

| Artifact                            | Source                                                                      | Generalize as                                                                                    |
| ----------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| YAML front-matter schema            | `docs/site-src/archive/adrs/*.md` headers                                   | `scripts/lint/frontmatter_schema.py`                                                             |
| `generate_archive_indexes.py`       | ADIS `scripts/`                                                             | Plugin script, host config supplies promoted-slugs                                               |
| `verify_footnotes.sh`               | ADIS `scripts/`                                                             | Reused as-is; host wires into CI                                                                 |
| `verify_docs_diagrams.py`           | ADIS `scripts/`                                                             | Reused; host site-dir/source-dir already configurable                                            |
| Redirect-stub pattern               | 15 files in PR #371                                                         | `scripts/lint/stub_redirect.py` + a "promote ADR/spec" helper                                    |
| Synthesized-into admonition snippet | Python in commit `24e001d`                                                  | Plugin-shipped, runs nightly to keep breadcrumbs in sync                                         |
| Lens-over-canonical-core IA         | `docs/site-src/{portfolio,future-me,core,onboarding,archive}/`              | `templates/lens-ia/` starter                                                                     |
| Doc-source map / drift hook design  | `.claude/hooks/doc_drift.py` + `scripts/build_doc_source_map.py` (ADIS-228) | Plugin generalizes; hook fires on source change, agent reads accumulated drift state on next run |

## 13. Open questions for the implementation plan

These are intentionally deferred to `writing-plans` so the plan can resolve
them with implementation context:

- Exact JSON schema for `pr-summarizer` output (fields, required vs optional, list-of-doc-targets cap).
- Precise URL-derivation rules per supported docs framework (mkdocs, Docusaurus); the regex and config override shape.
- Concurrency cap on parallel subagent dispatch (avoid hitting API rate limits during fan-out).
- Specific GitHub Actions concurrency group identity (per-host vs per-branch).
- How `engineering-docs-agent-setup` discovers Jira creds (env vars in CI vs interactive prompt vs `.netrc`).
- Whether `publish-verifier` should also screenshot the page via Playwright for visual confirmation (beyond HTTP 200 + content presence).

## 14. References

- `KICKOFF.md` (this repo) — brainstorming handoff.
- `~/Projects/advanced-data-importer/docs/superpowers/specs/2026-05-19-adis-architecture-docs-historical-merge-design.md`
- `~/Projects/advanced-data-importer/docs/superpowers/plans/2026-05-19-adis-architecture-docs-historical-merge.md`
- `~/Projects/advanced-data-importer/docs/superpowers/specs/2026-05-18-adis-architecture-documentation-design.md`
- ADIS PR #371 — historical-insight merge.
- ADIS PR #370 — placeholder-prose removal predecessor.
