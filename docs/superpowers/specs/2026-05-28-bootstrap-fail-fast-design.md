# Bootstrap fail-fast — post-write verification + progress file

**Status:** approved 2026-05-28 (brainstorm + 2 locked decisions); implementation plan next.
**Jira:** CCE-38.
**Origin:** retrospective on the CCE-36 / CCE-37 release run. Four uncaptured interventions were enumerated; three (gaps 2, 3, 4) share a single root cause and are scoped here. Gap 5 (Mermaid setup smoke test) and gap 6 (closed-shadow render gate) are out of scope — the latter shipped in CCE-37.

---

## Why this exists

`run_bootstrap_core` (`scripts/orchestrator_runner.py:1251`) trusts the page-author subagent's `ok=true` flag without re-reading the artifact it wrote. The CCE-36 release surfaced three intervention patterns that all trace back to that single missing contract:

| Gap | Symptom                                                                                                                           | Root mechanism                                                                                                                                                              |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2   | I had to `ls docs/site-src/architecture/ \| wc -l` to guess "stuck vs slow", and misdiagnosed a long page as hung                 | No external progress signal between dispatches; the ledger is only printed at the end                                                                                       |
| 3   | cce15's description contained `additionalProperties: false` inside backticks; the bare `: ` broke YAML parsing of the frontmatter | `dispatch_validated` checks the agent's **reply schema** against `agents/schemas/page-author.json`; it never re-parses the **frontmatter actually written to disk**         |
| 4   | 8/17 pages shipped with one- or two-word descriptions that passed schema (presence-only) and required manual rewriting            | `frontmatter_schema` lint at `scripts/lint/frontmatter_schema.py:42` only enforces field presence; no rule enforces description length, vocabulary, or "not equal to title" |

Resume is _already_ implemented (`if target_path.exists(): skipped_existing; continue` at `scripts/orchestrator_runner.py:1319`) — that's why a kill-and-restart of bootstrap "just works". The defect is therefore **not** missing functionality; it's missing verification + missing visibility.

This spec adds the verification, surfaces the visibility, and reuses the existing idempotency-on-existence to give free retry-on-rerun.

## The hard constraint: stdlib-first runtime

Per `CLAUDE.md`: "Python: stdlib-first. New runtime deps require explicit justification in the spec." This work introduces **no new runtime dependencies.** Every new module reuses what's already on the runtime path: `yaml`, `json`, `argparse`, `pathlib`, `subprocess`, plus the in-repo `frontmatter_contract` and a new sibling helper `archive_indexes.parse_frontmatter_strict` (see below).

## Why a new parser helper

`archive_indexes.parse_frontmatter` (`scripts/archive_indexes.py:45`) intentionally swallows `yaml.YAMLError` and returns `{}` — it has no way to distinguish "bad YAML", "no frontmatter at all", and "valid empty frontmatter". `lint/frontmatter_schema.parse_frontmatter` collapses bad YAML and absent frontmatter into a single `None`. Neither shape lets the bootstrap callback record `frontmatter_parse_error` vs `frontmatter_missing` with distinct ledger reasons.

Add a sibling `parse_frontmatter_strict(text) -> dict` in `scripts/archive_indexes.py`:

- Raises `yaml.YAMLError` on parse failure (the original exception, unwrapped).
- Raises `ValueError("no frontmatter")` when the document does not start with `---` or has no closing fence.
- Returns the parsed dict on success (with `{}` as the success value when the frontmatter block is present but empty).

The existing `parse_frontmatter` stays untouched — its callers in `source_map.py`, `whats_new` prepend logic, and elsewhere keep working unchanged. The new helper is the contract any caller that _needs_ the distinction can adopt.

## Architecture

Three additions, layered to keep the contract change small and the lint rule independently testable:

