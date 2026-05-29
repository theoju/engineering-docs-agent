# CCE-34 Scope Audit — Close the umbrella

- **Status:** As-built audit + small residual fix.
- **Ticket:** CCE-34 ("Dogfood verify-loop source reconciliation + Pages guard hardening (CCE-32 follow-up)")
- **Branch:** `chore/CCE-34-scope-audit`
- **Predecessors:** CCE-32 (#39, the Pages-publish capability this ticket follows up); CCE-34 itself has carried two unrelated follow-up branches (semantic routing PR #42, whats-new frontmatter PR #44/#45) which are tracked by their own specs.

## Problem

CCE-34 was opened as a CCE-32 follow-up enumerating three items:

1. **Dogfood verify-loop source mismatch (primary)** — `.engineering-docs-agent/config.yml` had `source_dir: docs`, but mkdocs published from `docs/site-src`, and the agent authored into `docs/_agent-sandbox/**` (outside the published tree). The publish-verifier's `url_map_rule=standard` strips `source_dir`, so dogfood-verify could not resolve real URLs.
2. **Missing NODE24 floor for `actions/upload-pages-artifact` (minor)** — `tests/ci/test_workflow_node_runtime.py` pins floors for `actions/checkout`, `actions/setup-python`, `actions/configure-pages`, `actions/deploy-pages` but not for `actions/upload-pages-artifact`. The template-validity test hard-checks `@v5` for the template, but a host that drifts to `@v4` on this one action passes the runtime guard.
3. **Generic template path-trigger breadth (minor)** — `templates/workflow-pages.yml` triggers on `docs/**`. The setup skill could substitute the discovered `source_dir` so hosts with non-site content under `docs/` don't rebuild the site on every unrelated change.

The ticket has remained Backlog while CCE-34 was used as the umbrella for two _unrelated_ follow-ups (#42, #44/#45). The audit's job is to ask: of the three _original_ items, what is still valid post-CCE-40/41/55/56/59?

## Audit findings

### Item 1 — REFUTED (already shipped)

Evidence: `git log --all --oneline -- .engineering-docs-agent/config.yml` shows commit `32182e1 fix(CCE-34): publish-align docs-agent to docs/site-src (dogfood publish loop)`. Current `.engineering-docs-agent/config.yml:6` sets `source_dir: docs/site-src`; line 11 sets `lens_paths.core: docs/site-src/`; line 9 sets `agent_editable_paths: ["docs/site-src/**"]`. Comment on line 3 explicitly names CCE-34.

Setup-skill detection also handles arbitrary hosts: `scripts/setup_discover.py:18-27` (`detect_source_dir`) prefers `docs/site-src` when it exists, else `docs` — so a new MkDocs host that follows the same publish-aligned convention is auto-aligned.

No residual work for item 1.

### Item 2 — STILL VALID (minor fix, ship)

Evidence: `tests/ci/test_workflow_node_runtime.py:25-30`:

```python
NODE24_FLOOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
}
```

`actions/upload-pages-artifact` is absent. The template (`templates/workflow-pages.yml:42`) and the dogfood workflow (`.github/workflows/docs-pages.yml:35`) both pin `@v5`. `tests/ci/test_workflow_pages_template.py:22` asserts the template carries `@v5`. But `test_no_workflow_pins_a_node20_action_major` (line 40-47) only flags actions listed in `NODE24_FLOOR` — so if a host (or this repo) regressed to `@v4`, the runtime guard would silently pass. v4 of that action ships Node 20 (deprecated June 2026); v5 is the first Node-24 major.

This is exactly the symmetry gap CCE-34 called out. Closing it costs one dict entry and one new test case.

### Item 3 — MARGINAL, DEFER

Evidence: `templates/workflow-pages.yml:10-11` triggers on `docs/**`. `skills/engineering-docs-agent-setup/SKILL.md:34` (Step 6a) describes the substitutions the setup skill does but does NOT substitute the `paths:` trigger with the discovered `source_dir`.

This is correctness-neutral (broader trigger = more conservative rebuilds, never wrong rebuilds). The ticket itself flagged it "Not incorrect — just broader than necessary." Shipping it requires either (a) post-write YAML edit logic in the setup skill, or (b) a `${SOURCE_DIR}` placeholder convention in the template plus substitution. Either path is more YAGNI-violating than the upside justifies for v0.1.

Defer-don't-fix: leave the broader default in place; if a host complains about unnecessary rebuilds, file a fresh ticket and address it then. No fresh CCE issue is opened by this audit.

## Scope of the deliverable

Single-file behavioral change + test:

- **`tests/ci/test_workflow_node_runtime.py`** — add `"actions/upload-pages-artifact": 5` to `NODE24_FLOOR`.
- Add a regression test that explicitly asserts the floor entry exists and that the production dogfood workflow (`docs-pages.yml`) and the scaffolded template (`workflow-pages.yml`) both satisfy it. (The existing `test_no_workflow_pins_a_node20_action_major` already iterates `WORKFLOWS`; adding the dict entry makes it automatically cover the new floor. The explicit "entry exists" test guards against future deletions.)
- This audit document itself — captures the rationale and serves as the documentation artifact CCE-34 wraps up against.

No source-code changes outside the test file. No template edits. No setup-skill changes.

## Non-goals

- Re-opening item 1. The dogfood publish loop is correct; the comment on line 3 of `config.yml` and the merged commit 32182e1 are the record.
- Implementing item 3's path-trigger narrowing. Documented as deferred above.
- Touching anything CCE-40 (durable state), CCE-41 (subagent forensics), CCE-55 (fence strip), CCE-56 (setup guide), or CCE-59 (actionlint path-filter) shipped. None of those work intersects the three original CCE-34 items.
- Transitioning the Jira ticket. The coordinator handles transitions; this PR posts a comment + link only.

## Test plan

- Add `"actions/upload-pages-artifact": 5` to `NODE24_FLOOR`.
- New explicit test: `test_upload_pages_artifact_in_node24_floor` — asserts the key exists with value 5. Future deletion of the entry fails this test loudly.
- Run `python3 -m pytest tests/ci/` to confirm green; run the full suite (`python3 -m pytest`) before opening the PR.
- The existing `test_no_workflow_pins_a_node20_action_major` will start covering `upload-pages-artifact` automatically; manual regression check: temporarily lower the dogfood workflow to `@v4`, watch the test fail; restore.

## Open questions

None. The audit answers are settled by evidence: item 1 by commit 32182e1, item 2 by the absent dict entry, item 3 by the explicit "minor" framing in the ticket plus the cost/benefit of the substitution machinery.
