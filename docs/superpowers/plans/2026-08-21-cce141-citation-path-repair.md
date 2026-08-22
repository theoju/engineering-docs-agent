# CCE-141 Citation Path Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `page-author` shortens a citation into an unresolvable relative path, repair it deterministically to the full repo-root path before the linter sees the page.

**Architecture:** A new self-contained module `scripts/citation_repair.py` holds the matching and rewriting logic and imports its resolution helpers from `scripts/lint/citation_exists.py` (a declared shared-helper contract). `orchestrator_runner.py` calls it once per authored page, immediately after `_enforce_agent_frontmatter`. Every lint rule stays a pure checker.

**Tech Stack:** Python 3.11+, stdlib only (`re`, `subprocess`, `pathlib`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md` (committed `0f6b224`)

## Global Constraints

- **Python stdlib only.** No new dependencies.
- **Never weaken the confabulation gate.** Repair may only turn a _block_ into a _correct citation_. Zero matches and ambiguous matches must leave the page byte-identical so `citation_exists` blocks exactly as today.
- **Honour every exclusion `check_path` honours**: `exempt_tokens(config)`, `example_prefixes(config)`, `_is_gitignored`, and tokens `_relativize` returns `None` for. Rewriting a deliberately-illustrative token into a real path is worse than the original defect.
- **Import, never reimplement,** the helpers from `citation_exists`. Its module docstring declares them a shared-helper contract.
- **Reporting is `info_only=True`.** A repair is a successful rescue; it must not flip `partial` (that would veto auto-merge for a self-correction) but must appear in the digest.
- **Run tests with the venv:** `PYTHONPATH=scripts .venv/bin/python -m pytest ...` from the repo root.
- Existing suite baseline: **1459 passed, 4 skipped**. It must still pass at every commit.

---

### Task 1: Suffix candidate matching

Pure function, no I/O. This is the core of the safety argument: a strict segment-boundary suffix match.

**Files:**

- Create: `scripts/citation_repair.py`
- Test: `tests/orchestrator/test_citation_repair.py`

**Interfaces:**

- Consumes: nothing (first task).
- Produces: `suffix_candidates(cited: str, files: set[str]) -> list[str]` — sorted tracked paths of which `cited` is a strict segment-boundary suffix.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_citation_repair.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import citation_repair as cr  # noqa: E402

FILES = {
    ".claude/skills/connector-builder/references/checklist.md",
    ".claude/skills/other-skill/references/notes.md",
    "docs/site-src/index.md",
    "README.md",
}


def test_unique_two_segment_suffix_matches_one_file():
    """The ADIS shape: 'references/checklist.md' names exactly one tracked file."""
    assert cr.suffix_candidates("references/checklist.md", FILES) == [
        ".claude/skills/connector-builder/references/checklist.md"
    ]


def test_match_requires_segment_boundaries():
    """A substring that is not a path-segment suffix must never match.

    Without the boundary rule, 'erences/checklist.md' would 'repair' to a file
    it does not name, which is exactly the silent-retarget failure the design
    rules out.
    """
    assert cr.suffix_candidates("erences/checklist.md", FILES) == []


def test_exact_path_is_not_a_candidate():
    """A token equal to a tracked path already resolves and is never a repair
    candidate. Candidates are always a STRICT shortening."""
    assert cr.suffix_candidates("README.md", {"README.md"}) == []


def test_ambiguous_one_segment_suffix_returns_all_matches():
    """Caller decides what to do with ambiguity; this function just reports it."""
    files = {"a/notes.md", "b/notes.md"}
    assert cr.suffix_candidates("notes.md", files) == ["a/notes.md", "b/notes.md"]


def test_no_match_returns_empty():
    assert cr.suffix_candidates("nope/absent.md", FILES) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'citation_repair'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/citation_repair.py`:

```python
"""Deterministic repair of shortened citation paths (CCE-141).

`page-author` sometimes emits a citation as a bare relative path — the
committed page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites and
the rewrite shortened it to `references/checklist.md`. `citation_exists`
correctly finds nothing at the repo root and blocks the page; post-CCE-140 the
deferral skip then abandons the PR, so the page is silently never written.

This module repairs the observable defect regardless of what causes it. The
safety argument is that a path is always a suffix of itself: if the page cited
`X` and now cites `suffix(X)`, that suffix necessarily matches `X`, so a UNIQUE
match is provably `X`. Repair cannot silently retarget a citation. Ambiguity
and zero-match both leave the page untouched and blocking, so repair can only
ever convert a block into a correct citation — never into a silent pass.

Spec: docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md
"""

from __future__ import annotations


def suffix_candidates(cited: str, files: set[str]) -> list[str]:
    """Tracked paths of which `cited` is a strict segment-boundary suffix.

    Segment boundaries are required, not substring matching:
    `references/checklist.md` matches
    `.claude/skills/connector-builder/references/checklist.md`, but
    `erences/checklist.md` matches nothing.

    `len(parts) > n` is what makes the shortening STRICT — it excludes the
    exact-match case, which is never a repair candidate because such a token
    already resolved.
    """
    segments = cited.split("/")
    n = len(segments)
    out = []
    for f in files:
        parts = f.split("/")
        if len(parts) > n and parts[-n:] == segments:
            out.append(f)
    return sorted(out)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/citation_repair.py tests/orchestrator/test_citation_repair.py
git commit -m "feat(citation-repair): segment-boundary suffix matching — CCE-141"
```

---

### Task 2: Token rewriting that preserves `:symbol` suffixes

`extract_citations` strips a trailing `:line`/`:symbol` before returning bare paths, so the rewrite must operate on the token as it appears in the page and put the suffix back.

**Files:**

- Modify: `scripts/citation_repair.py`
- Test: `tests/orchestrator/test_citation_repair.py`

**Interfaces:**

- Consumes: `suffix_candidates` from Task 1.
- Produces: `rewrite_token(text: str, old: str, new: str) -> str` — replaces the bare path `old` with `new` inside every inline code span whose bare path equals `old`, preserving any `:symbol` suffix and leaving all other text byte-identical.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_citation_repair.py`:

```python
def test_rewrite_replaces_bare_path_in_inline_span():
    text = "See `references/checklist.md` for the steps.\n"
    out = cr.rewrite_token(
        text,
        "references/checklist.md",
        ".claude/skills/connector-builder/references/checklist.md",
    )
    assert out == (
        "See `.claude/skills/connector-builder/references/checklist.md` "
        "for the steps.\n"
    )


def test_rewrite_preserves_a_symbol_suffix():
    """`path.py:Class.method` — the path is repaired, the symbol survives."""
    text = "The helper `lint/citation_exists.py:check_path` does this.\n"
    out = cr.rewrite_token(
        text,
        "lint/citation_exists.py",
        "scripts/lint/citation_exists.py",
    )
    assert out == (
        "The helper `scripts/lint/citation_exists.py:check_path` does this.\n"
    )


def test_rewrite_leaves_other_tokens_untouched():
    text = "Both `references/checklist.md` and `README.md` are cited.\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "`README.md`" in out
    assert "`a/b/references/checklist.md`" in out


def test_rewrite_ignores_a_prose_mention_outside_backticks():
    """Only inline code spans are citations; bare prose is not."""
    text = "the file references/checklist.md is mentioned in prose\n"
    assert cr.rewrite_token(text, "references/checklist.md", "a/b/c.md") == text


def test_rewrite_is_a_noop_when_nothing_matches():
    text = "Nothing to do here `README.md`.\n"
    assert cr.rewrite_token(text, "absent.md", "a/absent.md") == text


def test_rewrite_skips_a_closed_fence():
    """extract_citations strips fenced blocks, so repair never SEES a fenced
    token. The rewrite must skip them too, or a prose repair would silently
    mutate an unrelated illustration inside a code fence."""
    text = (
        "See `references/checklist.md`.\n"
        "\n"
        "```\n"
        "cite it as `references/checklist.md`\n"
        "```\n"
    )
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert out.count("a/b/references/checklist.md") == 1
    assert "cite it as `references/checklist.md`" in out


def test_rewrite_still_applies_inside_an_unterminated_fence():
    """Mirrors strip_fenced_blocks exactly: an UNTERMINATED fence strips
    nothing, so extract_citations DOES see these tokens. If the rewrite
    skipped them, repair_text would report a repair it never applied."""
    text = "```\nsee `references/checklist.md`\n"
    out = cr.rewrite_token(
        text, "references/checklist.md", "a/b/references/checklist.md"
    )
    assert "a/b/references/checklist.md" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: FAIL — `AttributeError: module 'citation_repair' has no attribute 'rewrite_token'`

- [ ] **Step 3: Write minimal implementation**

Replace the `from __future__ import annotations` line in `scripts/citation_repair.py` with:

```python
from __future__ import annotations

import re
import sys
from pathlib import Path

_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

# Imported, never reimplemented: citation_exists declares these a shared-helper
# contract. Repair must agree with check_path on what a citation IS and what
# resolves, or the two drift and repair starts "fixing" tokens the linter
# deliberately skips.
from citation_exists import (  # noqa: E402
    _INLINE_CODE_RE,
    _SUFFIX_RE,
)
```

Then append the function:

```python
def _closed_fence_lines(text: str) -> set[int]:
    """Line indices inside a CLOSED fence — the lines strip_fenced_blocks cuts.

    Mirrors that function's bookkeeping on purpose, including the awkward
    part: an UNTERMINATED fence strips nothing there, so its lines stay
    visible to extract_citations and must stay rewritable here. Any divergence
    would let repair_text report a repair that rewrite_token never applied.

    Indices are over text.split("\n") — the same split rewrite_token uses —
    so the two always align. _INLINE_CODE_RE excludes newlines, so no code
    span can straddle a line and per-line rewriting is equivalent.
    """
    fenced: set[int] = set()
    in_fence = False
    fence = ""
    start = 0
    for i, line in enumerate(text.split("\n")):
        stripped = line.lstrip()
        if not in_fence and (
            stripped.startswith("```") or stripped.startswith("~~~")
        ):
            in_fence, fence, start = True, stripped[:3], i
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            fenced.update(range(start, i + 1))
    return fenced


