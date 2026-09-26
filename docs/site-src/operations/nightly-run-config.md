---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/279
synthesized_into: []
---

# Nightly Run Config

The nightly run's shape — how long it works, how many PRs it admits, when it gives up on a stuck PR, and now, which other repositories it may cite — comes from two blocks in the host's config: `run:` and `lint:`. This page is the reference for both.

## The `run:` block

All five keys are optional; every one has a default that keeps a host that configures nothing running the pre-existing behavior.

| Key | Default | Meaning |
| --- | --- | --- |
| `time_budget_seconds` | `2700` (45 min) | Soft per-run deadline. `0` disables it — every per-loop check becomes a no-op and the run authors, fact-checks, and gap-checks everything it admitted. |
| `reuse_pr_summaries` | `true` | Serve a merged PR's stored `pr-summarizer` output across nightly runs instead of re-dispatching, while its `merge_sha` and the `agents/pr-summarizer.md` fingerprint both still match. |
| `deferral_skip_threshold` | `3` | Consecutive runs a PR may be deferred before the next run abandons it — the advance cursor walks past it and the PR is recorded in `state.json`'s `skipped_prs`. `0` disables skipping, restoring indefinite-stall behavior. |
| `authoring_hard_cap_seconds` | `time_budget_seconds * 1.15`, clamped against the GitHub App token TTL | Ceiling the page-authoring loop may never cross, even to finish the PR-boundary group the soft deadline defers to. Must be strictly greater than `time_budget_seconds` — an equal or lower value is rejected at startup, not clamped up. |
| `window_pr_cap` | `10` | Maximum merged PRs one run admits, oldest-first. PRs past the cap are held for a later run; `0` removes the cap. |

## The `merge:` block

| Key | Default | Meaning |
| --- | --- | --- |
| `policy` | `auto` | `auto` squash-merges a fully green, non-partial run's PR. `manual` leaves every PR open for operator review. Absent `merge:` block = `auto`. |
| `checks_grace_seconds` | `120` | How long to wait for host CI checks to register before merging without them. |
| `checks_timeout_seconds` | `900` | Maximum wait for registered checks to settle. |

Both windows are bounded by the `run.time_budget_seconds` budget, so polling can never itself blow the workflow timeout.

## Citing another repository: `lint.external_repos`

`citation_exists` — the Tier-1 rule that blocks a backticked path that does not exist in the host checkout — is correct to block a citation into a file that genuinely does not exist. It is *wrong* for a file that is real but lives in a different repository: a token that is simultaneously true and, without help, uncitable. Before this config block existed, that block was not a stall an operator noticed — the deferral skip abandoned the PR and the page was silently never written.

`lint.external_repos` lets you declare a neighboring repository so `page-author` can cite it safely:

```yaml
lint:
  external_repos:
    design-system:
      url: "https://github.com/acme/design-system"
    internal-tools:
      private: true
```

Each key is a single-segment prefix an author writes as `<prefix>/<path in that repo>`. `scripts/external_refs.py:resolve_config` validates the block at config load, raising `ExternalRepoConfigError` on any of:

- a prefix containing `/` (must be a single segment),
- a prefix that collides with a real directory in the host repo,
- an entry declaring both `url` and `private`, or neither — exactly one is required,
- a `blob_template` whose placeholders don't resolve against the fixed `{url}`, `{ref}`, `{path}` set (checked once, at load, by formatting it against dummy values — so a config typo fails loudly at startup instead of once per page on every run).

A public entry (`url` set) defaults `ref` to `main` and `blob_template` to `{url}/blob/{ref}/{path}`; both are overridable per entry. A private entry never gets a template — its whole point is that the repository name is never rendered anywhere.

### What `page-author` actually sees

The orchestrator hands the agent only the declared *prefixes* — `scripts/orchestrator_runner.py:_external_repo_prefixes` returns the config's `external_repos` keys, nothing else. `page-author` is told to cite a real cross-repo file as `` `<prefix>/<path>` `` and never to construct a URL itself; on a host with no `external_repos` declared, the list is empty and no prefix is legal for that dispatch, so an ordinary path is the only citable form. An undeclared prefix, or a plain in-repo path, is left completely alone by everything described below and still blocks exactly as it always did.

### Render before lint, not repair after block

The renderer runs on the finished page text, once per authored page, **before** `citation_exists` ever sees it: `scripts/orchestrator_runner.py:_render_external_refs_for_pages` calls `external_refs.render_external_refs`, and `run()` invokes it ahead of both the CCE-141 shortened-citation diagnostic and the lint pass. Ordering here is load-bearing — running the diagnostic first would inspect a token that is about to be rewritten and misreport it as a shortened, unresolvable citation.

Because the rewrite happens first, `citation_exists` never sees the prefixed form at all — it only ever sees an ordinary in-repo path (already resolvable) or a rendered link/filename (nothing left to check) or an undeclared-prefix token (correctly still blocks). The linter itself needed no change.

A declared token renders to one of two forms:

- **Public** (`url` set): a Markdown link, `` [`basename`](blob-url) ``, where `basename` is the last path segment and the blob URL is built from the entry's `url`/`ref`/`blob_template`. A trailing `:line`/`:symbol` citation suffix is kept in the visible link text but stripped from the URL — left in the URL it would silently 404 while still passing the linter.
- **Private** (`private: true`): the bare basename, `` `name` `` — the repository is never named anywhere in the rendered output.

The rewrite deliberately declines to touch a token that sits inside an ambiguous backtick run (for example, a token wrapped in double backticks next to another backtick) rather than try to model CommonMark's run-length pairing correctly. A declined token simply reverts to pre-existing behavior: `citation_exists` sees the raw, unrendered `prefix/path` form and blocks it, loudly and self-healing via the usual lint-block revert.

### Failure handling

The render step is config-gated and best-effort per page, not a hard dependency of the run:

- A host with no `lint.external_repos` declared is an exact no-op — no file I/O at all, and an already-clean page is byte-for-byte untouched.
- A page path that doesn't exist on disk (routine when a batch's dry-run synth never wrote it) is silently skipped, not an error.
- A render failure on one page does not stop the rest of the batch; it's caught, recorded as a `partial_reasons` entry of the form `external_ref_render_failed: <page>: <ExceptionType>: ...`, and classified `degraded=True` — the run held this page back rather than losing it blind.
- Writes are atomic: the renderer writes to a `.tmp` sibling and `os.replace`s it onto the real page, so a write-time failure (disk full, permission revoked mid-write) leaves the real page exactly as it was, never half-written.

### Reachability today

No host in production has declared `lint.external_repos` yet, so every behavior above is exercised only by tests, not a live nightly run.

## Related

- PR #279 — cross-repo citation rendering (CCE-181)
- CCE-181 — declared-neighbor citations, render-before-lint
- CCE-141 — the shortened-citation diagnostic this feature runs ahead of
- CCE-140 — the deferral-skip hatch that made an unrenderable cross-repo citation costly enough to fix
- `docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md` — full design spec
