---
description: "The docs site generates its own landing pages."
source_files:
  - scripts/section_overview.py
  - scripts/managed_block.py
last_reviewed: "2026-06-09"
status: draft
doc_kind: architecture
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/120
synthesized_into: []
---

# Section Overview Generation

The docs site generates its own landing pages. Every section index — Architecture, API, Operations, and Decision Archive — is populated automatically at build time, not hand-authored.

## Why generated landing pages

Static draft stubs were failing the holistic-review gate: readers landed on empty placeholder pages with no navigational signal. The generator was introduced to replace them with real content that stays accurate as the site grows.

The generator is **clobber-safe**: it updates only a bounded region in each page, leaving any author prose outside that region byte-for-byte unchanged.

## The managed block pattern

`scripts/section_overview.py` delegates the actual markdown surgery to `scripts/managed_block.py`. A managed block is a delimited region wrapped by:

```text
<!-- docs-agent:overview start -->
...generated content...
<!-- docs-agent:overview end -->
```

The `managed_block.py` upsert is idempotent. Running the generator twice on the same file produces the same output; running it on a page with existing hand-authored prose outside the sentinels leaves that prose untouched.

If the sentinels are absent, the upsert appends the block at the end of the file on first run.

## Section landing page content

For each section landing, the generator emits a child-page index: page titles and their summary lines, derived from frontmatter and the first paragraph of each child page.

The API section gets special treatment. Its managed block shows the CCE-105 API reference groups with live module counts sourced from the mkdocs-gen-files build VFS at generation time. This keeps the landing page synchronized with the actual API surface without manual updates.

## Generated nav block

`section_overview.py` also writes a complete `nav:` block into `mkdocs.yml`. The block is derived from the site's file tree plus the CCE-105 API group structure.

The awesome-pages plugin was removed as part of this work. awesome-pages cannot resolve API reference pages that exist only in the mkdocs-gen-files build VFS; a generated `nav:` block via literate-nav is the empirically-verified alternative, confirmed against `mkdocs build --strict`.

## GitHub edit widget

`repo_url` and `edit_uri` are derived at generation time from `git remote get-url origin` and injected into `mkdocs.yml`. Every published page gets a GitHub edit link wired to the correct source file without any manual configuration.

## Where the generator runs

`generate_overviews` is called inside `run_site_generators`, after the archive and contracts generators. It also runs during `engineering-docs-agent-setup` scaffold with `best_effort=True` so a partial failure logs at `INFO` and never blocks the scaffolding path.

The canonical design spec is at `docs/superpowers/specs/2026-06-08-cce106-section-overviews-home-design.md`.