def rewrite_token(text: str, old: str, new: str) -> str:
    """Replace bare path `old` with `new` inside matching inline code spans.

    Matching is on the token's BARE path (suffix stripped), but the replacement
    happens inside the original token, so `path.py:Class.method` keeps its
    symbol. Every other byte of the document is preserved — this must never
    reflow or normalise the author's prose.
    """

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if _SUFFIX_RE.sub("", token.strip()) != old:
            return match.group(0)
        return "`" + token.replace(old, new, 1) + "`"

    fenced = _closed_fence_lines(text)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i not in fenced:
            lines[i] = _INLINE_CODE_RE.sub(_sub, line)
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/citation_repair.py tests/orchestrator/test_citation_repair.py
git commit -m "feat(citation-repair): rewrite tokens preserving :symbol suffixes — CCE-141"
```

---

### Task 3: `repair_text` — resolution, exclusions, and the ambiguity tiebreak

The task where correctness actually lives. Every exclusion in the spec's table gets its own test.

**Files:**

- Modify: `scripts/citation_repair.py`
- Test: `tests/orchestrator/test_citation_repair.py`

**Interfaces:**

- Consumes: `suffix_candidates`, `rewrite_token` from Tasks 1–2.
- Produces:
  - `tracked_files(repo_root: Path) -> set[str]` — re-exported from `citation_exists`.
  - `repair_text(text: str, repo_root: Path, config: dict, files: set[str], prior_text: str | None = None) -> tuple[str, list[tuple[str, str]]]` — returns `(new_text, repairs)` where `repairs` is a list of `(old, new)` pairs in document order. `new_text == text` when `repairs` is empty.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_citation_repair.py`:

```python
import subprocess

import pytest


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A real git repo — _resolves and _is_gitignored both shell out to git."""
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True
    )
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    target = tmp_path / ".claude/skills/connector-builder/references"
    target.mkdir(parents=True)
    (target / "checklist.md").write_text("# checklist\n")
    (tmp_path / "README.md").write_text("# readme\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


CFG: dict = {}


def test_shortened_citation_is_repaired(repo):
    """The ADIS case, end to end."""
    text = "See `references/checklist.md` for the steps.\n"
    files = cr.tracked_files(repo)
    out, repairs = cr.repair_text(text, repo, CFG, files)
    assert repairs == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
        )
    ]
    assert ".claude/skills/connector-builder/references/checklist.md" in out


def test_confabulated_path_is_left_alone(repo):
    """STRICTNESS GUARD. Repair must not weaken the gate citation_exists IS.

    A path matching nothing is a confabulation. Leaving the page byte-identical
    is what keeps citation_exists blocking it.
    """
    text = "See `docs/invented-by-the-model.md`.\n"
    files = cr.tracked_files(repo)
    out, repairs = cr.repair_text(text, repo, CFG, files)
    assert repairs == []
    assert out == text


def test_ambiguous_suffix_is_left_alone(repo):
    """Two candidates, no prior version to disambiguate -> fail closed."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_ambiguity_is_broken_by_the_previous_version(repo):
    """When the prior page cited exactly one candidate, that one wins."""
    second = repo / "other/references"
    second.mkdir(parents=True)
    (second / "checklist.md").write_text("# other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "second")

    prior = "See `.claude/skills/connector-builder/references/checklist.md`.\n"
    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(
        text, repo, CFG, cr.tracked_files(repo), prior_text=prior
    )
    assert repairs == [
        (
            "references/checklist.md",
            ".claude/skills/connector-builder/references/checklist.md",
        )
    ]


def test_resolving_citation_is_byte_identical(repo):
    text = "See `README.md`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_repair_is_idempotent(repo):
    text = "See `references/checklist.md`.\n"
    files = cr.tracked_files(repo)
    once, _ = cr.repair_text(text, repo, CFG, files)
    twice, repairs = cr.repair_text(once, repo, CFG, files)
    assert repairs == []
    assert twice == once


def test_exempt_token_is_never_repaired(repo):
    """Exclusion row 1. The host declared this unverifiable on purpose."""
    cfg = {"lint": {"citation_exempt_tokens": ["references/checklist.md"]}}
    text = "See `references/checklist.md`.\n"
    out, repairs = cr.repair_text(text, repo, cfg, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_example_namespace_token_is_never_repaired(repo):
    """Exclusion row 2. `example/` is fictional by design.

    Rewriting it into a real path would make an illustration silently claim to
    cite real code — worse than the defect this module fixes.
    """
    ex = repo / "example/auth"
    ex.mkdir(parents=True)
    (ex / "session.py").write_text("# ex\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ex")

    text = "See `example/auth/session.py`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text


def test_gitignored_path_is_never_repaired(repo):
    """Exclusion row 3 (CCE-145): declared but absent from a fresh checkout."""
    (repo / ".gitignore").write_text("build/\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore")

    text = "See `build/output.md`.\n"
    out, repairs = cr.repair_text(text, repo, CFG, cr.tracked_files(repo))
    assert repairs == []
    assert out == text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: FAIL — `AttributeError: module 'citation_repair' has no attribute 'tracked_files'`

- [ ] **Step 3: Write minimal implementation**

Extend the import block in `scripts/citation_repair.py` to:

```python
from citation_exists import (  # noqa: E402
    _INLINE_CODE_RE,
    _SUFFIX_RE,
    _build_dir,
    _docs_dir,
    _is_gitignored,
    _relativize,
    _resolves,
    example_prefixes,
    exempt_tokens,
    extract_citations,
    source_roots,
    tracked_files,
)

