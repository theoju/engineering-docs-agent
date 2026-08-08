# CCE-131 `citation_exists` False-Positive Closure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `citation_exists` from blocking docs pages on tokens that are not citations, without weakening its guard against confabulated ones.

**Architecture:** Five changes to one lint module (`scripts/lint/citation_exists.py`) plus one authoring-contract change. Three of the five are bug fixes to how the rule resolves what exists; one adds a reserved namespace for illustrative paths; one adds the single policy surface — an exempt-token list for artifacts whose non-existence is the point. Everything acts before severity is computed, so nothing depends on the `content-validator` subagent relaying a `severity` field.

**Tech Stack:** Python 3.11 stdlib + `pyyaml` (already a runtime dep). pytest. No new dependencies.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-08-cce131-citation-exists-false-positive-closure-design.md`. Read it before starting.
- **Branch:** `docs/CCE-131-citation-exists-false-positive-closure` (PR #200 — already carries the spec and this plan). Do **not** branch again; commit on top.
- **Python: stdlib-first.** No new runtime dependencies. `yaml` is already imported in the target module.
- **TDD, no exceptions.** Failing test → run it and see it fail → minimal implementation → run it and see it pass → commit. A step that skips the red run is a failed step.
- **Every test uses the fixture-driven dry-run path.** Never invoke the real `claude` CLI.
- **`tests/scripts/` must NOT contain `__init__.py`.** Import scripts modules via the dotted namespace path (`from scripts.lint import citation_exists`), never `sys.path.insert` + bare import.
- **Docs cite code line-free:** `path/to/file.py` or `path/to/file.py:symbol`. Never `path:line`.
- **Shared-helper contract:** `extract_citations`, `extract_symbol_citations`, `line_pinned_citations`, `resolve_cited_sources`, and `check_path` are declared shared helpers (module docstring). Only `check_path` changes signature in this plan. Its external call sites are exactly two, both tests: `tests/lint/test_site_citations_line_free.py` and `tests/scripts/test_migrate_line_citations.py`.
- **Run the suite with the repo venv:** `.venv/bin/python -m pytest`. Bare `python3` on this machine resolves to a Homebrew 3.14 with no pytest, and piping to `tail` masks the failure as exit 0.
- **Baseline suite:** 1169 passed, 5 skipped. Every task must leave it green with its own new tests added.

---

## File Structure

| file                                                                      | responsibility                                               | tasks |
| ------------------------------------------------------------------------- | ------------------------------------------------------------ | ----- |
| `scripts/lint/citation_exists.py`                                         | the rule. All five code changes land here.                   | 1–5   |
| `tests/lint/test_citation_exists.py`                                      | the rule's unit + CLI tests. Also gets the import-style fix. | 1–5   |
| `tests/lint/test_site_citations_line_free.py`                             | corpus guard; one `check_path` call site to update.          | 3     |
| `tests/scripts/test_migrate_line_citations.py`                            | migration guard; one `check_path` call site to update.       | 3     |
| `templates/config.schema.json`                                            | declares the two new `lint.*` keys.                          | 4, 5  |
| `.engineering-docs-agent/config.yml`                                      | this host's exempt-token entry.                              | 5     |
| `agents/page-author.md`                                                   | the authoring contract gains the concept of a non-citation.  | 6     |
| `docs/site-src/architecture/cce-capability-c-canonical-core-citations.md` | the `example/` migration that unblocks PR #198.              | 6     |

Task order is chosen so the `check_path` signature changes exactly once (Task 3), before the two tasks that also need config (4, 5). Tasks 1 and 2 need no signature change and go first because they are pure bug fixes.

---

### Task 1: Fence stripping fails closed

An unterminated fence currently makes `strip_fenced_blocks` swallow every remaining line, so a Tier-1 **block** rule silently stops checking from that point to EOF with no report. This task also fixes the file's import style, since it is the first task to touch it.

**Files:**

- Modify: `scripts/lint/citation_exists.py` — `strip_fenced_blocks`
- Test: `tests/lint/test_citation_exists.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces: `strip_fenced_blocks(text: str) -> str` — unchanged signature, changed behavior on unterminated fences.

- [ ] **Step 1: Fix the import style at the top of the test file**

Replace the `sys.path.insert` + bare import at the top of `tests/lint/test_citation_exists.py` with the dotted namespace import. Note `tests/lint/__init__.py` exists, so this file is inside a package and the anti-pattern is live here.

```python
from scripts.lint import citation_exists
```

