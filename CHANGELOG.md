# Changelog

## [Unreleased]

### Fixed

- **CCE-152** — authoring is cut at a PR boundary, so a truncated run can still advance the baseline. CCE-114's cut fired at whatever batch index it happened to reach, but `per_target` is built by walking PRs oldest-first and `setdefault`-ing each doc target, so batches arrive already grouped by the oldest PR that references each page. Cutting at an arbitrary index therefore split a group, and `advance_cursor_list` breaks at the oldest unfinished PR — so a run whose OLDEST PR fans out to more pages than the budget can author split group(PR1) every single time, advanced nothing, and re-authored the same leading pages on the next nightly. The ADIS host sat on one baseline for 20.6 days on exactly that, reporting `no_advance_no_cursor` four nightlies running. The unit of the guarantee moves from one batch to **one complete PR group**: the soft deadline may only cut where `_owner != _prev_owner`, which always leaves a complete prefix behind it, so the cursor is non-empty and the baseline moves. Deferring to a boundary is unbounded on its own, so a second term bounds the overrun — a new `run.authoring_hard_cap_seconds` schema key (integer, `> 0`; `additionalProperties: false` on `run` means a typo like `authoring_hardcap_seconds` is rejected at load rather than silently ignored), defaulting to `time_budget_seconds * 1.15`. An explicit cap **at or below** the budget is a config error with exit 2 and a logged reason, not a clamp-up: equal collapses the hard deadline onto the soft one and silently restores the very mid-group cut the cap exists to prevent, and a config that asks for that is a typo, correctable at the source. That rejection compares against the RESOLVED budget, so `--time-budget-seconds` can trip it against an unedited config file — pinned by a characterisation test and now written down in the README rather than left to be discovered. The cap is then clamped against the real ceiling, which is not the job timeout (both workflows carry `timeout-minutes: 90` since CCE-140) but the GitHub App installation token's 1h TTL: `GITHUB_APP_TOKEN_TTL_SECONDS` less the merge poll this host will actually run (dropped for a `merge.policy: manual` host, which never runs it) less a 285s post-run tail — 285 being the largest reserve that still leaves a 2100s host its full 1.15 overrun, and a reserve that has to cover a whole page-author dispatch, since the cut test is evaluated before each iteration dispatches and the last admitted batch runs entirely past the hard deadline. A TTL squeeze is _not_ a config error, because it is arithmetic on a token nobody in this process controls: the cap is held at the budget, an advisory `authoring_hard_cap_squeezed` reason names it, and behaviour degrades to the pre-CCE-152 cut — never worse, never silent. **The stock `DEFAULT_TIME_BUDGET_SECONDS` (2700) is in that state**, so the squeezed wording is the one most operators will meet and it is phrased distinctly ("hard cap held at budget 2700s by the App-token TTL") rather than rendering as "hard cap 2700s over budget 2700s", a number over itself. An explicit override merely narrowed by the clamp was the one remaining silent case — legal, not squeezed, but smaller than what the operator wrote — and now appends an `authoring_hard_cap_clamped` advisory naming the configured value, the ceiling, and the poll term spending the difference. What is enforced is only what `run()` can see, measured from its own entry: the workflow mints the token in the job's FIRST step, minutes of checkout and install earlier, and nothing in the process can measure that gap, so the README states the setup offset as operator sizing rather than claiming to have removed it. Also extracts one `_run_cfg` accessor for all three `run.*` resolvers — `resolve_time_budget` used `config.get("run") or {}`, which raises `AttributeError` on any truthy non-mapping while its two siblings resolved the same block to defaults; the schema rejects such a block at load, so this is defence in depth for the unit-test callers that bypass it, pinned as agreement between the three rather than as the extraction.

