# CCE-110 Factual-Accuracy Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop page-author confabulation from shipping: block pages citing nonexistent tests/paths (deterministic Tier-1 lint rule), warn on prose that contradicts cited code (new fact-checker subagent), and steer the author toward grounding in source.

**Architecture:** Three independent layers per the approved spec (`docs/superpowers/specs/2026-06-09-cce110-page-author-confabulation-design.md`): (1) advisory grounding inputs in the page-author contract, (2) `scripts/lint/citation_exists.py` — importable extractor + CLI rule registered in `TIER1_DEFAULT`, riding the existing block path, (3) `agents/fact-checker.md` — an 8th subagent dispatched per surviving authored page with ≥1 resolvable cited source; findings render as a PR-body warnings section and never block.

**Tech Stack:** Python 3 stdlib (+ existing `yaml`/`jsonschema` deps), pytest, existing fixture-driven dry-run dispatch.

**Branch:** `fix/CCE-110-page-author-confabulation` (already created; spec committed).

---

## File map

| File                                      | Action | Responsibility                                                                                                              |
| ----------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------- |
| `scripts/lint/citation_exists.py`         | Create | Extractor functions (shared helper) + CLI lint rule                                                                         |
| `tests/lint/test_citation_exists.py`      | Create | Extractor units, CLI integration, regression fixtures                                                                       |
| `scripts/lint/lint_runner.py`             | Modify | Add `"citation_exists"` to `TIER1_DEFAULT`                                                                                  |
| `tests/lint/test_lint_runner.py`          | Modify | Registration test                                                                                                           |
| `agents/schemas/fact_checker.schema.json` | Create | fact-checker output schema                                                                                                  |
| `scripts/contracts.py`                    | Modify | `FactCheckerResult` dataclass + registry entry                                                                              |
| `agents/fact-checker.md`                  | Create | fact-checker agent contract                                                                                                 |
| `agents/page-author.md`                   | Modify | `source_paths` input, grounding procedure, `evidence` output                                                                |
| `agents/schemas/page_author.schema.json`  | Modify | Declare optional `evidence` property                                                                                        |
| `scripts/orchestrator_runner.py`          | Modify | `source_paths` into page-author dispatch; fact-checker dispatch loop; thread `fact_warnings` into PR body + notifier digest |
| `tests/orchestrator/test_fact_checker.py` | Create | Contract validation + orchestrator wiring tests                                                                             |
| `CLAUDE.md`, `CHANGELOG.md`               | Modify | Subagent count (7→8), changelog entry                                                                                       |

Conventions that bind every task:

- Tests use the arbitrary-host fixtures in `tests/orchestrator/conftest.py` (`init_host`, `read_current_run`, `CONFIG_YAML`) for orchestrator tests; lint tests build their own tmp git hosts. Never rely on this repo's own tree.
- TDD: write the failing test, watch it fail for the right reason, implement minimally, watch it pass, commit.
- Run commands from the repo root `/Users/theo/Projects/engineering-docs-agent`.

---

### Task 1: Citation extractor (pure functions)

**Files:**

- Create: `scripts/lint/citation_exists.py` (extraction half only)
- Test: `tests/lint/test_citation_exists.py`

- [ ] **Step 1: Write the failing extractor tests**

Create `tests/lint/test_citation_exists.py`:

````python
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPTS_LINT = Path(__file__).parent.parent.parent / "scripts" / "lint"
sys.path.insert(0, str(SCRIPTS_LINT))
import citation_exists  # noqa: E402

SCRIPT = SCRIPTS_LINT / "citation_exists.py"


# ---------- extraction (pure) ----------


def test_extracts_repo_path_and_test_id():
    text = "See `scripts/foo.py` and `test_bar_baz` for details."
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_bar_baz"]


def test_line_suffix_stripped():
    assert citation_exists.extract_citations("`scripts/foo.py:123`")["paths"] == [
        "scripts/foo.py"
    ]
    assert citation_exists.extract_citations("`scripts/foo.py:10-20`")["paths"] == [
        "scripts/foo.py"
    ]


def test_duplicates_collapse():
    text = "`scripts/foo.py` twice `scripts/foo.py`, `test_x` twice `test_x`"
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == ["scripts/foo.py"]
    assert cites["tests"] == ["test_x"]


def test_placeholders_urls_and_env_refs_skipped():
    text = (
        "`docs/specs/YYYY-MM-DD-x.md` `<path>` `glob/*.md` `{owner}/file.py` "
        "`https://x.test/a.py` `~/conf/a.yml` `$HOME/a.sh` `dir/.../file.py`"
    )
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}


def test_fenced_blocks_ignored():
    text = (
        "intro prose\n"
        "```python\n"
        "x = load(\"`scripts/fake_in_fence.py`\")\n"
        "```\n"
        "outro cites `test_real_one`\n"
    )
    cites = citation_exists.extract_citations(text)
    assert cites["paths"] == []
    assert cites["tests"] == ["test_real_one"]


