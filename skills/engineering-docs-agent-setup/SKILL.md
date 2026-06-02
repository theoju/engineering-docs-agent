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

1. Run `python <plugin_root>/scripts/setup_discover.py --json` and parse output. Output now includes a `toolchain` block (`{node, bun, deno, package_manager, docusaurus_dep}`) — surface this when displaying discovered values (CCE-57).
2. Display discovered values. Ask user to confirm or override each.
3. Ask: Slack webhook secret name, Slack enabled (y/n), email enabled (y/n), email SMTP secret names + recipients (if enabled), Tier 2 lint rules to enable, voice preferences, gap allowlist paths, glossary creation.
4. Compose final config dict.
5. If `--dry-run`, dump YAML to stdout and exit.
6. Write `.engineering-docs-agent/config.yml`, `.engineering-docs-agent/state.json` (initial), `.github/workflows/docs-agent-nightly.yml`, `.github/workflows/docs-agent-verify.yml`, optionally `docs-agent-glossary.yml`. (CCE-57, CCE-80) The shipped workflow checks out `theoju/engineering-docs-agent` into `.docs-agent-plugin/` and runs the orchestrator from that path — do not delete the checkout step. After writing the workflow files, ensure `.docs-agent-plugin/` is in the host repo's `.gitignore`. If `.gitignore` exists, append the line if absent. If `.gitignore` does not exist, create it with that single line. This prevents `git add .` (run by you or by automation outside this orchestrator) from registering the workflow's vendored plugin checkout as a submodule gitlink in host commits — CCE-70.
   6a. If discovery's `pages_publishable` is true (MkDocs + GitHub Actions) OR the user supplied a `publishing.build_command`, also write `.github/workflows/docs-agent-pages.yml` from `templates/workflow-pages.yml`. For a non-MkDocs host, substitute the "Build site" run step with the `build_command` and the `upload-pages-artifact` `path:` with `publishing.site_dir`. Set `publishing.build_workflow: docs-agent-pages.yml` and `publishing.base_url` via `derive_pages_base_url(owner, repo, cname)`. If neither condition holds, skip the pages workflow and print: "Pages deploy not scaffolded (no MkDocs site and no publishing.build_command) — add one to enable publishing." `configure-pages(enablement:true)` sets the repo's Pages source to GitHub Actions on first run.
   6b. **Render the workflow file with a deterministic per-host cron minute** (CCE-80) — instead of writing the raw template, run `python <plugin_root>/scripts/scaffold_workflow.py --owner "$OWNER" --repo "$REPO" --out .github/workflows/docs-agent-nightly.yml`, where `OWNER`/`REPO` come from `discovery["git"]["owner"]` and `discovery["git"]["repo"]` (from `setup_discover.discover_git_origin()`). If `discovery["git"]` is `None`, fall back to `AskUserQuestion("What is the GitHub owner/repo for this host?", header="Repo", ...)`. The helper is deterministic — re-scaffolding the same host always produces the same cron minute, so no operator-visible diff churn.
7. Scaffold the documentation site structure:
   `python <plugin_root>/scripts/setup_scaffold.py --repo-root . --site-name "<repo title>"`
   This writes `docs/site-src/` (sections + grid-card home + .pages) and a
   Material `mkdocs.yml` from `templates/site.default.yaml`. It is idempotent —
   re-running adds newly-configured sections and never overwrites authored
   pages. Tell the user to `pip install -r <plugin_root>/templates/docs-requirements.txt`
   to build the site locally (`mkdocs serve`).
8. Print a final "next steps" summary.
   Conditional warning (CCE-80): if `vars.DOCS_AGENT_APP_CLIENT_ID` is unset on the host, append this to the "next steps" output:
   > **Host CI will not run on docs-agent PRs** unless you register a GitHub App. Without `vars.DOCS_AGENT_APP_CLIENT_ID`, the workflow falls back to `secrets.GITHUB_TOKEN`, which GitHub deliberately prevents from triggering `push`/`pull_request` workflows on its own commits. To enable host CI on docs-agent PRs:
   >
   > 1. Register a GitHub App named `engineering-docs-agent` with `Contents: write`, `Pull requests: write`, `Issues: read` permissions.
   > 2. Install it on this repository.
   > 3. Set `vars.DOCS_AGENT_APP_CLIENT_ID` (the App's Client ID) and `secrets.DOCS_AGENT_APP_PRIVATE_KEY` (PEM-form private key).
   > 4. Re-scaffold via this skill (no-op for cron; activates the App-token step).
