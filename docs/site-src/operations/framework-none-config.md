---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/84
synthesized_into: []
---

# Using `docs.framework: none`

`docs.framework: none` is a valid, first-class config value. Use it when your host repo has no static-site generator (SSG) — for example, a JavaScript or TypeScript application that keeps documentation as plain markdown files read directly in the GitHub UI.

You do not need to install mkdocs, docusaurus, or any other SSG to pass schema validation. Prior to PR #84, the closed enum `['mkdocs', 'docusaurus']` forced hosts without an SSG to introduce a synthetic `mkdocs.yml` and `requirements-docs.txt` purely to satisfy validation. That requirement is gone.

## When to use `framework: none`

Set `framework: none` in `.engineering-docs-agent/config.yml` when:

- Your repo has no build step that produces an HTML docs site.
- Your team reads documentation directly from GitHub markdown rendering or another non-SSG surface.
- You want to onboard the docs-agent without adding new toolchain dependencies.

## Configuration

```yaml
# .engineering-docs-agent/config.yml
docs:
  framework: none
  docs_dir: docs/          # wherever your markdown lives
  lens_paths:
    core: docs/
  agent_editable_paths:
    - docs/**
```

Leave `publishing.base_url` unset (or `null`). The publish-verifier skips when no URL is configured.

## What runs with `framework: none`

All authoring and content-quality stages run normally:

- `pr-summarizer` — collects and summarizes merged PRs.
- `page-author` — creates and edits pages under the configured lens paths.
- `content-validator` — Tier-1 lint rules apply in full.
- `gap-detector` — flags PRs with no matching spec or plan.
- `notifier` — sends the Slack and email digest.

The nightly PR is opened and the What's New entry is produced exactly as it is for mkdocs or docusaurus hosts.

## What skips with `framework: none`

`framework_build` — the lint rule that runs an SSG build to catch broken cross-references and missing assets — skips cleanly. The run digest reports:

```
framework_build: skipped (framework=none; no build validation applicable)
```

This is a clean skip, not a failure. The run is not marked `partial: true` because of it.

The publish-verifier also skips if `publishing.base_url` is `null`. No post-merge URL checks are performed.

## Preflight behavior

`preflight_host.proposed_config()` previously coerced an absent-framework detection to `'mkdocs'` and emitted a `block`-severity warning. It now treats `framework: none` as an intentional steady state and emits an `info`-severity note instead. Your preflight run will not block on a missing SSG.

## Upgrading to a real framework later

When you want strict build-time link checking or a published site at a stable URL, upgrade to `framework: mkdocs`:

1. Run `mkdocs new .` in the repo root. Move your docs into `docs/` if they are not there already.
2. In `.engineering-docs-agent/config.yml`, set `framework: mkdocs`, set `publishing.base_url` to your GitHub Pages URL, and set `publishing.build_workflow` to your deploy workflow filename (e.g., `deploy.yml`).
3. Add an mkdocs install step to the nightly workflow (`.github/workflows/docs-agent-nightly.yml`) so `framework_build` can invoke `mkdocs build`.
4. Run preflight locally — `python3 scripts/orchestrator_runner.py --preflight-only` — to confirm the new config passes before committing.

## Related

- Architecture detail on how detection drives capability auto-derivation: [architecture/framework-detection.md](../architecture/framework-detection.md)
- Host-onboarding quick reference: `docs/host-onboarding/framework-none.md`
- `framework_build` lint rule: `scripts/lint/framework_build.py`
- Framework detection: `scripts/setup_discover.py` (`detect_framework()`)
- Config proposal: `scripts/preflight_host.py` (`proposed_config()`)