def test_vocabulary_tokens_skipped():
    # No slash and not a test identifier -> not a citation.
    text = "`partial_reasons` `run.time_budget_seconds` `frontmatter_contract.py`"
    assert citation_exists.extract_citations(text) == {"paths": [], "tests": []}
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'citation_exists'`

- [ ] **Step 3: Write the extraction half of the module**

Create `scripts/lint/citation_exists.py`:

````python
"""Lint rule: citation_exists (CCE-110, Tier-1).

Verifies that repo artifacts cited in a page's PROSE actually exist: inline
code spans naming repo paths (`scripts/foo.py`, optional `:line` /
`:start-end` suffix) or test identifiers (`test_snake_case`). Confabulated
pages cite tests/files that were never written; this rule blocks them.

Scope notes:
- Fenced code blocks are stripped first — fenced examples are legitimately
  hypothetical. Only inline code spans in prose are checked.
- Distinct from capability C1 (scripts/verify_citations.py), which verifies
  pinned `path:line` + `<!--pin:TOKEN-->` citations on existing pages. This
  rule needs no pins and checks bare existence on newly authored pages.
- Generic-first degradation: when the config's directory is not inside a git
  repo, every path passes trivially (we cannot verify; we never block).
- The extraction functions are imported by scripts/orchestrator_runner.py
  (fact-checker dispatch). They are a shared-helper contract: grep callers
  repo-wide before changing signatures (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RULE_NAME = "citation_exists"
SEVERITY = "block"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_TEST_ID_RE = re.compile(r"^test_[a-z0-9_]+$")
# dir/file.ext with optional :line or :start-end suffix; leading / allowed
# (absolute paths are relativized or skipped at verification time).
_REPO_PATH_RE = re.compile(r"^[\w.\-/]+/[\w.\-]+\.\w{1,8}(?::\d+(?:-\d+)?)?$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
_PLACEHOLDER_MARKERS = ("<", ">", "*", "{", "}", "YYYY", "...")


def strip_fenced_blocks(text: str) -> str:
    """Drop ``` / ~~~ fenced regions; return the remaining prose lines."""
    out: list[str] = []
    in_fence = False
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _is_placeholder(token: str) -> bool:
    return (
        any(m in token for m in _PLACEHOLDER_MARKERS)
        or token.startswith(("~", "$"))
        or "://" in token
    )


def extract_citations(text: str) -> dict[str, list[str]]:
    """Citations in prose, deduped in document order.

    Returns {"paths": [...], "tests": [...]} — repo-path tokens have any
    trailing :line suffix stripped.
    """
    paths: list[str] = []
    tests: list[str] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if not token or _is_placeholder(token):
            continue
        if _TEST_ID_RE.match(token):
            if token not in tests:
                tests.append(token)
        elif _REPO_PATH_RE.match(token):
            bare = _LINE_SUFFIX_RE.sub("", token)
            if bare not in paths:
                paths.append(bare)
    return {"paths": paths, "tests": tests}
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "feat(CCE-110): citation extractor — prose inline-code paths and test ids"
```

---

### Task 2: Repo verification + CLI + regression fixtures

**Files:**

- Modify: `scripts/lint/citation_exists.py` (verification half + `main`)
- Test: `tests/lint/test_citation_exists.py` (append)

- [ ] **Step 1: Write the failing verification/CLI tests**

Append to `tests/lint/test_citation_exists.py`:

```python
# ---------- verification + CLI (tmp git host) ----------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _init_host(tmp_path: Path) -> tuple[Path, Path]:
    """Arbitrary-host fixture: git repo with one module, one test, a config."""
    repo = tmp_path / "host"
    (repo / "scripts").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "scripts" / "real_module.py").write_text("def real_fn():\n    return 1\n")
    (repo / "tests" / "test_real.py").write_text(
        "def test_real_behavior():\n    assert True\n"
    )
    (repo / ".engineering-docs-agent").mkdir()
    cfg = repo / ".engineering-docs-agent" / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo, cfg


def _run_cli(paths: list[Path], cfg: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_existing_citations_pass(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("Cites `scripts/real_module.py` and `test_real_behavior`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0
    assert out["rule"] == "citation_exists"
    assert out["severity"] == "block"
    assert out["results"][0]["ok"] is True


def test_nonexistent_test_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("Verified by `test_never_written`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent test 'test_never_written'" in out["results"][0]["message"]


def test_nonexistent_path_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/ghost.py` for the sentinel logic.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent path 'scripts/ghost.py'" in out["results"][0]["message"]


def test_untracked_but_present_path_passes(tmp_path):
    # A page authored in the same run may cite a file that exists on disk but
    # is not yet tracked (e.g. a generated sibling). Existence on disk wins.
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "fresh.py").write_text("x = 1\n")  # not committed
    page = repo / "page.md"
    page.write_text("Cites `scripts/fresh.py`.\n")
    rc, _ = _run_cli([page], cfg)
    assert rc == 0


def test_no_git_passes_trivially(tmp_path):
    cfg = tmp_path / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    page = tmp_path / "page.md"
    page.write_text("Cites `scripts/ghost.py` and `test_never_written`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0
    assert "skipped" in out["results"][0]["message"]


def test_missing_page_file_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    rc, out = _run_cli([repo / "absent.md"], cfg)
    assert rc == 1
    assert out["results"][0]["message"] == "file not found"


# ---------- regression: the two confabulated pages (condensed) ----------

CONFABULATED_STATE_ADVANCEMENT = """\
# Orchestrator state advancement

Invariant 1 — no advance on partial. The runner records the decision in a
sentinel file `.engineering-docs-agent/last_run_invariant.json`.

