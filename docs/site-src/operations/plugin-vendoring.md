---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# Plugin vendoring

When the engineering-docs-agent runs in a host repo's CI, it runs from a **vendored copy** of the plugin, not from a development checkout. The vendored layout differs from the development layout in one critical way: the plugin's scripts live under `.docs-agent-plugin/scripts/` in the host repo, not under `scripts/` at the repo root.

Subagents that invoke plugin scripts must use the injected `plugin_root` path, not a hardcoded `scripts/` prefix. Using the wrong path causes a silent crash: the linter process exits with `No such file or directory` and the entire content-validation stage is skipped.

## Layouts

**Development layout** (running locally against this repo as both plugin source and dogfood host):

```
scripts/lint/lint_runner.py
agents/content-validator.md
```

**Vendored layout** (running in CI on a host repo that has installed the plugin):

```
.docs-agent-plugin/scripts/lint/lint_runner.py
.docs-agent-plugin/agents/content-validator.md
```

The orchestrator runner (`scripts/orchestrator_runner.py`) resolves the absolute plugin root at startup using the `_PLUGIN_ROOT` constant and injects it as `plugin_root` in every subagent dispatch payload. Subagent prompts in `agents/` use the `<plugin_root>` angle-bracket marker to interpolate this value before invocation.

## How plugin_root is resolved

`_PLUGIN_ROOT` is set once in `scripts/orchestrator_runner.py` using `Path(__file__).parent.parent` — the directory two levels above the runner script. This is correct for both layouts:

- Development: `scripts/orchestrator_runner.py` → plugin root is the repo root.
- Vendored: `.docs-agent-plugin/scripts/orchestrator_runner.py` → plugin root is `.docs-agent-plugin/`.

The resolved path is an absolute `Path` object. The orchestrator serializes it to a string before adding it to the dispatch payload under the key `plugin_root`.

## Angle-bracket interpolation in agent prompts

Subagent prompt files in `agents/` use angle-bracket markers for values the orchestrator injects at dispatch time. The pattern was already present for other variables; `plugin_root` follows the same convention.

`agents/content-validator.md` invokes the lint runner as:

```
python <plugin_root>/scripts/lint/lint_runner.py ...
```

Before the agent receives the prompt, the orchestrator replaces `<plugin_root>` with the resolved absolute path. The agent never sees the raw marker.

## What broke before this fix

Prior to PR #87, the content-validator invoked `python scripts/lint/lint_runner.py` with no path prefix. On every vendored host (CCSA and ADIS were the first two onboarded in CCE-57/CCE-58), this resolved to the host repo's own `scripts/` directory, which does not contain `lint_runner.py`. The subprocess exited with `No such file or directory`, and the orchestrator logged `lint_block: lint_runner crashed` in `partial_reasons`.

All seven Tier-1 lint rules were silently skipped on every vendored host. The CCE-41 partial-PR safety net surfaced the failure in `state.json` rather than dropping it silently, but no content validation ran.

## Onboarding a new host

You do not need to configure `plugin_root` manually when onboarding a new host. The orchestrator resolves it from its own file path and injects it automatically. Verify the resolved value is correct by checking `current_run.json` after the first dry run:

```bash
python3 .docs-agent-plugin/scripts/orchestrator_runner.py --repo-root . --no-pr
cat .engineering-docs-agent/current_run.json | python3 -m json.tool | grep plugin_root
```

The value should be an absolute path ending in `.docs-agent-plugin` (for vendored installs) or the repo root (for development checkouts).

If the content-validator stage shows `lint_block: lint_runner crashed` in `partial_reasons`, the most likely cause is a stale vendored copy that predates PR #87. Update the vendored plugin to pick up the fix.
