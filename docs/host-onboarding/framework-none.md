# Choosing `framework: none`

Use `docs.framework: none` when your host repo has no static-site
generator (SSG) — for example, a Next.js application whose docs are
plain markdown rendered by GitHub at `https://github.com/<owner>/<repo>/blob/main/docs/`.

## What runs

- `pr-summarizer`, `page-author`, `content-validator` (Tier-1 rules,
  including `citation_exists`), `fact-checker` (factual-accuracy
  warnings on pages that cite repo sources), `gap-detector`,
  `notifier`: all run normally.
- The What's New entry and the nightly PR are produced normally.

## What skips

- `framework_build` lint rule skips with reason
  `framework=none; no build validation applicable`. This is reported in
  the run digest as a clean skip, not a failure.
- The publish-verifier skips when `publishing.base_url` is `null` (the
  default for framework=none).

## When to upgrade

Add a real framework when you want any of:

- Strict build-time link checking (an mkdocs build catches broken
  cross-references between authored pages).
- A published docs site at a stable URL (GitHub Pages, Vercel, etc.)
  rather than reading markdown in GitHub's web UI.

To upgrade from `framework: none` to `framework: mkdocs`:

1. `mkdocs init` in the repo root.
2. Move docs into `docs/` if not already there.
3. Edit `.engineering-docs-agent/config.yml`: `framework: mkdocs`,
   set `publishing.base_url` to your GitHub Pages URL, set
   `publishing.build_workflow` to your deploy workflow filename.
4. Add an mkdocs install step to the nightly workflow so
   `framework_build` can run.

## Reference

- Spec: `docs/superpowers/specs/2026-05-29-cce64-framework-none-first-class-design.md`
- Default capabilities derive from the framework value — see
  `scripts/lint/framework_build.py` and `scripts/setup_discover.py`.