- **CCE-144** — blind-run detection: a nightly whose agents never answered exits 1. `run()` reported success on every path a rate limit could take, so a run whose source-collector was rejected with a seven_day limit was a green check by construction (runs 31472240064 and 31579090583 both did exactly that). The overloaded `partial` flag splits in two by the operational test of what the run did with input it could not process — **blind** (it CONSUMED it) versus **degraded** (it HELD it BACK) — decided at the call site, never by reason string, since `schema_invalid:` is emitted by three sites carrying two different classifications. `add_partial` classifies blocking reasons blind by default and `degraded=True` opts out, because failing open in the safe-looking direction is what made the incident invisible; a coverage test forbids relying on that default at any of the 28 blocking sites, which a decaying registry could not do. Blind then drives three interlocks: exit 1 (not a new code — `run` already returned 1 when the docs PR could not be opened, the same failure class), a watermark guard, and an unconditional auto-merge skip. The watermark hazard was not latent — PR #215 advanced `last_successful_run` past #211/#212/#213, none of which appear anywhere in `docs/site-src`, and `state.json` is tracked while `_stage_docs_run_changes` runs `git add -A .`, so merge-as-promotion never was the guard the draft assumed; `last_successful_run` is consume-once and a skipped window is never re-read, while re-processing one is cheap and idempotent. The `time_truncated` block moves inside that guard, since it mutates `last_successful_run` in place and would otherwise write `window_head_sha` into the previous run's cursor — a failure mode with no coverage against the real `run()` path until this ticket added one, verified by sabotage. The auto-merge gate needed new code the spec had claimed it did not: CCE-140 narrowed it to `partial and not advance_cursor_backed`, which is sound for a degraded run and invalid for a blind one, and gating on the computed flag closes the class rather than extending a one-entry allowlist that is itself scar tissue from this mistake made once already. Also repairs the `Print partial-run reasons` workflow step, which grepped `state.json` for a key `save_persistent_state` strips as ephemeral, so it printed nothing on every run since the ephemeral split and exited 0 either way — indistinguishable from a clean run, and worse than no diagnostic because it suppressed inquiry. Merged as #224.

