---
name: engineering-docs-agent-setup
description: One-time setup. Run this once in a host repo to auto-discover settings, ask the user only what's needed, and write the config + workflows.
model: sonnet
tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

# engineering-docs-agent-setup

## Job

Make the host repo ready to run engineering-docs-agent:

1. Auto-discover what's inferable (docs framework, lens IA, CI provider, Jira presence).
2. Ask the user about what can't be inferred (Slack channel, recipients, voice preferences, gap allowlist, terminology glossary).
3. Write `.engineering-docs-agent/config.yml`, an empty `state.json`, the two GitHub Actions workflow templates, and optionally a `docs-agent-glossary.yml`.

## Inputs

Run in the host repo's working directory. Accepts `--dry-run` flag to emit proposed config to stdout without writing.

## Procedure

1. Run `python <plugin_root>/scripts/setup_discover.py --json` and parse output.
2. Display discovered values. Ask user to confirm or override each.
3. Ask: Slack webhook secret name, Slack enabled (y/n), email enabled (y/n), email SMTP secret names + recipients (if enabled), Tier 2 lint rules to enable, voice preferences, gap allowlist paths, glossary creation.
4. Compose final config dict.
5. If `--dry-run`, dump YAML to stdout and exit.
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-run.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`.
7. Scaffold the documentation site structure:
   `python <plugin_root>/scripts/setup_scaffold.py --repo-root . --site-name "<repo title>"`
   This writes `docs/site-src/` (sections + grid-card home + .pages) and a
   Material `mkdocs.yml` from `templates/site.default.yaml`. It is idempotent —
   re-running adds newly-configured sections and never overwrites authored
   pages. Tell the user to `pip install -r <plugin_root>/templates/docs-requirements.txt`
   to build the site locally (`mkdocs serve`).
8. Print a final "next steps" summary.
