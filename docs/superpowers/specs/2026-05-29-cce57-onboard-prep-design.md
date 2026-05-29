# CCE-57 — Onboarding prep for `theoju/claude-code-self-assessment`

## Background

CCE-57 onboards `theoju/claude-code-self-assessment` as the third engineering-docs-agent host. The target is the plugin's **first JS/TS host** — 450KB JavaScript + 232KB TypeScript, no Python. Per CLAUDE.md the plugin is generic-first; in practice the Python-host path has been the only one exercised.

The ticket's "Tasks" list is split:

- **User-only steps:** GitHub App install on target, repo secrets, branch protection, smoke `gh workflow run`. None of these can be done from this repo.
- **Plugin-side steps:** anything that makes the user's per-host work shorter, less surprising, and more deterministic when they ARE ready to install.

This spec scopes the plugin-side work and produces a runbook for the user-only steps.

## Problem

A user landing on CCE-57 today hits four sharp edges that are plugin-side defects, not target-side gaps:

1. **`templates/workflow-run.yml` does not work on a non-dogfood host.** The template runs `python scripts/orchestrator_runner.py` at the host root. The dogfood host has that file because it IS the plugin. An arbitrary host does not. The template assumes vendoring or pip-install but does neither.
2. **`setup_discover.detect_*` has no toolchain dimension.** Discovery surfaces `framework`, `ci`, `python` — nothing about Node/Bun/Deno or `package.json` shape. A JS/TS host's discovery report omits the most relevant signal for that host.
3. **No JS/TS fixture under `tests/fixtures/setup_repos/`.** Only `bare/` and `mkdocs_lensy/` exist. CLAUDE.md is explicit: "tests use fixtures that represent arbitrary hosts." JS/TS behavior is untested terrain because no fixture exercises it.
4. **No host-side pre-flight script.** When the user IS ready to install on the target, they have no `python scripts/preflight_host.py --repo-root <path>` that says: "Here's what discovery sees. Here's the config we'd write. Here's the workflow you should commit. Here are the secrets you must set." They follow the setup guide and hope.

CCE-57 is also gated on user actions (App register, secrets, branch protection) that this plugin repo cannot perform. Those gates remain; the prep work just minimizes everything around them.

## Goal

Land plugin-side changes that:

1. Make the shipped workflow template runnable on an arbitrary host (no vendoring required by the user).
2. Surface toolchain detection so the setup skill reports the JS/TS shape.
3. Lock JS/TS host behavior with a fixture and tests.
4. Provide a host-side pre-flight CLI that produces a readiness report.
5. Ship a CCE-57 runbook that turns the remaining user-gated steps into a copy-paste sequence.

## Non-goals

- Installing the plugin on `theoju/claude-code-self-assessment`. User-gated.
- Registering the GitHub App, setting repo secrets, configuring branch protection. User-gated, UI-only.
- Scaffolding a Docusaurus site into the target. That is per-host work the user runs.
- Changing the orchestrator pipeline. CCE-57 is pre-install scaffolding, not behavioral.
- Building a Docusaurus-flavored `site.default.yaml`. Out of scope — `setup_scaffold.py` already skips cleanly when not MkDocs; document the gap, do not paper it over.
- Polyglot voice samples / Tier 2 lint rules tuned for JS/TS prose. Separate ticket if needed.

## What I can ship from this repo NOW

| ID  | Deliverable                                                                                                                                                                                                                                          | Affects all hosts?                                          |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| P1  | Fix `templates/workflow-run.yml` so a non-dogfood host can run it without vendoring the plugin (check out plugin repo as a sibling, run from that path).                                                                                             | **Yes** — generic plugin defect, surfaced by CCE-57.        |
| P2  | Add `setup_discover.detect_toolchain(cwd)` — detects `package.json`, `bun.lockb`, `deno.json`; returns `{node, bun, deno, package_manager, docusaurus_dep}`. Surface in `discover()` output.                                                         | **Yes**                                                     |
| P3  | Add `tests/fixtures/setup_repos/js_docusaurus/` fixture — `package.json` + `docusaurus.config.ts` + minimal `docs/` tree. Add pytest cases pinning discovery output.                                                                                 | **Yes** — closes the "tests use fixtures" gap in CLAUDE.md. |
| P4  | Add `scripts/preflight_host.py` — CLI that runs against any host repo, prints discovery, the config the setup skill would write, the workflow it would write, and a secret-readiness checklist. JSON `--format json` output for machine consumption. | **Yes**                                                     |
| P5  | Write the CCE-57 runbook at `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md` — copy-paste sequence the user follows on the target. References P4 output.                                                                                 | CCE-57-specific (referenced by sibling CCE-58)              |

P1 is the highest-leverage change. Until P1 lands, the plugin's shipped workflow template is broken on every non-dogfood host, not just JS/TS ones. CCE-57 surfaces the bug; CCE-58 will hit it too.