- **CCE-140** — the nightly merges itself. `_maybe_auto_merge`'s first condition was `if partial: return skip("partial_run")`, and every run this pipeline has ever produced is partial — so the auto-merge path never once fired on the flagship host. All ten docs-agent PRs that landed there were merged by hand, by one person, and the baseline froze on the day those manual merges stopped, unnoticed for sixteen days. `partial` now blocks only a run whose baseline advance would reach the full window HEAD; a run whose `advance_sha` came from the CCE-109 cursor has, by construction, advanced only past PRs whose pages all landed, and it merges. Making that guarantee true required narrowing the cursor itself: it was computed over the whole admitted PR list, so once CCE-138 taught the authoring loop to truncate, a run could advance past PRs whose page batches were never written. `advance_cursor_list` now stops the walk at the OLDEST unfinished PR, because the cursor is a prefix boundary — advancing past an unfinished PR strands it outside every future window and nothing re-collects it. That narrowing deliberately supersedes three of CCE-138's five acceptance tests, which asserted the weaker "advance to the last processed PR"; they are rewritten in place, not deleted, and the discriminating negative (`advance != head`) is kept in every one. `fact_check_warnings` stops gating: the fact-checker documents itself as a warn layer at `:1755-1760` ("never a partial flag, never a dropped page") and the gate contradicted its own contract; the warnings keep the PR-body section and the notifier digest, both now pinned by tests since nothing else depends on the list. An explicit `_MERGE_VETO_REASON_PREFIXES` list preserves the one coupling the old gate carried by accident: `app_token_unavailable` is recorded as blocking expressly so auto-merge skips, because a PR built on the fallback `GITHUB_TOKEN` never fires host CI and `gh pr checks` returning `[]` would read as green. And a PR deferred on `run.deferral_skip_threshold` consecutive runs (default 3, `0` disables) is abandoned on the next: the cursor walks past it, a record lands in a durable append-only `skipped_prs` array in `state.json`, and a non-informational partial reason names the PR and the pages it owed so it reaches notifications. Neither new state key is ever seeded empty, and `state.schema.json`'s root has no `additionalProperties: false` — so a pre-CCE-140 `state.json` validates unchanged, a post-CCE-140 one validates against the old schema, and there is no migration and no version bump; both directions are pinned by tests, and the back-compat claim is verified against the host's real production state file, not a synthetic one. The human-edit guard is untouched but changes character: it sits after the new gate and was previously unreachable on the merge path (every run skipped first), so it goes from dead code to the primary human override, and a test now pins that a cursor-backed partial still loses to it. Mutation-verified — disabling the gate fails both the unit test and the wired end-to-end test, the latter proving a real merge fires when the gate is removed rather than passing vacuously on an empty call log. Opening the gate turned out not to be sufficient: three lines below it, CCE-101's `if deadline is not None and clock() + grace > deadline` refused the merge on exactly the runs the gate had just admitted, because the only run that CAN be cursor-backed is a time-truncated one and a time-truncated run is past its deadline by construction — the original never-auto-merges bug one layer deeper, and it would have shipped green, since a gate unit test and a computation unit test both pass while nothing joins them. The CCE-109 run budget now bounds the authoring work only; the merge epilogue is exempt when the advance is cursor-backed and stays bounded by `merge.checks_grace_seconds`/`checks_timeout_seconds` measured from the merge attempt, so a run that earns a merge may overrun `time_budget_seconds` by up to `checks_timeout_seconds` (default 900s) waiting out host CI — an operator-visible trade recorded in the README, chosen over forfeiting every merge. It was found by the first test that drove `run()` all the way to `gh pr merge` instead of asserting on a module-global shadow of the gate's input; that end-to-end pair (merge fires when eligible, `app_token_unavailable` vetoes an otherwise-identical run) is now the guard on the call-site wiring, which mutation testing had shown was entirely unpinned in the permissive direction — forcing `advance_cursor_backed=False` at the call site left 1253 tests green. Three further silent-loss holes closed the same way, each shipped with a regression test proven red against the pre-fix code because the existing 1287 passed on both sides: `held_back` enumerated only time-deferred work, so a lint-reverted page or a failed dispatch let the cursor walk past a PR whose page was never written (replaced with the complement of what actually landed, which covers failure modes nobody has enumerated yet); deferral-count pruning ran only under `if time_truncated:`, so a clean run never reset a counter and a truncated/clean/truncated alternation accumulated toward skipping a PR the pipeline was handling correctly; and a skip was recorded for PRs behind an older still-deferred one, which the walk never crosses — an uncorrectable entry in an append-only array plus an alarm for a loss that did not happen.

- **CCE-138** — an authoring-loop time truncation now sets `time_truncated`, so the baseline advances to the CCE-109 cursor instead of falling through to the full window HEAD. The PR-admission loop has always set the flag when it hits the soft deadline (`orchestrator_runner.py:1491`); the authoring loop truncates for the same reason, its comment shows the author knew it needed the same deadline, and it set nothing — so the promotion block took its `else` branch and wrote `state["current_run"]["head_sha"]` as the new baseline. A run that authored 1 of N page batches therefore persisted a baseline claiming coverage of every PR in the window: every un-authored batch was dropped permanently, and the PR body reported the full window as covered. The guard was copied between the two loops; the state assignment was not, and an absence produces no error, so the consequence surfaced only later in a different function. Measured on the `advanced-data-import-system` host, where all ten docs-agent PRs that ever merged (2026-06-26 to 2026-07-25) were merged by hand and each advanced the baseline this way. The fix is five lines and adds no new state and no new refusal logic — the CCE-109 block at `:1973-2028` already computes the per-PR cursor and already refuses in three distinct ways when it cannot prove the advance is safe; this only makes those branches reachable from the authoring loop. The test asserts the negative, `advance != head`, because the bug was a fall-through: every fixture places a non-PR commit above the newest PR merge so cursor and HEAD are provably different shas, and asserting only `advance == cursor` would pass vacuously on a fixture where they coincide. Mutation-verified — removing the assignment fails exactly the four authoring tests and leaves the admission regression test passing, which is the discrimination a guard for untouched behaviour has to show. Deliberately does **not** set `deferred_unanchored` at the authoring break; a test pins that branch as correctly unreachable from an authoring truncation rather than leaving the omission to read as an oversight.