__all__ = ["suffix_candidates", "rewrite_token", "repair_text", "tracked_files"]
```

Append the function:

```python
def repair_text(
    text: str,
    repo_root: Path,
    config: dict,
    files: set[str],
    prior_text: str | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Repair shortened citations in `text`. Returns (new_text, repairs).

    The skip order mirrors `citation_exists.check_path` deliberately. Every
    class it declines to check is a class repair must decline to touch: an
    exempt token, a reserved `example/` path, and a gitignored path are all
    unresolvable BY DESIGN, and "fixing" one would convert a deliberate
    illustration into a false claim about real code.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)
    prior_cited = set(extract_citations(prior_text)["paths"]) if prior_text else set()

    repairs: list[tuple[str, str]] = []
    for cited in extract_citations(text)["paths"]:
        if cited in exempt:
            continue
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue
        if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
            continue
        if _is_gitignored(repo_root, rel):
            continue

        candidates = suffix_candidates(rel, files)
        if len(candidates) > 1:
            # Ambiguity tiebreak: the version this page shipped with before the
            # author touched it. Only a single surviving candidate counts —
            # two prior citations are no more decisive than none.
            narrowed = [c for c in candidates if c in prior_cited]
            if len(narrowed) == 1:
                candidates = narrowed
        if len(candidates) != 1:
            continue
        repairs.append((cited, candidates[0]))

    new_text = text
    for old, new in repairs:
        new_text = rewrite_token(new_text, old, new)
    return new_text, repairs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair.py -q`
Expected: PASS, 21 passed

Then confirm nothing else broke:

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest -q`
Expected: PASS, 1481 passed, 4 skipped