Verified by `test_state_not_advanced_on_partial`,
`test_state_advanced_on_clean`, and `test_state_no_sha_regression`.
"""

CONFABULATED_GIT_STAGING = """\
# Orchestrator git staging

The runner does not use git add -A; PR #97 replaced it with the pathspec
form. Verified by `test_stage_uses_pathspec_not_add_all`.
"""


def test_regression_confabulated_state_advancement_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "state-advancement.md"
    page.write_text(CONFABULATED_STATE_ADVANCEMENT)
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "test_state_not_advanced_on_partial" in msg
    assert "test_state_advanced_on_clean" in msg
    assert "test_state_no_sha_regression" in msg
    assert "last_run_invariant.json" in msg


def test_regression_confabulated_git_staging_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "git-staging.md"
    page.write_text(CONFABULATED_GIT_STAGING)
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "test_stage_uses_pathspec_not_add_all" in out["results"][0]["message"]


# ---------- orchestrator-facing helper ----------


def test_resolve_cited_sources_returns_existing_relative_paths(tmp_path):
    repo, _ = _init_host(tmp_path)
    text = "Cites `scripts/real_module.py:3` and `scripts/ghost.py`."
    assert citation_exists.resolve_cited_sources(text, repo) == [
        "scripts/real_module.py"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -v`
Expected: Task-1 tests PASS; new tests FAIL with `AttributeError` (no `resolve_cited_sources`) and CLI tests fail with empty stdout (`json.decoder.JSONDecodeError`) since the script has no `main`.

- [ ] **Step 3: Implement verification + CLI**

Append to `scripts/lint/citation_exists.py`:

```python
def repo_root_for(config_path: Path) -> Path | None:
    """Host repo root via git, anchored at the config's directory. None when
    the config does not live inside a git repo (degrade: never block)."""
    r = subprocess.run(
        ["git", "-C", str(config_path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    top = r.stdout.strip()
    return Path(top) if r.returncode == 0 and top else None


def tracked_files(repo_root: Path) -> set[str]:
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
    )
    return set(r.stdout.splitlines()) if r.returncode == 0 else set()


def cited_test_exists(repo_root: Path, name: str) -> bool:
    """True if any tracked file defines or calls the named test."""
    for needle in (f"def {name}(", f"{name}("):
        r = subprocess.run(
            ["git", "-C", str(repo_root), "grep", "-l", "-F", needle],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
    return False


def _relativize(path_str: str, repo_root: Path) -> str | None:
    """Repo-relative form of a cited path; None when an absolute path falls
    outside the repo (an environment reference, not a repo citation)."""
    if not path_str.startswith("/"):
        return path_str
    try:
        return str(Path(path_str).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return None


def check_path(
    path: Path, repo_root: Path | None, files: set[str]
) -> tuple[bool, str]:
    if repo_root is None:
        return True, "no git repo detected; citation check skipped"
    if not path.exists():
        return False, "file not found"
    cites = extract_citations(path.read_text())
    problems: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        # Disk-existence fallback: same-run siblings are not yet tracked.
        if rel not in files and not (repo_root / rel).exists():
            problems.append(f"cites nonexistent path '{cited}'")
    for name in cites["tests"]:
        if not cited_test_exists(repo_root, name):
            problems.append(f"cites nonexistent test '{name}'")
    if problems:
        return False, "; ".join(problems)
    return True, "ok"


def resolve_cited_sources(text: str, repo_root: Path) -> list[str]:
    """Repo-relative cited paths that exist on disk — the fact-checker's
    cited_sources input. Ordered, deduped."""
    out: list[str] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel and (repo_root / rel).exists() and rel not in out:
            out.append(rel)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = repo_root_for(args.config)
    files = tracked_files(repo_root) if repo_root else set()
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, repo_root, files)
        results.append({"path": str(p), "ok": ok, "message": message})
        if not ok:
            any_failed = True
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": results}, sys.stdout
        )
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -v`
Expected: all PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "feat(CCE-110): citation_exists verification, CLI, and regression fixtures"
```

---

### Task 3: Register the rule in Tier-1

**Files:**

- Modify: `scripts/lint/lint_runner.py:21-31`
- Test: `tests/lint/test_lint_runner.py`

- [ ] **Step 1: Write the failing registration test**

Append to `tests/lint/test_lint_runner.py`:

```python
def test_citation_exists_registered_in_tier1():
    from scripts.lint.lint_runner import TIER1_DEFAULT, enabled_rules

    assert "citation_exists" in TIER1_DEFAULT
    assert "citation_exists" in enabled_rules({"lint": {"tier1": "default"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_lint_runner.py::test_citation_exists_registered_in_tier1 -v`
Expected: FAIL — `assert 'citation_exists' in [...]`

- [ ] **Step 3: Register the rule**

In `scripts/lint/lint_runner.py`, add one entry to `TIER1_DEFAULT`:

```python
TIER1_DEFAULT = [
    "frontmatter_schema",
    "internal_links",
    "markdown_hygiene_lang",
    "markdown_hygiene_structure",
    "footnotes",
    "diagrams",
    "framework_build",
    "stub_redirect",
    "description_quality",
    "citation_exists",
]
```

- [ ] **Step 4: Run the lint test directory**

Run: `python3 -m pytest tests/lint/ -v`
Expected: all PASS. (`test_runs_tier1_default` keeps rc 0 because its config sits in `tmp_path`, outside any git repo, so the new rule passes trivially — the degradation path doing its job.)

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/lint_runner.py tests/lint/test_lint_runner.py
git commit -m "feat(CCE-110): register citation_exists in TIER1_DEFAULT"
```

---

### Task 4: fact-checker contract (schema + dataclass + agent doc)

**Files:**

- Create: `agents/schemas/fact_checker.schema.json`
- Create: `agents/fact-checker.md`
- Modify: `scripts/contracts.py`
- Test: `tests/orchestrator/test_fact_checker.py` (new)

- [ ] **Step 1: Write the failing contract tests**

Create `tests/orchestrator/test_fact_checker.py` (mirror the sys.path/import style of sibling files in `tests/orchestrator/` — they import `contracts` / `orchestrator_runner` directly via the test-suite path setup):

```python
from __future__ import annotations
import json
import subprocess
from pathlib import Path

from contracts import validate_and_parse

SCHEMAS = Path(__file__).parent.parent.parent / "agents" / "schemas"


def test_fact_checker_contradiction_output_validates():
    raw = {
        "ok": True,
        "verdict": "contradiction",
        "page": "docs/site-src/core/page.md",
        "findings": [
            {
                "claim": "page says partial runs never advance the baseline",
                "source_path": "scripts/runner.py",
                "evidence": "advance happens unconditionally at save_state()",
            }
        ],
    }
    parsed, reasons = validate_and_parse("fact-checker", raw)
    assert reasons == []
    assert parsed.verdict == "contradiction"
    assert parsed.findings[0]["source_path"] == "scripts/runner.py"


def test_fact_checker_minimal_output_validates_with_empty_findings():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "consistent"}
    )
    assert reasons == []
    assert parsed.findings == []


def test_fact_checker_bad_verdict_rejected():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "maybe"}
    )
    assert parsed is None
    assert any("schema_invalid" in r for r in reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: FAIL with `schema_missing: fact-checker` reasons (assertions on `reasons == []` fail)

- [ ] **Step 3: Create the schema**

Create `agents/schemas/fact_checker.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "fact-checker output",
  "type": "object",
  "required": ["ok", "verdict"],
  "properties": {
    "page": { "type": "string" },
    "verdict": { "enum": ["consistent", "contradiction", "unverifiable"] },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim"],
        "properties": {
          "claim": { "type": "string" },
          "source_path": { "type": "string" },
          "evidence": { "type": "string" }
        }
      }
    },
    "ok": { "type": "boolean" },
    "error": { "type": ["string", "null"] }
  }
}
```

- [ ] **Step 4: Add the dataclass and registry entry**

In `scripts/contracts.py`, after `NotifierResult`:

```python
@dataclass(frozen=True)
class FactCheckerResult:
    ok: bool
    verdict: str
    page: str | None = None
    findings: list[dict] = None  # type: ignore[assignment]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.findings is None:
            object.__setattr__(self, "findings", [])
```

And in `_DATACLASS_BY_NAME`:

```python
    "fact-checker": FactCheckerResult,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: 3 PASS

- [ ] **Step 6: Write the agent contract doc**

Create `agents/fact-checker.md`:

````markdown
---
name: fact-checker
description: Verify that an authored docs page's prose claims match the cited source code.
model: sonnet
tools:
  - Read
  - Grep
---

# fact-checker

## Job

Read one authored docs page and the repo source files it cites. For every
checkable behavioral claim (what a function does, an invariant, a default, a
contract), verify the cited source actually supports it.

**Counterintuitive code wins over convention.** If the source does something
surprising, the page must say the surprising thing. A claim that matches
common practice but contradicts the cited code is a contradiction — that is
exactly the confabulation this agent exists to catch (CCE-110).

This is a warn-layer check: you report findings; you never edit files.

## Inputs

- `page_path`: repo-relative path of the authored page
- `cited_sources`: list of repo-relative source paths the page cites (already
  filtered to files that exist)
- `lens`: lens name (e.g. "core") — context only
- `plugin_root`: absolute path to the plugin checkout (unused by the default
  procedure; present for parity with sibling agents)

## Output schema (canonical)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "fact-checker output",
  "type": "object",
  "required": ["ok", "verdict"],
  "properties": {
    "page": { "type": "string" },
    "verdict": { "enum": ["consistent", "contradiction", "unverifiable"] },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim"],
        "properties": {
          "claim": { "type": "string" },
          "source_path": { "type": "string" },
          "evidence": { "type": "string" }
        }
      }
    },
    "ok": { "type": "boolean" },
    "error": { "type": ["string", "null"] }
  }
}
```
````

Return ONLY a JSON object that validates against this schema. No prose, no
markdown fences around the response, no commentary.

## Output contract

The canonical schema is in §Output schema above; it is authoritative.

- `verdict: "consistent"` — every checkable claim is supported; `findings: []`.
- `verdict: "contradiction"` — at least one claim contradicts a cited source.
  One finding per contradicted claim: `claim` quotes or tightly paraphrases
  the page; `source_path` names the contradicting file; `evidence` states
  what the source actually does (cite the line or symbol).
- `verdict: "unverifiable"` — sources unreadable or no checkable claims.
  `findings: []`. This is a clean skip, never a failure.

## Procedure

1. Read the page at `page_path`. List its checkable behavioral claims.
2. Read each file in `cited_sources`. Grep for the symbols the page names.
3. For each claim, decide: supported, contradicted, or not checkable.
4. Emit the JSON verdict. Do not report style issues, omissions, or claims
   about files outside `cited_sources` — contradictions only.

## Failure handling

If the page itself cannot be read, return
`{ok: false, verdict: "unverifiable", error: "page unreadable: <path>"}`.

````

- [ ] **Step 7: Commit**

```bash
git add agents/schemas/fact_checker.schema.json agents/fact-checker.md scripts/contracts.py tests/orchestrator/test_fact_checker.py
git commit -m "feat(CCE-110): fact-checker subagent contract, schema, dataclass"
````

---

### Task 5: page-author grounding contract

**Files:**

- Modify: `agents/page-author.md`
- Modify: `agents/schemas/page_author.schema.json`
- Test: `tests/orchestrator/test_fact_checker.py` (append)

- [ ] **Step 1: Write the failing schema tests**

Append to `tests/orchestrator/test_fact_checker.py`:

```python
def test_page_author_schema_declares_evidence():
    schema = json.loads((SCHEMAS / "page_author.schema.json").read_text())
    assert "evidence" in schema["properties"]
    assert (
        schema["properties"]["evidence"]["properties"]["files_read"]["type"]
        == "array"
    )


def test_page_author_output_with_evidence_validates():
    raw = {
        "ok": True,
        "path": "docs/site-src/core/page.md",
        "action": "create",
        "evidence": {"files_read": ["scripts/real_module.py"]},
    }
    parsed, reasons = validate_and_parse("page-author", raw)
    assert reasons == []
    assert parsed.ok
```

- [ ] **Step 2: Run tests to verify the first fails**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: `test_page_author_schema_declares_evidence` FAILs (`KeyError: 'evidence'`); the second passes already (schema is permissive) — its value is pinning the contract against a future `additionalProperties: false`.

- [ ] **Step 3: Update the schema**

In `agents/schemas/page_author.schema.json`, add to `properties`:

```json
    "evidence": {
      "type": "object",
      "properties": {
        "files_read": { "type": "array", "items": { "type": "string" } }
      }
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: all PASS

- [ ] **Step 5: Update the agent doc**

In `agents/page-author.md`:

(a) Add to **## Inputs** after the `frontmatter_template` bullet:

```markdown
- `source_paths`: optional list of repo-relative code files the summarized
  PRs touched. Ground your claims in these files (see Procedure step 3).
```

(b) In the **## Output schema** JSON block, add to `properties` (matching the schema file):

```json
    "evidence": {
      "type": "object",
      "properties": {
        "files_read": { "type": "array", "items": { "type": "string" } }
      }
    }
```

(c) Replace Procedure step 3 (`3. Compose content reflecting ...`) with:

```markdown
3. Ground before you write (CCE-110): if `source_paths` is provided, Read the
   files relevant to the claims you are about to make. Any statement about
   behavior, invariants, defaults, or tests must come from what you read —
   never from what is conventional. If the code does something surprising,
   write the surprising thing. Cite only files and tests you confirmed exist.
   Then compose content reflecting `summaries`. Be concrete, no filler.
   Prefer second-person addressing the engineer-reader unless samples show
   otherwise.
```

(d) Append to step 6 (`6. Emit JSON response.`):

```markdown
6. Emit JSON response. Include `evidence: {files_read: [...]}` listing the
   source files you actually read (advisory — used for run forensics).
```

- [ ] **Step 6: Commit**

```bash
git add agents/page-author.md agents/schemas/page_author.schema.json tests/orchestrator/test_fact_checker.py
git commit -m "feat(CCE-110): page-author grounding inputs and advisory evidence"
```

---

### Task 6: Orchestrator — source_paths into page-author dispatch

**Files:**

- Modify: `scripts/orchestrator_runner.py` (authoring loop, ~line 1434)
- Test: `tests/orchestrator/test_fact_checker.py` (append)

- [ ] **Step 1: Write the failing wiring test**

Append to `tests/orchestrator/test_fact_checker.py`. The fakes-dir setup is shared by Tasks 6–8, so define it as a module-level helper now:

```python
import orchestrator_runner


def _write_fakes(fakes: Path, *, with_fact_checker: bool = True) -> None:
    """Minimal dry-run fixture set for one PR -> one core page."""
    fakes.mkdir(parents=True, exist_ok=True)
    (fakes / "fake_source_collector.json").write_text(
        json.dumps(
            {
                "prs": [
                    {
                        "number": 1,
                        "url": "https://example.test/pr/1",
                        "merge_sha": "",
                        "files": [
                            {"path": "scripts/real_module.py"},
                            "plain_listed.py",
                        ],
                        "jira_keys": [],
                    }
                ],
                "jira_issues": [],
            }
        )
    )
    (fakes / "fake_pr_summarizer.json").write_text(
        json.dumps(
            {
                "pr_number": 1,
                "what_changed": "module behavior",
                "doc_targets": [
                    {"lens": "core", "page_hint": "page.md", "action": "create"}
                ],
            }
        )
    )
    (fakes / "fake_page_author.json").write_text(
        json.dumps(
            {"ok": True, "path": "docs/site-src/core/page.md", "action": "create"}
        )
    )
    (fakes / "fake_content_validator.json").write_text(
        json.dumps({"passed": [], "failed": []})
    )
    (fakes / "fake_gap_detector.json").write_text(
        json.dumps({"pr_id": "o/r#1", "needs_spec": False})
    )
    (fakes / "fake_notifier.json").write_text(
        json.dumps({"slack_ok": True, "email_ok": True})
    )
    if with_fact_checker:
        (fakes / "fake_fact_checker.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "verdict": "contradiction",
                    "page": "docs/site-src/core/page.md",
                    "findings": [
                        {
                            "claim": "page says X but code does Y",
                            "source_path": "scripts/real_module.py",
                            "evidence": "real_fn returns 1",
                        }
                    ],
                }
            )
        )


def _host_with_module(init_host, tmp_path) -> Path:
    """init_host + one committed source file the pages can cite."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "real_module.py").write_text(
        "def real_fn():\n    return 1\n"
    )
    return init_host({"version": "1"})


