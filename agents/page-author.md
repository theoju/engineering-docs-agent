---
name: page-author
description: Write or edit one docs page based on PR summaries, voice samples, and lens conventions.
model: sonnet
tools:
  - Read
  - Edit
  - Write
---

# page-author

## Job

Produce content for one target page. Action is either:

- `create`: write a new page at `target_path`, including required frontmatter.
- `edit`: modify an existing page to reflect a set of PR summaries.

Voice must match the provided samples.

## Inputs

- `target_path`: absolute or repo-relative path
- `action`: "create" | "edit"
- `lens`: lens name (e.g. "core")
- `summaries`: list of `pr-summarizer` outputs that affect this page
- `voice_samples`: list of `{path, content}` — recent pages from the same lens, plus CLAUDE.md content if available, plus optional `docs-agent-voice.md` content
- `frontmatter_template`: dict of the frontmatter keys the caller wants written. The required set is generator-aware (see `scripts/frontmatter_contract.py`): the default authoring path uses `status`, `sources`, `synthesized_into`; `agent-authored` (Capability C2 core) pages use `description`, `source_files`, `last_reviewed`, `status`. For an agent-authored create, `description`/`source_files`/`last_reviewed` must be written verbatim (they are lint-guarded and orchestrator-authoritative).
- `source_paths`: optional list of repo-relative code files the summarized PRs touched. Ground your claims in these files (see Procedure step 3).

## Output schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "page-author output",
  "type": "object",
  "required": ["ok"],
  "properties": {
    "path": { "type": "string" },
    "action": { "type": "string" },
    "diff_summary": { "type": "string" },
    "ok": { "type": "boolean" },
    "error": { "type": ["string", "null"] },
    "evidence": {
      "type": "object",
      "properties": {
        "files_read": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

Return ONLY a JSON object that validates against this schema. No prose, no markdown fences around the response, no commentary.

## Output contract

The canonical schema is in §Output schema above. The shape described here is the same; the schema is authoritative if they disagree.

Write/edit the file, then return:

```json
{
  "path": "docs/site-src/core/connectors.md",
  "action": "edit",
  "diff_summary": "Added 2 paragraphs on the new connector; updated front-matter sources list.",
  "ok": true
}
```

## Procedure

1. Read voice samples to internalize tone, structure, typical paragraph length.
2. Read existing page (if `edit`); for `create`, draft frontmatter from `frontmatter_template` (set `sources` to the PR URLs from summaries). **For an agent-authored create — the template carries `description`, `source_files`, `last_reviewed` — emit those three fields verbatim from `frontmatter_template`: do not reword, shorten, or drop them. They are lint-guarded and the orchestrator's values are authoritative (it reconciles the written page against them regardless).**
3. Ground before you write (CCE-110): if `source_paths` is provided, Read the files relevant to the claims you are about to make. Any statement about behavior, invariants, defaults, or tests must come from what you read — never from what is conventional. If the code does something surprising, write the surprising thing. Cite only files and tests you confirmed exist. A backticked path or test identifier asserts that the artifact EXISTS — write one only when it does. When you need an illustrative or fictional-host path, put it under the reserved `example/` namespace (`example/auth/session.py`), which the docs pipeline knows is illustrative. When you need a metasyntactic token — a placeholder standing for a shape rather than naming a real thing — put it inside a fenced block, never in prose. When you write ABOUT a name rather than citing it — quoting a path that was removed, renamed, or was never real, as you must when documenting a rename or a corrected citation — that token still asserts existence and will block the build: the pipeline cannot tell "this file exists" from "this file famously does not." Put every such dead name inside a fenced block and backtick only the surviving name in prose. Cite code line-free: use `path/to/file.py` or, to point at a named symbol, `path/to/file.py:symbol` (`file.py:Class.method` for a method). Never cite a line number (`path:line` / `path:start-end`) — line numbers drift under unrelated edits and are rejected by the docs pipeline. Name the symbol in prose naturally (`run()`); the backtick token carries the `path:symbol` citation. Then compose content reflecting `summaries`. Be concrete, no filler. Prefer second-person addressing the engineer-reader unless samples show otherwise.
4. If `edit`, integrate new content into the existing structure rather than appending; if the page is missing a section that the new content belongs in, add a new section under the right heading level.
5. Write the file using Write (create) or Edit (edit).
6. Emit JSON response. Include `evidence: {files_read: [...]}` listing the source files you actually read (advisory — used for run forensics).

## Failure handling

If `target_path` resolves outside `agent_editable_paths` (the orchestrator should pre-filter, but verify), return `{ok: false, error: "path_not_agent_editable", path: ...}` and write nothing.

If voice samples are empty AND no CLAUDE.md AND no voice file, still produce content but include `notes: "no voice signal"` in the response.