## What the user must do on the target repo

These steps cannot be done from this repo and require human action. The runbook (P5) walks through each with the exact command/UI path.

1. Install the plugin: `claude plugin marketplace add https://github.com/theoju/engineering-docs-agent` then `claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace`.
2. Run `claude /engineering-docs-agent-setup` in the host worktree. The skill writes `.engineering-docs-agent/config.yml`, `state.json`, and (post-P1) a workflow that checks out the plugin repo as a sibling.
3. Register the GitHub App (or reuse an existing one). 11-step UI walkthrough lives in `docs/setup-guide.md` Part 1.2.
4. Install the App on `theoju/claude-code-self-assessment`. UI-only; `docs/setup-guide.md` Part 2.3.
5. Set five repo secrets via the GitHub UI: `CLAUDE_CODE_OAUTH_TOKEN`, `DOCS_AGENT_APP_ID`, `DOCS_AGENT_APP_PRIVATE_KEY`, `JIRA_API_TOKEN`, `JIRA_EMAIL`.
6. Commit the generated `.engineering-docs-agent/` + `.github/workflows/docs-agent-nightly.yml` to a feature branch and open a PR.
7. Configure branch protection (optional but recommended): `pytest`-style status checks + `actionlint`. The target is JS/TS, so the test check name will be Node-shaped (e.g. `test (node 20)`), not `pytest (3.11)`.
8. Smoke test: `gh workflow run docs-agent-nightly.yml -f reason="first-run smoke test"` and inspect the resulting PR.

Each of these is a single, focused action. The runbook (P5) gives the exact commands and the readiness check (P4) confirms the local state before the user pushes.

## Design

### P1 — Generic-host workflow template

The current `templates/workflow-run.yml:42` runs `python scripts/orchestrator_runner.py` from the host's root. On a non-dogfood host that path does not exist.

Add a `Check out engineering-docs-agent plugin` step before the orchestrator step:

```yaml
- name: Check out engineering-docs-agent plugin
  uses: actions/checkout@v5
  with:
    repository: theoju/engineering-docs-agent
    ref: main
    path: .docs-agent-plugin
```

Then change the orchestrator step to:

```yaml
run: python .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
```

The dogfood host's workflow at `.github/workflows/docs-agent-nightly.yml` remains unchanged because the dogfood IS the plugin — adding this step there is harmless but a no-op, so leave it. The template is what other hosts copy; that's where the fix lives.

The setup skill's "next steps" message points the user at this template. The skill should be updated to mention "the plugin checkout step lives in the workflow; do not delete it."

Non-goal: pinning the plugin to a specific tag/SHA. `ref: main` is correct for v0.1. A future ticket can wire in a release tag once the plugin cuts versioned releases.

### P2 — Toolchain detection

Add to `scripts/setup_discover.py`:

```python
def detect_toolchain(cwd: Path) -> dict:
    """Detect JavaScript / TypeScript toolchain hints.

    Returns a dict with:
      - node: bool (package.json present)
      - bun: bool (bun.lockb present)
      - deno: bool (deno.json or deno.jsonc present)
      - package_manager: "npm" | "yarn" | "pnpm" | "bun" | None (lockfile-derived)
      - docusaurus_dep: bool (docusaurus appears in package.json deps)
    """
```

Resolution order for `package_manager`:

1. `bun.lockb` → `bun`
2. `pnpm-lock.yaml` → `pnpm`
3. `yarn.lock` → `yarn`
4. `package-lock.json` → `npm`
5. else `None`

`docusaurus_dep` parses `package.json` only — checks `dependencies` / `devDependencies` for any key starting with `@docusaurus/`. Quiet on parse failure (returns `False`).

Wire into `discover()`:

```python
out["toolchain"] = detect_toolchain(cwd)
```

The setup skill renders the toolchain block in its discovery summary. No new prompts; this is observational.

### P3 — JS/TS fixture and tests

Add `tests/fixtures/setup_repos/js_docusaurus/`:

```
package.json              # {"name":"x","devDependencies":{"@docusaurus/core":"^3.0.0"}}
package-lock.json         # empty stub: {}
docusaurus.config.ts      # export default { title: "x" };
docs/intro.md             # # intro
.github/workflows/ci.yml  # minimal workflow with JIRA_BASE_URL hint
```

Tests in `tests/setup/test_setup_discover.py`:

- `test_detect_toolchain_js_docusaurus_fixture` — runs discovery on the fixture, asserts `framework == "docusaurus"`, `toolchain.node is True`, `toolchain.package_manager == "npm"`, `toolchain.docusaurus_dep is True`.
- `test_detect_toolchain_bare` — empty dir returns all-False.
- `test_detect_toolchain_bun_lockfile` — tmp_path with `bun.lockb` returns `package_manager == "bun"`.
- `test_detect_toolchain_invalid_package_json` — malformed `package.json` does not raise; returns `docusaurus_dep == False`.
- `test_discover_surfaces_toolchain_block` — `discover(tmp_path)["toolchain"]` is always present and is a dict.