- **CCE-134** — `citation_exists` no longer blocks on its own citation grammar's placeholder. `path/to/file.py` is the metasyntactic placeholder in the CCE-122 grammar that the plugin ships in `agents/page-author.md`, so it propagates into authored prose on every host and then fails the Tier-1 block rule it documents. It is added to `DEFAULT_EXEMPT_TOKENS` as an exact token — deliberately not as a `path/to/` entry in `DEFAULT_EXAMPLE_PREFIXES`, which was the obvious-looking fix and is wrong three ways: the prefix branch of `check_path` is a silent bare `continue`, so a reserved `path/to/` would swallow a confabulated `path/to/whatever.py` _and_ an invented `:symbol` inside a real file under that subtree (the authoritative-looking failure mode CCE-122 warns about); `example_prefixes` REPLACES on host override while `exempt_tokens` UNIONS, so any host configuring its own namespace would silently lose the plugin-intrinsic entry and start failing on pages the plugin itself authored; and the prefix branch emits no drift signal, where the exempt branch reports `stale exemption` once the token starts resolving. The corpus contains exactly one `path/to/` token, on two pages. Scope is measured, not assumed: across 106 pages the block-failure count is unchanged at 12 (`docs/site-src/whats-new.md` still fails on nine other tokens) and one archive-lens `warn` page clears (9 → 8) — a false positive closed at the resolver, with no page unblocked by relaxing the gate.

- **CCE-132** — six confabulated citations removed from the published corpus. Because `citation_exists` lints the whole edited page rather than the diff, each bad token latched its page shut against every future docs-agent edit: the page was re-authored, re-blocked, dropped from the PR, and the run flipped `partial` (outages on PRs #197 and #201). Four pages are now clean. Three tokens were genuine misnames and were repointed at the real module — `scripts/build_doc_source_map.py` → `scripts/source_map.py`, `scripts/generate_archive_indexes.py` → `scripts/archive_indexes.py`, `agents/schemas/page-author-output.json` → `agents/schemas/page_author.schema.json`. Three could not be fixed by swapping a path, because the surrounding prose was false about the corrected target — the CCE-122 hazard, where a wrong-but-existing path passes the lint while reading as authoritative. `scripts/verify_docs_diagrams.py` became `scripts/verify_diagrams.py` **and** the paragraph was rewritten: the Tier-1 `diagrams` rule is a separate pure-stdlib fence-syntax lint (`scripts/lint/diagrams.py`), while `verify_diagrams.py` is a post-build Playwright render gate whose docstring forbids the agent runtime from importing it. `.github/actionlint.yml` was **not** swapped — the prose accurately transcribed a real trigger glob whose target does not exist, so the `paths:` list moved into a fenced block (invisible to the rule) that names the dead glob as dead and records actionlint's actual `.yaml` convention. `.github/workflows/diagram-gate.yml` exists in no form; the claim was redirected to the `diagram-gate` job in `.github/workflows/docs.yml`, which required rewriting the page's structure as well as its filename — the "`filter` job" is a step, the "`include` block" is a bash `case`, the workflow deliberately carries no `paths:` filter (CCE-91), and the page's account of the pre-CCE-91 state was inverted (non-docs PRs did not run the full suite; GitHub skipped the workflow entirely and the required check never reported, deadlocking merge). Stale frontmatter `source_files` entries and Mermaid node labels carrying the dead names were swept in the same change — neither is scanned by the rule, so fixing prose alone would have left them lying. Docs-content only: no lint code is touched.

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