def test_page_author_receives_source_paths(init_host, tmp_path, monkeypatch):
    _host_with_module(init_host, tmp_path)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    captured: dict = {}
    real = orchestrator_runner.dispatch_validated

    def spy(name, inputs, **kw):
        if name == "page-author":
            captured["inputs"] = inputs
        return real(name, inputs, **kw)

    monkeypatch.setattr(orchestrator_runner, "dispatch_validated", spy)
    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    assert captured["inputs"]["source_paths"] == [
        "plain_listed.py",
        "scripts/real_module.py",
    ]
```

(`init_host` scaffolds the host and commits everything present in `tmp_path`, so create `scripts/real_module.py` BEFORE calling it — `_host_with_module` does this.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py::test_page_author_receives_source_paths -v`
Expected: FAIL — `KeyError: 'source_paths'`

- [ ] **Step 3: Implement**

In `scripts/orchestrator_runner.py`, inside the authoring loop, immediately before the `out, reasons = dispatch_validated("page-author", ...)` call (~line 1434), build the grounding list:

```python
            # CCE-110 layer 1: ground the author in the code the PRs touched.
            grounding: set[str] = set()
            for s in batch_summaries:
                for pr in prs:
                    if pr.get("number") != s.get("pr_number"):
                        continue
                    for f in pr.get("files") or []:
                        fname = f.get("path") if isinstance(f, dict) else f
                        if isinstance(fname, str) and fname:
                            grounding.add(fname)
```

