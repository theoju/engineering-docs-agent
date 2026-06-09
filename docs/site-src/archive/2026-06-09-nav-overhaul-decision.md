---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/120
synthesized_into: []
doc_kind: decision
---

# Decision: Nav Overhaul — Generated Nav Block Replaces awesome-pages (2026-06-09)

**Date:** 2026-06-09  
**PR:** [#120](https://github.com/theoju/engineering-docs-agent/pull/120)  
**Ticket:** CCE-106  
**Status:** Accepted

## Context

The docs site had four section landing pages — Architecture, API, Operations, and Decision Archive — that contained static draft stubs. Readers landed on empty placeholder pages. A holistic-review gate flagged all four as failing.

The existing nav was managed by the `awesome-pages` plugin. `awesome-pages` cannot resolve API reference pages that live only in the mkdocs-gen-files build VFS (they have no on-disk counterpart at build config time). This caused API reference groups to disappear from the rendered navigation entirely.

## Decision

Remove `awesome-pages`. Drive the site navigation with a fully generated `mkdocs.yml` `nav:` block via `literate-nav`.

The generated nav is produced by `scripts/section_overview.py` and written idempotently into `mkdocs.yml` on every docs-agent run. All six CCE-105 API groups appear in the site navigation because the nav block is built after `mkdocs-gen-files` populates the VFS — `literate-nav` can see them.

## Alternatives Considered

**Keep awesome-pages, patch the API reference pages onto disk.** Rejected. API reference pages are auto-generated at build time by `mkdocs-gen-files`; committing static copies would drift immediately and violate the forbidden-outputs contract for `api/reference/`.

**Manual nav maintenance in `mkdocs.yml`.** Rejected. Any new page added by the docs-agent or by a developer would require a manual nav update; the coupling would re-introduce the stale-stub problem at the nav level rather than the content level.

## Mechanism

`scripts/managed_block.py` provides an idempotent upsert of delimited markdown regions using `docs-agent:overview` start/end sentinels. Section landing pages (Architecture, API, Operations, Decision Archive) self-populate via `scripts/section_overview.py`, which lists child pages with titles and summaries. The API section landing gets an additional block showing CCE-105 groups with live module counts.

`repo_url` and `edit_uri` are derived from `git remote get-url origin` and injected into `mkdocs.yml` at generation time, wiring the GitHub edit widget onto every page without manual configuration.

`generate_overviews` runs inside `run_site_generators` (after the archive and contracts generators) and also at setup scaffold time with best-effort / `info_only` partial handling — a failure to generate overviews does not block the broader site build.

## Verification

The switch from `awesome-pages` to a generated `literate-nav` block was verified empirically via a real `mkdocs build --strict` spike before landing. The `--strict` flag was required: a `test -f` check on the nav entries would pass even when `mkdocs` would reject a VFS-only path.

## References

- Canonical spec: `docs/superpowers/specs/2026-06-08-cce106-section-overviews-home-design.md` — see the "Revised mechanism (empirical, 2026-06-08)" section for the spike methodology.
- `scripts/managed_block.py` — idempotent sentinel-delimited block upsert.
- `scripts/section_overview.py` — section landing page and nav block generator.
