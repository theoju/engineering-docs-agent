# CCE-122 Stable Code Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop recurring fact-checker line-drift warnings (which block the CCE-101 auto-merge gate) by making code citations line-free (`path:symbol` / bare `path`, never `path:line`), moving citation-existence onto a deterministic lint, scoping the fact-checker to behavioral truth, and migrating the 96 existing `:line` pins.

**Architecture:** Extend the existing `citation_exists` Tier-1 lint (block) to recognize and verify `:symbol` suffixes; add a sibling advisory `citation_line_free` rule (warn) that flags leftover `:line`; edit the `fact-checker` and `page-author` agent contracts; ship a committed, tested one-time `ast`-based migration script and run it over `docs/site-src`. Every change is additive/backward-compatible — bare-`path` behavior and the `extract_citations` return shape are unchanged (shared-helper contract with `orchestrator_runner.py`).

**Tech Stack:** Python 3 stdlib (`re`, `ast`, `subprocess`, `pathlib`), pytest, the plugin's lint framework (`scripts/lint/*.py` + `lint_runner.py`), Markdown agent contracts.

**Spec:** `docs/superpowers/specs/2026-07-18-cce122-stable-code-citations-design.md`

**Branch:** `feat/CCE-122-stable-code-citations` (already created off `origin/main`; spec committed `7a43c31`).

**Test convention:** run `python3 -m pytest` from the repo root. Lint tests live in `tests/lint/`. Verify published artifacts with the real consumer (`citation_exists.check_path` / the rule CLI), never `test -f`.

---

## File Structure

| File                                                 | Responsibility                                                 | Change                                                                                                                 |
| ---------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `scripts/lint/citation_exists.py`                    | path/test/symbol citation extraction + existence check (block) | Modify: `:symbol` grammar, `extract_symbol_citations`, `line_pinned_citations`, symbol-existence check in `check_path` |
| `scripts/lint/citation_line_free.py`                 | advisory nudge on `:line` (warn)                               | Create                                                                                                                 |
| `scripts/lint/lint_runner.py`                        | rule registry / dispatch                                       | Modify: add `citation_line_free` to `TIER1_DEFAULT`                                                                    |
| `agents/fact-checker.md`                             | fact-checker contract                                          | Modify: verify behavior only; exclude location precision                                                               |
| `agents/page-author.md`                              | page-author contract                                           | Modify: cite `path`/`path:symbol`, never `path:line`                                                                   |
| `scripts/migrate_line_citations.py`                  | one-time `:line`→`:symbol`/bare migration                      | Create                                                                                                                 |
| `tests/lint/test_citation_exists.py`                 | citation lint tests                                            | Modify: symbol grammar + symbol-existence + `line_pinned_citations`                                                    |
| `tests/lint/test_citation_line_free.py`              | advisory rule tests                                            | Create                                                                                                                 |
| `tests/lint/test_lint_runner.py`                     | runner registry test                                           | Modify: assert `citation_line_free` registered + warn never fails                                                      |
| `tests/agents/test_fact_checker_contract.py`         | fact-checker contract text                                     | Create                                                                                                                 |
| `tests/agents/test_page_author_citation_contract.py` | page-author contract text                                      | Create                                                                                                                 |
| `tests/scripts/test_migrate_line_citations.py`       | migration unit tests                                           | Create                                                                                                                 |
| `tests/lint/test_site_citations_line_free.py`        | repo-guard: no `:line` in site                                 | Create                                                                                                                 |

---

## Task 1: `citation_exists` — `:symbol` grammar + extraction helpers (pure)

Widen the path grammar to accept a `:symbol` suffix alongside `:digits`, keep the bare-path derivation clean for grounding, and add two pure helpers: `extract_symbol_citations` (for the block check in Task 2) and `line_pinned_citations` (for the warn rule in Task 3). No `check_path` change yet.

**Files:**

- Modify: `scripts/lint/citation_exists.py`
- Test: `tests/lint/test_citation_exists.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/lint/test_citation_exists.py`, in the `# ---------- extraction (pure) ----------` section)

````python
def test_symbol_suffix_stripped_to_bare_path():
    # A path:symbol citation resolves to the bare path in ["paths"] (grounding
    # must still receive a clean file path — the shared-helper contract).
    assert citation_exists.extract_citations("`scripts/foo.py:run`")["paths"] == [
        "scripts/foo.py"
    ]
    assert citation_exists.extract_citations("`scripts/foo.py:Cls.method`")["paths"] == [
        "scripts/foo.py"
    ]


def test_extract_symbol_citations_returns_path_and_leaf():
    text = "See `scripts/foo.py:run` and `pkg/bar.py:Cls.method` and `scripts/baz.py`."
    assert citation_exists.extract_symbol_citations(text) == [
        ("scripts/foo.py", "run"),
        ("pkg/bar.py", "method"),  # leaf = last dotted component
    ]


