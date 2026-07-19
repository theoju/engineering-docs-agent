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
last_reviewed: "2026-05-27"
status: draft
doc_kind: architecture
---

# Capability C — Canonical Core Citations

Capability C keeps documentation honest about the code it describes. It has two
distinct layers: **C1** verifies that every inline `path:line` citation still
points to the right line, and **C2** detects when source files changed in a PR
but the pages that cite them were not updated.

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

## C2 — Source-drift detection

Source drift occurs when a PR touches a source file that a docs page declares
ownership over, but no corresponding doc update was made. The orchestrator
detects this automatically during each run.

Every agent-authored page carries a `source_files` frontmatter list (see the
frontmatter at the top of this file). The entries are glob patterns:

```yaml
---
source_files:
  - scripts/auth/**/*.py
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

- A page with `source_files: [scripts/auth/**/*.py]` is flagged when
  `scripts/auth/session.py` appears in a PR's file list.
- Mixed file-entry shapes (dict `{"path": "..."}` and plain strings) are
  both handled.
- Malformed entries (integers, `None`, nested lists) are skipped without
  raising.
- An empty or missing `site:` config block returns an empty drift list
  rather than an error.

## Connecting C1 and C2

C1 and C2 are complementary. C1 guards individual line-level pointers; C2
guards page-level relevance at PR granularity. A page can pass C1 (all
citations resolve) but still need a C2 review if the logic around those
lines changed. Run both in CI and surface both in the nightly docs PR.

The recommended CI workflow:

1. Run `verify_citations.py --strict` on the docs tree after any PR touches
   agent-editable paths.
2. The orchestrator's source-drift stage runs automatically on every nightly
   pass; no manual invocation needed.
3. Review drifted pages flagged in the What's New entry before merging the
   docs PR.