Every existing reference already reads `citation_exists.<name>`, so only the import lines change. If a CLI test needs the script path, derive it as `Path(citation_exists.__file__)`; do not reintroduce a `sys.path` entry for the lint directory.

- [ ] **Step 2: Run the existing suite to confirm the import change broke nothing**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -q`
Expected: PASS, same test count as before the edit.

- [ ] **Step 3: Write the failing test**

````python
def test_unterminated_fence_still_checks_trailing_prose():
    """CCE-131: an unclosed fence used to swallow the rest of the file,
    silently disabling this block rule from that point on."""
    text = (
        "Intro citing `scripts/real.py`.\n"
        "\n"
        "```python\n"
        "never_closed = True\n"
        "\n"
        "Trailing prose citing `scripts/after_fence.py`.\n"
    )
    paths = citation_exists.extract_citations(text)["paths"]
    assert "scripts/after_fence.py" in paths


def test_terminated_fence_content_is_still_stripped():
    """The fix must not stop stripping properly closed fences."""
    text = (
        "Before `scripts/before.py`.\n"
        "```python\n"
        "x = `scripts/inside_fence.py`\n"
        "```\n"
        "After `scripts/after.py`.\n"
    )
    paths = citation_exists.extract_citations(text)["paths"]
    assert paths == ["scripts/before.py", "scripts/after.py"]
````

- [ ] **Step 4: Run the tests to verify the first fails**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -k "fence" -v`
Expected: `test_unterminated_fence_still_checks_trailing_prose` FAILS (`'scripts/after_fence.py' not in []`). `test_terminated_fence_content_is_still_stripped` PASSES already — it is the guard that the fix does not over-correct.

- [ ] **Step 5: Implement**

Replace `strip_fenced_blocks` in `scripts/lint/citation_exists.py`:

````python
def strip_fenced_blocks(text: str) -> str:
    """Drop fenced regions; return the remaining prose lines.

    CCE-131: an UNTERMINATED fence fails closed. Previously an unclosed fence
    swallowed every line to EOF, silently disabling this Tier-1 block rule for
    the rest of the file with no report. Buffered lines are now flushed back
    into the prose so their citations are still checked.
    """
    out: list[str] = []
    pending: list[str] = []
    in_fence = False
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            pending = []
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            pending = []
            continue
        if in_fence:
            pending.append(line)
            continue
        out.append(line)
    if in_fence:
        out.extend(pending)
    return "\n".join(out)
````

- [ ] **Step 6: Run the tests to verify both pass**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -q`
Expected: PASS, two more tests than the Step 2 count.

- [ ] **Step 7: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "fix(CCE-131): unterminated fence no longer silently disables citation_exists

An unclosed fence made strip_fenced_blocks swallow every remaining line, so
a Tier-1 block rule stopped checking from that point to EOF with no report.
Buffered lines are now flushed back into the prose.

Also converts this test file from sys.path.insert + bare import to the
dotted namespace import (CLAUDE.md CCE-122 invariant); tests/lint is a
package, so the old style was one collection-order change from the
order-dependent ModuleNotFoundError that entry documents."
```

---

### Task 2: Prefix-match test identifiers at a `_` boundary

`cited_test_exists` greps `def <name>(` — an exact match. The corpus writes test _families_: `test_lint_runner` names a group whose real members are `test_lint_runner_missing_script_reports_block` and `test_lint_runner_empty_output_reports_block`.

**Files:**

- Modify: `scripts/lint/citation_exists.py` — `cited_test_exists`
- Test: `tests/lint/test_citation_exists.py`

**Interfaces:**

- Consumes: nothing from Task 1 (independent).
- Produces: `cited_test_exists(repo_root: Path, name: str) -> bool` — unchanged signature, now also true for a family prefix. Also produces the two tmp-git helpers below, which Tasks 3–5 reuse.

- [ ] **Step 1: Write the failing test**

Add these two module-level helpers near the top of the test file if an equivalent does not already exist (check first — the file has tmp-git fixtures for its CLI tests; reuse rather than duplicate):

```python
def _tmp_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "host"
    (repo / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@e.st", "-c", "user.name=t",
         "commit", "-q", "-m", "seed"],
        check=True,
    )
