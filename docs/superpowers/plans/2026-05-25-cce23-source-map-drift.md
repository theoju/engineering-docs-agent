# doc↔source Map + Drift (M) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build capability M — a deterministic doc↔source map generator, a standalone drift detector, and the orchestrator `source-map` stage that surfaces drifted pages read-only.

**Architecture:** Two stdlib CLIs in `scripts/` (`source_map.py`, `source_drift.py`) plus a thin orchestrator stage. The generator resolves each page's `source_files:` globs against the repo's tracked files into a dual-view artifact `<docs_dir>/.doc-source-map.json` (`map`: source→pages for C's citations; `patterns`: page→globs for drift). Drift matches a PR's changed files against the patterns (catching added/renamed files), and the orchestrator surfaces results in the What's-New entry + notifier digest. Read-only — never mutates pages.

**Tech Stack:** Python 3.9 stdlib + `pyyaml`. Tests: pytest, run with `python3 -m pytest` (bare `pytest`/`python` are NOT on PATH). Spec: `docs/superpowers/specs/2026-05-25-cce23-source-map-drift-design.md`.

---

## File Structure

| File                                      | Responsibility                                                                                                                                                                                                                                                                       |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scripts/source_map.py` (new)             | `_glob_to_regex` (shared translator), `_page_globs` + `_collect_page_patterns` (shared frontmatter scan), `_resolve_tracked_files` (git ls-files + rglob fallback), `generate_source_map` (writes the dual-view artifact + returns ledger), `main()` CLI (`--repo-root`/`--config`). |
| `scripts/source_drift.py` (new)           | `detect_drift(docs_dir, changed_files)` (imports the two shared helpers from `source_map`), `main()` CLI reading a JSON array of changed paths from stdin.                                                                                                                           |
| `scripts/orchestrator_runner.py` (modify) | `compute_source_drift(repo_root, config, prs)` + `_drift_whats_new_lines(drifted)`; wire the `source-map` stage after archive-index regeneration; add the "Pages to review" block to the What's-New entry and `source_drift` to the digest.                                          |
| `tests/orchestrator/test_*.py` (new)      | Fixture-driven tests (arbitrary-host trees built inline in `tmp_path`), mirroring `tests/orchestrator/test_archive_indexes.py`.                                                                                                                                                      |

**Reused existing code:** `archive_indexes.parse_frontmatter(p)` (splits on `---`, `yaml.safe_load(parts[1])`); `state_io.load_config_validated(path)` → raises `ConfigError`; the orchestrator already exposes each PR's change set as `pr["files"]` and the What's-New entry at `orchestrator_runner.py:841-857`, digest at `:881-894`.

**Boundaries (constraints, not tasks):** stdlib + `pyyaml` only; NO `scripts/contracts.py` dataclass and NO `agents/schemas/*.json` (these CLIs are deterministic, not LLM-dispatched); NO `templates/config.schema.json` change (`source_files:` is page frontmatter). Every step degrades cleanly when a convention is absent.

---

## Task 1: Glob → regex translator (`_glob_to_regex`) — model: haiku

**Files:**

- Create: `scripts/source_map.py`
- Test: `tests/orchestrator/test_glob_to_regex.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_glob_to_regex.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from source_map import _glob_to_regex  # noqa: E402


def _m(glob: str, path: str) -> bool:
    return _glob_to_regex(glob).fullmatch(path) is not None


def test_star_is_single_segment():
    assert _m("scripts/*.py", "scripts/a.py")
    assert not _m("scripts/*.py", "scripts/sub/a.py")


def test_double_star_slash_spans_segments():
    assert _m("scripts/**/*.py", "scripts/a.py")
    assert _m("scripts/**/*.py", "scripts/sub/deep/a.py")
    assert _m("**/test_*.py", "test_x.py")
    assert _m("**/test_*.py", "a/b/test_x.py")


def test_trailing_double_star_matches_subtree():
    assert _m("src/auth/**", "src/auth/x.py")
    assert _m("src/auth/**", "src/auth/a/b.py")


def test_question_mark_is_one_non_slash():
    assert _m("a?.py", "ab.py")
    assert not _m("a?.py", "a/.py")


def test_literals_are_escaped():
    assert _m("a.b", "a.b")
    assert not _m("a.b", "axb")
    assert _m("scripts/orchestrator_runner.py", "scripts/orchestrator_runner.py")
    assert not _m("scripts/orchestrator_runner.py", "scripts/orchestrator_runnerXpy")


def test_no_partial_match():
    assert not _m("scripts/*.py", "x/scripts/a.py")
    assert not _m("scripts/*.py", "scripts/a.py.bak")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_glob_to_regex.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'source_map'` (or ImportError for `_glob_to_regex`).

- [ ] **Step 3: Write minimal implementation**

Create `scripts/source_map.py`:

```python
"""doc↔source map generator (capability M).

Resolves each site page's `source_files:` globs against the repo's tracked
files into a dual-view artifact. `_glob_to_regex` and `_collect_page_patterns`
are shared with source_drift.py (imported there).
"""

from __future__ import annotations

import re
from pathlib import Path


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a POSIX path glob to an anchored regex (use `.fullmatch`).

    `**/` matches zero or more path segments (incl. none); `**` matches
    anything including `/`; `*` matches a run of non-`/`; `?` matches one
    non-`/`; every other character is escaped. Python 3.9's fnmatch /
    PurePath.match mishandle `**`, hence this explicit translator.
    """
    i, n = 0, len(glob)
    parts: list[str] = []
    while i < n:
        if glob[i : i + 3] == "**/":
            parts.append("(?:.*/)?")
            i += 3
        elif glob[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif glob[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(parts))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_glob_to_regex.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_map.py tests/orchestrator/test_glob_to_regex.py
git commit -m "$(cat <<'EOF'
feat(CCE-23): _glob_to_regex — stdlib glob translator for source map (M)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Frontmatter scan helpers (`_page_globs`, `_collect_page_patterns`) — model: haiku

**Files:**

- Modify: `scripts/source_map.py`
- Test: `tests/orchestrator/test_collect_page_patterns.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_collect_page_patterns.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from source_map import _collect_page_patterns, _page_globs  # noqa: E402


def _page(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_collects_list_valued_source_files(tmp_path):
    docs = tmp_path / "site-src"
    _page(docs / "architecture/auth.md",
          "---\nsource_files:\n  - scripts/auth/**/*.py\n  - scripts/login.py\n---\n# Auth\n")
    _page(docs / "operations/index.md", "---\ntitle: Ops\n---\n# Ops\n")  # opts out
    patterns = _collect_page_patterns(docs)
    assert patterns == {"architecture/auth.md": ["scripts/auth/**/*.py", "scripts/login.py"]}


def test_missing_docs_dir_returns_empty(tmp_path):
    assert _collect_page_patterns(tmp_path / "nope") == {}


def test_page_globs_reports_skip_reasons(tmp_path):
    bad = _page(tmp_path / "a.md", "---\nsource_files: not-a-list\n---\n# A\n")
    globs, reason = _page_globs(bad)
    assert globs == [] and reason == "source_files is not a list"

    malformed = _page(tmp_path / "b.md", "---\n: : bad yaml :\n---\n# B\n")
    globs2, reason2 = _page_globs(malformed)
    assert globs2 == [] and reason2 == "malformed frontmatter"

    opted_out = _page(tmp_path / "c.md", "---\ntitle: C\n---\n# C\n")
    assert _page_globs(opted_out) == ([], None)


def test_non_string_glob_entries_are_dropped(tmp_path):
    p = _page(tmp_path / "d.md", "---\nsource_files:\n  - scripts/a.py\n  - 42\n  - ''\n---\n# D\n")
    globs, reason = _page_globs(p)
    assert globs == ["scripts/a.py"] and reason is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_collect_page_patterns.py -v`
Expected: FAIL — ImportError for `_collect_page_patterns` / `_page_globs`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/source_map.py` (add imports `import sys`, `import yaml` at top; `parse_frontmatter` is reused from `archive_indexes`):

```python
import yaml

# archive_indexes lives alongside this module; reuse its frontmatter parser.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_indexes import parse_frontmatter  # noqa: E402


def _page_globs(md: Path) -> tuple[list[str], str | None]:
    """Return (globs, skip_reason) for one page. globs is the list of string
    entries in `source_files:` (empty if the page opts out); skip_reason is set
    for malformed frontmatter or a non-list source_files, else None. Never raises.
    """
    try:
        fm = parse_frontmatter(md)
    except yaml.YAMLError:
        return [], "malformed frontmatter"
    sf = fm.get("source_files")
    if sf is None:
        return [], None
    if not isinstance(sf, list):
        return [], "source_files is not a list"
    return [x for x in sf if isinstance(x, str) and x], None


def _collect_page_patterns(docs_dir: Path) -> dict[str, list[str]]:
    """Map each opted-in page (POSIX path relative to docs_dir) to its
    source_files globs. Pages that opt out or are malformed are omitted.
    """
    out: dict[str, list[str]] = {}
    if not docs_dir.is_dir():
        return out
    for md in sorted(docs_dir.rglob("*.md")):
        globs, _reason = _page_globs(md)
        if globs:
            out[md.relative_to(docs_dir).as_posix()] = globs
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_collect_page_patterns.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_map.py tests/orchestrator/test_collect_page_patterns.py
git commit -m "$(cat <<'EOF'
feat(CCE-23): source_files frontmatter scan helpers for source map (M)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Map generator (`_resolve_tracked_files`, `generate_source_map`, CLI) — model: sonnet

**Files:**

- Modify: `scripts/source_map.py`
- Test: `tests/orchestrator/test_source_map.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_source_map.py
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import source_map  # noqa: E402

SCRIPT = _ROOT / "scripts" / "source_map.py"

_CONFIG = """\
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: index.md, title: Home }
"""


def _make_host(tmp_path: Path) -> Path:
    # arbitrary host: a real tracked source tree + a page mapping it
    (tmp_path / "scripts/auth").mkdir(parents=True)
    (tmp_path / "scripts/auth/session.py").write_text("x = 1\n")
    (tmp_path / "scripts/auth/token.py").write_text("y = 2\n")
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_generate_writes_dual_view_artifact(tmp_path):
    host = _make_host(tmp_path)
    ledger = source_map.generate_source_map(host, "docs/site-src")
    artifact = json.loads((host / "docs/site-src/.doc-source-map.json").read_text())
    assert artifact["version"] == 1
    assert artifact["map"] == {
        "scripts/auth/session.py": ["architecture/auth.md"],
        "scripts/auth/token.py": ["architecture/auth.md"],
    }
    assert artifact["patterns"] == {"architecture/auth.md": ["scripts/auth/**/*.py"]}
    assert ledger["written"] == ["docs/site-src/.doc-source-map.json"]
    assert ledger["mapped_sources"] == 2


def test_skip_clean_when_no_source_files(tmp_path):
    docs = tmp_path / "docs/site-src"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("---\ntitle: Home\n---\n# Home\n")
    ledger = source_map.generate_source_map(tmp_path, "docs/site-src")
    assert ledger["written"] == []
    assert not (docs / ".doc-source-map.json").exists()


def test_malformed_frontmatter_recorded_not_aborted(tmp_path):
    docs = tmp_path / "docs/site-src"
    docs.mkdir(parents=True)
    (docs / "bad.md").write_text("---\nsource_files: not-a-list\n---\n# Bad\n")
    ledger = source_map.generate_source_map(tmp_path, "docs/site-src")
    assert {"page": "bad.md", "reason": "source_files is not a list"} in ledger["skipped"]


def test_non_git_repo_falls_back_to_rglob(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("z = 3\n")
    page = tmp_path / "docs/site-src/api.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - src/*.py\n---\n# API\n")
    ledger = source_map.generate_source_map(tmp_path, "docs/site-src")  # not a git repo
    artifact = json.loads((tmp_path / "docs/site-src/.doc-source-map.json").read_text())
    assert artifact["map"] == {"src/app.py": ["api.md"]}


def test_cli_reads_config_and_prints_ledger(tmp_path):
    host = _make_host(tmp_path)
    (host / "config.yml").write_text(_CONFIG)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(host), "--config", str(host / "config.yml")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "error" not in proc.stderr.lower()
    ledger = json.loads(proc.stdout)
    assert ledger["written"] == ["docs/site-src/.doc-source-map.json"]


def test_cli_invalid_config_exits_1_no_traceback(tmp_path):
    (tmp_path / "config.yml").write_text(": bad: yaml: {{{\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--config", str(tmp_path / "config.yml")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()
    assert "Traceback" not in proc.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_source_map.py -v`
Expected: FAIL — `AttributeError: module 'source_map' has no attribute 'generate_source_map'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/source_map.py` (add `import argparse`, `import json`, `import subprocess` to the top imports):

```python
import argparse
import json
import subprocess

_SKIP_DIRS = {".git", ".venv", "node_modules", "site", "__pycache__"}


def _resolve_tracked_files(repo_root: Path) -> list[str]:
    """Repo-relative POSIX paths of candidate source files. Prefers
    `git ls-files`; falls back to a filtered rglob when not a git repo.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True, text=True, check=True,
        )
        files = [ln for ln in out.stdout.splitlines() if ln]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    files = []
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo_root)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def generate_source_map(repo_root: Path, docs_dir_rel: str) -> dict:
    """Write <docs_dir>/.doc-source-map.json (dual view) and return a ledger:
    {"written": [...], "pages_scanned": N, "mapped_sources": M, "skipped": [...]}.
    Skips writing (clean) when no page declares source_files.
    """
    docs_dir = repo_root / docs_dir_rel
    pages = sorted(docs_dir.rglob("*.md")) if docs_dir.is_dir() else []
    patterns: dict[str, list[str]] = {}
    skipped: list[dict] = []
    for md in pages:
        globs, reason = _page_globs(md)
        page = md.relative_to(docs_dir).as_posix()
        if reason:
            skipped.append({"page": page, "reason": reason})
        elif globs:
            patterns[page] = globs

    ledger = {"written": [], "pages_scanned": len(pages),
              "mapped_sources": 0, "skipped": skipped}
    if not patterns:
        return ledger

    tracked = _resolve_tracked_files(repo_root)
    inverse: dict[str, list[str]] = {}
    for page in sorted(patterns):
        regexes = [_glob_to_regex(g) for g in patterns[page]]
        for f in tracked:
            if any(r.fullmatch(f) for r in regexes):
                inverse.setdefault(f, [])
                if page not in inverse[f]:
                    inverse[f].append(page)

    artifact = {
        "version": 1,
        "_generated": "auto-generated by engineering-docs-agent; do not edit",
        "map": {k: sorted(inverse[k]) for k in sorted(inverse)},
        "patterns": {k: patterns[k] for k in sorted(patterns)},
    }
    out_rel = f"{docs_dir_rel.rstrip('/')}/.doc-source-map.json"
    (repo_root / out_rel).write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    ledger["written"] = [out_rel]
    ledger["mapped_sources"] = len(inverse)
    return ledger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the doc↔source map.")
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    args = ap.parse_args(argv)
    from state_io import ConfigError, load_config_validated  # scripts/ already on path
    try:
        config = load_config_validated(args.config)
    except (ConfigError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    docs_dir = (config.get("site") or {}).get("docs_dir")
    if not docs_dir:
        print(json.dumps({"written": [], "pages_scanned": 0, "mapped_sources": 0, "skipped": []}, indent=2))
        return 0
    print(json.dumps(generate_source_map(args.repo_root, docs_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_source_map.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_map.py tests/orchestrator/test_source_map.py
git commit -m "$(cat <<'EOF'
feat(CCE-23): source_map generator — dual-view .doc-source-map.json + CLI (M)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Drift detector (`detect_drift` + stdin CLI) — model: sonnet

**Files:**

- Create: `scripts/source_drift.py`
- Test: `tests/orchestrator/test_source_drift.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_source_drift.py
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))
import source_drift  # noqa: E402

SCRIPT = _ROOT / "scripts" / "source_drift.py"

_CONFIG = """\
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: "https://x", build_workflow: "ci.yml", url_map_rule: "strip-ext" }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: home, path: index.md, title: Home }
"""


def _host(tmp_path: Path) -> Path:
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    return tmp_path


def test_modified_mapped_file_drifts_its_page(tmp_path):
    host = _host(tmp_path)
    result = source_drift.detect_drift(host / "docs/site-src", ["scripts/auth/session.py"])
    assert result == {
        "drifted": [{"page": "architecture/auth.md", "changed_sources": ["scripts/auth/session.py"]}],
        "changed_files_seen": 1,
    }


def test_newly_added_file_matching_glob_drifts(tmp_path):
    # The added file need not exist on disk — drift matches patterns, not the map.
    host = _host(tmp_path)
    result = source_drift.detect_drift(host / "docs/site-src", ["scripts/auth/brand_new.py"])
    assert result["drifted"] == [
        {"page": "architecture/auth.md", "changed_sources": ["scripts/auth/brand_new.py"]}
    ]


def test_unrelated_change_is_no_op(tmp_path):
    host = _host(tmp_path)
    result = source_drift.detect_drift(host / "docs/site-src", ["README.md", "scripts/other/x.py"])
    assert result == {"drifted": [], "changed_files_seen": 2}


def test_missing_docs_dir_no_op(tmp_path):
    result = source_drift.detect_drift(tmp_path / "nope", ["scripts/auth/a.py"])
    assert result == {"drifted": [], "changed_files_seen": 1}


def test_cli_reads_changed_files_from_stdin(tmp_path):
    host = _host(tmp_path)
    (host / "config.yml").write_text(_CONFIG)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(host), "--config", str(host / "config.yml")],
        input=json.dumps(["scripts/auth/session.py"]),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["drifted"][0]["page"] == "architecture/auth.md"


def test_cli_empty_stdin_is_no_op(tmp_path):
    host = _host(tmp_path)
    (host / "config.yml").write_text(_CONFIG)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(host), "--config", str(host / "config.yml")],
        input="", capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"drifted": [], "changed_files_seen": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_source_drift.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'source_drift'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/source_drift.py`:

```python
"""doc↔source drift detector (capability M).

Given a set of changed files, reports which site pages declare a `source_files:`
glob that matches one of them. Read-only. Shares pattern collection + glob
translation with source_map.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_map import _collect_page_patterns, _glob_to_regex  # noqa: E402


def detect_drift(docs_dir: Path, changed_files: list[str]) -> dict:
    """Return {"drifted": [{"page", "changed_sources"}], "changed_files_seen"}.
    A page drifts when any of its source_files globs matches a changed file.
    """
    patterns = _collect_page_patterns(docs_dir)
    drifted: list[dict] = []
    for page in sorted(patterns):
        regexes = [_glob_to_regex(g) for g in patterns[page]]
        matched = [f for f in changed_files if any(r.fullmatch(f) for r in regexes)]
        if matched:
            drifted.append({"page": page, "changed_sources": sorted(matched)})
    return {"drifted": drifted, "changed_files_seen": len(changed_files)}


def _read_changed_from_stdin() -> list[str]:
    raw = sys.stdin.read()
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, str)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect doc↔source drift.")
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    args = ap.parse_args(argv)
    from state_io import ConfigError, load_config_validated
    try:
        config = load_config_validated(args.config)
    except (ConfigError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    changed = _read_changed_from_stdin()
    docs_dir = (config.get("site") or {}).get("docs_dir")
    if not docs_dir:
        print(json.dumps({"drifted": [], "changed_files_seen": len(changed)}, indent=2))
        return 0
    print(json.dumps(detect_drift(args.repo_root / docs_dir, changed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_source_drift.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/source_drift.py tests/orchestrator/test_source_drift.py
git commit -m "$(cat <<'EOF'
feat(CCE-23): source_drift — pattern-matched drift detector + stdin CLI (M)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Orchestrator `source-map` stage — model: sonnet

**Files:**

- Modify: `scripts/orchestrator_runner.py` (add two functions near the other module-level helpers; wire into `run()` after the archive-index loop at `:797-806`; extend the What's-New block at `:841-857` and the digest at `:881-894`)
- Test: `tests/orchestrator/test_source_map_stage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_source_map_stage.py
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as orun  # noqa: E402


def test_compute_source_drift_flags_changed_page(tmp_path):
    page = tmp_path / "docs/site-src/architecture/auth.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - scripts/auth/**/*.py\n---\n# Auth\n")
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 1, "files": [{"path": "scripts/auth/session.py"}, {"path": "README.md"}]}]
    drifted = orun.compute_source_drift(tmp_path, config, prs)
    assert drifted == [
        {"page": "architecture/auth.md", "changed_sources": ["scripts/auth/session.py"]}
    ]


def test_compute_source_drift_no_site_is_empty(tmp_path):
    assert orun.compute_source_drift(tmp_path, {}, []) == []


def test_compute_source_drift_handles_string_file_entries(tmp_path):
    page = tmp_path / "docs/site-src/a.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nsource_files:\n  - src/*.py\n---\n# A\n")
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 2, "files": ["src/x.py"]}]  # plain-string file entries
    assert orun.compute_source_drift(tmp_path, config, prs) == [
        {"page": "a.md", "changed_sources": ["src/x.py"]}
    ]