| Layer         | New thing                                                                                | Reuses                                                                                                |
| ------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Dispatch      | `dispatch_verified(name, payload, *, post_write_check, …)` wrapping `dispatch_validated` | `dispatch_validated` (`orchestrator_runner.py:486`), no new schema                                    |
| Lint          | `scripts/lint/description_quality.py` (Tier-1 default, generator-aware)                  | `frontmatter_contract.section_generator_for`, `lint_runner` `--json` interface                        |
| Observability | `.engineering-docs-agent/bootstrap.progress.json`, atomic-write per page transition      | Reuses the existing `.engineering-docs-agent/` state directory; same JSON conventions as `state.json` |

A bootstrap-specific callback composed in `run_bootstrap_core` glues the first two together; the progress file is the orchestrator loop's responsibility, not the wrapper's.

### The `dispatch_verified` wrapper

Signature:

```python
def dispatch_verified(
    name: str,
    payload: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path,
    post_write_check: Callable[[Path, dict], tuple[bool, list[str]]] | None = None,
    target_path: Path | None = None,
    manifest_page: dict | None = None,
) -> tuple[dict | None, list[str]]:
```

Behavior:

1. Delegate to `dispatch_validated(name, payload, dry_run_dir=…, cwd=…)`. If it returns `(None, reasons)`, return that unchanged — existing schema-validation semantics are preserved.
2. If `post_write_check is None`, return the validated `(out, reasons)` unchanged. Callers that don't opt in see no behavior change.
3. Otherwise, call `post_write_check(target_path, manifest_page)`. On `(True, [])`, return the validated `(out, reasons)`. On `(False, check_reasons)`:
   - `target_path.unlink(missing_ok=True)` — delete the file the agent wrote, so the next `--bootstrap-core` run retries it (the existing `if target_path.exists()` skip is the retry mechanism).
   - Return `(None, reasons + check_reasons)`.

The wrapper is content-agnostic; all artifact knowledge lives in the callback.

### The `description_quality` lint rule

New file: `scripts/lint/description_quality.py`. Standard rule shape (matches `frontmatter_schema.py`):

- `RULE_NAME = "description_quality"`, `SEVERITY = "block"`.
- `--config`, `--paths`, `--json` flags.
- `check_path(path, config) -> (ok, message)` and `main()` returning 1 on any failure.
- **Generator-aware**: when `section_generator_for(path, config) != "agent-authored"`, returns `(True, "not agent-authored; skipped")`. The other lenses use a different required-field set (`status`, `sources`, `synthesized_into`); imposing a long-description requirement on them would be wrong.

Config (under `lint.tier1.description_quality`, all optional):

| Key                     | Default | Meaning                                                                                |
| ----------------------- | ------- | -------------------------------------------------------------------------------------- |
| `min_words`             | `6`     | Minimum whitespace-tokenised word count in `description`                               |
| `forbid_equal_to_title` | `true`  | Reject when `description.strip().lower() == title.strip().lower()`                     |
| `forbid_trailing_colon` | `true`  | Reject when `description.rstrip().endswith(":")` (catches `"Source-collector:"` cases) |

Registered in `lint_runner.TIER1_DEFAULT` (extending the list to 8 rules). Hosts that don't want it can drop `tier1: default` and enumerate the seven they want.

A side door for in-process use (`check_fm(fm: dict, manifest_page: dict, config: dict) -> (bool, str)`) lets the bootstrap callback skip the subprocess hop. It must be a pure function over the dict; `check_path` is the file-reading shim that calls it.

### The bootstrap callback

Composed once at the top of `run_bootstrap_core`, after config is loaded:

```python
def _check(target_path: Path, page: dict) -> tuple[bool, list[str]]:
    rel = target_path.resolve().relative_to(repo_root.resolve())
    try:
        fm = archive_indexes.parse_frontmatter_strict(target_path.read_text())
    except yaml.YAMLError as e:
        return False, [f"frontmatter_parse_error: {rel}: {e.__class__.__name__}"]
    except ValueError:
        return False, [f"frontmatter_missing: {rel}"]
    ok, msg = description_quality.check_fm(fm, page, config)
    if not ok:
        return False, [f"description_quality: {rel}: {msg}"]
    return True, []
```

