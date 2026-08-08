---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/72
synthesized_into: []
---

# actionlint CI gate

The `.github/workflows/actionlint.yml` workflow runs [`actionlint`](https://github.com/rhysd/actionlint) as a required pre-merge check on every pull request targeting `main`. It catches a class of GitHub Actions bugs that YAML schema validation cannot: context-scoping violations, illegal expression references, and expression syntax errors that only surface at dispatch time.

## Why this gate exists

CCE-45 diagnosed a hot-fix loop caused by `GITHUB_TOKEN` suppression of CI triggers. The fix (PR #65) introduced `GH_TOKEN: ${{ steps.app-token.outputs.token }}` at job-env scope. That construct is syntactically valid YAML — `yaml.safe_load` accepts it without complaint — but it is semantically illegal under GitHub Actions' context-scoping rules: `steps.*` is only available inside step definitions, not at the `env:` block of a job. GitHub's runtime validator rejected it with HTTP 422, requiring an immediate follow-up PR.

CCE-52 added `actionlint` so this class of error is caught before the branch merges, not after dispatch.

## What actionlint checks

`actionlint` understands GitHub Actions semantics beyond raw YAML structure. Key checks relevant to this repo:

- **Context scoping.** `steps.*`, `needs.*`, `matrix.*`, and similar contexts are only valid in specific positions. A reference at the wrong scope (e.g., `steps.*` inside a job-level `env:` block) is flagged as an error.
- **Expression syntax.** `${{ }}` expressions are parsed and validated. Mismatched braces, unknown functions, and type mismatches are reported.
- **Action reference validity.** Uses of `actions/*` and other pinned actions are checked for structural correctness.

Plain `yaml.safe_load` passes all of these silently; `actionlint` rejects them.

## Workflow structure

`.github/workflows/actionlint.yml` triggers on:

- **Every PR** targeting `main` (no `paths:` filter — actionlint is a required status check; omitting the filter ensures GitHub never sees the check as absent and blocks merge).
- **Push to `main`**, scoped by a `paths:` list so post-merge runs stay quiet:

```yaml
push:
  # post-merge runs on main only when workflows actually change
  branches: [main]
  paths:
    - ".github/workflows/**"
    - ".github/actionlint.yml"
```

The second glob currently matches nothing — `.github/` holds only `workflows/`, so this repo has no actionlint config file at all. It is dead because the file is absent, not because the extension is wrong: actionlint looks for a repo config under `.github/` at both spellings, trying the `.yaml` name first and falling back to the `.yml` name (`loadRepoConfig` in rhysd/actionlint v1.7.7). If you add a config, the `.yml` spelling is already covered by the trigger above; choosing the `.yaml` spelling means adding a second `paths:` entry alongside it. Either way, do not read the existing glob as evidence that a config file exists.

The job downloads `actionlint` at a pinned version (`1.7.7`) via the official download script, which verifies a checksum. The `Run actionlint` step (`.github/workflows/actionlint.yml`) runs with `-color` and exits non-zero on any finding, blocking merge.

## Running actionlint locally

Install `actionlint` before pushing workflow changes:

```bash
# One-time install (macOS with Homebrew)
brew install actionlint

# Or download the same pinned binary the CI uses
bash <(curl -sL https://raw.githubusercontent.com/rhysd/actionlint/v1.7.7/scripts/download-actionlint.bash) 1.7.7
```

Run it from the repo root:

```bash
./actionlint -color
```

Fix all reported errors before pushing. A clean local run means the CI gate passes without a round-trip to GitHub.

## Updating the pinned version

When you bump the `actionlint` version, update both the version tag in the download URL and the version argument on the same line (`.github/workflows/actionlint.yml`). The download script verifies a checksum; the version argument pins which release is fetched.