and add to the page-author `inputs` dict (after `"frontmatter_template": fm_template,`):

```python
                    "source_paths": sorted(grounding),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_fact_checker.py
git commit -m "feat(CCE-110): thread source_paths grounding into page-author dispatch"
```

---

### Task 7: Orchestrator — fact-checker dispatch loop

**Files:**

- Modify: `scripts/orchestrator_runner.py` (after the content-validation block, ~line 1537; plus `authored_lens` tracking in the authoring loop)
- Test: `tests/orchestrator/test_fact_checker.py` (append)

- [ ] **Step 1: Write the failing dispatch tests**

Append to `tests/orchestrator/test_fact_checker.py`:

```python
CITED_PAGE = """\
---
status: draft
sources: []
synthesized_into: null
---
# Page

This page cites `scripts/real_module.py` in prose.
"""

UNCITED_PAGE = CITED_PAGE.replace(" cites `scripts/real_module.py` in", " has no citations in")


def _precreate_page(tmp_path: Path, text: str) -> Path:
    page = tmp_path / "docs" / "site-src" / "core" / "page.md"
    page.write_text(text)  # exists -> orchestrator takes the edit path
    return page


def test_fact_checker_dispatched_for_cited_page(
    init_host, tmp_path, read_current_run
):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert len(cr["fact_check_warnings"]) == 1
    warning = cr["fact_check_warnings"][0]
    assert "docs/site-src/core/page.md" in warning
    assert "page says X but code does Y" in warning
    assert "scripts/real_module.py" in warning
    assert cr["partial"] is False  # warn layer never flips partial


def test_fact_checker_skipped_for_page_without_citations(
    init_host, tmp_path, read_current_run
):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, UNCITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes, with_fact_checker=False)  # dispatch would log a reason

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["fact_check_warnings"] == []
    assert not any("fact_checker" in r for r in cr["partial_reasons"])


def test_fact_checker_failure_is_info_only(init_host, tmp_path, read_current_run):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes, with_fact_checker=False)  # missing fixture = dispatch None

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    cr = read_current_run(state_path)
    assert cr["fact_check_warnings"] == []
    assert any(
        r.startswith("fact_checker_unavailable: docs/site-src/core/page.md")
        for r in cr["partial_reasons"]
    )
    assert cr["partial"] is False  # info_only: never flips partial


def test_fact_checker_consistent_verdict_yields_no_warnings(
    init_host, tmp_path, read_current_run
):
    state_path = _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)
    (fakes / "fake_fact_checker.json").write_text(
        json.dumps({"ok": True, "verdict": "consistent", "findings": []})
    )

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=True)
    assert rc == 0
    assert read_current_run(state_path)["fact_check_warnings"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: the four new tests FAIL with `KeyError: 'fact_check_warnings'`

- [ ] **Step 3: Implement the dispatch loop**

(a) In the authoring loop, next to `authored: list[str] = []` (~line 1405) add:

```python
        authored_lens: dict[str, str] = {}
