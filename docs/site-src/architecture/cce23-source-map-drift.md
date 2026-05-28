---
description: How the source-map generator and drift detector track which docs pages are affected by source-code changes, and how the orchestrator scopes citation verification using the map.
source_files:
  - "**/"
  - agents/schemas/*.json
  - scripts/contracts.py
  - scripts/orchestrator_runner.py
  - scripts/source_drift.py
  - scripts/source_map.py
last_reviewed: '2026-05-27'
status: draft
---

# Source Map and Drift Detection (CCE-23)

The source map (`scripts/source_map.py`) and drift detector (`scripts/source_drift.py`) together answer: when source code changes, which docs pages need a human review?

Pages declare their source files via `source_files:` in frontmatter. The map generator resolves those globs against tracked files, and the drift detector uses the result to flag pages whose declared sources appeared in a PR's changed-files list.

## The artifact: `.doc-source-map.json`

`generate_source_map` writes `<docs_dir>/.doc-source-map.json` — a dual-view JSON artifact:

- **`patterns`**: page → declared `source_files` globs. One entry per opted-in page.
- **`map`**: source file → list of pages that declared a matching glob. The inverted index, used for O(1) scoping at citation-verification time.

When no page declares `source_files`, the file is not written. Pages with malformed frontmatter or a non-list `source_files` are collected in a `skipped` list in the ledger returned to the orchestrator.

`_resolve_tracked_files` (`scripts/source_map.py:98`) prefers `git ls-files` to enumerate candidate source files. When the repo has no git history, it falls back to an `rglob` that skips `.git`, `.venv`, `node_modules`, `site`, and `__pycache__`.

## Glob translation

`_glob_to_regex` (`scripts/source_map.py:66`) translates POSIX path globs to anchored regexes. Python 3.9's `fnmatch` and `PurePath.match` mishandle `**`, so this module implements the translation explicitly:

| Glob token | Regex equivalent |
|---|---|
| `**/` | `(?:.*/)?` — zero or more path segments, including none |
| `**` | `.*` — anything including `/` |
| `*` | `[^/]*` — one filename segment |
| `?` | `[^/]` — one non-`/` character |
| everything else | `re.escape(char)` |

Matching uses `.fullmatch` so partial overlaps don't fire.

## How drift detection works

`detect_drift` (`scripts/source_drift.py:21`) receives the docs directory and a list of changed files (repo-relative POSIX paths). For each opted-in page it compiles the declared globs to regexes and tests every changed file. Pages with at least one match appear in the `drifted` list, each carrying the matched file names.

The function is read-only. It imports `_collect_page_patterns` and `_glob_to_regex` from `source_map.py` directly — the two modules share the same pattern-collection and glob-translation logic.

## Orchestrator integration

`compute_source_drift` (`scripts/orchestrator_runner.py:615`) runs after page authoring on every nightly pass:

1. Calls `source_map.generate_source_map(...)` to (re)generate the artifact against the current repo state.
2. Collects the union of changed files across all PRs in the batch.
3. Calls `source_drift.detect_drift(...)` and returns the drifted list.

The stage is best-effort. Any exception is caught, recorded as an `info_only` partial reason (`source_map_failed: <exc>`), and the run continues. Results land in `state["current_run"]["source_drift"]` and appear in the What's New entry under "Pages to review (source drift)".

`compute_citation_drift` (`scripts/orchestrator_runner.py:678`) then calls `_changed_pages_from_map` to read the inverted `map` from `.doc-source-map.json` and returns the set of pages whose mapped sources appear in the batch's changed-files list. Citation verification runs only on that set rather than the full docs tree. When the map is absent or unreadable, `_changed_pages_from_map` returns `None` and citation verification falls back to a full scan.

`compute_core_drift` (`scripts/orchestrator_runner.py:708`) is a flag-only step that intersects the M (source drift) and C1 (citation drift) results with the pages listed in `.doc-core-manifest.json`. It writes nothing and dispatches nothing — it only surfaces which canonical-core pages have drifted so a human re-reviews them, regardless of page status.

## Opting a page in

Add `source_files:` to a page's YAML frontmatter:

```yaml
---
description: The orchestrator runner.
source_files:
  - scripts/orchestrator_runner.py
  - scripts/state_io.py
last_reviewed: '2026-05-27'
status: draft
---
```

Any POSIX path glob is valid. The catch-all `**/` matches every tracked file — useful for pages that should be reviewed whenever anything in the repo changes. Omitting the key or leaving it empty opts the page out silently.

## Diagnostics

Run the source-map generator standalone to inspect the artifact:

```bash
python scripts/source_map.py \
  --repo-root . \
  --config .engineering-docs-agent/config.yml
```

Run the drift detector with a JSON array of changed files on stdin:

```bash
echo '["scripts/orchestrator_runner.py", "scripts/source_map.py"]' \
  | python scripts/source_drift.py \
    --repo-root . \
    --config .engineering-docs-agent/config.yml
```

Both scripts print a JSON result to stdout and exit `0` on success, `1` on config error.
