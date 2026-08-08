# Changelog

## [Unreleased]

### Fixed

- **CCE-131** — `citation_exists` false-positive closure. The CCE-89 corpus scan found the Tier-1 block rule rejecting correct citations on six independent grounds; each is fixed at the resolver rather than by adding a way to overrule the block. `strip_fenced_blocks` now fails closed — an unterminated fence previously swallowed every line to EOF, silently disabling the rule for the rest of the file with no report. `cited_test_exists` matches a test-family shorthand at a `_` boundary (`test_lint_runner` now resolves via `test_lint_runner_missing_script_reports_block`), so a wholly invented name still blocks. `check_path` resolves a cited path against `site.docs_dir` as well as repo root, so a docs page citing a sibling page passes, and skips citations naming the mkdocs `site_dir` build-output directory — parsed from `mkdocs.yml` with a permissive multi-constructor loader that degrades unknown tags to `None` instead of aborting the parse (plain `yaml.safe_load` cannot read a mkdocs-material config: `!!python/name:` on `pymdownx.superfences` raises `ConstructorError`), and empty — skip nothing — when no mkdocs config parses at all, so a host with no such config never gets `site/` treated as a permanently reserved prefix. A reserved `example/` illustrative namespace (RFC 2606's `example.com` precedent, host-configurable via `lint.citation_example_prefixes`) lets generic-first fictional-host documentation live in prose without fencing. `lint.citation_exempt_tokens` covers the residual class where non-existence IS the claim (`tests/scripts/__init__.py`), plugin defaults unioned with host entries, self-cleaning via a `stale exemption` warn when a listed token starts resolving. And the page-author contract gains the concept of a non-citation — a backticked path or test identifier now explicitly asserts existence, with the `example/` namespace and fenced-block escape hatches for the illustrative and metasyntactic cases that previously had no compliant way to write in prose. Regression-locked against the CCE-110 incident fixtures throughout.

- **CCE-127** — a failed GitHub App-token step no longer kills the nightly. The workflow ran `actions/create-github-app-token` with no `continue-on-error`, so a failed mint aborted the job before the `steps.app-token.outputs.token || secrets.GITHUB_TOKEN` fallback on the following steps was ever evaluated — GitHub resolves that expression only for a _skipped_ step, never a failed one. CCE-80 documented the skip path as the whole degradation story, and that wording is why the unreachable failure path went unexamined for two months. Live consequence: an org transfer on 2026-07-23 deleted the App's installation on this repo (credentials untouched — the mint 404s on `/repos/{owner}/{repo}/installation`, where a 401 would instead mean bad credentials), and `theoju/engineering-docs-agent` plus `theoju/claude-code-self-assessment` each failed 15 consecutive nightlies with no notification. Both workflows now run the step under `continue-on-error` and export `steps.app-token.outcome` — never `conclusion`, which `continue-on-error` rewrites to `success` — as `DOCS_AGENT_APP_TOKEN_STATUS`; the orchestrator records a blocking `app_token_unavailable` reason for the literal `failure` only, flipping the run to `partial` so the CCE-101 auto-merge gate skips with `partial_run` (a PR built on `GITHUB_TOKEN` never fires host CI, and zero registered checks would otherwise read as "nothing failed"). `skipped` (the bare-host path, no `DOCS_AGENT_APP_CLIENT_ID`), `success`, and unset stay silent. Also closes the CCE-71/CCE-80 template-vs-dogfood divergence: the dogfood absorbed the `if:` guard, both `GITHUB_TOKEN` fallbacks, and `SLACK_WEBHOOK_URL` job-env, and the three `_TEMPLATE_ONLY_DIVERGENCES` entries that recorded those gaps as _accepted_ are removed — `test_05` and a new `test_09` now enforce the wiring in both files.

- **CCE-125** — gap-detector `needs_spec: null` is advisory "unjudged", not a partial driver. The agent's documented malformed-input fallback (`{"error":"malformed_input","needs_spec": null}`) failed its own schema — `needs_spec` was a required boolean — so `validate_and_parse` returned `schema_invalid`, the callsite recorded it via `_record_dispatch_reasons(ok=False)`, and the run flipped `partial`, blocking the CCE-101 auto-merge gate. This was the last recurring partial driver from nightly PR #189 (its `citation_exists` driver was fixed by CCE-124; its `prose_contamination_rescued: fact-checker` was already info-only since CCE-118). The schema now types `needs_spec` as `["boolean","null"]` (still `required`, with the canonical `agents/gap-detector.md` block updated in lockstep and the generated `docs/site-src/api/contracts/gap_detector.schema.md` regenerated); a validated null verdict records an info-only `gap_detector_unjudged: pr_id=…` reason and is skipped — never appended, so it stays out of "Gaps flagged" and the CCE-89 digest — and the run stays non-partial. Only present-`null` is downgraded: an absent `needs_spec` key, a wrong non-null type, or unparseable output still fails schema and still flips `partial`, preserving the genuine-malfunction signal. A fact-checker-specific regression test locks the CCE-118 info-only behavior. gap-detector now joins fact-checker as an advisory agent whose "couldn't judge" is info-only, distinct from the blocking pipeline.

- **CCE-122** — stable code citations. Docs now cite `` `path:symbol` `` or bare `` `path` ``, never `` `path:line` `` — line numbers drift under unrelated code churn, so the nightly `fact-checker` kept re-flagging benign drift as `contradiction` warnings that blocked the CCE-101 zero-warnings auto-merge gate. The fix splits the two concerns: `citation_exists` (Tier-1, block) now verifies a cited `:symbol` is defined in its file (a confabulated symbol blocks like a bad file/test), a new advisory `citation_line_free` rule (Tier-1, warn) nudges on leftover `:line` without failing the run, and the `fact-checker` is scoped to behavioral truth only (it no longer polices citation line/location — a wrong symbol still fails the behavioral check). A one-time `ast`-based migration (`scripts/migrate_line_citations.py`) rewrote 99 `:line` citations across 21 pages to `:symbol`/bare, resolving each line to its enclosing def/class or module constant; a repo-guard test keeps `:line` out. Generic-first: bare-`path` citations are unchanged and the advisory rule degrades gracefully on hosts with legacy pins.

- **CCE-119** — create-path frontmatter fidelity. The orchestrator now reconciles a freshly-created agent-authored page's frontmatter against its own deterministic `agent_fields` after the page-author returns (declare-then-discharge — the LLM's write is no longer trusted on the production dispatch path), and the synthesized description's `min_words` floor is resolved from the host's `description_quality` config instead of a duplicated `_DESC_MIN_WORDS` constant. Both were CCE-117 residuals; neither was a live failure (the content-validator lint-drop safety net masked them).