```

and where a page is recorded (`authored.append(str(target_path))`) add:

```python
                authored_lens[str(target_path)] = lens
```

(b) Insert AFTER the content-validation block (after the `add_partial(state, f"lint_block: ...")` loop ends, ~line 1537) and BEFORE the site-generators block:

```python
        # CCE-110 layer 3: factual-accuracy fact-checker (warn layer). One
        # dispatch per surviving authored page that cites >=1 resolvable repo
        # source. Findings are operator-facing warnings only: info_only
        # reasons, a PR-body section, and the run record — never a partial
        # flag, never a dropped page.
        fact_warnings: list[str] = []
        fact_pages = [p for p in authored if Path(p).exists()]
        if fact_pages:
            lint_dir = str(_PLUGIN_ROOT / "scripts" / "lint")
            if lint_dir not in sys.path:
                sys.path.insert(0, lint_dir)
            import citation_exists as _citation_exists

            for page in fact_pages:
                page_path = Path(page)
                try:
                    page_text = page_path.read_text()
                except OSError:
                    continue
                cited_sources = _citation_exists.resolve_cited_sources(
                    page_text, repo_root
                )
                if not cited_sources:
                    continue
                try:
                    page_rel = str(
                        page_path.resolve().relative_to(repo_root.resolve())
                    )
                except ValueError:
                    page_rel = page
                fc_out, fc_reasons = dispatch_validated(
                    "fact-checker",
                    {
                        "page_path": page_rel,
                        "cited_sources": cited_sources,
                        "lens": authored_lens.get(page, ""),
                        "plugin_root": str(_PLUGIN_ROOT),
                    },
                    dry_run_dir=dry_run_dir,
                    cwd=repo_root,
                )
                for r in fc_reasons:
                    add_partial(state, r, info_only=True)
                if fc_out is None:
                    add_partial(
                        state,
                        f"fact_checker_unavailable: {page_rel}",
                        info_only=True,
                    )
                    continue
                if fc_out.get("verdict") == "contradiction":
                    for finding in fc_out.get("findings", []):
                        claim = (finding.get("claim") or "").strip()
                        src = (finding.get("source_path") or "").strip()
                        suffix = f" (vs `{src}`)" if src else ""
                        fact_warnings.append(f"`{page_rel}`: {claim}{suffix}")
        state["current_run"]["fact_check_warnings"] = fact_warnings
