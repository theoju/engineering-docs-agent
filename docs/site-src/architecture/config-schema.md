---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/82
synthesized_into: []
---

# Config Schema Reference

The host config lives at `.engineering-docs-agent/config.yml` in each host repo. This page documents every top-level block and field. The orchestrator loads and validates the file at boot via `scripts/state_io.py`.

## Top-level blocks

| Block | Required | Purpose |
|---|---|---|
| `docs` | yes | Docs site framework, paths, and editable-path globs |
| `sources` | yes | Git and Jira source configuration |
| `voice` | no | Paths to voice sample files for authoring |
| `lint` | no | Tier enable/disable overrides |
| `publishing` | no | Deploy URL, CI provider, and publish-verifier settings |
| `notifications` | no | Slack and email digest settings |

---

## `docs` block

Controls where the agent reads docs, where it writes them, and which framework owns the build.

```yaml
docs:
  framework: mkdocs          # supported: mkdocs, docusaurus
  source_dir: docs/site-src  # root of the docs tree MkDocs/Docusaurus reads
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths:
    - "docs/site-src/**"     # globs the orchestrator accepts writes to
  lens_paths:
    core: docs/site-src/     # maps lens names to doc roots for reading
```

**Invariant:** every `lens_paths` entry must be covered by at least one `agent_editable_paths` glob. The loader enforces this at boot via `_validate_lens_paths_are_editable`. If a lens path has no matching editable glob, the agent can read docs it can never update — the loader rejects that config.

The editable glob can be narrower than the lens path. A lens `core: docs/` paired with editable `docs/generated/**` is valid: the agent reads from `docs/` but only writes into the `generated/` sub-path.

---

## `sources` block

```yaml
sources:
  git:
    host: github   # only "github" is supported today
  jira:
    enabled: true
    base_url: https://your-instance.atlassian.net
    project_keys:
      - CCE        # one or more project key prefixes to query
```

Jira enrichment is optional. Set `enabled: false` (or omit the `jira` key) to skip it. When `enabled: true` but `JIRA_EMAIL`/`JIRA_API_TOKEN` are missing from the environment, the run continues and marks `partial: true` with `error: "jira_auth_missing"`.

---

## `voice` block

```yaml
voice:
  sample_paths:
    - CLAUDE.md   # one or more paths; loaded by load_voice_samples in state_io.py
    - README.md
```

The `page-author` subagent reads these files to match your team's prose style. At least one path is recommended. If all paths are missing, authoring continues without voice signal and the output notes the gap.

---

## `lint` block

```yaml
lint:
  tier1: default   # enables all 7 Tier-1 rules
```

Tier-2 and Tier-3 rules are opt-in. Set a rule to `enabled` or `disabled` individually:

```yaml
lint:
  tier1: default
  tier2:
    heading-hierarchy: enabled
  tier3:
    passive-voice: disabled
```

---

## `publishing` block

The `publishing` block configures the publish-verifier: after a docs-agent PR merges, the verifier polls the host's CI to confirm the build succeeded and the page URL is live.

```yaml
publishing:
  base_url: https://your-org.github.io/your-repo/
  build_workflow: docs-pages.yml   # GitHub Actions workflow filename
  url_map_rule: standard
  verify_timeout_seconds: 60
  ci_provider: github              # "github" (default) | "circleci"
```

### Fields

**`base_url`** *(string | null)*

The root URL where pages are published. The verifier strips the `source_dir` prefix from a page's repo path and appends the remainder to `base_url` to construct the live URL it checks. Set to `null` to skip URL liveness checks while still verifying the CI build status.

**`build_workflow`** *(string | null)*

The filename of the GitHub Actions workflow that builds and deploys the docs site (e.g. `docs-pages.yml`). The verifier watches this workflow run on the merge commit. Set to `null` to disable CI-status polling; the verifier will only check the `base_url` if that is set.

**`url_map_rule`** *(string)*

Controls how the verifier maps a page's source path to its published URL. `standard` (the only supported value today) strips the `source_dir` prefix, drops the `.md` extension, and appends `.html`.

**`verify_timeout_seconds`** *(integer)*

How long the verifier waits for the CI run to complete and the page URL to respond with HTTP 200. Defaults to `60` if omitted.

**`ci_provider`** *(enum: `"github"` | `"circleci"`, default `"github"`)*

Identifies which CI system runs the docs-publish pipeline. This field was added in PR #82 (CCE-58) to support hosts that use CircleCI as the primary CI but GitHub Actions for docs publishing — the first example being `theoju/advanced-data-import-system`.

The field is **additive and backward-compatible**: omitting it is equivalent to `ci_provider: github`. Existing host configs with no `ci_provider` key continue to work unchanged.

> **Current limitation:** the publish-verifier reads `ci_provider` from the config but its CircleCI polling path is not yet implemented. When `ci_provider: circleci`, the verifier skips the CI-status poll and only checks the `base_url` liveness. Full CircleCI support is tracked in CCE-63.

### Hybrid-CI setup

Some hosts run primary checks on CircleCI but publish docs via a GitHub Actions workflow (the Pages deploy job). For these hosts, set `ci_provider: circleci` and keep `build_workflow` pointing to the GitHub Actions workflow filename. The agent uses `build_workflow` for the publish-side CI status check regardless of `ci_provider`.

```yaml
publishing:
  base_url: https://your-org.github.io/your-repo/
  build_workflow: docs-pages.yml
  url_map_rule: standard
  verify_timeout_seconds: 120
  ci_provider: circleci
```

Branch protection for hybrid-CI hosts requires deliberate configuration. See [the `advanced-data-import-system` onboarding runbook](../operations/advanced-data-import-system-onboarding.md) for a worked example of the branch-protection trade-offs.

---

## `notifications` block

```yaml
notifications:
  slack:
    enabled: false
    webhook_url: ""          # set via env var; do not commit tokens
  email:
    enabled: false
    recipients: []
```

Both channels are disabled by default. When `enabled: true`, the orchestrator sends a digest after each nightly run. Webhook URLs and credentials belong in environment variables or repo secrets, not committed into the config file.