```

Then the tests:

```python
def test_test_family_shorthand_resolves_via_prefix(tmp_path):
    """CCE-131: `test_lint_runner` names a family; the real symbols are
    test_lint_runner_missing_script_reports_block etc."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text(
        "def test_lint_runner_missing_script_reports_block():\n    pass\n"
    )
    _commit_all(repo)
    assert citation_exists.cited_test_exists(repo, "test_lint_runner") is True


def test_confabulated_test_with_no_family_still_blocks(tmp_path):
    """The guard CCE-111 needed: a wholly invented name matches no prefix."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text(
        "def test_lint_runner_missing_script_reports_block():\n    pass\n"
    )
    _commit_all(repo)
    assert citation_exists.cited_test_exists(repo, "test_no_advance_on_partial") is False


def test_prefix_match_respects_the_underscore_boundary(tmp_path):
    """`test_lintrunner` must NOT match `test_lint_runner_x` — the boundary is
    what keeps the prefix match from degenerating into substring matching."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "tests" / "test_x.py").write_text("def test_lint_runner_x():\n    pass\n")
    _commit_all(repo)
    assert citation_exists.cited_test_exists(repo, "test_lintrunner") is False
```

- [ ] **Step 2: Run to verify the first fails**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -k "family or boundary or confabulated_test" -v`
Expected: `test_test_family_shorthand_resolves_via_prefix` FAILS (returns `False`). The other two PASS already — they are the guards.

- [ ] **Step 3: Implement**

In `scripts/lint/citation_exists.py`, add the third needle:

```python
def cited_test_exists(repo_root: Path, name: str) -> bool:
    """True if any tracked file defines or calls the named test.

    CCE-131: `def {name}_` also counts, so a test-FAMILY shorthand resolves —
    `test_lint_runner` is satisfied by test_lint_runner_missing_script_reports_block.
    The trailing underscore is the boundary: a confabulated `test_foo` passes
    only when a real `test_foo_*` exists, so the CCE-111 guard against wholly
    invented names is preserved.
    """
    for needle in (f"def {name}(", f"{name}(", f"def {name}_"):
        r = subprocess.run(
            ["git", "-C", str(repo_root), "grep", "-l", "-F", needle],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
    return False
```

- [ ] **Step 4: Run to verify all three pass**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py
git commit -m "fix(CCE-131): test-family shorthand resolves via underscore-bounded prefix

cited_test_exists matched test names exactly, so test_lint_runner failed
despite test_lint_runner_missing_script_reports_block existing. The
underscore boundary keeps the CCE-111 guard: a confabulated test_foo passes
only when a real test_foo_* exists."
```

---

### Task 3: Thread config into `check_path`; resolve docs-relative and build-output paths

The rule resolves cited paths repo-root-relative only. A docs page that cites a sibling page (`api/reference/pkg/calc.md`) or names mkdocs build output (`site/api/http/index.html`) therefore fails, though both are correct references. This task also performs the one signature change the plan needs, so Tasks 4 and 5 have config available.

**Files:**

- Modify: `scripts/lint/citation_exists.py` — new `_docs_dir`, `_build_dir`, `_resolves`; `check_path` signature; `main`
- Modify: `tests/lint/test_site_citations_line_free.py` — one call site
- Modify: `tests/scripts/test_migrate_line_citations.py` — one call site
- Test: `tests/lint/test_citation_exists.py`

**Interfaces:**

- Consumes: `strip_fenced_blocks` (Task 1), `cited_test_exists` (Task 2), `_tmp_git_repo` / `_commit_all` (Task 2).
- Produces:
  - `check_path(path: Path, repo_root: Path | None, files: set[str], config: dict) -> tuple[bool, str]` — **new fourth positional parameter.** Tasks 4 and 5 extend the body, not the signature.
  - `_docs_dir(config: dict) -> str` — `site.docs_dir`, slash-stripped, `""` when absent.
  - `_build_dir(repo_root: Path) -> str` — mkdocs `site_dir`, default `"site"`.
  - `_resolves(rel: str, repo_root: Path, files: set[str], docs_dir: str, build_dir: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
_SITE_CFG = {"site": {"docs_dir": "docs/site-src"}}


def test_docs_relative_sibling_citation_resolves(tmp_path):
    """CCE-131: a docs page citing a sibling page names it relative to
    docs_dir, not to the repo root."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src" / "api").mkdir(parents=True)
    (repo / "docs" / "site-src" / "api" / "index.md").write_text("# API\n")
    page = repo / "docs" / "site-src" / "guide.md"
    page.write_text("See `api/index.md` for the reference.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


def test_build_output_path_is_skipped(tmp_path):
    """mkdocs site_dir output is generated, never tracked — not a confabulation."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "mkdocs.yml").write_text("docs_dir: docs/site-src\nsite_dir: site\n")
    page = repo / "page.md"
    page.write_text("Published to `site/api/http/index.html`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is True, msg


def test_no_docs_dir_configured_still_blocks(tmp_path):
    """Generic-first guard: a host with no site.docs_dir keeps today's
    repo-root-only behavior."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src" / "api").mkdir(parents=True)
    (repo / "docs" / "site-src" / "api" / "index.md").write_text("# API\n")
    page = repo / "page.md"
    page.write_text("See `api/index.md`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "api/index.md" in msg


def test_genuine_confabulation_still_blocks_with_docs_dir(tmp_path):
    """The docs_dir fallback must not become a blanket pass."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "docs" / "site-src").mkdir(parents=True)
    page = repo / "docs" / "site-src" / "page.md"
    page.write_text("See `scripts/build_doc_source_map.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, _SITE_CFG)
    assert ok is False
    assert "scripts/build_doc_source_map.py" in msg
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -k "docs_relative or build_output or no_docs_dir or genuine_confabulation" -v`
Expected: all four FAIL with `TypeError: check_path() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Implement the helpers**

In `scripts/lint/citation_exists.py`, add above `check_path`:

```python
def _docs_dir(config: dict) -> str:
    """site.docs_dir, slash-stripped. Empty when the host declares none."""
    return str((config.get("site") or {}).get("docs_dir") or "").strip("/")


def _build_dir(repo_root: Path) -> str:
    """mkdocs site_dir (generated build output), default 'site'.

    Build artifacts are generated, never tracked, so a page naming one is
    making a correct reference — not a confabulation. A host on a different
    generator simply has no such directory and this skips nothing.
    """
    try:
        mk = yaml.safe_load((repo_root / "mkdocs.yml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return "site"
    return str(mk.get("site_dir") or "site").strip("/")


def _resolves(
    rel: str, repo_root: Path, files: set[str], docs_dir: str, build_dir: str
) -> bool:
    """True when a cited repo-relative path names something real.

    Three ways to resolve, in order: it is generated build output; it is
    tracked or present on disk (the disk fallback covers same-run siblings not
    yet added to git); or it resolves under docs_dir, which is how a docs page
    naturally cites a sibling page.
    """
    if build_dir and (rel == build_dir or rel.startswith(build_dir + "/")):
        return True
    if rel in files or (repo_root / rel).exists():
        return True
    if docs_dir:
        alt = f"{docs_dir}/{rel}"
        if alt in files or (repo_root / alt).exists():
            return True
    return False
```

- [ ] **Step 4: Change the `check_path` signature and its paths loop**

Replace the signature line:

```python
def check_path(
    path: Path, repo_root: Path | None, files: set[str], config: dict
) -> tuple[bool, str]:
```

Then, immediately after `cites = extract_citations(text)`, add the lookups and replace the paths loop body:

```python
    cites = extract_citations(text)
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    problems: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if not _resolves(rel, repo_root, files, docs_dir, build_dir):
            problems.append(f"cites nonexistent path '{cited}'")
```

Leave the tests loop, the symbol loop, and the return statement exactly as they are — Task 5 rewrites those.

- [ ] **Step 5: Update `main` to pass config**

In `main()`, hoist the config load above `archive_dirs` and thread it through:

```python
    repo_root = repo_root_for(args.config)
    config = _load_config(args.config)
    files = tracked_files(repo_root) if repo_root else set()
    arch = archive_dirs(config, repo_root) if repo_root else []
    results, any_block_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, repo_root, files, config)
```

- [ ] **Step 6: Update the two external call sites**

`tests/lint/test_site_citations_line_free.py` currently calls `citation_exists.check_path(page, repo_root, files)`. Load this host's real config so the corpus guard exercises the real `docs_dir`:

```python
    cfg = citation_exists._load_config(
        repo_root / ".engineering-docs-agent" / "config.yml"
    )
    ...
        ok, msg = citation_exists.check_path(page, repo_root, files, cfg)
```

`tests/scripts/test_migrate_line_citations.py` builds a synthetic repo with no site config, so pass an empty dict:

```python
    ok, msg = citation_exists.check_path(page, repo, files, {})
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. If `test_site_citations_line_free.py` newly fails, that is a real signal — read the message before touching the test.

- [ ] **Step 8: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py \
        tests/lint/test_site_citations_line_free.py tests/scripts/test_migrate_line_citations.py
git commit -m "fix(CCE-131): resolve docs-relative and build-output citations

citation_exists resolved cited paths repo-root-relative only, so a docs page
citing a sibling page or naming mkdocs build output read as a confabulation.
check_path gains a config parameter -- aligning it with every other rule in
scripts/lint/, all of which already take (path, config) -- and resolves
against docs_dir and site_dir as well as the repo root."
```

---

### Task 4: Reserved `example/` namespace

The generic-first mandate _requires_ fictional-host examples; documentation that hardcodes this host's `scripts/` layout is wrong documentation. Fenced examples are already safe. This gives prose the same affordance, following RFC 2606's reserved `example.com`.

**Files:**

- Modify: `scripts/lint/citation_exists.py` — `DEFAULT_EXAMPLE_PREFIXES`, `example_prefixes`, `check_path` paths loop
- Modify: `templates/config.schema.json` — declare `lint.citation_example_prefixes`
- Test: `tests/lint/test_citation_exists.py`

**Interfaces:**

- Consumes: `check_path(path, repo_root, files, config)` (Task 3), `_tmp_git_repo` / `_commit_all` (Task 2).
- Produces: `example_prefixes(config: dict) -> tuple[str, ...]` — each entry normalized with a trailing slash. Host config **replaces** the default (it is a namespace choice, not an additive list).

- [ ] **Step 1: Write the failing test**

```python
def test_example_namespace_path_passes(tmp_path):
    """CCE-131: `example/` is a reserved illustrative namespace (RFC 2606
    precedent) and never resolves by design."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("A page with `example/auth/session.py` in its file list.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_non_example_fictional_path_still_blocks(tmp_path):
    """The namespace is the affordance; inventing another root is still a defect."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("A page with `scripts/auth/session.py` in its file list.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "scripts/auth/session.py" in msg


def test_host_configured_prefix_replaces_the_default(tmp_path):
    """A host with a real top-level example/ dir picks a different word."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Both `acme/auth/session.py` and `example/auth/session.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_example_prefixes": ["acme"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "example/auth/session.py" in msg
    assert "acme/auth/session.py" not in msg
```

- [ ] **Step 2: Run to verify the first and third fail**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -k "example_namespace or fictional_path or configured_prefix" -v`
Expected: `test_example_namespace_path_passes` FAILS (blocks). `test_host_configured_prefix_replaces_the_default` FAILS (`acme/...` is reported). `test_non_example_fictional_path_still_blocks` PASSES already.

- [ ] **Step 3: Implement**

Add beside the other module constants in `scripts/lint/citation_exists.py`:

```python
# CCE-131: reserved illustrative namespace, RFC 2606's example.com precedent.
# The generic-first mandate requires fictional-host examples in docs; a token
# under this namespace is guaranteed never to resolve, so it is documentation,
# not a citation. Hosts with a real top-level example/ dir override the word.
DEFAULT_EXAMPLE_PREFIXES = ("example/",)
```

Add beside the other config readers:

```python
def example_prefixes(config: dict) -> tuple[str, ...]:
    """Reserved illustrative-namespace prefixes, each with a trailing slash.

    Host config REPLACES the default rather than extending it: this is a
    namespace choice, and a host that picks `acme/` because it has a real
    `example/` directory must not keep the shadowed default.
    """
    lint = config.get("lint") or {}
    configured = lint.get("citation_example_prefixes")
    if configured is None:
        return DEFAULT_EXAMPLE_PREFIXES
    return tuple(f"{str(p).strip('/')}/" for p in configured if str(p).strip("/"))
```

In `check_path`, add the prefix lookup beside the others and the skip inside the paths loop:

```python
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    problems: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue  # reserved illustrative namespace, never expected to resolve
        if not _resolves(rel, repo_root, files, docs_dir, build_dir):
            problems.append(f"cites nonexistent path '{cited}'")
```

- [ ] **Step 4: Declare the config key**

In `templates/config.schema.json`, under `properties.lint.properties`, add:

```json
"citation_example_prefixes": {
  "type": "array",
  "items": { "type": "string" },
  "description": "Reserved illustrative path namespaces citation_exists never resolves (CCE-131). Replaces the built-in default of [\"example\"]."
}
```

If `properties.lint` has no `properties` object today, add one containing this key. The object declares no `additionalProperties`, so existing host configs keep validating either way.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py tests/schemas -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py templates/config.schema.json
git commit -m "feat(CCE-131): reserved example/ namespace for illustrative paths

The generic-first mandate requires fictional-host examples, and they leak out
of fenced blocks into prose where citation_exists treats them as citations.
A reserved namespace (RFC 2606 precedent) makes them deterministically safe
and turns an unrecognizable example into a naming bug with a mechanical fix."
```

---

### Task 5: `lint.citation_exempt_tokens` with plugin defaults and a stale-exemption note

One class survives every resolver improvement: tokens whose **non-existence is the claim**. `tests/scripts/__init__.py` must not exist — a recorded `CLAUDE.md` invariant — and a page documenting that necessarily names it.

**Files:**

- Modify: `scripts/lint/citation_exists.py` — `DEFAULT_EXEMPT_TOKENS`, `exempt_tokens`, all three loops in `check_path`, the return
- Modify: `templates/config.schema.json` — declare `lint.citation_exempt_tokens`
- Modify: `.engineering-docs-agent/config.yml` — this host's entry
- Test: `tests/lint/test_citation_exists.py`

**Interfaces:**

- Consumes: `check_path(path, repo_root, files, config)` (Task 3), `_resolves` (Task 3), `example_prefixes` (Task 4), `_tmp_git_repo` / `_commit_all` (Task 2).
- Produces: `exempt_tokens(config: dict) -> set[str]` — plugin defaults **unioned** with host entries. Host config extends; it never replaces.

- [ ] **Step 1: Write the failing test**

```python
def test_exempt_token_passes(tmp_path):
    """CCE-131: a file whose non-existence IS the claim."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("tests/scripts must not be a package: no `tests/scripts/__init__.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg


def test_unlisted_sibling_still_blocks(tmp_path):
    """The list exempts exact tokens, not a directory."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("See `tests/scripts/conftest.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "tests/scripts/conftest.py" in msg


def test_plugin_default_exempts_the_rules_own_placeholder(tmp_path):
    """test_snake_case is plugin-intrinsic: it lives in this module's docstring,
    so every host documenting this lint hits it. No host config needed."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Test identifiers look like `test_snake_case`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is True, msg


def test_host_entries_extend_rather_than_replace_defaults(tmp_path):
    """A host that lists its own token keeps the plugin defaults."""
    repo = _tmp_git_repo(tmp_path)
    page = repo / "page.md"
    page.write_text("Both `test_snake_case` and `tests/scripts/__init__.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["tests/scripts/__init__.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg


def test_stale_exemption_is_noted_without_blocking(tmp_path):
    """A listed token that now resolves must surface, or the list rots silently."""
    repo = _tmp_git_repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "real.py").write_text("x = 1\n")
    page = repo / "page.md"
    page.write_text("See `scripts/real.py`.\n")
    _commit_all(repo)
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_exempt_tokens": ["scripts/real.py"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True
    assert "stale exemption" in msg
    assert "scripts/real.py" in msg
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/lint/test_citation_exists.py -k "exempt or stale or placeholder" -v`
Expected: `test_unlisted_sibling_still_blocks` PASSES already (it is the guard). The other four FAIL.

- [ ] **Step 3: Implement the constant and reader**

Add beside the other module constants:

```python
# CCE-131: tokens whose NON-EXISTENCE is the claim. Plugin-intrinsic entries
# ship here because every host that documents this lint hits them --
# test_snake_case is this module's own docstring placeholder. Host-specific
# invariants go in the host config and are unioned with these.
DEFAULT_EXEMPT_TOKENS = ("test_snake_case",)
```

Add beside the other config readers:

```python
def exempt_tokens(config: dict) -> set[str]:
    """Exact tokens citation_exists must not require to exist.

    Plugin defaults UNIONED with the host's lint.citation_exempt_tokens: host
    config extends, never replaces, so a host cannot silently lose a
    plugin-intrinsic entry by declaring one of its own.
    """
    lint = config.get("lint") or {}
    host = lint.get("citation_exempt_tokens") or []
    return set(DEFAULT_EXEMPT_TOKENS) | {str(t) for t in host}
```

- [ ] **Step 4: Rewrite the three loops and the return in `check_path`**

```python
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    problems: list[str] = []
    notes: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if cited in exempt:
            if _resolves(rel, repo_root, files, docs_dir, build_dir):
                notes.append(f"stale exemption: '{cited}' now resolves")
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue  # reserved illustrative namespace, never expected to resolve
        if not _resolves(rel, repo_root, files, docs_dir, build_dir):
            problems.append(f"cites nonexistent path '{cited}'")
    for name in cites["tests"]:
        exists = cited_test_exists(repo_root, name)
        if name in exempt:
            if exists:
                notes.append(f"stale exemption: '{name}' now resolves")
            continue
        if not exists:
            problems.append(f"cites nonexistent test '{name}'")
    for bare, leaf in extract_symbol_citations(text):
        if bare in exempt:
            continue
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
    if problems:
        return False, "; ".join(problems + notes)
    return True, "; ".join(["ok"] + notes)
```

- [ ] **Step 5: Declare the config key**

In `templates/config.schema.json`, under `properties.lint.properties`, beside the Task 4 key:

```json
"citation_exempt_tokens": {
  "type": "array",
  "items": { "type": "string" },
  "description": "Exact citation tokens whose non-existence is intentional (CCE-131). Unioned with the plugin defaults, never replacing them."
}
```

- [ ] **Step 6: Add this host's entry**

In `.engineering-docs-agent/config.yml`, under the existing `lint:` block:

```yaml
# CCE-131: tests/scripts must NOT be a package (CLAUDE.md invariant), so a
# page documenting that rule necessarily names a file that cannot exist.
citation_exempt_tokens:
  - tests/scripts/__init__.py
```

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/lint/citation_exists.py tests/lint/test_citation_exists.py \
        templates/config.schema.json .engineering-docs-agent/config.yml
git commit -m "feat(CCE-131): citation_exempt_tokens for artifacts whose absence is the claim

The one class no resolver improvement reaches: tests/scripts/__init__.py must
not exist, so a page documenting that invariant necessarily names it. Plugin
defaults are unioned with host entries so a host cannot silently drop a
plugin-intrinsic entry, and a listed token that starts resolving emits a
stale-exemption note so the list cannot rot unnoticed."
```

---

### Task 6: Authoring contract and the PR #198 content migration

Without the contract change the migration buys one night: the page regenerates nightly from the same grounding set and an author who has not been told the convention re-emits the old token.

**Files:**

- Modify: `agents/page-author.md` — the citation rule in step 3
- Modify: `docs/site-src/architecture/cce-capability-c-canonical-core-citations.md`

**Interfaces:**

- Consumes: the `example/` default from `example_prefixes` (Task 4) — the contract must name the same namespace the rule reserves.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Extend the page-author citation rule**

In `agents/page-author.md`, inside the step-3 paragraph, immediately after the sentence `Cite only files and tests you confirmed exist.`, insert:

```
A backticked path or test identifier asserts that the artifact EXISTS — write one only when it does. When you need an illustrative or fictional-host path, put it under the reserved `example/` namespace (`example/auth/session.py`), which the docs pipeline knows is illustrative. When you need a metasyntactic token — a placeholder standing for a shape rather than naming a real thing — put it inside a fenced block, never in prose.
```

Leave the rest of the paragraph (the line-free citation grammar) unchanged.

- [ ] **Step 2: Verify the agent-contract suite still passes**

Run: `.venv/bin/python -m pytest tests/agents -q`
Expected: PASS. If a contract test asserts on the exact wording of the citation rule, read it before editing — it may be pinning a phrase this insertion must preserve.

- [ ] **Step 3: Migrate the fictional-host path that blocks PR #198**

In `docs/site-src/architecture/cce-capability-c-canonical-core-citations.md`, in the "Source-drift test coverage" bullet list (around line 115):

```diff
- - A page with `source_files: [scripts/auth/**/*.py]` is flagged when
-   `scripts/auth/session.py` appears in a PR's file list.
+ - A page with `source_files: [example/auth/**/*.py]` is flagged when
+   `example/auth/session.py` appears in a PR's file list.
```

Also change the matching path inside the fenced YAML block earlier in the same section (around lines 90–96) so the example is internally consistent. The fenced copy is not linted, but a page whose fence and prose disagree is worse documentation than either alone.

- [ ] **Step 4: Verify the page now passes the rule**

```bash
.venv/bin/python scripts/lint/citation_exists.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/architecture/cce-capability-c-canonical-core-citations.md \
  --json | python3 -m json.tool
```

Expected: `"ok": true` for that path, and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add agents/page-author.md docs/site-src/architecture/cce-capability-c-canonical-core-citations.md
git commit -m "feat(CCE-131): page-author learns the concept of a non-citation

The contract said 'cite only files and tests you confirmed exist' and had no
vocabulary for an illustrative path, a fictional host, or a metasyntactic
placeholder -- so an author writing a generic-host example had no compliant
way to do it in prose. Adds the example/ namespace and the fence rule, and
migrates the fictional-host path that has blocked two consecutive nightlies."
```

---

### Task 7: Full-corpus verification and PR

Task 1 can _increase_ the blocked-token count; Tasks 3–5 lower it. The net must be measured, not assumed — the repo's "run the actual consumer tool" invariant applied to a linter. Passing pytest is not sufficient evidence.

**Files:**

- No permanent files. Scratch output goes to the session scratchpad.

**Interfaces:**

- Consumes: every prior task.
- Produces: before/after token counts recorded in the PR body.

- [ ] **Step 1: Measure the corpus after the change**

```bash
.venv/bin/python scripts/lint/citation_exists.py \
  --config .engineering-docs-agent/config.yml \
  --paths $(git ls-files 'docs/site-src/**/*.md') \
  --json > /tmp/after.json; echo "exit=$?"
.venv/bin/python - <<'PY'
import json
d = json.load(open("/tmp/after.json"))
bad = [r for r in d["results"] if not r["ok"]]
print(f"failing pages: {len(bad)} / {len(d['results'])}")
for r in bad:
    print(" -", r["path"], "|", r["severity"], "|", r["message"])
stale = [r for r in d["results"] if "stale exemption" in r["message"]]
print(f"stale exemptions: {len(stale)}")
PY
```

- [ ] **Step 2: Measure the same corpus on `main` for the baseline**

```bash
git stash -u
git checkout -q main
.venv/bin/python scripts/lint/citation_exists.py \
  --config .engineering-docs-agent/config.yml \
  --paths $(git ls-files 'docs/site-src/**/*.md') \
  --json > /tmp/before.json; echo "exit=$?"
git checkout -q docs/CCE-131-citation-exists-false-positive-closure
git stash pop
```

Expected shape: `before` shows roughly 20 failing pages; `after` shows materially fewer. **The six genuine near-miss confabulations (CCE-132) must still fail.** If they do not, a change went too far and the guard has been weakened — stop and diagnose before proceeding. They are: `scripts/build_doc_source_map.py`, `scripts/generate_archive_indexes.py`, `scripts/verify_docs_diagrams.py`, `agents/schemas/page-author-output.json`, `.github/actionlint.yml`, `.github/workflows/diagram-gate.yml`.

- [ ] **Step 3: Run the full suite one final time**

Run: `.venv/bin/python -m pytest -q`
Expected: 1169 + the new tests passed, 5 skipped, 0 failed.

- [ ] **Step 4: Push and update PR #200**

```bash
git push
gh pr view 200 --json number,title,state
```

Add the measured before/after counts and the surviving-failures list to the PR body, naming which survivors are the intended CCE-132 residue.

- [ ] **Step 5: Verify before merge**

Merge only on a green _integrated_ suite: merge `main` into the branch locally and re-run `.venv/bin/python -m pytest` against the combined tree, then poll `gh pr checks 200` parsing `state`/`bucket` (never `conclusion`). After merging, run `scripts/prune_merged_branches.py --apply`.

---

## Self-Review

**Spec coverage.** A1 → Task 3. A2 → Task 2. A3 → Task 1. A4 → Tasks 4 and 6. B → Task 5. C → Task 6. Spec §5's mandated corpus verification → Task 7. Spec §5's drive-by import fix → Task 1 Step 1. All four blocking tokens are cleared: `scripts/auth/session.py` by Task 6's migration into Task 4's namespace, `test_snake_case` by Task 5's plugin default, `tests/scripts/__init__.py` by Task 5's host entry, `test_lint_runner` by Task 2. No spec section is unimplemented.

**Placeholder scan.** No TBD/TODO. Every code step carries the actual code; every test step carries the actual test body. Task 3 Step 4 and Task 5 Step 4 both state explicitly which surrounding code they leave alone, rather than implying unwritten content.

**Type consistency.** `check_path` gains its fourth parameter once, in Task 3; Tasks 4 and 5 extend only its body. `_resolves` is defined in Task 3 with the exact signature Task 5 calls. `example_prefixes` returns trailing-slash-normalized strings, which is what Task 4's `rel.startswith(p)` requires. `exempt_tokens` returns `set[str]` matched against the _cited_ token as written — the form an operator puts in config — consistently across all three loops. `_tmp_git_repo` / `_commit_all` are introduced in Task 2 and declared as consumed inputs by Tasks 3, 4, and 5.

**One deliberate asymmetry, flagged for the implementer:** `example_prefixes` **replaces** the default when configured; `exempt_tokens` **unions**. This is intentional and both docstrings say so — a namespace is a choice, an exemption list is additive. Do not "fix" one to match the other.
