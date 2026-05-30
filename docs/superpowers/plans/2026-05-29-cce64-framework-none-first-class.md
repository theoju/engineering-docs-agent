# CCE-64 — framework=none as first-class config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docs.framework: none` a valid, first-class config value so plain-markdown host repos can adopt the plugin without scaffolding a synthetic mkdocs site.

**Architecture:** Additive enum extension on `templates/config.schema.json` + four small code edits across `scripts/preflight_host.py` and `scripts/lint/framework_build.py` + tests + a host-onboarding doc section. No new abstractions. Existing mkdocs and docusaurus host configs validate and behave identically.

**Tech Stack:** Python 3.11+, jsonschema (Draft 7), pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-05-29-cce64-framework-none-first-class-design.md`

**Branch:** `feat/CCE-64-framework-none-first-class` (already exists, one commit ahead of `main` with the spec).

**Test runner:** `python3 -m pytest`

**Commit trailer (every commit):**

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Constraints:** Never use `-f` / `--force` / `--no-verify` / `--amend`. All commits to `feat/CCE-64-framework-none-first-class`.

---

## File map

| File                                           | Action                        | What changes                                                                                                       |
| ---------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `templates/config.schema.json`                 | Modify (lines 17-21)          | Add `"none"` to `docs.framework` enum; update description                                                          |
| `scripts/lint/framework_build.py`              | Modify (lines 44-52)          | Default fallback `"mkdocs"` → `"none"`; add explicit `elif framework == "none"` branch                             |
| `scripts/preflight_host.py`                    | Modify (line 41)              | `framework or "mkdocs"` → `framework or "none"`                                                                    |
| `scripts/preflight_host.py`                    | Modify (lines 94-106)         | Replace `no_docs_framework` _warning_ with `framework_none` _info_ notice; add optional `severity` field           |
| `tests/schemas/test_config_schema.py`          | Extend                        | Add `framework: none` accept + `framework: hugo` reject case                                                       |
| `tests/lint/test_framework_build.py`           | Extend                        | Add `framework: none` skip-with-reason case + assert default fallback                                              |
| `tests/setup/test_preflight_host.py`           | Extend + modify (lines 63-78) | Replace existing `no_docs_framework` assertion with `framework_none` + add `proposed_config` framework value check |
| `docs/host-onboarding/framework-none.md`       | Create                        | New onboarding section: "Choosing framework=none"                                                                  |
| `skills/engineering-docs-agent-setup/SKILL.md` | Inspect; modify if needed     | Verify the prompt's framework hint doesn't hard-code mkdocs/docusaurus only                                        |

---

## Task 1: Schema — accept `framework: none`

**Files:**

- Modify: `templates/config.schema.json:17-21`
- Test: `tests/schemas/test_config_schema.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_config_schema.py`:

```python
def test_framework_none_accepted():
    cfg = yaml.safe_load("""
docs:
  framework: none
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/ }
sources: { git: { host: github } }
lint: { tier1: default }
publishing:
  base_url: null
  build_workflow: null
  url_map_rule: standard
notifications: {}
""")
    validate(cfg, SCHEMA)