def test_drift_whats_new_lines():
    assert orun._drift_whats_new_lines([]) == []
    lines = orun._drift_whats_new_lines(
        [{"page": "a.md", "changed_sources": ["x.py", "y.py"]}]
    )
    assert lines[0] == "### Pages to review (source drift)"
    assert "- a.md — changed: x.py, y.py" in lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_source_map_stage.py -v`
Expected: FAIL — `AttributeError: module 'orchestrator_runner' has no attribute 'compute_source_drift'`.

- [ ] **Step 3: Write minimal implementation**

(a) Add these two module-level functions to `scripts/orchestrator_runner.py` (e.g. just above `def run(`):

```python
def compute_source_drift(repo_root: Path, config: dict, prs: list[dict]) -> list[dict]:
    """Run the source-map generator and return drifted pages for this batch.
    Changed files = union of every PR's files[] (dict-with-path or plain string).
    Returns [] when no site/docs_dir is configured.
    """
    docs_dir = (config.get("site") or {}).get("docs_dir")
    if not docs_dir:
        return []
    import source_map
    import source_drift

    source_map.generate_source_map(repo_root, docs_dir)
    changed = sorted({
        (f["path"] if isinstance(f, dict) else f)
        for pr in prs
        for f in (pr.get("files") or [])
        if (f.get("path") if isinstance(f, dict) else f)
    })
    return source_drift.detect_drift(repo_root / docs_dir, changed)["drifted"]


def _drift_whats_new_lines(drifted_pages: list[dict]) -> list[str]:
    """What's-New block for drifted pages (empty list → no block)."""
    if not drifted_pages:
        return []
    lines = ["### Pages to review (source drift)"]
    for d in drifted_pages:
        lines.append(f"- {d['page']} — changed: {', '.join(d['changed_sources'])}")
    return lines
```

(b) Wire the stage into `run()` immediately after the archive-index regeneration loop (after `orchestrator_runner.py:806`). Best-effort — a failure must never block the docs PR:

```python
    # Source map + drift (M) — best-effort, read-only
    try:
        drifted_pages = compute_source_drift(repo_root, config, prs)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        drifted_pages = []
        add_partial(state, f"source_map_failed: {exc}", info_only=True)
    state["current_run"]["source_drift"] = drifted_pages
```

(c) Extend the What's-New entry: in the `if prs:` block, after the `gaps_flagged` loop (after `orchestrator_runner.py:854`, before the `entry = "\n".join(...)` line), add:

```python
        entry_lines.extend(_drift_whats_new_lines(drifted_pages))
```

(d) Extend the digest dict (the literal starting at `orchestrator_runner.py:882`) with one key:

```python
        "source_drift": drifted_pages,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_source_map_stage.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite (no regressions in the orchestrator run path)**

Run: `python3 -m pytest -q`
Expected: PASS — all prior tests plus the new M tests green.

- [ ] **Step 6: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_source_map_stage.py
git commit -m "$(cat <<'EOF'
feat(CCE-23): orchestrator source-map stage — surface drift in What's-New + digest (M)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Execution coda (after Task 5)

**A. Final whole-branch review.** Dispatch one reviewer (opus) over `feat/CCE-23-structured-docs-site..HEAD`: confirm the dual-view artifact, glob correctness (esp. `**`), generic-first degradation (no `source_files`, non-git repo, malformed frontmatter), read-only drift, and clean orchestrator wiring. Confirm the boundaries held: no `contracts.py`/`schemas` entry, no `config.schema.json` change. Address any Critical/Important findings (fresh implementer + re-review) before proceeding.

**B. EXTRA dedicated validation pass (opus).** A second, independent spec-compliance + quality validation against `docs/superpowers/specs/2026-05-25-cce23-source-map-drift-design.md` — every design unit and locked decision A–D mapped to code with evidence, plus an independent full-suite run (`python3 -m pytest`). Verdict must be READY TO SHIP before C.

**C. `/ship`** with the full gate (verify + code review). PR base **`feat/CCE-23-structured-docs-site`** (stacked, NOT main). Jira **CCE-23 comment-only, no transition**. Expect a small What's-New / orchestrator-stage reconciliation against D (#25) at eventual merge — note it in the PR body.

---

## Self-Review (plan vs spec)

- **Unit 1 (generator)** → Task 3 (`generate_source_map`, dual-view artifact, `git ls-files`+rglob fallback, skip-clean, malformed-skip ledger, CLI). ✓
- **Unit 2 (drift)** → Task 4 (`detect_drift`, stdin JSON array, shared-helper import, output shape). ✓
- **Unit 3 (`_glob_to_regex`)** → Task 1; defined in `source_map.py`, imported by `source_drift.py` (Task 4). ✓
- **Unit 4 (orchestrator stage)** → Task 5 (`compute_source_drift`, What's-New block, digest, run-state, best-effort, read-only, slotted after archive-indexes). ✓
- **Unit 5 (`_collect_page_patterns`)** → Task 2; defined in `source_map.py`, imported by drift. Implementation note: a sibling `_page_globs` returns `(globs, reason)` so the generator's ledger can report skips while the public helper stays `{page: [globs]}` — a refinement of the spec's signature sketch, not a contradiction. ✓
- **Unit 6 (boundaries)** → honored throughout: no `contracts.py`/schema entry, no `config.schema.json` change; degradation tested in Tasks 2–5. ✓
- **Decisions A–D** → A dual-view artifact (Task 3); B globs via `_glob_to_regex`, no third-party lib (Tasks 1/3/4); C read-only surfacing (Task 5); D deterministic CLIs (no contract/schema). ✓
- **Placeholder scan:** none — every code step has complete code. ✓
- **Type consistency:** `generate_source_map(repo_root, docs_dir_rel: str)`, `detect_drift(docs_dir: Path, changed_files)`, `compute_source_drift(repo_root, config, prs)`, drift dict `{page, changed_sources}` — consistent across Tasks 3/4/5. ✓
