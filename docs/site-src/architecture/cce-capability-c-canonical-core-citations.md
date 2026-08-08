---
description:
  How the engineering-docs-agent links documentation pages to their source
  files through inline citations, pin tokens, and source-drift detection.
source_files:
  - backend/connectors/base.py
  - core/**
  - docs/site-src/core/**
  - docs/superpowers/**
  - scripts/audit_docs.py
  - scripts/verify_citations.py
  - scripts/verify_docs_diagrams.py
  - scripts/{verify_docs_diagrams,audit_docs,build_doc_source_map}.py
  - site-src/core/**
  - tests/orchestrator/test_source_map_stage.py
  - scripts/lint/citation_exists.py
  - scripts/lint/citation_line_free.py
  - scripts/lint/lint_runner.py
  - scripts/migrate_line_citations.py
  - agents/fact-checker.md
  - agents/page-author.md
  - templates/config.schema.json
last_reviewed: "2026-08-08"
status: draft
doc_kind: architecture
---

# Capability C — Canonical Core Citations

Capability C keeps documentation honest about the code it describes. **C1**
verifies that every inline pinned `path:line` citation still points to the
right line; **C2** detects when source files changed in a PR but the pages
that cite them were not updated; and a third layer — the `citation_exists`
and `citation_line_free` Tier-1 lints — checks that every citation on every
authored page, pinned or not, actually resolves and stays line-free.

## C1 — Inline citation verification

A citation is an inline code span of the form `` `path:line` `` immediately
followed by an HTML-comment pin: `<!--pin:TOKEN-->`. TOKEN is a short literal
string expected to appear on that line of the cited file.

```markdown
The connector base class is defined in
`backend/connectors/base.py:12` <!--pin:class BaseConnector-->
```

The verifier in `scripts/verify_citations.py:verify_citations` scans
every Markdown file under `docs_dir`, resolves each citation against the
repo tree, and classifies it into one of four states:

| Status      | Meaning                                                              |
| ----------- | -------------------------------------------------------------------- |
| `ok`        | Token found at the declared line number.                             |
| `relocated` | Token found, but at a different line. Auto-fixable with `--fix`.     |
| `ambiguous` | Token appears on multiple lines; human review required.              |
| `gone`      | Token not found anywhere in the file, or the file itself is missing. |

The verifier returns a **ledger** — a dict with counts and per-status detail
lists — rather than raising. Callers decide whether to block or warn based on
the ledger contents.

### Running the verifier

```bash
python scripts/verify_citations.py \
  --docs-dir docs/site-src \
  --repo-root . \
  --fix \
  --strict \
  --json
```

`--fix` rewrites relocated citations in place. It patches only the matching
span using byte offsets from the regex match (`scripts/verify_citations.py:verify_citations`), so
look-alike text elsewhere on the same page is not disturbed.

`--strict` exits non-zero if any `gone` or `ambiguous` citations remain after
processing. Use this in CI to block merges on broken citations.

### Pin token rules

- Tokens are matched as substrings, not whole-word anchors. A token like
  `def load_config` matches any line containing that substring.
- Empty tokens are skipped silently (`scripts/verify_citations.py`). Pin every
  citation you want verified.
- If a token becomes ambiguous after a refactor, tighten it to a more specific
  substring — one that appears on exactly one line in the file.

## Citation grammar: line-free and existence-checked

C1's pin-token mechanism isn't the only thing standing between a page and a
stale citation. Two Tier-1 lints run on every authored page automatically,
independent of pins, wired into the default rule set
(`scripts/lint/lint_runner.py:TIER1_DEFAULT`):

| Rule                 | Severity | Enforces                                                          |
| --------------------- | -------- | ------------------------------------------------------------------ |
| `citation_exists`     | block    | every cited path, `:symbol`, and test identifier actually exists   |
| `citation_line_free`  | warn     | no surviving `path:line` pin outside the C1 mechanism above        |

The grammar — a bare repo path, or a path with a trailing `:symbol` naming a
`def`/`class` (`Class.method` for a method):

```text
path/to/file.py
path/to/file.py:symbol
```

Never `path:line` or `path:start-end`. Line numbers drift under
routine code churn, and a drifting citation used to surface nightly as a
`fact-checker` `contradiction` — a false alarm that tripped the CCE-101
zero-warnings auto-merge gate on noise, not a real defect. `citation_exists`
now owns citation *existence*; `agents/fact-checker.md` is scoped to
behavioral truth only and must not emit `contradiction` for citation
location or line drift (CCE-122).

`citation_exists` strips fenced code first — fenced examples are legitimately
hypothetical — then scans inline code spans in prose. A bare path must
resolve: as a tracked file, a file present on disk, a path under the host's
`docs_dir`, or generated mkdocs build output
(`scripts/lint/citation_exists.py:check_path`). A `:symbol` suffix must
additionally name a real `def`, `class`, or module-level assignment in the
cited file (`scripts/lint/citation_exists.py:extract_symbol_citations`). A
cited test identifier must match `def <name>(` or `def <name>_` in some
tracked file — the trailing-underscore form lets a test-family shorthand
like `test_lint_runner` resolve against a member such as
`test_lint_runner_missing_script_reports_block` without requiring every
citation to spell out the exact test
(`scripts/lint/citation_exists.py:cited_test_exists`, CCE-131).

Two escape hatches exist, both deliberate rather than silent:

- **Reserved example namespace.** A cited path under `example/`
  (configurable via `lint.citation_example_prefixes`) is never checked for
  existence — it documents a fictional host, not a real citation
  (`scripts/lint/citation_exists.py:example_prefixes`). The `source_files`
  glob in the C2 example below uses this namespace.
- **Exempt tokens.** `lint.citation_exempt_tokens` names tokens whose
  *non-existence* is the point — a file that must stay absent, or a
  metasyntactic placeholder shaped like a test identifier that appears in
  this rule's own docstring:

  ```text
  test_snake_case
  ```

  Plugin defaults union with host entries; a listed token that starts
  resolving emits a `warn` naming it a stale exemption, so the list can't
  silently accumulate dead entries
  (`scripts/lint/citation_exists.py:exempt_tokens`, CCE-131).

Archive pages get one more accommodation: a page under a `site.sections`
entry with `generator: archive-index` is a historical record, so
`citation_exists` downgrades to `warn` there instead of blocking
(`scripts/lint/citation_exists.py:archive_dirs`) — the same reasoning C2
gives source-drift review, applied to existence.

A one-time migration (`scripts/migrate_line_citations.py`) converted 99
`path:line` citations across 21 published pages to `path:symbol` or bare
`path`, AST-scanning each cited Python file to decide the target: a line
inside a `def`/`class` becomes `path:symbol`, a line on a module-level
assignment becomes `path:NAME`, and anything else — imports, blank lines,
unresolvable files — becomes a bare path. It kept `:symbol` only where the
page's own prose corroborated it and downgraded everything else to bare
`path`, because a migrated symbol that resolves to a real but *wrong*
function reads as more authoritative than the opaque line number it
replaced.

`agents/page-author.md` carries the authoring side of this contract: a
backticked path or test identifier asserts the artifact exists — write one
only when it does. An illustrative or fictional-host path goes under
`example/`. A metasyntactic token — a placeholder standing for a shape
rather than naming a real thing — goes inside a fenced block, never loose in
prose, where `citation_exists` would read it as a real claim.

## C2 — Source-drift detection

Source drift occurs when a PR touches a source file that a docs page declares
ownership over, but no corresponding doc update was made. The orchestrator
detects this automatically during each run.

Every agent-authored page carries a `source_files` frontmatter list (see the
frontmatter at the top of this file). The entries are glob patterns:

```yaml
---
source_files:
  - example/auth/**/*.py
  - backend/connectors/base.py