Passed to `dispatch_verified(..., post_write_check=_check, target_path=target_path, manifest_page=page)` from inside the existing per-page loop at `orchestrator_runner.py:1311-1352`. The loop body changes one call; the surrounding ledger-extending code stays the same.

### The progress file

Path: `.engineering-docs-agent/bootstrap.progress.json` (sibling of `state.json`).

Shape (compact-overwritten, not append-only):

```json
{
  "phase": "bootstrap",
  "started_at": "2026-05-28T07:14:00+00:00",
  "total": 17,
  "current_index": 7,
  "current_page": "architecture/cce23-source-map-drift.md",
  "current_page_started_at": "2026-05-28T07:16:32+00:00",
  "completed": ["architecture/cce-capability-c-canonical-core-citations.md"],
  "skipped_existing": [],
  "failed": [
    {
      "path": "architecture/cce15-source-collector-root-cause-sweep.md",
      "reason": "frontmatter_parse_error: …"
    }
  ]
}
```

Write cadence (atomic via temp-file + `os.replace`):

| When                          | Fields updated                                                                            |
| ----------------------------- | ----------------------------------------------------------------------------------------- |
| Start of `run_bootstrap_core` | All — `current_index=0`, `current_page=null`, empty lists                                 |
| Before each dispatch          | `current_index += 1`, `current_page`, `current_page_started_at`                           |
| After successful authoring    | Append to `completed`                                                                     |
| After `skipped_existing`      | Append to `skipped_existing`; `current_index` still advances                              |
| After verification failure    | Append `{path, reason}` to `failed`; `current_index` still advances                       |
| End of run                    | File deleted (`unlink(missing_ok=True)`); `state.json` already carries the durable record |

The "delete on completion" rule means an existing `bootstrap.progress.json` is itself a signal that a run is in progress (or crashed mid-flight) — useful for monitors and humans alike.

## Data flow

```
                       run_bootstrap_core
                              │
       ┌──────────────────────┴──────────────────────┐
       │ for page in manifest_pages:                 │
       │   if target.exists(): skip; advance         │
       │   else:                                     │
       │     write progress(current_page, started_at)│
       │     dispatch_verified(                      │
       │       "page-author", …, post_write_check=_check,
       │       target_path=target, manifest_page=page)
       │       │                                     │
       │       │ ── dispatch_validated ──> page-author writes target
       │       │                                     │
       │       │ ── post_write_check(target, page)   │
       │       │       parse_frontmatter             │
       │       │       description_quality.check_fm  │
       │       │                                     │
       │       ├─ ok=true  → ledger.authored,        │
       │       │              progress.completed     │
       │       └─ ok=false → target.unlink(),        │
       │                     ledger.reasons,         │
       │                     progress.failed         │
       └─────────────────────────────────────────────┘
                              │
                  print(ledger); unlink(progress)
```

## Error handling

Reject + delete + report is the rule:

- **Unparseable YAML**: file deleted, reason `frontmatter_parse_error: <relpath>: <exception class>`. Re-run retries.
- **Missing frontmatter block**: file deleted, reason `frontmatter_missing: <relpath>`. Re-run retries.
- **Thin description / equal-to-title / trailing colon**: file deleted, reason `description_quality: <relpath>: <human message>`. Re-run retries.
- **Subagent dispatch failure (existing path)**: unchanged. `dispatch_validated` still returns `(None, reasons)`; the wrapper short-circuits without invoking the post-write check, and there is no file to delete.
- **Progress-file write failure**: caught and logged to stderr; bootstrap proceeds. The file is best-effort observability, never a correctness gate.

The ledger printed at the end retains the same shape (`authored`, `skipped_existing`, `reasons`), so existing consumers (notifier, tests) keep working. New rejection reasons land in `reasons` exactly like dispatch failures do today.

## Bootstrap-time vs lint-time enforcement

The `description_quality` check runs in two places, intentionally:

