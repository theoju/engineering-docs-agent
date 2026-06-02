---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/87
synthesized_into: []
---

# content-validator subagent

The content-validator runs the lint suite on pages the orchestrator just authored or edited, then surfaces structured pass/fail results. It is one of the seven subagents dispatched by `scripts/orchestrator_runner.py`.

## Inputs

The orchestrator dispatches the content-validator with four inputs:

| Field | Type | Description |
|---|---|---|
| `paths` | list of strings | Paths to the pages just authored or edited in this run. |
| `config_path` | string | Absolute path to the host's `.engineering-docs-agent/config.yml`. |
| `voice_samples` | object | Voice sample bundle, used if `voice_consistency` is enabled at Tier 2. |
| `plugin_root` | string | Absolute path to the plugin checkout. The lint runner lives at `<plugin_root>/scripts/lint/lint_runner.py`. |

`plugin_root` is the critical input added by PR #87. See [Path resolution](#path-resolution) below.

## What the subagent does

The subagent runs `scripts/lint/lint_runner.py` from the plugin tree, using the host config and the paths it received. The runner output is a structured JSON blob; the subagent aggregates per-rule pass/fail results per path. If `voice_consistency` is enabled in the config and not implemented as a script rule, the subagent performs an LLM check comparing prose against the voice samples.

The full procedure is in `agents/content-validator.md`.

## Output

The subagent returns a single JSON object with two arrays:

```json
{
  "passed": [{ "path": "docs/site-src/...", "rules": ["frontmatter_present", "..."] }],
  "failed": [
    { "path": "docs/site-src/...", "rule": "voice_consistency", "message": "...", "severity": "block" }
  ]
}
```

`severity` is either `block` (the orchestrator treats this page as failed) or `warn` (informational, run continues). The JSON schema is in `agents/schemas/content-validator.schema.json`.

## Path resolution

When the plugin is installed **inside a host repo** (vendored at `.docs-agent-plugin/` in CI), the path `scripts/lint/lint_runner.py` does not exist relative to the host repo root. This caused silent lint failures before PR #87.

The fix is a two-part contract:

1. **Orchestrator side** (`scripts/orchestrator_runner.py:65`): `_PLUGIN_ROOT` is computed from `Path(__file__).resolve().parent.parent` at module load time — this is always the plugin's own directory regardless of where the host repo lives.

2. **Subagent side** (`agents/content-validator.md`): the procedure uses the literal `plugin_root` value from the dispatch payload to construct the runner path. The subagent never assumes the runner is on `$PATH` or at a host-relative path.

The orchestrator injects `plugin_root` into every content-validator payload at dispatch time. The subagent constructs the runner invocation as:

```
python <plugin_root>/scripts/lint/lint_runner.py --config <config_path> --paths <paths...> --json
```

This is portable across three layouts:

- **Dogfood host** (this repo): `_PLUGIN_ROOT` points to the repo root; `scripts/lint/lint_runner.py` exists there.
- **Vendored install** (e.g. `.docs-agent-plugin/`): `_PLUGIN_ROOT` points into the vendor directory; lint runner resolves correctly.
- **Development checkout**: works identically to the dogfood case.

## Failure handling

If `lint_runner.py` exits non-zero and its output is unparseable, the subagent returns a single `failed` entry with `path: "*"` and `rule: "lint_runner"`, including the stderr. The orchestrator treats this as a blocking failure for the affected pages.

If the subagent dispatch itself fails (no `claude` binary, non-zero exit, empty stdout), `dispatch_subagent` returns `None` and the orchestrator adds a `partial_reason` to the run state. The run continues with the remaining pages; the `partial: true` flag in the docs-agent PR body makes the gap visible.

## Lint tiers

The host repo's `lint.tier1: default` setting enables all 7 Tier-1 rules. Tier-2 and Tier-3 rules are opt-in per rule in the host config. The runner reads the active rule set from the config at invocation time — the subagent does not hard-code any rules.

See the lint runner's own documentation and `scripts/lint/` for the full rule catalogue.
