# Durable state persistence — design spec

**Ticket:** CCE-40
**Author:** Theo Jungeblut (with Claude Opus 4.7)
**Date:** 2026-05-28
**Status:** Draft

## 1. Problem

The CCE-39 smoke-test (`gh run view 26599462402`) exited in 3 seconds with the output:

```
On branch docs-agent/2026-05-28T20
nothing to commit, working tree clean
```

Tracing the failure:

- `.engineering-docs-agent/state.json` is gitignored. In CI it does not exist.
- `scripts/state_io.py:179-188` returns `{"version": "1"}` for the missing-file case — no `last_successful_run`, no `head_sha`.
- `scripts/orchestrator_runner.py:857` reads `state.get("last_successful_run", {}).get("head_sha", "")` and passes `last_sha=""` to `source-collector`.
- Source-collector with empty `last_sha` returns zero PRs. Page-author has nothing to author. `git commit` finds nothing staged. Runner exits 1.

This is also the root cause of brainstorm Issue #1 ("What's New only has PR #39 entry"). Every prior run hit the same empty-state path. The deployed site has not been updated by the agent since CCE-31.

## 2. Goal

Make state persist across nightly runs through git itself, so each cron fire advances `last_successful_run.head_sha` and the next fire picks up from there. No external state store, no separate promote workflow.

## 3. Architecture

State splits by lifecycle, not by file count:

