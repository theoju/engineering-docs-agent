# CCE-124 Implementation Plan — archive-lens `citation_exists` advisory

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use `- [ ]`.

**Goal:** Make `citation_exists` advisory (`warn`) on archive-lens pages via a
per-result lint `severity`, so archive pages that legitimately cite removed/forbidden
code stop blocking + flagging the nightly run partial. Live lenses keep the hard block.

**Architecture:** Per-result `severity` (new); `citation_exists` resolves archive-index
section dirs from `site.sections`/`docs_dir` and marks results under them `warn`;
`lint_runner` respects per-result severity with rule-global fallback; the orchestrator
already gates on `fail.severity == "block"` (unchanged).

**Tech Stack:** Python stdlib + `yaml` (already a lint dep); pytest.

Spec: `docs/superpowers/specs/2026-07-23-cce124-archive-lens-citation-advisory-design.md`

---

### Task 1: per-result severity + archive-lens resolution in `citation_exists`

**Files:**

- Modify: `scripts/lint/citation_exists.py`
- Test: `tests/lint/test_citation_exists.py`

- [ ] **Step 1 — failing tests.** Build a tmp git repo + host config with a `site`
      block: `docs_dir: docs/site-src`, one section `{path: archive/, generator: archive-index}`
      and one live section `{path: architecture/}`. Author an archive page and a live page
      that both cite a nonexistent path (`` `scripts/nope.py` ``). Assert via `main()`/`check`:
  - archive page result → `ok False`, `severity == "warn"`; process exit `0`.
  - live page result → `ok False`, `severity == "block"`; exit `1`.
  - config with the archive section removed → archive page result `severity == "block"`.
  - clean archive page (cites a real file) → `ok True`.
- [ ] **Step 2 — run red:** `pytest tests/lint/test_citation_exists.py -k archive -v` → FAIL (no per-result severity yet).
- [ ] **Step 3 — implement.** Add `import yaml`. Add helpers:

  ```python
  def _load_config(config_path: Path) -> dict:
      try:
          return yaml.safe_load(config_path.read_text()) or {}
      except (OSError, yaml.YAMLError):
          return {}

  def archive_dirs(config: dict, repo_root: Path) -> list[Path]:
      site = config.get("site") or {}
      docs_dir = site.get("docs_dir") or ""
      out: list[Path] = []
      for sec in site.get("sections") or []:
          if isinstance(sec, dict) and sec.get("generator") == "archive-index":
              out.append((repo_root / docs_dir / (sec.get("path") or "")).resolve())
      return out

  def _under(path: Path, roots: list[Path]) -> bool:
      try:
          rp = path.resolve()
      except OSError:
          return False
      for r in roots:
          try:
              rp.relative_to(r)
              return True
          except ValueError:
              continue
      return False
  ```

  In `main()`: after `repo_root = repo_root_for(args.config)`, compute
  `arch = archive_dirs(_load_config(args.config), repo_root) if repo_root else []`.
  Per path: `sev = "warn" if _under(p, arch) else SEVERITY`; append
  `{"path": str(p), "ok": ok, "message": message, "severity": sev}`; set
  `any_block_failed = True` only when `not ok and sev == "block"`. Return
  `1 if any_block_failed else 0`. Keep top-level `"severity": SEVERITY`.

- [ ] **Step 4 — run green:** `pytest tests/lint/test_citation_exists.py -v` → PASS.
- [ ] **Step 5 — commit:** `feat(CCE-124): per-result severity + archive-lens advisory in citation_exists`.

### Task 2: `lint_runner` respects per-result severity

**Files:**

- Modify: `scripts/lint/lint_runner.py`
- Test: `tests/lint/test_lint_runner.py`

- [ ] **Step 1 — failing tests.** Monkeypatch/stub `run_rule` to return a rule output
      whose `results` carry per-result `severity`. Assert `main()` (or the aggregation
      helper) returns exit `0` when the only failing results are `severity:"warn"`, exit
      `1` when a failing result is `severity:"block"`, and — backward-compat — a rule
      output with no per-result `severity` falls back to the rule-global `severity`.
- [ ] **Step 2 — run red** → FAIL (runner uses rule-global severity only).
- [ ] **Step 3 — implement.** Replace the block-gate in `main()`:
  ```python
  for r in out["results"]:
      sev = r.get("severity", out.get("severity"))
      if sev == "block" and not r["ok"]:
          any_block_failed = True
          break
  ```
  (Drop the outer `if out.get("severity") == "block"` guard — per-result severity with
  rule-global fallback subsumes it.)
- [ ] **Step 4 — run green** → PASS.
- [ ] **Step 5 — commit:** `feat(CCE-124): lint_runner block-gate respects per-result severity`.

### Task 3: content-validator contract forwards per-result severity

**Files:**

- Modify: `agents/content-validator.md`
- Verify (no change): `agents/schemas/content_validator.schema.json`

- [ ] **Step 1 — doc edit.** In the parsing-contract section, state that each
      `failed[]` item's `severity` is the **per-result** `severity` from the rule output
      when present, else the rule's top-level `severity`. Note archive-index pages emit
      `warn` for `citation_exists`.
- [ ] **Step 2 — verify schema unchanged.** Confirm `content_validator.schema.json`
      already permits `severity ∈ {block, warn}` (no edit needed); if a sync test exists,
      run it.
- [ ] **Step 3 — commit:** `docs(CCE-124): content-validator forwards per-result lint severity`.

### Final: integrated suite + adversarial subagent validation + /ship

- [ ] Full `python3 -m pytest` green on the integrated tree (mkdocs on PATH for site tests).
- [ ] Adversarial subagent validation (correctness / test non-vacuity / blast-radius) over the branch diff.
- [ ] `/ship` — PR title contains `CCE-124`; auto-deliver per standing posture (merge on green CI, verify Jira Done, prune).