- **CCE-121:** the partial-reasons digest header now reflects the run's `partial` flag, not merely the presence of reasons. Since CCE-118 made benign prose-contamination rescues `info_only` (they don't flip `partial`), a non-partial run that auto-merged under the CCE-101 gate still rendered its rescues under a "WARNING — Partial run" header — mislabeling a clean run (nightly PR #176 exemplar). `_format_partial_digest` gained a `partial` parameter; the PR body and `GITHUB_STEP_SUMMARY` now show an "INFO — advisory notices" header for non-partial runs and keep the warning header for genuinely partial ones. Display-only; the `partial` flag, auto-merge eligibility, and `add_partial` semantics are unchanged.

- **CCE-116:** the branch pruners no longer choke on a branch checked out in a linked git worktree. `git branch -d`/`-D` refuse to delete a branch checked out in any worktree, but both pruners recognized only the _current_ worktree's branch — so a `[gone]` branch checked out elsewhere reached the delete path and was misreported (`delete-failed` from the CCE-99 post-merge hook; `skipped_unmerged` with useless "re-run with --force-unmerged" advice from the in-repo `scripts/prune_merged_branches.py` floor). Both now enumerate every checked-out branch via `git worktree list --porcelain` and skip cleanly (hook reason `checked-out (worktree)`; the floor excludes it like the current branch). The user-global hook change ships in `~/.claude/skills/ship/`; the in-repo floor + tests ship here.

- **CCE-118 (item 1):** a benign JSON rescue no longer flips a run to `partial`. Six blocking-pipeline dispatch callsites (source-collector, pr-summarizer, page-author, content-validator, gap-detector, notifier) recorded their dispatch reasons as partial-flipping, so a subagent that emitted valid JSON wrapped in prose — recovered by `_rescue_json_object` and schema-validated — still marked the whole run partial and blocked CCE-101 auto-merge (the recurring nightly toil; PR #170 exemplar). They now route through `_record_dispatch_reasons(state, reasons, ok=<dispatch succeeded>)`: a dispatch that returns usable output can only carry benign `prose_contamination_rescued` diagnostics (a schema failure forces `out=None`), so those are `info_only`; genuine failures still flip `partial`. Fact-checker advisory reasons and the contradiction-warning gate are unchanged.

- **CCE-117:** the incremental nightly authoring path now writes the agent-authored frontmatter set (`description`, `source_files`, `last_reviewed`, `status`) when creating a page in an `agent-authored` section, so Tier-1 `frontmatter_schema`/`description_quality` no longer drops those pages and the nightly run stops going partial on them. Also single-quotes the `description` field in `agent_authored_frontmatter_text` so synthesized sentences containing colons remain valid YAML.

- **CCE-109 time budget now bounds the authoring fan-out (CCE-114).** The
  soft deadline was only checked at PR admission, which completes minutes
  into a run — the page-author fan-out (one dispatch per doc-target batch)
  then ran unbounded, and six consecutive scheduled nightlies died at the
  workflow's 60-minute hard kill with all work discarded. The deadline is
  now checked before each authoring batch (at-least-one-progress, mirroring
  admission) and before each advisory fact-checker/gap-detector dispatch
  (skip outright). All cuts flip `partial`, so the CCE-101 gate never
  auto-merges a run whose pages were cut or never fact-checked.

### Added

- **Factual-accuracy guard for authored pages (page-author confabulation fix).** Three layers: page-author now receives `source_paths` grounding inputs and returns advisory `evidence.files_read`; a new Tier-1 `citation_exists` lint rule blocks pages citing nonexistent repo paths or test identifiers (regression-pinned against the two 2026-06-09 confabulated pages); a new warn-only `fact-checker` subagent (the eighth) flags prose that contradicts cited source, rendered as a "Factual-accuracy warnings" PR-body section. Generic-first: no git → trivial pass, no citations → no dispatch, fact-checker failure → info-only note. Tracker: CCE-110.

### Changed

- **Behavior change (CCE-101):** docs-agent PRs now auto-merge by default
  when the run is non-partial with zero fact-checker warnings (squash +
  branch delete, host CI respected when it reports). Set
  `merge: { policy: manual }` in `.engineering-docs-agent/config.yml` to
  keep PRs open for review. The setup skill now asks this explicitly.
  After an auto-merge the runner dispatches `publishing.build_workflow`
  directly, so Pages deploys fire even for `GITHUB_TOKEN` merges.

## [0.5.1] — 2026-06-09

Consolidates the 20 changes merged since v0.5.0 (CCE-66, CCE-83, CCE-86, CCE-89 through CCE-108). The headline is the structured docs-site upgrade — a config-driven `site:` block with deterministic generators, a service/component-grouped API reference backed by JSON-Schema contracts, per-section overview pages, a richer home page, and freshness-sorted architecture/archive routing. Alongside: the SDD fidelity verification ladder, Jira auto-transition on merge, and the docs-agent nightly cadence controls. No breaking changes to the host config surface; existing `.engineering-docs-agent/config.yml` files continue to load.

### Added

- **Config-driven `site:` block + deterministic generators.** The setup skill and orchestrator now read a `site:` config block (`sources`, `extractors`, `docs_dir`) and run deterministic page generators wired end-to-end into scaffolding and the nightly run. Generic-first: hosts without the convention skip cleanly. Tracker: CCE-104.
- **Grouped API reference with JSON-Schema contracts.** The API reference groups entries by service/component instead of a flat list, and each subagent contract is backed by a JSON Schema in `agents/schemas/`. Tracker: CCE-105.
- **Section overviews, rich home page, and repo-URL linking.** Each published section gets an auto-generated overview index; the home page surfaces GitHub integration and recent activity; source links resolve against a configured/derived repo URL base; the API reference is grouped in the nav. Tracker: CCE-106.
- **Architecture-index freshness sort + architecture-vs-archive routing.** Decision-kind `create` pages route deterministically to the archive section; architecture indexes sort newest-first. Tracker: CCE-107.
- **SDD fidelity verification ladder.** A declare-then-discharge gate (Tier 0 git baseline diff, Tier 1 consumer-tool run, Tier 2 red/green, plus a reviewer gate) that verifies subagent self-reports against external authority. Canonical doc + dependency-injected reference implementation under `docs/superpowers/templates/`. Tracker: CCE-92 (pattern: CCE-93/CCE-94).
- **Jira auto-transition on PR merge.** A merged CCE PR transitions its Jira issue(s) to Done via `.github/workflows/jira-transition.yml`; the PR title is the single source of truth for keys. Comments-then-transitions, fails loud, dry-run via `workflow_dispatch`. Repo-local hygiene (not scaffolded onto hosts). Tracker: CCE-103.
- **In-repo branch-prune helper.** `scripts/prune_merged_branches.py` removes local `[gone]` refs and `worktree-*` orphans left after `gh pr merge --delete-branch`; dry-run by default. Tracker: CCE-90.
- **docs-agent PR-body enrichment.** Nightly PRs now render a review-window header (baseline → current head SHA), file count by lens (with `other` bucket for non-lens paths), top-5 changed pages with `(+M more)` truncation, and an inline `partial_reasons` digest when the run is partial. Operators can review a nightly in <60s without opening the diff. The composer is pure (`_compose_pr_body`); back-compat preserved via optional kwargs with safe defaults. Tracker: CCE-89 D1.
- **docs-agent auto-close-stale policy ("freshest-only").** After a new nightly opens its PR, the orchestrator walks open `docs-agent/*` PRs and closes each one authored entirely by the bot with the comment `Auto-closing: superseded by #<new> (docs-agent freshest-only policy)`. PRs with any human-authored commit are left open for human resolution. Prevents the stale-PR pileup that accumulated 2026-05-30 to 2026-06-01 (6 PRs against a single stale baseline). All hygiene reasons are `info_only=True` — D2 failures cannot flip the run to partial. Tracker: CCE-89 D2.

### Changed

- **docs-agent nightly cron unpaused.** The `07:07 UTC` schedule is restored on `.github/workflows/docs-agent-nightly.yml` now that D1 + D2 provide the cadence floor. D3 (merge-gate decision: auto-merge vs operator-promote vs hybrid) remains open as a separate ticket; until it lands, the operator promotes each morning's PR manually after the enriched body provides the review signal. Tracker: CCE-89.
- **`archive_indexes.find_archive_section` promoted to public API.** The cross-capability section-lookup helper is now public (was `_find_archive_section`); `doc_routing` consumes it without reaching into a private name. Both callers updated atomically. Tracker: CCE-108.
- **CI / process hygiene.** Narrowed `docs.yml` paths and added docstring lint as part of the CCE-77/CCE-80 cycle cleanup; paused-then-archived 6 stale docs-agent PRs and codified the freshest-only cadence invariant. Trackers: CCE-77/CCE-80, CCE-89.

### Fixed

- **diagram-gate required-check deadlock on non-docs PRs.** Removed the workflow-level `paths:` filter from `.github/workflows/docs.yml` and replaced it with an in-job `filter` step that diffs against the PR base / push parent and gates the expensive Playwright/mkdocs steps on a `relevant` output. Without this, GitHub skipped the workflow entirely on PRs that didn't touch the listed paths — the `diagram-gate` required status check never reported, and `mergeStateStatus` stayed BLOCKED forever (originating incident: PR #108). Same invariant as `actionlint.yml` (CCE-59): required status checks must never carry a workflow-level paths filter. Tracker: CCE-91.

### Docs

- **Release & rollback runbook.** New `docs/runbooks/release-and-rollback.md` (two-clock SLA, rollback playbook, tag-cut-misfire recovery) plus a CHANGELOG-as-release-artifact step and cross-link in the CCE-80 runbook. Tracker: CCE-86.
- **Plan-verification + meta-orchestrator conventions.** Plan steps must verify with the real consumer tool (not `test -f`); the meta-orchestrator spec and the Phase 4 closeout are documented. Trackers: CCE-83, CCE-66.

## [0.5.0] — 2026-06-04

Synchronizes `templates/workflow-run.yml` with the live dogfood nightly workflow, absorbing 16 stale divergences accumulated since the template was last touched (CCE-39 / 41 / 45 / 49 / 53 / 66 / 73). Hosts onboarded via the setup skill now receive a parity-checked workflow with App-token plumbing, OAuth pre-flight assertions, forensics upload, run-summary writer, partial-reasons stderr echo, and a per-host deterministic cron.

### Added

- **Deterministic per-host cron rewriter.** `scripts/scaffold_workflow.py` computes `sha256(owner/repo) % 51 + 5`, so re-scaffolding the same host always produces the same cron minute (no operator-visible diff churn). Invoked by the setup skill's step 6b.
- **Workflow parity tests.** `tests/templates/test_workflow_run_parity.py` — 8 structural parity tests comparing against the live dogfood workflow via `ruamel.yaml` (guards against PyYAML's `on:` key collapse).
- **Host-migration runbook + provisioning matrix.** `docs/runbooks/cce80-host-migration.md` and the `setup-guide.md` provisioning matrix (all 7 vars/secrets). `CONTRIBUTING.md` codifies the dogfood↔template parity gate and release-tagging cadence.

### Fixed

- **Pages bootstrap on first host deploy.** Replaced `actions/configure-pages@v6 enablement: true` (a no-op on first deploy because the workflow's `GITHUB_TOKEN` lacks admin scope) with a setup-time `gh api -X POST repos/.../pages -f build_type=workflow` call from the new `scripts/enable_pages.py`. The setup skill's step 6c invokes it after writing the docs-pages workflow. Graceful fallback on all error paths — scaffolding never blocks on Pages bootstrap. Originating incident: `theoju/claude-code-self-assessment` PR #121 / CCE-81. Tracker: CCE-82.

## [0.2.0] — 2026-05-27

Consolidates the work merged since v0.1.4 (CCE-17 through CCE-34). The headline additions are a structured, publishable docs site; verified-citation and core-manifest authoring stages; a Playwright diagram-render CI gate; a generic GitHub Pages publish target; and discovery-driven semantic section routing for generated pages. No breaking changes to the host config surface; existing `.engineering-docs-agent/config.yml` files continue to load.

### Semantic section routing (CCE-34, item 1)

- The orchestrator scans each lens root for top-level section directories at runtime and passes them to the pr-summarizer as `available_sections`. Generated `action: create` pages now route into published sections (`operations/`, `architecture/`, `archive/`) instead of the removed `_agent-sandbox/` path, which was no longer in `agent_editable_paths` and silently dropped. Hidden directories are excluded from the scan (generic-first safety for arbitrary host repos).
- The pr-summarizer `lens` schema field opened from a hardcoded enum to any non-empty string; known-lens enforcement stays at runtime via `resolve_lens`. Scaffolded section stubs now carry descriptive bodies so the summarizer LLM gets clearer section-intent signal. Vestigial `docs/_agent-sandbox/.gitkeep` removed; stale `_agent-sandbox/**` references in `state_io.py` and the README aligned to `docs/site-src/**`.

### GitHub Pages publish target (CCE-32) + dogfood alignment (CCE-34)

- Generic, Actions-source GitHub Pages deploy capability: the setup skill scaffolds a `workflow-pages.yml` deploy template when `detect_pages_publishable` confirms the host builds docs, wires `publishing.target` / `build_command` / `site_dir`, and derives the base URL for the publish-verifier. Non-MkDocs hosts are supported via `publishing.build_command` + `site_dir`. This repo's own site now deploys to Pages from `docs/site-src/`.

### Diagram render gate (CCE-30)

- New required CI gate renders Mermaid diagrams via Playwright on docs changes and asserts per-page render success, with graceful skip when Playwright is absent and a pinned test that the agent runtime never imports Playwright.

### Structured docs site + authoring stages (CCE-23, CCE-26, CCE-28)

- Structured docs-site scaffolding, decision archive, source-map drift detection, and an API reference surface (CCE-23). Verified-citation enforcement and agent-authored frontmatter helpers (CCE-26). Core-manifest detection, a `--bootstrap-core` authoring mode, and a nightly core-drift update stage (CCE-28).

### Source-collector reliability (CCE-17, CCE-18, CCE-19)

- Fixes to the pr-summarizer page-hint contract, source-collector Jira auth, and the diff-window bound.

### CI hardening (CCE-6, CCE-31)

- Added `@pytest.mark.live` marker and a `conftest.py` default-skip hook: live real-LLM tests run only via `pytest -m live`. Two `dispatch_subagent` smoke tests (notifier, pr-summarizer) exercise the real dispatch path with different payload shapes. New `.github/workflows/release.yml` runs them on tag pushes only. Cost ~$1-3 per full pass; the default mocked suite stays free. (CCE-6)
- Bumped CI actions to Node-24-compatible majors (`checkout@v5`, `setup-python@v6`). (CCE-31)

## [0.1.4] — 2026-05-20

### Source-collector reliability investigation (CCE-9 — partial fix + diagnostic infrastructure)

This release ships two independently useful pieces from the CCE-9 systematic-debugging investigation, plus measurement evidence. The full source-collector reliability fix continues in CCE-10.

**Diagnostic instrumentation (lands fully).**

- New `DOCS_AGENT_DEBUG_DIR` env var on `scripts/orchestrator_runner.py`. When set, `dispatch_subagent` writes the full prompt, raw stdout, raw stderr, and meta (returncode + argv) for each subagent invocation to that directory, one file per artifact type. Off-contract LLM responses are now diagnosable without re-running and adding ad-hoc logging. Unset → byte-identical to v0.1.3.
- New unit tests at `tests/orchestrator/test_dispatch_debug_capture.py` (2 cases) lock the on/off behavior. Total suite: 163 passed (161 baseline + 2 new).

**Source-collector empty-`last_sha` guidance (lands; partial improvement).**

- Added explicit step 0 to `agents/source-collector.md` `## Procedure`: when `last_sha` is empty, return canonical `{"prs": [], "jira_issues": []}` and stop. Phase 1 evidence had shown the agent inventing a non-canonical `{"status": "idle", ...}` shape in this case.
- **Empirical result:** 3 Mode B runs against ADIS confirm the step 0 changes behavior — the agent now cites empty `last_sha` as its reason and early-exits — but it still emits the non-canonical `{"status": "idle", ...}` shape rather than the instructed `{"prs": [], "jira_issues": []}`. The step 0 is kept because the early-exit half is honored and the edit does no harm; the canonical-shape half awaits CCE-10.

**Systematic-debugging artifacts (committed for reference).**

- `docs/superpowers/measurements/2026-05-20-cce9-phase1-evidence.md` — original H4 confirmation + H1 refutation, with captured raw stdout.
- `docs/superpowers/measurements/2026-05-20-cce9-h4-validation.md` — null+evidence narrative from the 3-run validation, with two new orthogonal root causes identified (stop-verify hook contamination + agent's "status report" reflex overriding three explicit canonical-shape signals).
- Six raw-evidence artifact files (3× stdout, 3× state.json) alongside.

**Follow-up filed.**

- **CCE-10** — bundles hook-suppression + stronger canonical-shape forcing into one PR, using the new `DOCS_AGENT_DEBUG_DIR` capture as the measurement vehicle. See https://designitright.atlassian.net/browse/CCE-10.

No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.

## [0.1.3] — 2026-05-20

### State hygiene (CCE-5)

- `state.current_run.partial_reasons` no longer carries forward across runs. The state-init block in `scripts/orchestrator_runner.py` now constructs a fresh `current_run` with `partial: false` / `partial_reasons: []` before checking the prior run for staleness; the `stale_current_run_cleared` diagnostic is preserved by writing into the fresh `current_run` via `add_partial`.
- Persistent root causes (e.g. a malformed agent contract) re-accumulate naturally on each run's own dispatches. Transient reasons (e.g. `schema_invalid: source-collector: ...`, `push_failed: ...`) now belong only to the run that produced them.
- New integration tests at `tests/orchestrator/test_state_carry_forward.py` (3 cases) lock the no-carry-forward contract. Existing stale-clear sentinel at `tests/orchestrator/test_pipeline_integration.py::test_stale_current_run_cleared_on_next_run` remains green.
- No new dependencies. No new configuration. Future opt-in carry-forward (none today) would require an explicit allowlist per the design spec.

## [0.1.2] — 2026-05-20

### Schema enforcement (CCE-4)

- New `dispatch_validated(name, inputs, *, dry_run_dir, cwd) -> tuple[dict | None, list[str]]` in `scripts/orchestrator_runner.py` composes `dispatch_subagent` with `contracts.validate_and_parse`. Off-contract LLM responses now surface as a specific `schema_invalid: <name>: <field-detail>` line in `state.current_run.partial_reasons` instead of being silently absorbed by `dict.get(...)` fallbacks.
- All nine subagent call sites (six in `orchestrator_runner.py`, two effective in `verify_runner.py`) consume the new tuple. The `if not reasons` guard ensures exactly one reason line per failed dispatch — specific schema reason if available, the existing generic `<name>_invalid: returned None` otherwise.
- All seven agent `.md` files gain an `## Output schema (canonical)` section containing the canonical JSON Schema from `agents/schemas/<name>.schema.json`. The schema is now authoritative in the agent system prompt itself, not just in code.
- New drift-prevention lint at `tests/agents/test_schema_md_sync.py` (parameterized over all 7 agents) asserts the `.md` schema block is JSON-equivalent to the `.json` file.
- New `dispatch_validated` boundary tests (4 cases) at `tests/orchestrator/test_dispatch_validated.py`.
- New end-to-end schema-invalid soft-fail integration test at `tests/orchestrator/test_schema_invalid_soft_fail.py` with `fakes_schema_invalid/` fixtures (the literal Mode-B observed wrong shape).
- No new runtime dependencies. No new configuration surfaces. Soft-fail contract from v0.1.1 preserved.

## [0.1.1] — 2026-05-20

### Foundation

- New `scripts/contracts.py`: typed dataclasses for all 7 subagent outputs + `validate_and_parse` against per-agent JSON schemas in `agents/schemas/`. _Runtime enforcement (wiring `validate_and_parse` into `dispatch_subagent`) is deferred to v0.1.2; the production dispatch still consumes raw dicts but tolerates malformed output via the None-return path added in B2._
- New `scripts/gh_client.py`: `GhClient` wraps all gh CLI calls with `GhResult` (ok/value/error). `FakeGhClient` for tests.
- New `scripts/state_io.py`: `load_config_validated` and `load_state_validated` hard-fail with exit 2 on schema violations. Also hosts `add_partial`, `cleanup_empty_parents`, `load_voice_samples`, `resolve_lens`.
- New per-subagent schemas in `agents/schemas/`.

### Contract fixes (Category A)

- A1: source-collector now receives `jira` input when configured.
- A2: source-collector's `jira_issues` are looked up per PR and passed as `jira_context` to pr-summarizer.
- A3, A4: voice samples (host CLAUDE.md + `voice.sample_paths`) passed to page-author and content-validator.
- A5: orchestrator constructs `pr_id` and passes it to gap-detector; agent echoes it back.
- A6: page paths pre-filtered against `agent_editable_paths` before any `mkdir`.

### Error handling (Category B + F)

- B1: PR-number parsing has 3-stage fallback (URL int → regex → pr_list_for_branch).
- B2: `dispatch_subagent` catches `JSONDecodeError`, `FileNotFoundError`, empty stdout — returns `None` and the caller adds a `partial_reason`.
- B3: verify_runner wraps subagent calls in `try/finally` so state.json is always written.
- B4: `git push` failures recorded as `push_failed: ...` partial reasons.
- B5: `pr_list_for_branch` catches non-JSON gh output.
- B6: zero-PR runs no longer write empty whats_new entries.
- B7, B8: source-collector and pr-summarizer `error`/`partial` fields propagated.
- F1: source-collector `partial: true` trips orchestrator's partial flag.
- F2: stale `current_run` (>24h old) cleared with `stale_current_run_cleared` reason.
- F3: branch names use hour precision (`docs-agent/YYYY-MM-DDTHH`).
- F4: empty parent directories cleaned up after blocked-create unlinks.
- F5: page-author dispatches batched per (lens, page_hint) target.

### Schemas (Category C)

- C1: config and state validated on load via `jsonschema`; hard-fail with exit 2.
- C2: `dismissed_gap_flags` schema describes the value semantics.
- C2: `current_run.started_at` required.
- Config schema accepts `lens_paths` dict form, `voice.sample_paths`, `lint.stub_paths`.

### Dead code & structural (Category D)

- D1: archive*indexes wired in via `archive_indexes.regenerate()`; empty subdirs emit `\_No entries yet.*`.
- D2: Docusaurus detection emits `docusaurus_v0.1_unsupported` warning; framework_build skip is now structured.
- D3: lint_runner CLI contract documented at top of `lint_runner.py`.
- D4, D5: `duplicate_content.py` and `reading_grade.py` now exit 1 on failure (was 2).
- D6: `diagrams.py` returns structured `(False, "file not found")` instead of raising.
- D7: `stub_redirect.py` reads paths from `lint.stub_paths` when `tier1: default`.

### Test coverage (Category E)

- ~37 new tests across `tests/contracts/`, `tests/gh/`, plus integration tests for partial-run paths, multi-PR runs, unsafe page paths, jira threading, voice samples, hour-precision branches, stale state cleanup, and gh-fixture-driven verify_runner production path.
- Final suite: 100+ tests (was 64 at v0.1.0).

### Item 3 — framework_build signaling

- `framework_build.py` result now includes `skipped: bool` and `reason: str` fields. `ok=true skipped=true` means "couldn't validate"; `ok=true skipped=false` means "build passed".

## v0.1.0 — 2026-05-19

Initial release.

### Plugin

- 7 specialized subagents (source-collector, pr-summarizer, gap-detector, page-author, content-validator, publish-verifier, notifier).
- Orchestrator skill + setup skill.
- Main authoring workflow + post-merge verify workflow.

### Lint

- Tier 1 (default-on, block): frontmatter_schema, internal_links, markdown_hygiene, footnotes, diagrams, framework_build, stub_redirect.
- Tier 2 (opt-in, block): banned_phrases, ai_tells, voice_consistency (LLM-based), terminology, second_person, paragraph_length.
- Tier 3 (advisory, warn): reading_grade, sentence_variance, duplicate_content (placeholder).

### Verification

- Tests for every lint rule (good + bad fixtures).
- Orchestrator integration tests using fake subagent outputs.
- E2E main-pipeline test with a fixture host repo.
- JSON schemas for config and state with validation tests.
