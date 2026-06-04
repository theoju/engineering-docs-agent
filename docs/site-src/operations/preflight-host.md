---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/83
synthesized_into: []
---

# Preflight: inspecting a target host before install

`scripts/preflight_host.py` is a read-only diagnostic CLI. Run it against any repository before you invoke the setup skill. It prints what the setup skill _would_ write — the generated config, the workflow YAML, and a secrets checklist — without touching the target repo.

## When to use it

Run preflight any time you're onboarding a new host repo, or after you've changed the host's toolchain and want to see how the plugin would respond. It is safe to run repeatedly; it writes nothing.

## Usage

```bash
python3 scripts/preflight_host.py --repo-root /path/to/target-repo
```

The output has three sections:

1. **Discovery** — the full output of `setup_discover.py`, including the detected language, framework, package manager, and toolchain block.
2. **Projected config** — the `.engineering-docs-agent/config.yml` the setup skill would emit.
3. **Projected workflow** — the `.github/workflows/docs-agent-nightly.yml` the setup skill would write.
4. **Secrets checklist** — the exact secret names that must be set in the target repo before the nightly workflow can run.

## Toolchain detection

The discovery step calls `detect_toolchain()` in `scripts/setup_discover.py`. It checks for Node, Bun, and Deno binaries; derives the package manager from which lockfile is present (`package-lock.json` → npm, `yarn.lock` → yarn, `bun.lockb` → bun, `pnpm-lock.yaml` → pnpm); and inspects `devDependencies` to flag Docusaurus as the docs framework when present. The result appears under a `toolchain` key in the `discover()` output.

If no JS runtime is detected, the `toolchain` block is omitted and the rest of discovery continues normally. Detection never errors — it degrades to an empty block.

## Onboarding runbook

The step-by-step install sequence — GitHub App registration, secret names, branch protection, smoke run — lives in `docs/superpowers/specs/2026-05-29-cce57-onboard-runbook.md`. That runbook is CCE-57-specific but captures the pattern for any new host. Cross-reference it after reviewing preflight output to confirm the discovery matches your expectations before running the setup skill.

## What preflight does not cover

Preflight does not validate that the generated config is _semantically correct_ for the host — it only shows what would be written. After running the setup skill, verify the config manually: check that `docs.lens_paths` entries resolve to real directories and that every entry is covered by an `agent_editable_paths` glob. The config loader enforces this at boot via `_validate_lens_paths_are_editable` in `scripts/state_io.py` and will fail loudly if the invariant is broken.