def test_framework_hugo_rejected():
    cfg = yaml.safe_load("""
docs:
  framework: hugo
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing:
  base_url: https://x
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
""")
    with pytest.raises(ValidationError):
        validate(cfg, SCHEMA)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/schemas/test_config_schema.py::test_framework_none_accepted tests/schemas/test_config_schema.py::test_framework_hugo_rejected -v`

Expected: `test_framework_none_accepted` FAILS with `ValidationError: 'none' is not one of ['mkdocs', 'docusaurus']`. `test_framework_hugo_rejected` PASSES (existing schema already rejects `hugo`).

If `test_framework_none_accepted` doesn't fail with that message, stop and investigate before editing the schema.

- [ ] **Step 3: Update the schema**

Edit `templates/config.schema.json` lines 17-21. Replace:

```json
"framework": {
  "type": "string",
  "enum": ["mkdocs", "docusaurus"],
  "description": "Docusaurus support is partial in v0.1; build validation skipped."
},
```

with:

```json
"framework": {
  "type": "string",
  "enum": ["mkdocs", "docusaurus", "none"],
  "description": "SSG framework for the host's docs site. Use 'none' when the host has no SSG and renders raw markdown via GitHub or another mechanism. Docusaurus support is partial in v0.1; build validation is skipped for 'docusaurus' and 'none'."
},
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/schemas/test_config_schema.py -v`

Expected: all schema tests (existing + new two) PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/schemas/test_config_schema.py
git commit -m "$(cat <<'EOF'
feat(CCE-64): add 'none' to docs.framework enum

Additive enum extension. Existing host configs with framework: mkdocs
or framework: docusaurus continue to validate unchanged. New value
'none' is the explicit form of "host has no SSG; renders markdown via
GitHub or another mechanism". Code paths that honor framework=none
land in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: framework_build lint — explicit `none` branch + default

**Files:**

- Modify: `scripts/lint/framework_build.py:44-52`
- Test: `tests/lint/test_framework_build.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/lint/test_framework_build.py`:

```python
def test_framework_none_skipped_with_reason(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("docs:\n  framework: none\n  source_dir: docs\n")
    fake = tmp_path / "fake.md"
    fake.write_text("# x")
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            str(fake),
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    result = out["results"][0]
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "framework=none; no build validation applicable"


def test_framework_default_is_none_when_missing(tmp_path):
    # When docs.framework is omitted, the lint rule must treat it as 'none'
    # (not silently coerce to 'mkdocs' as before).
    cfg = tmp_path / "c.yml"
    cfg.write_text("docs:\n  source_dir: docs\n")
    fake = tmp_path / "fake.md"
    fake.write_text("# x")
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            str(fake),
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    out = json.loads(r.stdout)
    result = out["results"][0]
    assert result["ok"] is True
    assert result["skipped"] is True
    assert "framework=none" in result["reason"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/lint/test_framework_build.py::test_framework_none_skipped_with_reason tests/lint/test_framework_build.py::test_framework_default_is_none_when_missing -v`

Expected: `test_framework_none_skipped_with_reason` FAILS — current code returns reason `"framework=none; build validation not supported in v0.1"` (because the else branch catches `none`). `test_framework_default_is_none_when_missing` FAILS — current code defaults to `"mkdocs"` and tries to find `mkdocs.yml`, returning `"no mkdocs.yml in repo root"` instead of a `framework=none` reason.

- [ ] **Step 3: Update the lint rule**

Edit `scripts/lint/framework_build.py` lines 44-52. Replace:

```python
    framework = config.get("docs", {}).get("framework", "mkdocs")
    if framework == "mkdocs":
        ok, skipped, reason = run_mkdocs(Path.cwd())
    else:
        ok, skipped, reason = (
            True,
            True,
            f"framework={framework}; build validation not supported in v0.1",
        )
```

with:

```python
    framework = config.get("docs", {}).get("framework", "none")
    if framework == "mkdocs":
        ok, skipped, reason = run_mkdocs(Path.cwd())
    elif framework == "none":
        ok, skipped, reason = (
            True,
            True,
            "framework=none; no build validation applicable",
        )
    else:
        ok, skipped, reason = (
            True,
            True,
            f"framework={framework}; build validation not supported in v0.1",
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/lint/test_framework_build.py -v`

Expected: all `test_framework_build.py` tests PASS (existing mkdocs/docusaurus/no-mkdocs-yml tests + new two).

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/framework_build.py tests/lint/test_framework_build.py
git commit -m "$(cat <<'EOF'
feat(CCE-64): framework_build honors 'none' explicitly

- Default fallback when docs.framework is missing changes from 'mkdocs'
  to 'none'. This stops silently driving the rule into a mkdocs build
  path when the host has no SSG.
- New elif branch returns a tighter reason for framework=none, distinct
  from the generic "not supported in v0.1" message used for other
  frameworks (e.g. docusaurus).

Block-severity behavior unchanged: ok=True + skipped=True short-
circuits the block path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: preflight `proposed_config` — drop silent mkdocs coercion

**Files:**

- Modify: `scripts/preflight_host.py:41`
- Test: `tests/setup/test_preflight_host.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/setup/test_preflight_host.py`:

```python
def test_preflight_proposed_config_writes_framework_none_for_bare_host():
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "bare"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # Was silently coerced to "mkdocs" before CCE-64; now explicit "none".
    assert out["proposed_config"]["docs"]["framework"] == "none"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/setup/test_preflight_host.py::test_preflight_proposed_config_writes_framework_none_for_bare_host -v`

Expected: FAILS — current value is `"mkdocs"` (from the `framework or "mkdocs"` coercion).

- [ ] **Step 3: Update preflight**

Edit `scripts/preflight_host.py` line 41. Change:

```python
            "framework": framework or "mkdocs",
```

to:

```python
            "framework": framework or "none",
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v`

Expected: the new test PASSES. **One existing test, `test_preflight_emits_warning_when_no_framework`, still passes** because it inspects `warnings`, not `proposed_config` — and `compute_warnings` still emits `no_docs_framework` at this point (Task 4 changes that).

If any other test fails, stop and investigate before committing.

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight_host.py tests/setup/test_preflight_host.py
git commit -m "$(cat <<'EOF'
feat(CCE-64): preflight writes framework=none, not silent mkdocs

scripts/preflight_host.py:41 was silently coercing a detected
framework of None into "mkdocs", which then forced framework-less
hosts (e.g. plain-markdown Next.js hosts like CCE-57's target) to
install Python + mkdocs purely to satisfy schema validation.

With "none" now in the schema enum (Task 1), the coercion isn't
needed and is actively misleading: the user sees a proposed_config
that doesn't match their actual host shape.

Warning-emission code in compute_warnings is updated in the next
commit; this commit is scoped to the proposed_config change so the
diff stays focused.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: preflight `compute_warnings` — replace `no_docs_framework` warning with `framework_none` info notice

**Files:**

- Modify: `scripts/preflight_host.py:94-106`
- Modify: `tests/setup/test_preflight_host.py:63-78` (the existing `test_preflight_emits_warning_when_no_framework` test)

- [ ] **Step 1: Update the existing test to assert the new shape (this is the failing test)**

Edit `tests/setup/test_preflight_host.py`. Replace the function `test_preflight_emits_warning_when_no_framework` (currently lines 63-78) with:

```python
def test_preflight_emits_framework_none_info_for_bare_host():
    """Bare host (no mkdocs.yml, no docusaurus.config.*) gets an info-
    level notice, NOT a block-severity warning. The notice's code is
    `framework_none`. The old `no_docs_framework` warning is gone."""
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(FIX / "bare"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    codes = {w["code"] for w in out["warnings"]}
    assert "framework_none" in codes
    assert "no_docs_framework" not in codes
    framework_none = next(w for w in out["warnings"] if w["code"] == "framework_none")
    assert framework_none.get("severity") == "info"
    # Message names both detection points and the upgrade hint.
    msg = framework_none["message"]
    assert "mkdocs.yml" in msg
    assert "docusaurus" in msg.lower()
```

- [ ] **Step 2: Run to verify the test fails**

Run: `python3 -m pytest tests/setup/test_preflight_host.py::test_preflight_emits_framework_none_info_for_bare_host -v`

Expected: FAILS — current `compute_warnings` emits a warning with `code: no_docs_framework` and no `severity` field.

- [ ] **Step 3: Update `compute_warnings`**

Edit `scripts/preflight_host.py`. Replace lines 94-106 (the `if not discovery.get("framework"):` block) with:

```python
    if not discovery.get("framework"):
        warnings.append(
            {
                "code": "framework_none",
                "severity": "info",
                "message": (
                    "No mkdocs.yml or docusaurus.config.* found at the repo root. "
                    "Config will write framework: none. The framework_build lint "
                    "rule and the publish-verifier skip cleanly; PR summaries, "
                    "page authoring, and what's-new updates run normally. "
                    "If you want strict build-time link checking, scaffold mkdocs "
                    "(`mkdocs init`) and re-run preflight."
                ),
            }
        )
```

- [ ] **Step 4: Run to verify the test passes — and that existing tests still pass**

Run: `python3 -m pytest tests/setup/test_preflight_host.py -v`

Expected: all preflight tests PASS, including the modified `test_preflight_emits_framework_none_info_for_bare_host`. No other test referenced `no_docs_framework` (verified by `grep -rn no_docs_framework tests/` returning only the one we just updated).

If anything fails, stop and investigate before committing.

- [ ] **Step 5: Commit**

```bash
git add scripts/preflight_host.py tests/setup/test_preflight_host.py
git commit -m "$(cat <<'EOF'
feat(CCE-64): preflight info notice replaces no_docs_framework warning

With framework=none a first-class config (Task 1), the previous
`no_docs_framework` warning is semantically wrong — it told the user
to install mkdocs or Docusaurus to fix a problem that's no longer a
problem.

Replaced with an info-level `framework_none` notice that:
- declares the resulting capability degradation (build lint + publish-
  verify skip cleanly; everything else runs normally)
- describes the upgrade path (scaffold mkdocs if strict link checking
  is desired)

Introduces an optional `severity` field on warning entries with two
values: `info` (notice) and the implicit block-severity (anything
without `severity`). Existing callers that don't read severity are
unaffected.

Existing test `test_preflight_emits_warning_when_no_framework` updated
in the same commit to match the new shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Documentation — host-onboarding section + setup-skill audit

**Files:**

- Create: `docs/host-onboarding/framework-none.md`
- Inspect (and modify if needed): `skills/engineering-docs-agent-setup/SKILL.md` (or equivalent file)

- [ ] **Step 1: Locate the setup skill file**

Run: `find skills/engineering-docs-agent-setup -type f 2>/dev/null && ls -la skills/ 2>/dev/null | head -20`

Expected: produces the path to the setup skill's SKILL.md (or equivalent).

- [ ] **Step 2: Inspect the setup skill for hard-coded framework enum**

Run: `grep -n -E 'framework|mkdocs|docusaurus' skills/engineering-docs-agent-setup/SKILL.md`

Read the output. If the file references `framework: mkdocs|docusaurus` (or "must be mkdocs or docusaurus") in user-facing prompts, the prompt needs to mention `none` as a third option. If the file only references frameworks in narrative context without enumerating valid values, no change is needed.

If a prompt-enum hint exists and needs `none` added, make the edit. Example: a line like `"framework": "<mkdocs|docusaurus>"` becomes `"framework": "<mkdocs|docusaurus|none>"`. Match the surrounding format exactly.

- [ ] **Step 3: Create the host-onboarding section**

Write `docs/host-onboarding/framework-none.md`:

```markdown
# Choosing `framework: none`

Use `docs.framework: none` when your host repo has no static-site
generator (SSG) — for example, a Next.js application whose docs are
plain markdown rendered by GitHub at `https://github.com/<owner>/<repo>/blob/main/docs/`.

## What runs

- `pr-summarizer`, `page-author`, `content-validator` (Tier-1 rules),
  `gap-detector`, `notifier`: all run normally.
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
```

- [ ] **Step 4: Verify the doc renders as expected**

Run: `head -20 docs/host-onboarding/framework-none.md && wc -l docs/host-onboarding/framework-none.md`

Expected: prints the first 20 lines + a line count (should be ~40 lines). No mkdocs build step needed — this repo's docs build pipeline already covers the directory.

- [ ] **Step 5: Commit**

```bash
git add docs/host-onboarding/framework-none.md
# Add the SKILL.md change only if Step 2 found a hard-coded enum that needed updating:
git status --short skills/ 2>/dev/null
# If 'M skills/engineering-docs-agent-setup/SKILL.md' appears, include it:
# git add skills/engineering-docs-agent-setup/SKILL.md

git commit -m "$(cat <<'EOF'
docs(CCE-64): host-onboarding guide for framework=none

Adds docs/host-onboarding/framework-none.md describing:
- which orchestrator stages run (all of them) and which skip
  (framework_build, publish-verifier with null base_url)
- when to upgrade to mkdocs and how (4-step recipe)

If the setup skill's prompt enumerated framework values as
mkdocs|docusaurus only, that hint is updated to include 'none' in
the same commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Full-suite verification + preflight smoke test

**Files:** none modified

- [ ] **Step 1: Run the full pytest suite**

Run: `python3 -m pytest`

Expected: all tests PASS. No skips beyond the ones that were already skipped before CCE-64. No new warnings about deprecated config shapes.

If any test fails, stop and investigate. The most likely failure modes are:

- A test elsewhere that asserts `framework or "mkdocs"` behavior.
- A test that imports the warning code `no_docs_framework` from another module.

Run `grep -rn 'no_docs_framework\|framework or "mkdocs"' tests/ scripts/` to confirm no other site references the old behavior.

- [ ] **Step 2: Smoke-test preflight against the bare fixture**

Run: `python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/bare --format json | python3 -m json.tool`

Expected output includes:

- `discovery.framework: null`
- `proposed_config.docs.framework: "none"`
- A `warnings` entry with `code: "framework_none"` and `severity: "info"`
- NO warning with `code: "no_docs_framework"`

- [ ] **Step 3: Smoke-test against an mkdocs fixture (regression check)**

Run: `python3 scripts/preflight_host.py --repo-root tests/fixtures/setup_repos/mkdocs_lensy --format json | python3 -m json.tool 2>&1 | head -30`

Expected: `discovery.framework: "mkdocs"`, `proposed_config.docs.framework: "mkdocs"`. No `framework_none` warning emitted. Existing behavior preserved.

- [ ] **Step 4: Confirm the branch is in good shape for shipping**

Run: `git log --oneline origin/main..HEAD`

Expected: 6 commits on this branch (the spec from before + 5 implementation commits):

1. `docs(CCE-64): spec — framework=none as first-class config`
2. `feat(CCE-64): add 'none' to docs.framework enum`
3. `feat(CCE-64): framework_build honors 'none' explicitly`
4. `feat(CCE-64): preflight writes framework=none, not silent mkdocs`
5. `feat(CCE-64): preflight info notice replaces no_docs_framework warning`
6. `docs(CCE-64): host-onboarding guide for framework=none`

Run: `git status` — must show "nothing to commit, working tree clean".

- [ ] **Step 5: No commit — this is a verification-only task**

If everything above passes, the branch is ready for `/ship`. The controller (subagent-driven-development) will hand off to /ship as a separate step.

---

## Out of scope (do not implement here)

- Adapter-class refactor (`scripts/framework_adapters/`) — revisit when a 3rd framework with build-validation lands.
- Capability flags (`lint.framework_build.enabled` etc.) — revisit if a host needs to override a single capability.
- Docusaurus build-validation parity — still partial; `framework_build` still skips for docusaurus.
- CCE-57 host follow-up (claude-code-self-assessment#100) — separate work after this plan ships.

---

## Verification of self-review (controller bookkeeping)

| Spec section                    | Task(s) covering it                                                          |
| ------------------------------- | ---------------------------------------------------------------------------- |
| §1 Config schema                | Task 1                                                                       |
| §2 Discovery                    | (no change needed — already returns `None`; covered by smoke test in Task 6) |
| §3 Preflight `proposed_config`  | Task 3                                                                       |
| §3 Preflight `compute_warnings` | Task 4                                                                       |
| §4 Lint rule                    | Task 2                                                                       |
| §5 Documentation                | Task 5                                                                       |
| Testing (§Testing)              | Tasks 1, 2, 3, 4 + Task 6 verification                                       |
| Data flow                       | Task 6 smoke tests                                                           |
| Error handling                  | Tasks 2, 4 (behaviors verified by tests)                                     |
| Migration                       | No code; verified by Task 6 mkdocs fixture smoke test                        |
| Success criteria                | Task 6                                                                       |

All spec requirements have a task. No placeholders. Type/name consistency: every reference to `framework_none` (code, severity, message), `framework=none; no build validation applicable` (reason string), and `framework or "none"` (preflight default) is used identically across tasks.