- [ ] **Step 5: Commit**

```bash
git add scripts/citation_repair.py tests/orchestrator/test_citation_repair.py
git commit -m "feat(citation-repair): resolution, exclusions, ambiguity tiebreak — CCE-141"
```

---

### Task 4: Wire into the authoring loop and report info-only

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add two functions after `_enforce_agent_frontmatter`, which begins at line 1540; add the call at line 2385)
- Test: `tests/orchestrator/test_citation_repair_wiring.py`

**Interfaces:**

- Consumes: `citation_repair.repair_text`, `citation_repair.tracked_files` from Task 3.
- Produces: `_repair_citation_paths(path: Path, repo_root: Path, config: dict, state: dict) -> None` — repairs in place and appends one `info_only` reason per repair; and `_prior_page_text(repo_root: Path, path: Path) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_citation_repair_wiring.py`:

```python
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as runner  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    subprocess.run(
        ["git", "init", "-q", str(tmp_path)], check=True, capture_output=True
    )
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    refs = tmp_path / ".claude/skills/connector-builder/references"
    refs.mkdir(parents=True)
    (refs / "checklist.md").write_text("# checklist\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _state() -> dict:
    return {"current_run": {"partial": False, "partial_reasons": []}}


def test_repair_rewrites_the_page_and_reports_info_only(repo):
    page = repo / "page.md"
    page.write_text("See `references/checklist.md` for the steps.\n")
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state)

    assert (
        ".claude/skills/connector-builder/references/checklist.md"
        in page.read_text()
    )
    cr = state["current_run"]
    assert cr["partial"] is False, (
        "a successful repair must not degrade the run — flipping partial here "
        "would veto auto-merge for a self-correction"
    )
    assert any("citation_path_repaired" in r for r in cr["partial_reasons"]), (
        f"the repair must be visible in the digest: {cr['partial_reasons']}"
    )


def test_no_repair_leaves_the_page_and_state_untouched(repo):
    page = repo / "page.md"
    original = "See `docs/invented.md`.\n"
    page.write_text(original)
    state = _state()

    runner._repair_citation_paths(page, repo, {}, state)

    assert page.read_text() == original
    assert state["current_run"]["partial_reasons"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair_wiring.py -q`
Expected: FAIL — `AttributeError: module 'orchestrator_runner' has no attribute '_repair_citation_paths'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/orchestrator_runner.py`, immediately after the end of `_enforce_agent_frontmatter` (which begins at line 1540):

```python
def _prior_page_text(repo_root: Path, path: Path) -> str | None:
    """The page as HEAD has it, or None for a new page / no commit."""
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        return None
    r = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{rel}"],
        capture_output=True,
        text=True,
    )
    return r.stdout if r.returncode == 0 else None


def _repair_citation_paths(
    path: Path, repo_root: Path, config: dict, state: dict
) -> None:
    """CCE-141: repair citations the author shortened into unresolvable paths.

    Runs beside _enforce_agent_frontmatter so content-validator only ever sees
    an already-correct page. Reported info_only: nothing was lost, so the run
    is not degraded — but the digest line is the only signal that would ever
    justify revisiting the author prompt, so it must not be silent.
    """
    import citation_repair

    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return
    files = citation_repair.tracked_files(repo_root)
    new_text, repairs = citation_repair.repair_text(
        text, repo_root, config, files, prior_text=_prior_page_text(repo_root, path)
    )
    if not repairs:
        return
    path.write_text(new_text)
    try:
        label = path.relative_to(repo_root).as_posix()
    except ValueError:
        label = path.name
    for old, new in repairs:
        add_partial(
            state,
            f"citation_path_repaired: {label}: '{old}' -> '{new}'",
            info_only=True,
        )
```