### P4 — `preflight_host.py`

CLI signature:

```bash
python scripts/preflight_host.py --repo-root /path/to/host [--format text|json]
```

Output sections:

1. **Discovery** — full `discover()` dict (framework, source_dir, lens_paths, ci, jira_hint, python, openapi_hint, toolchain, pages_publishable).
2. **Proposed config** — the dict the setup skill would write to `.engineering-docs-agent/config.yml`, computed without writing it.
3. **Proposed workflow** — the rendered `workflow-run.yml` (post-P1), substituted with concrete values.
4. **Secrets checklist** — for each `${{ secrets.X }}` reference in the proposed workflow, a `[ ] X` line. The user ticks each off via the GitHub UI.
5. **Warnings** — `framework: None` and other detection gaps.

Text format is the default for human consumption; JSON for piping into other tooling.

`preflight_host.py` does not write anything to the host repo. Read-only. The setup skill is what actually writes the files.

### P5 — CCE-57 runbook

Path: `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md`. Per the ticket assignment this is the "deliverable-only" artifact if no code lands; with P1-P4 landing, the runbook is the user's copy-paste sequence.

Structure (8 steps, mapped 1:1 to the "What the user must do" list above):

1. Clone the target.
2. Run preflight: `python <plugin>/scripts/preflight_host.py --repo-root .` — read the report.
3. Install plugin in the target.
4. Run `claude /engineering-docs-agent-setup` — confirm/override the discovery values preflight surfaced.
5. Register / reuse GitHub App (link to `docs/setup-guide.md` Part 1.2).
6. Install App on target (link to Part 2.3).
7. Set secrets (table copied from preflight output's checklist).
8. Commit, push, open PR, smoke `gh workflow run`, validate the PR.

Each step has an "Expected" block and a "If this fails" block pointing at `docs/setup-guide.md` troubleshooting Part 6.

## Test plan

- `python3 -m pytest tests/setup/` — new toolchain tests pass; old tests pass unchanged.
- `python3 -m pytest` — full suite green (no regression).
- `python scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/js_docusaurus` — runs without error, output includes toolchain block.
- `python scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/mkdocs_lensy` — runs without error, output is mkdocs-flavored.
- Workflow template lint: `python -c "import yaml; yaml.safe_load(open('templates/workflow-run.yml'))"` — no syntax break.
- Manual: read the runbook end-to-end; verify each step has expected/recovery hint.

## Files changed

- `templates/workflow-run.yml` — add `Check out engineering-docs-agent plugin` step, update orchestrator path. (~8 line delta)
- `scripts/setup_discover.py` — add `detect_toolchain` + wire into `discover()`. (~50 line delta)
- `scripts/preflight_host.py` — new file, ~150 lines.
- `tests/fixtures/setup_repos/js_docusaurus/...` — new fixture, ~5 small files.
- `tests/setup/test_setup_discover.py` — add ~5 toolchain tests. (~80 line delta)
- `tests/setup/test_preflight_host.py` — new file, ~80 lines.
- `skills/engineering-docs-agent-setup/SKILL.md` — mention toolchain block in discovery summary; note that workflow includes the plugin checkout step.
- `docs/superpowers/specs/2026-05-29-cce57-onboard-prep-design.md` — this file.
- `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md` — the user runbook.
- `docs/superpowers/plans/2026-05-29-cce57-onboard-prep.md` — plan.

## Risk

- **Workflow template change is a behavior change for any future hosts.** The dogfood host doesn't use this template, so dogfood is unaffected. But any host that already ran the old setup-skill output is using the broken template — they'd need a re-scaffold. Mitigation: the change is additive (one new step + one path change); easy to apply by hand to existing hosts.
- **`detect_toolchain` reads `package.json`.** If `package.json` is huge or malformed it could waste time; mitigation: read with size cap (32KB) and catch JSONDecodeError.
- **Race with in-flight nightly runs.** None of these files are written by the nightly authoring path (this is setup/scripts/templates territory). No conflict.

## Out of scope

- Docusaurus-flavored `site.default.yaml`. Setup skill keeps printing the "no scaffold" message for non-MkDocs hosts; that's correct fallback behavior.
- Auto-detecting an existing `package.json` `scripts.build` and wiring it into `publishing.build_command`. Possible follow-up.
- Building a custom workflow for hosts that pin Node versions. The default `actions/setup-node@v4` plus the host's existing `package.json` engines field is enough for v0.1.
- Bun-specific orchestrator path. The orchestrator is Python; Bun on the host is unrelated to running the plugin.
