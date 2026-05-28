---
description: Roadmap and preparation summary for the CCE-5 through CCE-9 batch — orchestrator hardening, state I/O validation, test harness foundation, and v0.1.0 release prep.
source_files:
  - release/*
  - scripts/orchestrator_runner.py
  - scripts/state_io.py
  - tests/conftest.py
last_reviewed: "2026-05-28"
status: draft
---

# CCE-5 through CCE-9: Batch Prep Roadmap

This page covers the architectural groundwork delivered across Jira tickets CCE-5 through CCE-9. Together they establish the orchestrator's runtime reliability: validated config/state loading, a dry-run test harness, and a releasable v0.1.0 baseline that subsequent capabilities build on.

## What the batch covers

The five tickets fall into three areas:

1. **Orchestrator runtime hardening** — `scripts/orchestrator_runner.py` gained the `dispatch_subagent` path, the `_rescue_json_object` fallback parser (CCE-15 retroactively references the pattern; the guard itself landed here), and the `--dry-run-subagents` flag that lets the full pipeline run against canned fixture outputs without invoking the Claude CLI.

2. **State and config I/O validation** — `scripts/state_io.py` introduced hard-fail schema validation on both `config.yml` and `state.json` at load time. The `_validate_lens_paths_are_editable` invariant (every `lens_paths` entry covered by at least one `agent_editable_paths` glob) runs at boot so misconfigured hosts fail loudly before touching any files.

3. **Test harness and v0.1.0 seed** — `tests/conftest.py` wires the dry-run fixture path as the default test mode, monkeypatches `dispatch_subagent`, and registers the `@pytest.mark.live` gate to keep real-LLM tests out of the default run. The `release/*` artifacts pin the v0.1.0 tag commit as `last_successful_run.head_sha` in `state.example.json`, giving `source-collector` a real diff window over the entire CCE-1 through CCE-9 PR history.

## Key files

| File | Role |
|---|---|
| `scripts/orchestrator_runner.py` | Main pipeline entry point; `dispatch_subagent`, `--dry-run-subagents`, JSON rescue |
| `scripts/state_io.py` | Config/state loading with `ConfigError`, `StateError`, lens-path invariant check |
| `tests/conftest.py` | Pytest harness; dry-run default, live-test opt-in, subagent monkeypatch |
| `release/*` | v0.1.0 changelog and seed state for dogfood bootstrap |

## Invariants introduced

Two invariants introduced in this batch are load-time enforced and must hold in all future configs:

- **Lens coverage:** every `docs.lens_paths` entry must match at least one `docs.agent_editable_paths` glob. The compatibility check is bidirectional — glob anchor and lens root must share a path branch. See `state_io.py:_validate_lens_paths_are_editable`.
- **State schema:** `state.json` is validated against its JSON schema on every load. A schema mismatch raises `StateError` and halts the run. Never write `state.json` outside `state_io.py`.

## Bootstrap reference

The README's dogfood bootstrap depends on outputs from this batch:

```bash
cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
```

The `--no-pr` flag and the v0.1.0 seed SHA together give you a dry run that exercises every subagent dispatch without opening a PR or spending additional LLM tokens beyond the subagent calls themselves.

## Next steps

These tickets close out the v0.1.0 foundation. CCE-10 and later address Jira enrichment wiring, live integration test coverage, and the `--setting-sources` hardening that closes the output-contamination pathway identified in CCE-14/15.