---
```

After the `pr-summarizer` stage collects per-PR file lists,
`orchestrator_runner.compute_source_drift` (`scripts/orchestrator_runner.py`)
cross-matches each PR's changed files against the glob patterns in every page's
frontmatter. Pages where at least one glob matches a changed file are flagged as
drifted.

The result feeds directly into the **What's New** entry: drifted pages appear
under a `### Pages to review (source drift)` heading with the changed source
paths listed (`orchestrator_runner._drift_whats_new_lines`). The `page-author`
receives those pages in its authoring batch so they can be updated in the same
PR.

### Source-drift test coverage

`tests/orchestrator/test_source_map_stage.py` covers the key behaviors:

- A page with `source_files: [example/auth/**/*.py]` is flagged when
  `example/auth/session.py` appears in a PR's file list.
- Mixed file-entry shapes (dict `{"path": "..."}` and plain strings) are
  both handled.
- Malformed entries (integers, `None`, nested lists) are skipped without
  raising.
- An empty or missing `site:` config block returns an empty drift list
  rather than an error.

## Connecting the three layers

C1, the `citation_exists`/`citation_line_free` lints, and C2 are
complementary, not redundant. C1 guards individual pinned line-level
pointers on pages that use that mechanism. `citation_exists` guards bare
existence of every citation on every authored page, pinned or not — it's
what blocks a confabulated path or symbol before the page ever merges. C2
guards page-level relevance at PR granularity: a page can pass every
citation check and still need review if the logic around a correctly-cited
symbol changed underneath it. Run all three in CI and surface their findings
in the nightly docs PR.

The recommended CI workflow:

1. `citation_exists` (block) and `citation_line_free` (warn) run
   automatically as part of the Tier-1 default set
   (`scripts/lint/lint_runner.py:TIER1_DEFAULT`) whenever `content-validator`
   lints an authored or edited page — no separate invocation needed.
2. Run `verify_citations.py --strict` on the docs tree after any PR touches
   agent-editable paths, for pages still using C1's pin mechanism.
3. The orchestrator's source-drift stage runs automatically on every nightly
   pass; no manual invocation needed.
4. Review drifted pages flagged in the What's New entry, and any surviving
   `citation_line_free` warnings, before merging the docs PR.
