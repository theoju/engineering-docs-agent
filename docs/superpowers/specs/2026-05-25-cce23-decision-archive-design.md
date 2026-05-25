# Decision Archive (capability D) — Design

**Date:** 2026-05-25
**Status:** draft (awaiting review)
**Ticket:** [CCE-23](https://designitright.atlassian.net/browse/CCE-23)
**Refines:** the **D — Decision Archive** section of `docs/superpowers/specs/2026-05-24-structured-docs-site-generation-design.md`.
**Builds on:** capability **S** (structure + setup engine), shipped in PR #24 — `scripts/site_structure.py`, the `site:` config block, and `apply_scaffold`.
**Reference:** `advanced-data-importer/scripts/generate_archive_indexes.py` (ADIS).

---

## Scope

D turns the configured `archive` section into generated index pages. It reads the section's `sources` directories (by default `docs/superpowers/{specs,plans,measurements}`), and for each one emits a `docs/site-src/archive/<category>.md` page listing that directory's documents — grouped by ISO month, newest first, with title, status, and a one-line summary, each linking back to its source.

D is **generic-first, convention-optimized**: it runs on any repo, indexes only what a directory actually contains, and skips cleanly when a source is absent. It is _markedly better_ on Claude Code / superpowers repos because those carry dated `docs/superpowers/{specs,plans}` files the index understands.

This is Phase 1 work, independently shippable, building on S's real interfaces.

## Why a rewrite, not an extension

A seed `scripts/archive_indexes.py` exists from an earlier batch. Its model is wrong for this design: it assumes the source files already live inside an `archive_root/<subdir>/` tree and emits a per-subdir `index.md`. The spec's D reads **external** `sources` directories and emits flat `archive/<category>.md` pages with month grouping, summaries, an auto-generated banner, and source links — none of which the seed does.

D rewrites `scripts/archive_indexes.py` in place and replaces its test (`tests/orchestrator/test_archive_indexes.py`) and fixtures (`tests/fixtures/archive_indexes/`). The module mirrors S's `site_structure.py` shape: pure functions, one filesystem entry point, and a CLI.

### Write discipline: D overwrites, S never clobbers

`apply_scaffold` skips any file that already exists — it protects human-authored content. D's pages carry an "auto-generated; do not edit by hand" banner, so `generate_archive` **always overwrites** them. Same repo, opposite write discipline. That is why D is a separate module with its own entry point rather than folded into the scaffold engine.

## Resolved decisions

These were settled during brainstorming against S's now-real interfaces:

1. **Source linking — hybrid (strict-safe).** `mkdocs build --strict` (S's build gate) rejects links that escape `docs_dir`, and the sources live outside `docs/site-src/`. So entries link to an **absolute external URL** or not at all. The link base resolves in order:
   1. explicit `repo_url_base` on the archive section (or `--repo-url-base` on the CLI);
   2. else derive from git: `detect_repo(repo_root)` (reused from `scripts/orchestrator_runner.py:28`) + current branch (`git rev-parse --abbrev-ref HEAD`, default `main`) → `https://github.com/{owner}/{name}/blob/{ref}/`;
   3. else `None` → plain text (no link).

   This satisfies "entries link to source" out of the box, offers an explicit override, and never emits a build-breaking or misleading link (an unresolvable base degrades to plain text rather than a wrong URL).

2. **Status column — included.** Rows render `| Title | Status | Summary |`. Status comes from YAML frontmatter (`status:`), `—` when absent. This matches Decision-Archive semantics (draft / accepted / superseded) and the existing fixtures.

3. **Skip vs. validate (resolves a spec contradiction).** The umbrella spec's error-handling section says config validation checks "`archive` `sources` exist", but that conflicts with "skip cleanly when no sources" and would break the shipped default config on any non-superpowers repo. Resolution, matching ADIS (`if not src.is_dir(): continue`): config-load validates only that `sources` entries are **relative, non-escaping path strings** (read-safety); **existence is a per-source runtime skip**.

4. **No ADR special-case.** ADIS hardcoded an `adr-*.md` glob and a "promoted files" link table — both repo-specific. D drops them. A category is simply the source directory's basename, so a host gets an `adrs.md` page only by adding an `adrs` source whose files follow the same date-prefixed `.md` convention (undated files are filtered out, see `DATE_PREFIX` below). This repo has no ADRs; none is emitted.

## Components (`scripts/archive_indexes.py`, rewritten)

Pure unless noted.

- `DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-\d{2}-")` — the load-bearing filter. Only date-prefixed `.md` is indexed, which excludes `measurements/`'s `.txt`/`.json`/`.jsonl` run artifacts and any non-dated `.md`. The month bucket comes from this prefix.
- `Entry` — frozen dataclass: `filename, title, status, summary, month, source_rel_path`.
- `parse_frontmatter(text) -> dict` — split on `---`; `yaml.safe_load` the block; `{}` on absence or malformed input (never raises).
- `parse_title_and_summary(text) -> tuple[str, str]` — title from the first `# H1`; summary from the first non-blank, non-heading line after it (ported from ADIS).
- `collect_entries(source_dir, repo_root) -> list[Entry]` — glob `*.md`, keep date-prefixed, parse title/status/summary, compute `source_rel_path` relative to `repo_root`, sort newest-first by filename.
- `render_archive_page(label, entries, *, link_base) -> str` — banner (`_Auto-generated; N entries. Do not edit by hand._`) + `## YYYY-MM` sections (descending), each a `| Title | Status | Summary |` table. Title links to `link_base + source_rel_path` when `link_base` is set, else plain text. Summary truncated to ~120 chars; `|` escaped in title and summary.
- `resolve_repo_url_base(repo_root, section, *, override) -> str | None` (impure: git) — the hybrid resolution above.
- `generate_archive(repo_root, site_config, *, repo_url_base=None) -> dict` (impure: the only filesystem writer) — find the `generator: archive-index` section; resolve the link base once; for each `sources` entry compute `category = Path(source).name`, collect entries, **skip** (record) when the directory is missing or yields no entries, else **overwrite** `<docs_dir>/archive/<category>.md`. Returns `{"written": [...], "skipped": [...]}` — `written` lists the category pages emitted (new or overwritten), `skipped` the sources passed over. (Contrast `apply_scaffold`'s `created`, which means _newly created_ under its never-clobber rule.)
- `main()` — CLI: `--repo-root` (required), `--config`, `--repo-url-base`. Loads config via `state_io.load_config_validated`, calls `generate_archive`, prints the result as JSON.

## Data flow

`config.yml` → `load_config_validated` → archive section → for each `sources` dir under `repo_root`: collect dated `.md` → parse title/status/summary/month → group by month, newest first → render table with hybrid link → overwrite `docs/site-src/archive/<category>.md`. Returns written/skipped lists.

## Interaction with S

S scaffolds `archive/index.md` (the section landing stub) and `archive/.pages` (the section title). D writes sibling `archive/specs.md`, `archive/plans.md`, … . They coexist: `awesome-pages` auto-includes the category pages under the Archive section, so they appear in the nav without hand-maintained ordering. **D never touches `index.md`** — S owns the section landing.

## Config / schema changes

- `templates/config.schema.json`: add an optional `repo_url_base` (string) to the section properties. Required because the section schema sets `additionalProperties: false`.
- `scripts/state_io.py`: a light guard rejecting absolute or `..`-escaping `sources` entries (D _reads_ these paths). No existence check — existence is a runtime skip.

## Error handling

- Missing source directory → skip + a stderr warning; recorded in `skipped`.
- Source directory with no date-prefixed `.md` → skip (never an empty page).
- Malformed or absent frontmatter → `status: —`; no crash.
- No archive section, or section with no `sources` → `generate_archive` is a no-op returning empty lists.
- `detect_repo` returns `unknown` / no remote → plain-text fallback.
- Branch detection fails → default `main`.

## Testing strategy

TDD, fixture-driven (the existing dry-run pattern).

New fixtures under `tests/fixtures/archive_indexes/`: external-style `specs/` and `plans/` directories holding dated `.md` (frontmatter `status` + `# H1` + a summary paragraph), **plus noise** (`.txt` files, a non-dated `.md`) to prove filtering.

- **Pure units:** `parse_title_and_summary`; `parse_frontmatter` (status present / absent / malformed); `collect_entries` (excludes non-`.md` and non-dated; includes dated; newest-first); month grouping descending; `render_archive_page` with a `link_base` (asserts the blob URL) and without (asserts plain title); summary truncation and `|` escaping.
- **Link resolution:** `resolve_repo_url_base` — explicit override wins; monkeypatched `detect_repo` → GitHub → blob URL with branch; `unknown` → `None`.
- **Integration:** a tmp repo with a `site:` config and source dirs → writes `archive/specs.md` + `archive/plans.md`; a missing `measurements` source is skipped; a stale generated page is overwritten; S's `archive/index.md` is left intact.
- **Build smoke:** S-scaffold + D-generate → `mkdocs build --strict` succeeds (absolute and plain links do not trip strict).

The seed's `tests/orchestrator/test_archive_indexes.py` and old fixtures are replaced by the above.

## Files

- Rewrite: `scripts/archive_indexes.py`
- Modify: `templates/config.schema.json` (add `repo_url_base`), `scripts/state_io.py` (sources path-shape guard)
- Replace: `tests/orchestrator/test_archive_indexes.py`, `tests/fixtures/archive_indexes/**`
- Add: unit, integration, and build-smoke tests per above

## Out of scope (Phase 1 D)

- Orchestrator stage wiring (the later "orchestrator integration" step retargets pipelines; D ships as a generator + CLI driven by config).
- Publishing or promoting raw specs into the site (`docs/superpowers/` stays unpublished input, surfaced only through the generated index).
- Any non-`archive-index` generator (API, changelog, agent-authored).