Then change the call site at line 2385 from:

```python
                if agent_fields is not None and target_path.exists():
                    # CCE-119 Item A: enforce the deterministic frontmatter on the
                    # written page (production: the LLM wrote it; dry-run: the synth
                    # above wrote it). Runs on both paths; a no-op when the write
                    # already matches.
                    _enforce_agent_frontmatter(target_path, agent_fields)
```

to:

```python
                if agent_fields is not None and target_path.exists():
                    # CCE-119 Item A: enforce the deterministic frontmatter on the
                    # written page (production: the LLM wrote it; dry-run: the synth
                    # above wrote it). Runs on both paths; a no-op when the write
                    # already matches.
                    _enforce_agent_frontmatter(target_path, agent_fields)
                if target_path.exists():
                    # CCE-141: repair shortened citations before content-validator
                    # runs. Deliberately NOT nested under the agent_fields guard —
                    # a shortened citation blocks any page, not only the
                    # agent-authored-frontmatter ones.
                    _repair_citation_paths(target_path, repo_root, config, state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/orchestrator/test_citation_repair_wiring.py -q`
Expected: PASS, 2 passed

Then the full suite:

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest -q`
Expected: PASS, 1483 passed, 4 skipped

- [ ] **Step 5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_citation_repair_wiring.py
git commit -m "feat(orchestrator): repair shortened citations after authoring — CCE-141"
```

---

### Task 5: Record the decision in CLAUDE.md

The repo convention is one entry per ticket capturing the traps, not just the change.

**Files:**

- Modify: `CLAUDE.md`

**Interfaces:**

- Consumes: nothing at runtime.
- Produces: nothing at runtime.

- [ ] **Step 1: Add the entry**

Insert as a new top-level bullet in the same list that holds the CCE-144 and CCE-151 entries, immediately after the CCE-151 bullet:

> **Historical draft — superseded.** What actually shipped is detection only; the
> repair this draft describes was withdrawn (spec Revision 3). Item (2)'s original
> "provably correct" wording is retired in place below rather than reproduced, because
> it is exactly the sentence a future reader would copy back into `CLAUDE.md`. Read the
> live bullet in `CLAUDE.md`, not this block.

```markdown
- **Shortened citations are repaired deterministically, not prompted away (CCE-141).** `page-author` sometimes shortens an already-resolvable citation — the ADIS page cited `.claude/skills/connector-builder/references/checklist.md` at three sites and the rewrite emitted bare `references/checklist.md`, which `citation_exists` correctly blocked. Post-CCE-140 that is not a stall: the deferral skip abandons the PR and **the page is silently never written**. `scripts/citation_repair.py` repairs it after authoring, beside `_enforce_agent_frontmatter`. Four things worth knowing. **(1) The prompt fix was rejected for being unverifiable, not for being hard.** CCE-141's stated acceptance asks for a regression test that the AUTHOR preserves a citation — a test of non-deterministic LLM behaviour. On 2026-08-21 one page blocked on an invented `docs/runbook.md`, re-authored and blocked on a _different_ `docs/foo.md`, then re-authored again containing no markdown links at all. Such a test passes or fails by luck; the substitution to deterministic repair tests is recorded in the spec. **(2) [CLAIM RETIRED — DO NOT COPY BACK.** This draft's item (2) asserted that a unique suffix match is correct because a path is always a suffix of itself. It is not. The argument is conditional on the cited token having been a shortening of a real path, and nothing ever checked that antecedent; the entry condition was only "does not resolve," which is the confabulation population `citation_exists` exists to block. Revision 2 replaced the claim with corroboration-as-entry-condition; Revision 3 deleted the rewrite altogether. The live wording is the CCE-141 bullet in `CLAUDE.md`. Retired 2026-08-21.**] **(3) The exclusion set is the dangerous part.** Repair must skip everything `check_path` skips — `citation_exempt_tokens`, the reserved `example/` namespace, gitignored paths, and tokens `_relativize` rejects. Rewriting `example/auth/session.py` into a real path would make a deliberate illustration silently claim to cite real code, which is worse than the original defect; each row has its own test. **(4) Placement kept lint rules pure.** `citation_exists --fix` was rejected because every rule in `scripts/lint/` follows `check_path(path, config) -> (ok, message)` and `lint_runner`'s CLI contract has no notion of _mutated_. Reporting is `info_only` — a repair is a successful rescue and must not flip `partial` (that would veto auto-merge for a self-correction), but it must stay visible in the digest or nobody ever learns the author is still doing it. **Unconfirmed and stated as such:** the originating mechanism. ADIS was never reproduced locally, so the relative-to-skill-directory hypothesis is untested; the design does not depend on which cause it is. Spec: `docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md`. Reference: CCE-141 (2026-08-21).
```