```

Note: `monkeypatch.setattr(orchestrator_runner, "dispatch_validated", ...)` in the Task-6 test only intercepts module-global lookups, which is exactly how this loop calls it — no change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: all PASS

- [ ] **Step 5: Run the full orchestrator test directory (regression sweep)**

Run: `python3 -m pytest tests/orchestrator/ -q`
Expected: all PASS — existing dry-run tests author citation-free default pages, so no fact-checker dispatch fires and no fixture is required.

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_fact_checker.py
git commit -m "feat(CCE-110): fact-checker dispatch loop with warn-only semantics"
```

---

### Task 8: PR-body warnings section + notifier digest

**Files:**

- Modify: `scripts/orchestrator_runner.py` — `_compose_pr_body` (~line 2097), `open_or_append_pr` (~line 2490) and its internal `_compose_pr_body` call, the `open_or_append_pr` call site in `run()` (~line 1723), and the notifier `digest` dict (~line 1760)
- Test: `tests/orchestrator/test_fact_checker.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_fact_checker.py`:

```python
def test_compose_pr_body_renders_fact_warnings():
    body = orchestrator_runner._compose_pr_body(
        changed_files=["docs/site-src/core/page.md"],
        lens_paths={"core": "docs/site-src/core"},
        partial=False,
        partial_reasons=[],
        baseline_sha="a" * 40,
        current_sha="b" * 40,
        fact_warnings=["`docs/site-src/core/page.md`: claim (vs `scripts/x.py`)"],
    )
    assert "**Factual-accuracy warnings:**" in body
    assert "- `docs/site-src/core/page.md`: claim (vs `scripts/x.py`)" in body


def test_compose_pr_body_warnings_alone_render():
    body = orchestrator_runner._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
        fact_warnings=["w1"],
    )
    assert "Factual-accuracy warnings" in body
    assert body != "docs-agent run"


def test_compose_pr_body_no_warnings_keeps_legacy_sentinel():
    body = orchestrator_runner._compose_pr_body(
        changed_files=[],
        lens_paths=None,
        partial=False,
        partial_reasons=[],
        baseline_sha="",
        current_sha="",
    )
    assert body == "docs-agent run"


def test_run_threads_fact_warnings_to_pr_and_digest(
    init_host, tmp_path, monkeypatch
):
    _host_with_module(init_host, tmp_path)
    _precreate_page(tmp_path, CITED_PAGE)
    fakes = tmp_path / "fakes"
    _write_fakes(fakes)

    seen_pr: dict = {}

    def fake_open(repo_root, gh, **kw):
        seen_pr.update(kw)
        return 1, []

    monkeypatch.setattr(orchestrator_runner, "open_or_append_pr", fake_open)

    seen_notifier: dict = {}
    real = orchestrator_runner.dispatch_validated

    def spy(name, inputs, **kw):
        if name == "notifier":
            seen_notifier.update(inputs)
        return real(name, inputs, **kw)

    monkeypatch.setattr(orchestrator_runner, "dispatch_validated", spy)

    rc = orchestrator_runner.run(tmp_path, dry_run_dir=fakes, no_pr=False)
    assert rc == 0
    assert len(seen_pr["fact_warnings"]) == 1
    assert "page says X but code does Y" in seen_pr["fact_warnings"][0]
    assert seen_notifier["digest"]["fact_check_warnings"] == seen_pr["fact_warnings"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: the three `_compose_pr_body` tests FAIL with `TypeError: ... unexpected keyword argument 'fact_warnings'`; the threading test FAILs with `KeyError: 'fact_warnings'`

- [ ] **Step 3: Implement**

(a) `_compose_pr_body`: add the kwarg and section. New signature:

```python
def _compose_pr_body(
    *,
    changed_files: list[str],
    lens_paths: dict[str, str] | None,
    partial: bool,
    partial_reasons: list[str],
    baseline_sha: str,
    current_sha: str,
    top_n: int = 5,
    fact_warnings: list[str] | None = None,
) -> str:
```

Inside, define `has_warnings = bool(fact_warnings)` next to the other `has_*` flags, and extend BOTH early returns so warnings force full rendering:

```python
    if not has_files and not has_baseline and not has_reasons and not has_warnings:
        return "docs-agent run"

    if not has_files and not has_baseline and has_reasons and not has_warnings:
        return _format_partial_digest(partial_reasons)