- **Bootstrap-time (unconditional)**: the bootstrap callback calls `description_quality.check_fm` directly, regardless of host config. Bootstrap is the controlled entry point for canonical-core pages; rejecting thin descriptions there is non-negotiable.
- **Lint-time (config-gated)**: when `lint.tier1 == "default"`, `content-validator` runs `description_quality` against authored/edited paths via the standard `lint_runner` path. Hosts that opt out of Tier-1 default still get the bootstrap-time enforcement; they just don't get the nightly-authoring enforcement.

The two paths share the same pure `check_fm` function, so behavior cannot drift.

## Testing surface

Unit (stdlib pytest, monkeypatched dispatch):

- `archive_indexes.parse_frontmatter_strict`: valid frontmatter returns dict; bad YAML raises `yaml.YAMLError`; missing frontmatter raises `ValueError`; empty frontmatter block returns `{}`.
- `dispatch_verified`: passing callback returns `(out, reasons)` unchanged; failing callback deletes the file, returns `(None, augmented_reasons)`; `post_write_check=None` is a pure pass-through.
- `description_quality.check_fm`: thin (< min_words), copied-from-title, trailing-colon, ok, missing description, non-`agent-authored` generator (always ok).
- `description_quality.check_path` against fixture markdown files; same matrix.
- `lint_runner.enabled_rules` returns `description_quality` when `lint.tier1 == "default"`.

Integration:

- `tests/orchestrator/test_bootstrap_core.py` extended with `fakes_bootstrap/fake_page_author_bad_yaml.json`, `fake_page_author_thin_desc.json`, `fake_page_author_ok.json`. Asserts:
  - Bad-YAML and thin-desc cases: target file does _not_ exist after `run_bootstrap_core`; ledger `reasons` contains the matching token; exit code 0 (per-page best-effort).
  - OK case: target file exists and frontmatter parses; ledger `authored` contains the relpath.
  - Re-running the bootstrap after rejection re-attempts only the rejected pages (idempotency contract preserved).

Progress file:

- After the loop, `bootstrap.progress.json` is gone.
- During the loop (using a callback that captures the file's state per iteration), `current_index` is monotonically increasing and `current_page` matches the dispatched page.

## Out of scope

- **Gap 5: Mermaid setup smoke test.** The `engineering-docs-agent-setup` skill should drop a trivial Mermaid block and run the diagram-gate end-to-end as a final setup step, catching mis-scaffolded `mkdocs.yml` at setup time. Separate spec; setup-capability concern.
- **In-process retry with feedback.** Re-dispatching page-author with `"your previous YAML failed at line N; fix it"`. Explicitly rejected during brainstorm — the "delete + report" path already gives free retry-on-rerun without requiring a retry loop in the orchestrator.
- **Full Tier-1 lint sweep at bootstrap time.** Rules like `internal_links` and `stub_redirect` would cascade-fail on partial site state mid-bootstrap. Only `frontmatter_schema`'s logical equivalent (via the inline `parse_frontmatter` call) and the new `description_quality` rule run inline. The full sweep happens later via the existing `content-validator` path on the docs-agent PR.
- **Non-bootstrap callers of `dispatch_validated`.** The wrapper is added so the nightly authoring loop _can_ opt in later, but this spec does not wire it in there. That's a follow-up once gap-3-class defects are observed in nightly runs.

## Acceptance

- `run_bootstrap_core` rejects + deletes pages with unparseable frontmatter; ledger `reasons` contains `frontmatter_parse_error:` for that page.
- `run_bootstrap_core` rejects + deletes pages whose `description` is shorter than `min_words` OR equals the title verbatim OR ends in a colon; ledger `reasons` contains `description_quality:` for that page.
- `.engineering-docs-agent/bootstrap.progress.json` exists and updates between dispatches during the run; is removed at the end.
- `scripts/lint/description_quality.py` is invocable as a standalone script and integrates with `lint_runner` via Tier-1 default; existing `frontmatter_schema` results are unchanged for the same fixtures.
- Full pytest suite passes (count = current + new tests; no existing tests regressed).
- Bootstrap re-run skips successfully-authored pages and re-attempts rejected ones.