- [ ] **Step 2: Verify the CLAUDE.md tests still pass**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest tests/ -q -k "claude_md or CLAUDE"`
Expected: PASS, 4 passed

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=scripts .venv/bin/python -m pytest -q`
Expected: PASS, 1483 passed, 4 skipped

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): record the CCE-141 citation-repair decision"
```

---

## Verification

Before opening the PR, verify through the **real consumer** rather than the unit tests alone — a repaired page must actually satisfy `lint_runner`, not just `repair_text`'s own assertions.

- [ ] **Repair a page with a shortened citation, then run `lint_runner` over the result and confirm `citation_exists` reports `ok`.**

```bash
PYTHONPATH=scripts .venv/bin/python - <<'PY'
import json, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, "scripts")
import citation_repair as cr

T = Path(tempfile.mkdtemp())
subprocess.run(["git", "init", "-q", str(T)], check=True, capture_output=True)
for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
    subprocess.run(["git", "-C", str(T), "config", k, v], check=True)
refs = T / ".claude/skills/connector-builder/references"
refs.mkdir(parents=True)
(refs / "checklist.md").write_text("# checklist\n")
page = T / "page.md"
page.write_text(
    "---\nstatus: draft\nsources: []\nsynthesized_into: []\n---\n\n"
    "# Connector builder\n\nSee `references/checklist.md` for the steps.\n"
)
subprocess.run(["git", "-C", str(T), "add", "-A"], check=True)
subprocess.run(["git", "-C", str(T), "commit", "-qm", "init"], check=True)

text, repairs = cr.repair_text(page.read_text(), T, {}, cr.tracked_files(T))
page.write_text(text)
print("repairs:", repairs)

cfg = T / "cfg.yml"
cfg.write_text("docs:\n  framework: mkdocs\nlint:\n  tier1: default\n")
r = subprocess.run(
    [".venv/bin/python", "scripts/lint/lint_runner.py",
     "--config", str(cfg), "--paths", str(page), "--json"],
    capture_output=True, text=True,
)
out = json.loads(r.stdout)
ce = [x for x in out["results"] if x["rule"] == "citation_exists"]
print("citation_exists:", json.dumps(ce, indent=2))
PY
```

Expected: `repairs` shows one pair, and `citation_exists` reports `"ok": true`.

- [ ] **Open the PR** against `main` using `--body-file` (never a heredoc containing patterns `block-destructive.sh` scans for).

## Notes for the executor

- **Do not add repo-root guidance to `agents/page-author.md` as part of this plan.** The spec scopes the prompt as explicitly unchanged. It remains available as a separate change, and bundling it would make it impossible to tell which half fixed anything.
- **Do not touch `internal_links`.** Markdown link targets are a different rule with a different failure mode, already fixed separately on 2026-08-21.
- **CCE-167** (extraction-layer defects in `_REPO_PATH_RE` / `_relativize`) is out of scope. If a test seems to need those changed, stop and re-read the spec's Scope section rather than widening.
- If the ambiguity tiebreak proves hard to trigger in a real run, that is expected — the measured 2-segment ambiguity rate is 0.6%. It is tested at the unit level and needs no live reproduction.
- The expected full-suite counts (1481 after Task 3, 1483 after Task 4) assume the measured 1459-passed / 4-skipped baseline. Note the arithmetic is **not** simply the new tests: `tests/ci/test_docstring_flag_value_lint.py` parametrizes over every `scripts/*.py`, so creating `scripts/citation_repair.py` in Task 1 adds one case there as well. Verified after Task 1: baseline 1463 collected → 1469 collected (+5 new tests, +1 parametrized). New tests per task: +5, +7, +9, +2, +0.