```

Add the section between the top-N block and the partial-digest block:

```python
    if has_warnings:
        warn_lines = ["**Factual-accuracy warnings:**"]
        warn_lines.extend(f"- {w}" for w in fact_warnings)
        sections.append("\n".join(warn_lines))
```

(b) `open_or_append_pr`: add `fact_warnings: list[str] | None = None` after `current_sha: str = ""` in the signature, and pass `fact_warnings=fact_warnings` through at its internal `_compose_pr_body(` call (locate with `grep -n "_compose_pr_body(" scripts/orchestrator_runner.py` — pass it at every call inside `open_or_append_pr`).

(c) `run()` call site (~line 1723): add to the `open_or_append_pr(...)` kwargs:

```python
            fact_warnings=state["current_run"].get("fact_check_warnings") or [],
```

(d) Notifier `digest` dict (~line 1760): add:

```python
            "fact_check_warnings": state["current_run"].get("fact_check_warnings")
            or [],
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_fact_checker.py -v`
Expected: all PASS

- [ ] **Step 5: Run orchestrator + lint suites**

Run: `python3 -m pytest tests/orchestrator/ tests/lint/ -q`
Expected: all PASS (existing `_compose_pr_body` tests unaffected — the kwarg defaults to None)

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_fact_checker.py
git commit -m "feat(CCE-110): factual-accuracy warnings in PR body and notifier digest"
```

---

### Task 9: Docs, changelog, full validation

**Files:**

- Modify: `CLAUDE.md` (subagent count), `CHANGELOG.md` (`## [Unreleased]`)
- Possibly modify: other files enumerating the seven subagents

- [ ] **Step 1: Find stale subagent-count references**

Run: `grep -rn --include="*.md" --include="*.json" -i "seven s\|seven a\|7 subagent\|seven subagent" CLAUDE.md README.md agents/ skills/ .claude-plugin/ docs/setup-guide.md 2>/dev/null`

Update every hit that counts the subagents: seven → eight (the CLAUDE.md header line "seven specialized subagents" is a known hit). Do not touch historical/archived prose (e.g. old spec documents describing the state at their date).

- [ ] **Step 2: Add the changelog entry**

In `CHANGELOG.md` under `## [Unreleased]`, add (create an `### Added` heading there if absent):

```markdown
### Added

- **Factual-accuracy guard for authored pages (page-author confabulation fix).** Three layers: page-author now receives `source_paths` grounding inputs and returns advisory `evidence.files_read`; a new Tier-1 `citation_exists` lint rule blocks pages citing nonexistent repo paths or test identifiers (regression-pinned against the two 2026-06-09 confabulated pages); a new warn-only `fact-checker` subagent (the eighth) flags prose that contradicts cited source, rendered as a "Factual-accuracy warnings" PR-body section. Generic-first: no git → trivial pass, no citations → no dispatch, fact-checker failure → info-only note. Tracker: CCE-110.
```

- [ ] **Step 3: Full integrated test suite**

Run: `python3 -m pytest -q`
Expected: 0 failures (baseline before this branch: 986 passed, 3 skipped)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md CHANGELOG.md README.md docs/setup-guide.md
git commit -m "docs(CCE-110): changelog entry; subagent count seven -> eight"
```

(Only add the files Step 1 actually changed.)

---

## Post-plan quality gates (session-level, after all tasks)

1. `/simplify` pass over the diff (`git diff main...HEAD`) — apply verified simplifications only.
2. `/code-review` (high effort, 7 finder angles + verify) over the branch diff; fix confirmed findings TDD-style.
3. Full `python3 -m pytest -q` green; then push, open PR titled `fix(CCE-110): factual-accuracy guard — citation lint rule, fact-checker subagent, page-author grounding`, merge per repo conventions (integrated suite green, not GitHub "mergeable"), and run `scripts/prune_merged_branches.py --apply` after merge.
