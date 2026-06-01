---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin Vendoring in CI

How to vendor the `engineering-docs-agent` plugin at a non-root path in CI, and what the `plugin_root` dispatch field does to keep lint rules working.

## The standard vendoring convention

When your CI workflow installs the plugin, it lands at `.docs-agent-plugin/` relative to the host repo root. That path is the standard CI vendoring convention across all host repos.

The orchestrator resolves `_PLUGIN_ROOT` at startup and passes it to every subagent dispatch payload as `plugin_root`. Before PR #87, the content-validator subagent invoked `python scripts/lint/lint_runner.py` as a bare relative path, which resolved from the host root rather than the plugin root. On a vendored install all 7 Tier-1 lint rules crashed, and the orchestrator surfaced `lint_block` in `partial_reasons`.

## What `plugin_root` does

`orchestrator_runner.py` sets `plugin_root` in the dispatch payload to the value of `_PLUGIN_ROOT` — the absolute path where the plugin is installed. The content-validator agent contract now interpolates `<plugin_root>` in the lint invocation command:

```
<plugin_root>/scripts/lint/lint_runner.py --config <host_root>/.engineering-docs-agent/config.yml --paths <docs_dir>/**/*.md --json
```

The orchestrator sets `plugin_root`; the agent uses it. Neither component hard-codes the install location.

## Vendoring layout

A typical vendored host looks like this:

```
<host-repo>/
  .docs-agent-plugin/          # plugin install — this is _PLUGIN_ROOT
    scripts/
      lint/
        lint_runner.py
      orchestrator_runner.py
      ...
    agents/
    ...
  .engineering-docs-agent/
    config.yml
    state.json
  docs/site-src/               # or whatever docs_dir is configured
```

The CI workflow installs the plugin before the orchestrator step. A minimal install step:

```yaml
- name: Install docs-agent plugin
  run: |
    mkdir -p .docs-agent-plugin
    git clone --depth=1 https://github.com/theoju/engineering-docs-agent .docs-agent-plugin
```

Then invoke the orchestrator via the vendored path:

```yaml
- name: Run docs-agent
  run: python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root .
  env:
    CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    GITHUB_TOKEN: ${{ secrets.GITHUB_APP_TOKEN }}
```

`orchestrator_runner.py` detects its own location and sets `_PLUGIN_ROOT` accordingly — no extra config required.

## Verifying the fix

After onboarding, confirm lint rules fire correctly by inspecting the run's `partial_reasons` in `.engineering-docs-agent/state.json`. A healthy run with lint enabled has an empty `partial_reasons` list. `lint_block` in that list means the lint invocation still fails to resolve — check that the plugin was cloned to `.docs-agent-plugin/` and that `orchestrator_runner.py` is present at `.docs-agent-plugin/scripts/orchestrator_runner.py`.

For raw stdout from the content-validator dispatch, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking the orchestrator. The validator's output is written to a timestamped file in that directory.

## Pipeline integration test

PR #87 added a pipeline integration test that asserts `plugin_root` is present in the content-validator dispatch payload. Run it with:

```bash
python3 -m pytest tests/ -k "plugin_root"
```

The test uses the fixture-driven dry-run path — no LLM invoked, no cost.

## Related tickets

- **CCE-67**: root-cause fix (this PR)
- **CCE-41**: forensics design that surfaced the breakage
- **CCE-57, CCE-58, CCE-64, CCE-65, CCE-66**: host-onboarding and CI wave that exposed the gap