def test_line_pinned_citations_flags_digit_suffix_including_bare_filename():
    text = (
        "prose `scripts/foo.py:12` and `orchestrator_runner.py:128` and "
        "`scripts/foo.py:10-20` but not `scripts/foo.py:run` or `scripts/foo.py`"
    )
    assert citation_exists.line_pinned_citations(text) == [
        "scripts/foo.py:12",
        "orchestrator_runner.py:128",
        "scripts/foo.py:10-20",
    ]


def test_line_pinned_citations_ignores_fenced_blocks():
    text = "intro\n```\n`scripts/foo.py:12`\n```\nafter `scripts/bar.py:7`\n"
    assert citation_exists.line_pinned_citations(text) == ["scripts/bar.py:7"]
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -k "symbol or line_pinned" -q`
Expected: FAIL — `extract_symbol_citations` / `line_pinned_citations` do not exist; `:run` token not yet matched so its bare path is absent.

- [ ] **Step 3: Implement the grammar + helpers**

In `scripts/lint/citation_exists.py`, replace the three module-level regexes (lines ~37-38) with:

```python
# dir/file.ext with an optional :line, :start-end, or :symbol suffix.
_REPO_PATH_RE = re.compile(
    r"^[\w.\-/]+/[\w.\-]+\.\w{1,8}(?::(?:\d+(?:-\d+)?|[A-Za-z_][\w.]*))?$"
)
# strips either a :line/:start-end or a :symbol suffix to the bare path
_SUFFIX_RE = re.compile(r":(?:\d+(?:-\d+)?|[A-Za-z_][\w.]*)$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
# advisory detector: any `path.ext:digits` span, slash optional (bare filenames
# like `orchestrator_runner.py:128` are the worst offenders — unlinted AND drifting)
_LINE_PIN_RE = re.compile(r"^[\w.\-/]+\.\w{1,8}:\d+(?:-\d+)?$")
```

In `extract_citations`, change the bare-path derivation (line ~84) from `_LINE_SUFFIX_RE` to `_SUFFIX_RE`:

```python
        elif _REPO_PATH_RE.match(token):
            bare = _SUFFIX_RE.sub("", token)
            if bare not in paths:
                paths.append(bare)
```

Add two pure helpers after `extract_citations`:

```python
def extract_symbol_citations(text: str) -> list[tuple[str, str]]:
    """(bare_path, leaf_symbol) for every `path:symbol` citation in prose.

    leaf = last dotted component (`Cls.method` -> `method`). Line-number and
    bare-path citations yield nothing here. Used by check_path for the
    deterministic symbol-existence guard."""
    out: list[tuple[str, str]] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if not token or _is_placeholder(token) or not _REPO_PATH_RE.match(token):
            continue
        m = _SUFFIX_RE.search(token)
        if not m or _LINE_SUFFIX_RE.search(token):  # no suffix, or a :line suffix
            continue
        bare = _SUFFIX_RE.sub("", token)
        leaf = m.group(0)[1:].split(".")[-1]  # drop leading ':', take last component
        pair = (bare, leaf)
        if pair not in out:
            out.append(pair)
    return out


def line_pinned_citations(text: str) -> list[str]:
    """Inline `path:line` spans still using the fragile digit suffix (advisory).

    Broader than _REPO_PATH_RE on purpose: catches bare-filename `foo.py:12`
    too. Single source of the `:line` grammar for the citation_line_free rule."""
    out: list[str] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if _is_placeholder(token):
            continue
        if _LINE_PIN_RE.match(token) and token not in out:
            out.append(token)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -q`
Expected: PASS — the four new tests plus all pre-existing extraction tests (`test_line_suffix_stripped`, `test_vocabulary_tokens_skipped`, etc.) stay green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "feat(CCE-122): citation_exists recognizes :symbol grammar + line_pinned helper

Widen _REPO_PATH_RE to accept a :symbol suffix, strip it to a bare path for
grounding, and add extract_symbol_citations + line_pinned_citations pure
helpers. extract_citations return shape unchanged (shared-helper contract).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `citation_exists.check_path` — symbol-existence guard (block)

Verify each cited `:symbol` is defined in its file. A confabulated symbol blocks, exactly like today's nonexistent file/test. File-scoped grep (the path already pins the file). `resolve_cited_sources` still returns clean paths for `:symbol` citations.

**Files:**

- Modify: `scripts/lint/citation_exists.py`
- Test: `tests/lint/test_citation_exists.py`

- [ ] **Step 1: Write the failing tests** (append to the `# ---------- verification + CLI (tmp git host) ----------` section)

```python
def test_symbol_citation_present_passes(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("The entry point is `scripts/real_module.py:real_fn`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out
    assert out["results"][0]["ok"] is True


def test_confabulated_symbol_blocks(tmp_path):
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/real_module.py:ghost_fn` for the logic.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    assert "cites nonexistent symbol 'ghost_fn' in 'scripts/real_module.py'" in (
        out["results"][0]["message"]
    )


def test_method_symbol_resolves_via_leaf(tmp_path):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "svc.py").write_text(
        "class Service:\n    def handle(self):\n        return 1\n"
    )
    page = repo / "page.md"
    page.write_text("`scripts/svc.py:Service.handle` does the work.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out


def test_module_constant_symbol_resolves(tmp_path):
    repo, cfg = _init_host(tmp_path)
    (repo / "scripts" / "cfg.py").write_text("DEFAULT_BUDGET = 2700\n")
    page = repo / "page.md"
    page.write_text("The default is `scripts/cfg.py:DEFAULT_BUDGET`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 0, out


def test_symbol_on_missing_file_reports_path_not_symbol(tmp_path):
    # A :symbol cite to a nonexistent file reports the path problem (from the
    # paths loop); the symbol loop must not crash or double-report.
    repo, cfg = _init_host(tmp_path)
    page = repo / "page.md"
    page.write_text("See `scripts/ghost.py:whatever`.\n")
    rc, out = _run_cli([page], cfg)
    assert rc == 1
    msg = out["results"][0]["message"]
    assert "cites nonexistent path 'scripts/ghost.py'" in msg
    assert "nonexistent symbol" not in msg


def test_resolve_cited_sources_handles_symbol_suffix(tmp_path):
    repo, _ = _init_host(tmp_path)
    text = "Cites `scripts/real_module.py:real_fn` and `scripts/ghost.py:x`."
    assert citation_exists.resolve_cited_sources(text, repo) == [
        "scripts/real_module.py"
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -k "symbol or resolve_cited" -q`
Expected: FAIL — `test_confabulated_symbol_blocks` passes (rc 0) because no symbol check exists yet; `test_symbol_on_missing_file` may see an unexpected message. (`test_resolve_cited_sources_handles_symbol_suffix` should already pass after Task 1 — that is fine.)

- [ ] **Step 3: Implement the symbol-existence check**

In `scripts/lint/citation_exists.py`, add a helper above `check_path`:

```python
def _symbol_defined(source: str, leaf: str) -> bool:
    """True if `leaf` is defined in the file source: a def/class (any indent,
    so methods count) or a module-level (column-0) assignment/annotation."""
    name = re.escape(leaf)
    pattern = re.compile(
        rf"(?m)^\s*(?:async\s+)?(?:def|class)\s+{name}\b|^{name}\s*[:=]"
    )
    return bool(pattern.search(source))
```

In `check_path`, after the `for name in cites["tests"]:` loop and before `if problems:`, add:

```python
    for bare, leaf in extract_symbol_citations(text):
        rel = _relativize(bare, repo_root)
        if rel is None:
            continue
        target = repo_root / rel
        if not target.exists():
            continue  # nonexistent path already reported by the paths loop
        try:
            source = target.read_text()
        except (UnicodeDecodeError, OSError):
            continue  # unreadable cited file: do not false-block
        if not _symbol_defined(source, leaf):
            problems.append(f"cites nonexistent symbol '{leaf}' in '{bare}'")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_citation_exists.py -q`
Expected: PASS — all citation tests including the six new ones.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "feat(CCE-122): citation_exists blocks confabulated :symbol citations

check_path verifies each cited symbol is defined in its file (file-scoped
def/class/module-assignment grep). Confabulated symbol blocks like a bad
file/test; missing file still reports the path, not the symbol.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `citation_line_free` advisory rule (warn) + register in Tier-1

A new rule module flags any `:line` span as an advisory `warn` — never fails a run (`lint_runner.py:158` fails only on `severity == "block"`). Registered in `TIER1_DEFAULT` so it runs by default and degrades gracefully on un-migrated hosts.

**Files:**

- Create: `scripts/lint/citation_line_free.py`
- Modify: `scripts/lint/lint_runner.py` (add to `TIER1_DEFAULT`)
- Create: `tests/lint/test_citation_line_free.py`
- Modify: `tests/lint/test_lint_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/lint/test_citation_line_free.py`:

```python
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPTS_LINT = Path(__file__).parent.parent.parent / "scripts" / "lint"
SCRIPT = SCRIPTS_LINT / "citation_line_free.py"


def _cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    return cfg


def _run(paths: list[Path], cfg: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(cfg),
         "--paths", *[str(p) for p in paths], "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_line_pin_warns_but_does_not_fail(tmp_path):
    cfg = _cfg(tmp_path)
    page = tmp_path / "p.md"
    page.write_text("The entry is `scripts/orchestrator_runner.py:1240` today.\n")
    rc, out = _run([page], cfg)
    assert out["rule"] == "citation_line_free"
    assert out["severity"] == "warn"
    assert out["results"][0]["ok"] is False
    assert "scripts/orchestrator_runner.py:1240" in out["results"][0]["message"]
    # advisory: the rule's own exit code is non-zero to surface the finding,
    # but the runner never fails a run on a warn rule (asserted in Task 3 runner test).


def test_clean_page_passes(tmp_path):
    cfg = _cfg(tmp_path)
    page = tmp_path / "p.md"
    page.write_text("The entry is `scripts/orchestrator_runner.py:run` today.\n")
    rc, out = _run([page], cfg)
    assert rc == 0
    assert out["results"][0]["ok"] is True
```

Append to `tests/lint/test_lint_runner.py`:

```python
def test_citation_line_free_registered_in_tier1(tmp_path):
    import lint_runner
    assert "citation_line_free" in lint_runner.TIER1_DEFAULT


def test_line_pinned_page_does_not_fail_aggregate_run(tmp_path):
    # A page whose only issue is a :line citation must NOT fail the aggregate
    # lint run — the advisory rule is warn, so the runner stays green.
    import lint_runner
    repo = tmp_path / "host"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "m.py").write_text("def run():\n    return 1\n")
    cfg = repo / "config.yml"
    cfg.write_text("lint: { tier1: default }\n")
    page = repo / "p.md"
    # cite by :line (advisory warn) — path+symbol both otherwise valid
    page.write_text("# T\n\nThe `scripts/m.py:1` entry point runs nightly.\n")
    out = lint_runner.run_rule("citation_line_free", cfg, [page])
    assert out["severity"] == "warn"
    assert any(not r["ok"] for r in out["results"])  # finding present
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_citation_line_free.py tests/lint/test_lint_runner.py -k "line_free or line_pinned" -q`
Expected: FAIL — `citation_line_free.py` does not exist; not in `TIER1_DEFAULT`.

- [ ] **Step 3: Implement the rule and register it**

Create `scripts/lint/citation_line_free.py`:

```python
"""Lint rule: citation_line_free (CCE-122, Tier-1, advisory).

Flags inline `path:line` code citations. Line numbers drift under unrelated
code churn, so they are banned in favor of `path:symbol` / bare `path`. This
rule is SEVERITY=warn: it surfaces the finding but never fails a run, so a
host still carrying legacy :line pins is nudged, not blocked. Detection reuses
citation_exists.line_pinned_citations (single source of the :line grammar).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import citation_exists

RULE_NAME = "citation_line_free"
SEVERITY = "warn"


def check_path(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError) as e:
        return False, f"file unreadable: {e}"
    pins = citation_exists.line_pinned_citations(text)
    if pins:
        joined = ", ".join(pins)
        return False, f"prefer path:symbol or bare path over line pins: {joined}"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p)
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

Note: the module runs from `scripts/lint/`, and `run_rule` invokes it with that directory on `sys.path[0]` (the script's own dir), so `import citation_exists` resolves. To be safe when imported as a module in `test_lint_runner.py`, that test already inserts `scripts/lint` on `sys.path` (existing conftest/pattern) — confirm the file's first import lines mirror the sibling rules.

In `scripts/lint/lint_runner.py`, add `"citation_line_free"` to `TIER1_DEFAULT` (after `"citation_exists"`):

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
    "citation_line_free",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_citation_line_free.py tests/lint/test_lint_runner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_line_free.py scripts/lint/lint_runner.py tests/lint/test_citation_line_free.py tests/lint/test_lint_runner.py
git commit -m "feat(CCE-122): add citation_line_free advisory (warn) Tier-1 rule

Flags inline path:line citations without failing the run; reuses
citation_exists.line_pinned_citations. Registered in TIER1_DEFAULT
(markdown_hygiene_lang is the existing Tier-1 warn precedent).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Fact-checker contract — scope to behavior, exclude location precision

Stop the fact-checker from emitting `contradiction` on line/location drift. It keeps checking behavioral truth (and a wrong symbol still fails that check). This is the change that unblocks auto-merge.

**Files:**

- Modify: `agents/fact-checker.md`
- Create: `tests/agents/test_fact_checker_contract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agents/test_fact_checker_contract.py`:

```python
"""CCE-122: the fact-checker contract must scope verdicts to behavioral truth
and explicitly exclude citation line/location precision (owned by the
citation_exists lint now)."""

from pathlib import Path

_CONTRACT = (Path(__file__).parent.parent.parent / "agents" / "fact-checker.md").read_text()


def test_contract_excludes_location_precision():
    lowered = _CONTRACT.lower()
    # Anchor on the load-bearing instruction; deleting it must break this test.
    assert "do not" in lowered and "line number" in lowered
    assert "location precision" in lowered
    assert "citation_exists" in _CONTRACT  # names the lint that owns existence
    # Behavioral checking must remain the job.
    assert "behavioral claim" in lowered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_fact_checker_contract.py -q`
Expected: FAIL — the contract does not yet mention "location precision" / the exclusion.

- [ ] **Step 3: Edit the contract**

In `agents/fact-checker.md`, in the `## Output contract` section, change the `verdict: "contradiction"` bullet (the `evidence` clause "cite the line or symbol") and add a scope note. Replace the contradiction bullet with:

```markdown
- `verdict: "contradiction"` — at least one claim contradicts a cited source.
  One finding per contradicted claim: `claim` quotes or tightly paraphrases
  the page; `source_path` names the contradicting file; `evidence` states
  what the source actually does (name the symbol; a line number is optional
  and never required).
```

Add a new subsection immediately after the three verdict bullets:

```markdown
### Scope: behavior, not citation location

You verify the **behavioral claim** — what a function does, an invariant, a
default, a contract. You do **not** police citation-location precision: do not
emit `contradiction` because a cited line number, `path:line`, or `path:symbol`
location no longer points exactly where the prose implies. Citation existence
(the file exists, the cited symbol is defined in it) is owned by the
`citation_exists` lint, not by you. If the named symbol exists and the page's
behavioral statement about it is true, the verdict is `consistent` even when a
line number has drifted. A genuinely wrong symbol still fails the behavioral
check and is still a real `contradiction`.
```

In `## Procedure` step 4, change "contradictions only." to:

```markdown
4. Emit the JSON verdict. Do not report style issues, omissions, citation
   line/location drift, or claims about files outside `cited_sources` —
   behavioral contradictions only.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_fact_checker_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/fact-checker.md tests/agents/test_fact_checker_contract.py
git commit -m "feat(CCE-122): scope fact-checker to behavior, exclude citation location

The fact-checker no longer emits contradiction on line/location drift; citation
existence is owned by the citation_exists lint. Behavioral confabulation
detection is unchanged (a wrong symbol still fails the behavioral check).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Page-author contract — line-free citation convention

Tell the author to cite `path` / `path:symbol`, never `path:line`.

**Files:**

- Modify: `agents/page-author.md`
- Create: `tests/agents/test_page_author_citation_contract.py`

- [ ] **Step 1: Write the failing test**

Create `tests/agents/test_page_author_citation_contract.py`:

```python
"""CCE-122: the page-author contract must require line-free code citations
(`path` or `path:symbol`, never `path:line`)."""

from pathlib import Path

_CONTRACT = (Path(__file__).parent.parent.parent / "agents" / "page-author.md").read_text()


def test_contract_requires_line_free_citations():
    lowered = _CONTRACT.lower()
    assert "path:symbol" in lowered
    assert "never" in lowered and "path:line" in lowered
    # Anchor on the load-bearing phrase so deleting the rule breaks the test.
    assert "line-free" in lowered or "never cite a line number" in lowered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/agents/test_page_author_citation_contract.py -q`
Expected: FAIL — no citation-format rule in the contract yet.

- [ ] **Step 3: Edit the contract**

In `agents/page-author.md`, extend Procedure step 3. After the sentence "Cite only files and tests you confirmed exist." add:

```markdown
Cite code line-free: use `` `path/to/file.py` `` or, to point at a named
symbol, `` `path/to/file.py:symbol` `` (`` `file.py:Class.method` `` for a
method). Never cite a line number (`` `path:line` `` / `` `path:start-end` ``) —
line numbers drift under unrelated edits and are rejected by the docs pipeline.
Name the symbol in prose naturally (`run()`); the backtick token carries the
`path:symbol` citation.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/agents/test_page_author_citation_contract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/page-author.md tests/agents/test_page_author_citation_contract.py
git commit -m "feat(CCE-122): page-author cites path/path:symbol, never path:line

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Migration script `scripts/migrate_line_citations.py` (committed, tested)

A one-time, idempotent, `ast`-based rewriter: `.py` `path:line` → `path:symbol` (enclosing def/class, or module-level assignment name); non-`.py`/unresolvable → bare `path`; bare-filename → resolved full path when the basename is unique among tracked files. Fence-aware (never touches fenced code). Pure `migrate_text` core + CLI walker.

**Files:**

- Create: `scripts/migrate_line_citations.py`
- Test: `tests/scripts/test_migrate_line_citations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_migrate_line_citations.py`:

````python
from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lint"))
import migrate_line_citations as mlc  # noqa: E402
import citation_exists  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _host(tmp_path: Path) -> Path:
    repo = tmp_path / "host"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "runner.py").write_text(
        "import os\n\n"
        "DEFAULT_BUDGET = 2700\n\n\n"
        "def run(repo):\n"
        "    x = 1\n"
        "    return x\n\n\n"
        "class Engine:\n"
        "    def start(self):\n"
        "        return 2\n"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_function_line_becomes_symbol(tmp_path):
    repo = _host(tmp_path)
    # line 6 is inside def run
    new, changes = mlc.migrate_text("Entry `scripts/runner.py:6`.", repo)
    assert new == "Entry `scripts/runner.py:run`."
    assert changes == [("scripts/runner.py:6", "scripts/runner.py:run")]


def test_method_line_becomes_class_dot_method(tmp_path):
    repo = _host(tmp_path)
    # line 12 is inside Engine.start
    new, _ = mlc.migrate_text("`scripts/runner.py:12` starts it.", repo)
    assert new == "`scripts/runner.py:Engine.start` starts it."


def test_module_assignment_line_becomes_name(tmp_path):
    repo = _host(tmp_path)
    # line 3 is the DEFAULT_BUDGET assignment
    new, _ = mlc.migrate_text("Default `scripts/runner.py:3`.", repo)
    assert new == "Default `scripts/runner.py:DEFAULT_BUDGET`."


def test_range_uses_start_line_symbol(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("`scripts/runner.py:6-8` body.", repo)
    assert new == "`scripts/runner.py:run` body."


def test_unresolvable_line_strips_to_bare(tmp_path):
    repo = _host(tmp_path)
    # line 1 is `import os` — no enclosing def/class, not an assignment
    new, _ = mlc.migrate_text("Top `scripts/runner.py:1`.", repo)
    assert new == "Top `scripts/runner.py`."


def test_non_python_strips_to_bare(tmp_path):
    repo = _host(tmp_path)
    (repo / "deploy.yml").write_text("on: push\n")
    _git(repo, "add", "."); _git(repo, "commit", "-q", "-m", "yml")
    new, _ = mlc.migrate_text("Config `deploy.yml:1`.", repo)
    assert new == "Config `deploy.yml`."


def test_bare_filename_resolves_to_tracked_path(tmp_path):
    repo = _host(tmp_path)
    new, _ = mlc.migrate_text("See `runner.py:6`.", repo)
    assert new == "See `scripts/runner.py:run`."


def test_fenced_blocks_untouched(tmp_path):
    repo = _host(tmp_path)
    text = "before `scripts/runner.py:6`\n```\n`scripts/runner.py:6`\n```\n"
    new, _ = mlc.migrate_text(text, repo)
    assert new == "before `scripts/runner.py:run`\n```\n`scripts/runner.py:6`\n```\n"


def test_idempotent(tmp_path):
    repo = _host(tmp_path)
    once, _ = mlc.migrate_text("`scripts/runner.py:6`", repo)
    twice, changes = mlc.migrate_text(once, repo)
    assert twice == once
    assert changes == []


def test_migrated_page_passes_citation_exists(tmp_path):
    # Consumer verification: the migrated page must satisfy the real lint.
    repo = _host(tmp_path)
    (repo / ".engineering-docs-agent").mkdir()
    (repo / ".engineering-docs-agent" / "config.yml").write_text("lint: { tier1: default }\n")
    page = repo / "page.md"
    page.write_text("# T\n\nThe `scripts/runner.py:6` entry runs nightly.\n")
    new, _ = mlc.migrate_text(page.read_text(), repo)
    page.write_text(new)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files)
    assert ok, msg
    assert citation_exists.line_pinned_citations(new) == []
````

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/scripts/test_migrate_line_citations.py -q`
Expected: FAIL — `migrate_line_citations` module does not exist.

- [ ] **Step 3: Implement the migration**

Create `scripts/migrate_line_citations.py`:

````python
"""One-time migration: rewrite `path:line` code citations to `path:symbol`
(or bare `path`). CCE-122. Idempotent, fence-aware.

- .py + line inside a def/class    -> path:symbol (path:Class.method for methods)
- .py + line on a module assignment -> path:NAME
- .py + line elsewhere (imports, blank) -> bare path
- non-.py or unresolvable file      -> bare path
- bare filename, unique in tracked  -> resolved dir-qualified path (+ symbol)

Verify migrated pages with scripts/lint/citation_exists.check_path (the real
consumer), never test -f.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINE_PIN_RE = re.compile(r"^([\w.\-/]+\.\w{1,8}):(\d+)(?:-\d+)?$")


def _tracked_files(repo_root: Path) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"], capture_output=True, text=True
    )
    return r.stdout.splitlines() if r.returncode == 0 else []


def _resolve_path(cited: str, repo_root: Path, tracked: list[str]) -> str | None:
    """Repo-relative path for a cited token. Bare filenames resolve against
    tracked files only when the basename is unique; ambiguous -> None."""
    if "/" in cited:
        return cited if (repo_root / cited).exists() else None
    matches = [f for f in tracked if Path(f).name == cited]
    return matches[0] if len(matches) == 1 else None


def _enclosing_symbol(source: str, lineno: int) -> str | None:
    """Dotted name of the innermost def/class containing `lineno`, or the name
    of a module-level assignment on that exact line, else None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    best: tuple[int, str] | None = None  # (span_size, dotted_name), smallest span wins

    def visit(node: ast.AST, prefix: list[str]) -> None:
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = child.lineno
                end = getattr(child, "end_lineno", start)
                name_path = prefix + [child.name]
                if start <= lineno <= end:
                    span = end - start
                    if best is None or span < best[0]:
                        best = (span, ".".join(name_path))
                    visit(child, name_path)
            else:
                visit(child, prefix)

    visit(tree, [])
    if best is not None:
        return best[1]

    # module-level assignment on the exact line
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and stmt.lineno == lineno:
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    return tgt.id
        if isinstance(stmt, ast.AnnAssign) and stmt.lineno == lineno:
            if isinstance(stmt.target, ast.Name):
                return stmt.target.id
    return None


def _rewrite_token(token: str, repo_root: Path, tracked: list[str]) -> str | None:
    """New spelling for a `path:line` token, or None if it is not one."""
    m = _LINE_PIN_RE.match(token)
    if not m:
        return None
    cited, line_s = m.group(1), m.group(2)
    rel = _resolve_path(cited, repo_root, tracked)
    if rel is None:
        # unresolvable: strip the :line from whatever path was written
        return cited
    if rel.endswith(".py"):
        try:
            source = (repo_root / rel).read_text()
        except (UnicodeDecodeError, OSError):
            source = ""
        symbol = _enclosing_symbol(source, int(line_s)) if source else None
        if symbol:
            return f"{rel}:{symbol}"
    return rel  # non-.py or unresolvable symbol -> bare (resolved) path


def migrate_text(text: str, repo_root: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return (new_text, [(old_token, new_token), ...]). Fenced blocks skipped."""
    tracked = _tracked_files(repo_root)
    changes: list[tuple[str, str]] = []
    out_lines: list[str] = []
    in_fence = False
    fence = ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            out_lines.append(line)
            continue
        if in_fence:
            if stripped.startswith(fence):
                in_fence = False
            out_lines.append(line)
            continue

        def repl(match: re.Match) -> str:
            token = match.group(1).strip()
            new_token = _rewrite_token(token, repo_root, tracked)
            if new_token is None or new_token == token:
                return match.group(0)
            changes.append((token, new_token))
            return f"`{new_token}`"

        out_lines.append(_INLINE_CODE_RE.sub(repl, line))
    return "\n".join(out_lines), changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--docs-dir", type=Path, default=Path("docs/site-src"))
    parser.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    docs = (root / args.docs_dir) if not args.docs_dir.is_absolute() else args.docs_dir
    total = 0
    for md in sorted(docs.rglob("*.md")):
        original = md.read_text()
        new, changes = migrate_text(original, root)
        if changes:
            total += len(changes)
            rel = md.relative_to(root)
            for old, new_tok in changes:
                print(f"{rel}: `{old}` -> `{new_tok}`")
            if args.apply:
                md.write_text(new)
    print(f"\n{total} citation(s) {'rewritten' if args.apply else 'to rewrite (dry-run)'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/scripts/test_migrate_line_citations.py -q`
Expected: PASS (all 11 tests). If `tests/scripts/` lacks `__init__.py`, add an empty one (`touch tests/scripts/__init__.py`) to match the sibling test packages.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_line_citations.py tests/scripts/test_migrate_line_citations.py tests/scripts/__init__.py
git commit -m "feat(CCE-122): ast-based path:line -> path:symbol migration tool

Idempotent, fence-aware rewriter. Resolves enclosing def/class or module
assignment for .py; strips to bare path otherwise; resolves unique bare
filenames to dir-qualified paths. Verified by citation_exists.check_path.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Run the migration over `docs/site-src` + repo-guard test

Execute the migration on the real site, verify zero `:line` pins remain and every touched page still passes `citation_exists`, add a permanent repo-guard test, and commit the content changes.

**Files:**

- Modify: `docs/site-src/**/*.md` (content — the 21 pages)
- Create: `tests/lint/test_site_citations_line_free.py`

- [ ] **Step 1: Write the failing repo-guard test**

Create `tests/lint/test_site_citations_line_free.py`:

```python
"""CCE-122 repo guard: no published page may carry an inline `path:line`
citation, and every page passes the citation_exists symbol/file check."""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lint"))
import citation_exists  # noqa: E402

SITE = ROOT / "docs" / "site-src"


def _pages() -> list[Path]:
    return sorted(SITE.rglob("*.md"))


def test_no_inline_line_pins_in_site():
    offenders = {}
    for page in _pages():
        pins = citation_exists.line_pinned_citations(page.read_text())
        if pins:
            offenders[str(page.relative_to(ROOT))] = pins
    assert not offenders, f"inline :line citations remain: {offenders}"


def test_all_pages_pass_citation_exists():
    repo_root = citation_exists.repo_root_for(SITE / "x")
    files = citation_exists.tracked_files(repo_root) if repo_root else set()
    failures = {}
    for page in _pages():
        ok, msg = citation_exists.check_path(page, repo_root, files)
        if not ok:
            failures[str(page.relative_to(ROOT))] = msg
    assert not failures, f"citation_exists failures: {failures}"
```

- [ ] **Step 2: Run the guard test to verify it fails**

Run: `python3 -m pytest tests/lint/test_site_citations_line_free.py -q`
Expected: FAIL — `test_no_inline_line_pins_in_site` reports the 96 pins across 21 pages.

- [ ] **Step 3: Run the migration (dry-run, then apply)**

```bash
python3 scripts/migrate_line_citations.py --repo-root "$(pwd)" --docs-dir docs/site-src
# review the printed old -> new rewrites, then apply:
python3 scripts/migrate_line_citations.py --repo-root "$(pwd)" --docs-dir docs/site-src --apply
```

Expected: dry-run lists ~96 rewrites; apply reports "96 citation(s) rewritten." Spot-check `docs/site-src/architecture/orchestrator.md`: `` `scripts/orchestrator_runner.py:1240` `` → `` `scripts/orchestrator_runner.py:run` ``, `:339` → `:resolve_time_budget`, `:310` → `:DEFAULT_TIME_BUDGET_SECONDS` (or bare if not a module assignment).

- [ ] **Step 4: Verify with the real consumers**

Run: `python3 -m pytest tests/lint/test_site_citations_line_free.py -q`
Expected: PASS — no pins remain and every page passes `citation_exists`.

If `test_all_pages_pass_citation_exists` flags a page (a symbol the regex resolver could not confirm — e.g. a line that mapped to a symbol not matched by `_symbol_defined`), fix that page's citation by hand to bare `path` or the correct `path:symbol`, then re-run. Do NOT relax the lint to make it pass.

- [ ] **Step 5: Commit**

```bash
git add docs/site-src tests/lint/test_site_citations_line_free.py
git commit -m "docs(CCE-122): migrate 96 path:line citations to path:symbol/bare

One-time ast-based sweep across 21 pages; adds a repo-guard test asserting no
inline :line citations remain and every page passes citation_exists.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Full-suite integration + changelog

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest`
Expected: green (all prior tests + the CCE-122 additions; no regressions).

- [ ] **Step 2: Add a changelog entry**

Add under the current unreleased/dated section of `CHANGELOG.md`:

```markdown
- **CCE-122** — Stable code citations. Docs cite `path:symbol` / bare `path`,
  never `path:line`. `citation_exists` verifies cited symbols exist (block); a
  new advisory `citation_line_free` rule warns on leftover `:line`; the
  fact-checker is scoped to behavioral truth (no more line-drift contradictions
  that blocked CCE-101 auto-merge). One-time `ast`-based migration converted
  the 96 existing pins across 21 pages.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(CCE-122): changelog entry for stable code citations

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Order matters:** Tasks 1→2→3 build on each other in `citation_exists`; Task 6 (migration) depends on Task 1's grammar; Task 7 runs the Task 6 script and depends on Task 2's symbol check being live. Execute in order.
- **Shared-helper contract:** `citation_exists.extract_citations` is imported by `scripts/orchestrator_runner.py` (fact-checker dispatch). Its `{"paths","tests"}` return shape and the meaning of `["paths"]` (bare, existing-or-not paths) must stay identical. New behavior lives in _new_ functions (`extract_symbol_citations`, `line_pinned_citations`) — never widen the old return shape.
- **Degrade-gracefully:** the symbol check only fires on a `:symbol` suffix; bare `path` citations behave exactly as before. The advisory rule is `warn` — it never fails a host's run. Both honor the generic-first mandate.
- **Consumer verification:** Tasks 6 and 7 verify migrated pages with `citation_exists.check_path`, never `test -f` (CLAUDE.md invariant).

```

```
