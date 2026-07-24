---
ticket: CCE-124
status: approved
date: 2026-07-23
---

# CCE-124 — archive-lens `citation_exists` advisory via per-result lint severity

## 1. Problem

`citation_exists` (Tier-1 **block**) treats every inline-code span in a page's
prose as a repo citation that must resolve against today's HEAD. That contract is
correct for **live** documentation pages — a confabulated citation there is a real
navigation defect and must block.

It is the **wrong contract for an archive page**. An archive page is a historical
record, generated from a spec/plan; its citations are true _as of archival_ and
legitimately name code that has since moved, been removed, or is discussed as a
thing that must _not_ exist. The CCE-122 archive page cites:

- `` `tests/scripts/__init__.py` `` — absent **by design** (CCE-122's own rule:
  "tests/scripts must NOT be a package").
- `` `test_lint_runner` `` — a test-**family** shorthand; the real tests are
  `test_lint_runner_missing_script_reports_block`, etc.

So `citation_exists` blocks the page, the orchestrator excludes it, and **every
nightly run goes partial** re-authoring it (root cause of the recurring partial in
PR #189; the page has never landed on `main`). Enforcing current-HEAD existence
against a frozen historical record is a category error.

## 2. Approach — lens-scoped advisory (per-result severity)

Promote lint severity from **rule-global** to **per-result**, and make
`citation_exists` emit `severity: "warn"` for pages under an
`archive-index`-generator section, while staying a hard `block` on live lenses.

This is durable because it is **generation- and agent-independent**: it changes the
_policy applied to the output_, so it holds no matter how the archive page is
re-rendered. It is also _conceptually correct_ (archives are historical) and
_minimal + general_ (per-result severity is a small contract extension any future
rule can reuse).

### Why the change is small: the data model is already per-result

- `agents/content-validator.md` already emits `failed: [{path, rule, message,
severity∈{block,warn}}]` per failure (schema `content_validator.schema.json`).
- `scripts/orchestrator_runner.py` already gates page-exclusion + the `lint_block`
  partial reason on `fail.get("severity") == "block"` (a `warn` failure leaves the
  page in place and adds **no** partial reason).

The only gap is that `citation_exists` emits a single rule-global `block`. Close
that gap and the archive page lands (with an advisory warning in the digest —
signal preserved, gating power removed) and the run stops going partial. **The
orchestrator needs zero changes.**

## 3. Change set

| File                              | Change                                                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scripts/lint/citation_exists.py` | Load the host config; resolve archive-section dirs from `site.sections` (`generator == "archive-index"`, joined to `site.docs_dir` under the git repo root); add a per-result `severity` field to each result — `"warn"` for a page under an archive dir, else `"block"` (the module `SEVERITY` default). Rule-global top-level `severity` stays `"block"` for backward-compat. Exit code reflects **block-severity** failures only. |
| `scripts/lint/lint_runner.py`     | `any_block_failed` respects per-result severity: a result fails the build only if `not r["ok"] and r.get("severity", out.get("severity")) == "block"`. Rules with no per-result severity fall back to the rule-global value (byte-for-byte prior behavior).                                                                                                                                                                          |
| `agents/content-validator.md`     | Parsing contract: each `failed[]` item's `severity` is the **per-result** `severity` when present, else the rule's top-level `severity`. (`content_validator.schema.json` already permits `block`/`warn` — no schema change.)                                                                                                                                                                                                        |
| `scripts/orchestrator_runner.py`  | **No change** — already gates on `fail.severity == "block"`.                                                                                                                                                                                                                                                                                                                                                                         |

### Archive-dir resolution (generic-first)

```
archive_dirs(config, repo_root):
  docs_dir = config["site"]["docs_dir"]           # e.g. docs/site-src
  for sec in config["site"]["sections"]:
    if sec.get("generator") == "archive-index":
      yield (repo_root / docs_dir / sec["path"]).resolve()   # e.g. .../docs/site-src/archive
```

A page is archive-lens iff its resolved path is inside one of those dirs. Hosts
with **no** `archive-index` section (or no `site` block) yield no archive dirs, so
every result is `block` — identical to today. When the config is not inside a git
repo, `citation_exists` already degrades to "never block"; that path is unchanged.

## 4. Error handling / degradation

- Missing/empty `site`, `sections`, or `docs_dir` → no archive dirs → pure `block`
  (no crash). Unreadable/invalid config YAML → treat as no archive dirs (degrade to
  block, never crash the lint).
- A path that does not resolve on disk still gets a `severity` (default `block`);
  existence is decided by `check_path` as today.
- Live lenses (api, architecture, host-onboarding, whats-new, …) keep the hard
  block — the high-value navigation surface is unchanged.

## 5. Tradeoff (accepted)

A genuinely confabulated citation in a _future_ archive page would `warn`, not
`block`. Acceptable: archive pages are low-navigation historical records derived
from already-reviewed specs/plans, the finding still surfaces in the run digest,
and a permanent partial-run loop is strictly worse. Live pages are unaffected.

## 6. Test matrix

**`scripts/lint/citation_exists.py`:**

- Archive-lens page with a bad citation → result `ok:false, severity:"warn"`;
  process exit `0` (no block-failure).
- Live-lens page with the same bad citation → result `ok:false, severity:"block"`;
  exit `1`.
- Generic-first: config with **no** `archive-index` section → bad citation on any
  page → `severity:"block"` (backward-compat).
- Clean archive page (all citations resolve) → `ok:true` (severity field present,
  advisory; does not gate).

**`scripts/lint/lint_runner.py`:**

- A rule whose only failing results carry per-result `severity:"warn"` →
  `any_block_failed` False → exit `0`, result still reported.
- A failing result with per-result `severity:"block"` → exit `1`.
- Backward-compat: a rule output with no per-result `severity` → runner uses the
  rule-global `severity` (prior behavior preserved).

## 7. Acceptance criteria

1. `citation_exists` emits per-result `severity`, `"warn"` for archive-lens pages
   and `"block"` for live pages, resolved from `site.sections` under the repo root.
2. `lint_runner`'s block-gate respects per-result severity, with rule-global
   fallback (existing rules unchanged).
3. A bad citation on an archive-lens page no longer blocks, no longer excludes the
   page, and no longer flags the run partial; the same citation on a live page
   still blocks.
4. `content-validator.md` forwards per-result severity; `content_validator.schema.json`
   unchanged.
5. Generic-first: a host with no `archive-index` section behaves exactly as today.
6. Full `python3 -m pytest` suite green on the integrated tree.

## 8. Out of scope

The two stochastic partial causes in PR #189 — gap-detector `null`-for-boolean and
fact-checker prose-contamination — are separate follow-ups extending the CCE-118
benign-rescue precedent (cleanly-recovered agent quirks → info-only, not partial).
A per-token "negative citation" opt-out marker (for the rare live-page case) is a
possible future complement, deferred (YAGNI).