| Field                                                                       | Lifecycle                         | Storage                                                                      |
| --------------------------------------------------------------------------- | --------------------------------- | ---------------------------------------------------------------------------- |
| `version`, `last_successful_run.*`, `dismissed_gap_flags`, `cursors`        | persistent (one update per merge) | committed `state.json`                                                       |
| `current_run.*` (started_at, head_sha, partial, partial_reasons, pr_number) | ephemeral (one run's lifetime)    | in-memory only; optionally written to `DOCS_AGENT_DEBUG_DIR` for diagnostics |

Merge-as-promotion is inherent in git:

1. Cron starts. Runner reads `state.json` from main's checkout.
2. Runner runs the pipeline, then promotes `current_run.head_sha` into `last_successful_run.head_sha` on the in-memory state dict.
3. Runner writes the persistent fields back to `state.json` on the working tree (via the new `save_persistent_state` helper that drops ephemeral fields).
4. The existing `git checkout -B docs-agent/<date>` + `git add . && git commit` path (`scripts/orchestrator_runner.py:1376-1400`) carries `state.json` into the docs-agent PR — **once it is no longer gitignored**.
5. Human reviews and merges the PR. Main's `state.json` is now advanced.
6. Next cron reads the advanced state. Window is `new_last_sha..HEAD`.

## 4. Files touched

### Modify

| File                                     | Change                                                                                                                                                                                                                             |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.gitignore`                             | Remove `.engineering-docs-agent/state.json`                                                                                                                                                                                        |
| `templates/state.schema.json`            | Drop `current_run` from `properties`                                                                                                                                                                                               |
| `scripts/state_io.py`                    | Add `save_persistent_state(path, state)`; `load_state_validated` strips legacy `current_run` from committed state with an `info_only` partial reason                                                                               |
| `scripts/orchestrator_runner.py`         | Replace 4 `state_path.write_text(json.dumps(state, indent=2))` sites (lines 1193, 1209, 1212, 1247) with `save_persistent_state(state_path, state)`; insert `last_successful_run` advancement immediately before line 1193's write |
| `.engineering-docs-agent/state.json`     | Commit at current seed (`bcfc489ac5ccaf2533ad8634b80317d8c9330be8`, `pr_number: 41`) — this is what the local file already contains                                                                                                |
| `README.md`                              | Update §"Self-hosting (dogfood)": state.json is committed; remove the `cp` step; explain merge-as-promotion in two sentences                                                                                                       |
| `skills/engineering-docs-agent/SKILL.md` | Update "State transitions" + "PR handling" sections: replace "promotion happens via a follow-up workflow when the PR merges" with the merge-as-promotion model implemented here                                                    |

### Create

| File                                                | Purpose                                                                                                                           |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `tests/state_io/test_save_persistent_state.py`      | Unit tests for the helper: drops `current_run`, preserves other fields, atomic write semantics, schema-valid output               |
| `tests/state_io/test_load_state_legacy_strip.py`    | Migration test: committed state with `current_run` is loaded with `current_run` stripped and an info-only partial reason recorded |
| `tests/orchestrator/test_runner_state_promotion.py` | Integration test: runner advances `last_successful_run.head_sha` before commit; the committed file does not contain `current_run` |

### Remove

None.

## 5. Detailed design

### 5.1 `save_persistent_state(path, state)`

```python
# scripts/state_io.py
_EPHEMERAL_KEYS = ("current_run",)

def save_persistent_state(path: Path, state: dict[str, Any]) -> None:
    """Write only persistent fields of `state` to `path` as JSON.

    Ephemeral fields (current_run) are dropped before writing. The on-disk
    copy is the source of truth promoted by merging the docs-agent PR.
    """
    persistent = {k: v for k, v in state.items() if k not in _EPHEMERAL_KEYS}
    path.write_text(json.dumps(persistent, indent=2) + "\n")
```

The trailing newline matches git's "files end with newline" convention and avoids a noisy whitespace warning on commit.

The in-memory `state` dict is unchanged; `current_run` continues to be used by the runner for its lifetime.

### 5.2 `load_state_validated` migration

`load_state_validated` returns `(state, notes)` where `notes` is a list of strings the runner appends to `current_run.partial_reasons` as `info_only`. This keeps the helper pure (no logging side effects, no sentinel fields) while surfacing the migration to the run digest.

```python
# scripts/state_io.py
def load_state_validated(path: Path) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    if not path.exists():
        return {"version": "1"}, notes
    raw = json.loads(path.read_text())
    if "current_run" in raw:
        # Pre-CCE-40 state had current_run persisted. Drop it; the runner
        # creates a fresh one each run anyway (orchestrator_runner.py:836-843).
        raw = {k: v for k, v in raw.items() if k != "current_run"}
        notes.append("state_legacy_current_run_stripped")
    schema = json.loads((TEMPLATES_DIR / "state.schema.json").read_text())
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as e:
        raise StateError(f"state invalid at {e.json_path}: {e.message}") from e
    return raw, notes
```

Callers at `orchestrator_runner.py:815` unpack the tuple and pass each note to `add_partial(state, note, info_only=True)` after `current_run` is initialized.

### 5.3 Runner state advancement

In `scripts/orchestrator_runner.py`, immediately before the existing line 1193 (the first `state_path.write_text` after What's New is composed):

```python
# Promote current_run.head_sha into last_successful_run. The merge of the
# docs-agent PR is what actually promotes this to main; until then it lives
# only on the docs-agent branch and on disk locally.
state["last_successful_run"] = {
    "head_sha": state["current_run"]["head_sha"],
    "completed_at": now,  # ISO timestamp captured earlier in run()
}
state["current_run"]["pr_number"] = None
save_persistent_state(state_path, state)
```

The four other write sites (lines 1209, 1212, 1247) become `save_persistent_state(state_path, state)` calls. They no longer need to worry about ephemeral fields contaminating the committed file.

### 5.4 Schema change

Remove the entire `current_run` property block from `templates/state.schema.json` (lines 16-26 of the current file). No other fields change. The schema remains permissive — there is no `additionalProperties: false`, so older state files that still carry `current_run` continue to validate. The runner just won't write that field going forward.

After the edit, `state.schema.json`'s `properties` lists exactly `version`, `last_successful_run`, `dismissed_gap_flags`, `cursors`.

### 5.5 Seed file

`.engineering-docs-agent/state.json` enters version control with exactly:

```json
{
  "version": "1",
  "last_successful_run": {
    "head_sha": "bcfc489ac5ccaf2533ad8634b80317d8c9330be8",
    "pr_number": 41
  }
}
```

This is what the local file already contains. The first cron fire after CCE-40 merges processes PRs #41 through current main HEAD — backfilling all the What's New entries that have been missing.

### 5.6 README update

Replace the existing dogfood bootstrap recipe at `README.md:39-48`:

```markdown
Bootstrap a fresh checkout:

\`\`\`bash
python3 scripts/orchestrator_runner.py --repo-root . --no-pr
\`\`\`

The committed `.engineering-docs-agent/state.json` is the source of truth for `last_successful_run.head_sha`. Each merged `docs-agent/YYYY-MM-DD` PR advances it in main — there is no separate promote workflow. For per-subagent raw-stdout diagnostics, set `DOCS_AGENT_DEBUG_DIR=/tmp/cce-debug` before invoking.

`state.example.json` is the seed template for fresh forks installing the plugin; this host already has a real `state.json`.
```

The `cp .engineering-docs-agent/state.example.json .engineering-docs-agent/state.json` step disappears.

## 6. Migration & backward compatibility

**Host repos forked before CCE-40:** their local `state.json` may contain `current_run`. `load_state_validated` strips it and the runner records an info-only partial reason `state_legacy_current_run_stripped`. No operator action required.

**`state.example.json`:** stays for fresh-host bootstrap via the setup skill. Its content (pointing at SHA `1f4563c…`) does not change — that is the v0.1.0 tag commit, the right backfill window for a fresh host.

**Generic-host design note:** Hosts installing the plugin must seed `.engineering-docs-agent/state.json` from `state.example.json` (or pin to their own starting SHA) and commit it to their fork. Whatever logic does the seeding is host-side — the merge-as-promotion flow then takes over on first nightly, with no host-specific code path in this spec. Whether `/engineering-docs-agent-setup` automates the seed is a separate setup-skill concern.

## 7. Risk & mitigation

| Risk                                                                              | Mitigation                                                                                                                                                                                                                   |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Operator-edited `dismissed_gap_flags` conflicts with nightly's state.json advance | Different keys in the same JSON object; git merges cleanly. If both touch the same key, normal merge conflict surfaces for the operator.                                                                                     |
| Two nightly runs (cron + manual dispatch) race on the same docs-agent branch      | Already mitigated by the CCE-39 concurrency group `docs-agent-nightly` (cancel-in-progress: false). Manual fires queue.                                                                                                      |
| Runner writes state.json with new SHA but PR open fails                           | State.json sits in the runner's local working tree; nothing reaches main. Next run reads the unchanged committed state and tries again with the same window. Self-healing.                                                   |
| Partial run merged by human                                                       | Intentional. `last_successful_run` advances; partial_reasons (ephemeral) are dropped on next run start (matches existing CCE-5 fresh-current_run semantics). Operators see partial-run status in the PR body before merging. |
| State.json schema drift between runner version and committed state                | `load_state_validated` already raises `StateError` on schema mismatch; the actionable error message tells the operator to update.                                                                                            |

## 8. Acceptance criteria

- [ ] `.gitignore` no longer excludes `.engineering-docs-agent/state.json`
- [ ] `templates/state.schema.json` does not list `current_run` under `properties`
- [ ] `scripts/state_io.py` exports `save_persistent_state` that strips ephemeral fields and writes valid JSON ending with `\n`
- [ ] `scripts/orchestrator_runner.py`'s four state-write sites use `save_persistent_state`; `last_successful_run` is advanced before the first such write
- [ ] `.engineering-docs-agent/state.json` is tracked in git at the seed value `bcfc489…` with `pr_number: 41`
- [ ] `README.md` dogfood section reflects the new model
- [ ] Full pytest passes (`python3 -m pytest`)
- [ ] New tests cover: helper unit (`drops current_run`, writes valid JSON, trailing newline); migration (legacy current_run stripped); runner integration (committed state.json contains advanced last_successful_run, no current_run)
- [ ] Manual smoke-test post-merge: `gh workflow run docs-agent-nightly.yml` on main produces a docs-agent PR whose state.json shows `last_successful_run.head_sha` advanced from `bcfc489…` to the post-merge main HEAD

## 9. Out of scope

- **CCE-42:** Chain publish-verification (`publish-verifier` subagent) after the docs-agent PR merges. Additive, not blocking.
- **Operator UI for editing `dismissed_gap_flags`:** stays a manual JSON edit + PR review.
- **Cross-host state-storage substrates** (S3, KV, GitHub issue body): rejected in the prior brainstorm.
- **Promote workflow:** rejected after `open_or_append_pr` investigation showed merge-as-promotion is already inherent in the runner's commit path.

## 10. References

- Smoke-test that exposed the bug: https://github.com/theoju/engineering-docs-agent/actions/runs/26599462402
- `scripts/orchestrator_runner.py:1193, 1209, 1212, 1247` — current state-write sites
- `scripts/orchestrator_runner.py:1376-1400` — existing `git add . && git commit` path
- `scripts/state_io.py:179-188` — missing-file return path
- CCE-39: nightly cron (the trigger this spec makes useful)
- CCE-38: bootstrap fail-fast (the most recent merged change to the runner)
- CCE-34: frontmatter-aware What's New prepend (touches the same state-write path)
- engineering-docs-agent skill ("State transitions" + "PR handling"): the skill text says "promotion happens via a follow-up workflow when the PR merges." This spec **supersedes** that with merge-as-promotion (no separate workflow needed). The skill text should be updated as part of this change — added to §4 Files touched below if not already covered.
