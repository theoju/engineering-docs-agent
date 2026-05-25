# Decision Archive (D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate Decision-Archive index pages (`docs/site-src/archive/<category>.md`) from the `archive-index` section's configured `sources`, grouped by ISO month with title/status/summary and hybrid source links, building on capability S.

**Architecture:** Rewrite `scripts/archive_indexes.py` as pure parse/render functions plus one filesystem entry point `generate_archive`, mirroring `scripts/site_structure.py`. Source links resolve via a hybrid base (explicit config → derived `github.com/.../blob/<ref>/` via the existing `detect_repo` → plain text). Unlike the scaffold engine, generated pages are always overwritten (they carry an auto-generated banner).

**Tech Stack:** Python stdlib + `pyyaml` (agent runtime); `mkdocs build --strict` as the build gate (doc-build dep, skipped when mkdocs absent). pytest, `--import-mode=importlib`, fixture-driven TDD.

**Branch:** `feat/CCE-23-decision-archive`, stacked on `feat/CCE-23-structured-docs-site` (PR #24). D ships as its own PR (#25), retargeted to `main` after #24 merges.

**Spec:** `docs/superpowers/specs/2026-05-25-cce23-decision-archive-design.md`.

---

## File Structure

| File                                         | Responsibility                                                    | Action                          |
| -------------------------------------------- | ----------------------------------------------------------------- | ------------------------------- |
| `scripts/archive_indexes.py`                 | Pure parse/render + `generate_archive` (I/O) + CLI                | **Rewrite** (replaces the seed) |
| `templates/config.schema.json`               | Add optional `repo_url_base` to section schema                    | Modify                          |
| `scripts/state_io.py`                        | `_validate_site_sections`: reject absolute/`..` `sources`         | Modify                          |
| `tests/fixtures/archive_indexes/`            | External-style `specs/` + `plans/` with dated `.md` + noise       | **Replace**                     |
| `tests/orchestrator/test_archive_indexes.py` | Seed test for the old per-subdir model                            | **Delete**                      |
| `tests/site/test_archive_parse.py`           | `parse_frontmatter`, `parse_title_and_summary`, `collect_entries` | Create                          |
| `tests/site/test_archive_render.py`          | `render_archive_page`                                             | Create                          |
| `tests/site/test_archive_resolve.py`         | `resolve_repo_url_base`                                           | Create                          |
| `tests/site/test_archive_generate.py`        | `generate_archive` integration                                    | Create                          |
| `tests/site/test_archive_cli.py`             | `main()` CLI                                                      | Create                          |
| `tests/site/test_archive_build_smoke.py`     | S-scaffold + D-generate → `mkdocs build --strict`                 | Create                          |
| `tests/schemas/test_config_schema.py`        | `repo_url_base` accepted                                          | Modify                          |
| `tests/state_io/test_site_validation.py`     | sources guard                                                     | Modify                          |

**Conventions to follow (from the existing codebase):**

- Tests put `scripts/` on the path: `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))` then `import archive_indexes  # noqa: E402`.
- CLI tests shell `sys.executable` against the script (see `tests/site/test_setup_scaffold_cli.py`).
- Commit trailer is exactly: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
- Never use `--amend`, `--no-verify`, or force-push. Commit per task.

---

### Task 1: Housekeeping — new fixtures, remove seed, reset module

The seed `archive_indexes.py` and its test model the wrong shape (source files already inside `archive_root/<subdir>/`, per-subdir `index.md`). Clear them so the rewrite starts clean. The seed is not wired into any orchestrator stage, so removing it is safe.

**Files:**

- Delete: `tests/orchestrator/test_archive_indexes.py`
- Delete: `tests/fixtures/archive_indexes/archive/` (old subtree)
- Create: `tests/fixtures/archive_indexes/specs/2026-05-24-structured-docs-site.md`
- Create: `tests/fixtures/archive_indexes/specs/2026-05-20-schema-enforcement.md`
- Create: `tests/fixtures/archive_indexes/specs/notes.md` (non-dated — must be excluded)
- Create: `tests/fixtures/archive_indexes/specs/2026-05-19-run.txt` (non-md — must be excluded)
- Create: `tests/fixtures/archive_indexes/plans/2026-05-25-decision-archive.md`
- Reset: `scripts/archive_indexes.py` to a docstring-only stub

- [ ] **Step 1: Remove the seed test and old fixtures**

```bash
git rm tests/orchestrator/test_archive_indexes.py
git rm -r tests/fixtures/archive_indexes/archive
```

- [ ] **Step 2: Create the new fixtures**

`tests/fixtures/archive_indexes/specs/2026-05-24-structured-docs-site.md`:

```markdown
---
status: draft
---

# Structured Docs Site

Turn the agent into a structured-site generator with a configurable IA.
```

`tests/fixtures/archive_indexes/specs/2026-05-20-schema-enforcement.md` (no frontmatter → status must render `—`):

```markdown
# Schema Enforcement

Validate config and agent outputs against JSON schemas at the boundaries.
```

`tests/fixtures/archive_indexes/specs/notes.md` (no date prefix → excluded):

```markdown
# Scratch notes

Not a dated decision doc.
```

`tests/fixtures/archive_indexes/specs/2026-05-19-run.txt` (not `.md` → excluded):

```text
raw run artifact, not markdown
```

`tests/fixtures/archive_indexes/plans/2026-05-25-decision-archive.md`:

```markdown
---
status: draft
---

# Decision Archive Plan

Generate month-grouped archive index pages from configured sources.
```

- [ ] **Step 3: Reset the module to a stub**

Overwrite `scripts/archive_indexes.py` with:

```python
"""Generate Decision Archive index pages from configured source dirs.

Reads the `archive-index` section's `sources` directories and, for each one,
emits a `<docs_dir>/<archive-path>/<category>.md` index page: date-prefixed
`.md` files grouped by ISO month (newest first), each row carrying title,
status (YAML frontmatter), and a one-line summary, linking back to source via
a resolved repo URL base (or plain text when none resolves).

Pure functions parse and render; `generate_archive` is the only function that
writes files. Unlike the scaffold engine, generated pages are *overwritten*
every run (they carry an auto-generated banner).
"""

from __future__ import annotations
```

- [ ] **Step 4: Run the full suite to confirm green**

Run: `pytest -q`
Expected: PASS (no archive tests reference the module now; the seed test is gone).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(CCE-23): reset archive_indexes seed + new archive fixtures

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Frontmatter + title/summary parsers

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_parse.py`

- [ ] **Step 1: Write the failing tests**

`tests/site/test_archive_parse.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def test_parse_frontmatter_reads_status():
    text = "---\nstatus: accepted\n---\n\n# Foo\n"
    assert archive_indexes.parse_frontmatter(text).get("status") == "accepted"


def test_parse_frontmatter_absent_returns_empty():
    assert archive_indexes.parse_frontmatter("# No frontmatter\n") == {}


def test_parse_frontmatter_malformed_returns_empty():
    # Unparseable YAML in the block must degrade to {}, not raise.
    text = "---\nstatus: : :\n  - [bad\n---\n\n# Foo\n"
    assert archive_indexes.parse_frontmatter(text) == {}


def test_parse_title_and_summary():
    text = "---\nstatus: draft\n---\n\n# My Title\n\nFirst paragraph here.\n"
    title, summary = archive_indexes.parse_title_and_summary(text)
    assert title == "My Title"
    assert summary == "First paragraph here."


def test_parse_title_and_summary_skips_subheadings():
    text = "# Title\n\n## Section\n\nReal summary line.\n"
    title, summary = archive_indexes.parse_title_and_summary(text)
    assert title == "Title"
    assert summary == "Real summary line."
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_parse.py -q`
Expected: FAIL with `AttributeError: module 'archive_indexes' has no attribute 'parse_frontmatter'`.

- [ ] **Step 3: Implement**

Add to the top imports of `scripts/archive_indexes.py` (after `from __future__ import annotations`):

```python
import yaml
```

Append:

```python
def parse_frontmatter(text: str) -> dict:
    """Return the YAML frontmatter block as a dict ({} if absent/malformed)."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_title_and_summary(text: str) -> tuple[str, str]:
    """Title from the first '# ' heading; summary from the first non-blank,
    non-heading line after it."""
    title = ""
    summary = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not title and stripped.startswith("# "):
            title = stripped[2:].strip()
            continue
        if title and stripped and not stripped.startswith("#"):
            summary = stripped
            break
    return title, summary
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_parse.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_parse.py
git commit -m "feat(CCE-23): archive frontmatter + title/summary parsers

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Entry model + dated-`.md` collection

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_parse.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/site/test_archive_parse.py`:

```python
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"


def test_collect_entries_filters_and_sorts():
    entries = archive_indexes.collect_entries(_FIXTURES / "specs", _FIXTURES)
    names = [e.filename for e in entries]
    # only date-prefixed .md, newest first; notes.md and the .txt are excluded
    assert names == [
        "2026-05-24-structured-docs-site.md",
        "2026-05-20-schema-enforcement.md",
    ]


def test_collect_entries_fields():
    entries = archive_indexes.collect_entries(_FIXTURES / "specs", _FIXTURES)
    by_name = {e.filename: e for e in entries}
    a = by_name["2026-05-24-structured-docs-site.md"]
    assert a.title == "Structured Docs Site"
    assert a.status == "draft"
    assert a.month == "2026-05"
    assert a.source_rel_path == "specs/2026-05-24-structured-docs-site.md"
    assert a.summary.startswith("Turn the agent")
    # no frontmatter status -> "—"
    assert by_name["2026-05-20-schema-enforcement.md"].status == "—"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_parse.py -q`
Expected: FAIL with `AttributeError: module 'archive_indexes' has no attribute 'collect_entries'`.

- [ ] **Step 3: Implement**

Add to the top imports of `scripts/archive_indexes.py`:

```python
import re
from dataclasses import dataclass
from pathlib import Path
```

Append (place the constant + dataclass above the existing parsers if you prefer; order does not matter for correctness):

```python
DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-\d{2}-")


@dataclass(frozen=True)
class Entry:
    filename: str
    title: str
    status: str
    summary: str
    month: str  # "YYYY-MM"
    source_rel_path: str  # POSIX, relative to repo_root


def collect_entries(source_dir: Path, repo_root: Path) -> list[Entry]:
    """Date-prefixed *.md in source_dir -> Entry list, newest filename first."""
    entries: list[Entry] = []
    for path in sorted(source_dir.glob("*.md")):
        m = DATE_PREFIX.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8")
        title, summary = parse_title_and_summary(text)
        status = str(parse_frontmatter(text).get("status", "") or "").strip()
        entries.append(
            Entry(
                filename=path.name,
                title=title or path.name,
                status=status or "—",
                summary=summary,
                month=f"{m.group(1)}-{m.group(2)}",
                source_rel_path=path.relative_to(repo_root).as_posix(),
            )
        )
    entries.sort(key=lambda e: e.filename, reverse=True)
    return entries
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_parse.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_parse.py
git commit -m "feat(CCE-23): Entry model + dated-.md collection (DATE_PREFIX filter)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Render an archive page (month-grouped table, hybrid link)

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_render.py`

- [ ] **Step 1: Write the failing tests**

`tests/site/test_archive_render.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def _entry(filename, title="T", status="draft", summary="S", month="2026-05",
           rel="specs/x.md"):
    return archive_indexes.Entry(filename, title, status, summary, month, rel)


def test_render_has_banner_and_month_headers():
    entries = [
        _entry("2026-05-24-a.md", month="2026-05", rel="specs/2026-05-24-a.md"),
        _entry("2026-04-01-b.md", month="2026-04", rel="specs/2026-04-01-b.md"),
    ]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "# Specs archive" in page
    assert "Auto-generated; 2 entries" in page
    assert "Do not edit by hand" in page
    # newest month first
    assert page.index("## 2026-05") < page.index("## 2026-04")
    assert "| Title | Status | Summary |" in page


def test_render_links_when_base_present():
    entries = [_entry("2026-05-24-a.md", title="Alpha",
                      rel="specs/2026-05-24-a.md")]
    page = archive_indexes.render_archive_page(
        "Specs", entries, link_base="https://h/blob/main/"
    )
    assert "[Alpha](https://h/blob/main/specs/2026-05-24-a.md)" in page


def test_render_plain_when_no_base():
    entries = [_entry("2026-05-24-a.md", title="Alpha")]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "| Alpha |" in page
    assert "](" not in page  # no markdown links


def test_render_truncates_and_escapes():
    long = "x" * 200
    entries = [_entry("2026-05-24-a.md", title="A|B", status="d|e",
                      summary=long + " | pipe")]
    page = archive_indexes.render_archive_page("Specs", entries, link_base=None)
    assert "…" in page                 # truncated
    assert "x" * 200 not in page        # not the full 200 chars
    assert "A\\|B" in page              # title pipe escaped
    assert "d\\|e" in page              # status pipe escaped
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_render.py -q`
Expected: FAIL with `AttributeError: module 'archive_indexes' has no attribute 'render_archive_page'`.

- [ ] **Step 3: Implement**

Add near the other module constants in `scripts/archive_indexes.py`:

```python
_SUMMARY_MAX = 120
```

Append:

```python
def render_archive_page(
    label: str, entries: list[Entry], *, link_base: str | None
) -> str:
    """Render one archive index page: banner + month-grouped tables."""
    lines = [f"# {label} archive", ""]
    lines.append(
        f"_Auto-generated; {len(entries)} entries. "
        "Do not edit by hand — see `scripts/archive_indexes.py`._"
    )
    lines.append("")
    if not entries:
        lines.append("_No entries yet._")
        lines.append("")
        return "\n".join(lines)

    grouped: dict[str, list[Entry]] = {}
    for e in entries:
        grouped.setdefault(e.month, []).append(e)

    for month in sorted(grouped, reverse=True):
        lines.append(f"## {month}")
        lines.append("")
        lines.append("| Title | Status | Summary |")
        lines.append("|---|---|---|")
        for e in grouped[month]:
            title = e.title.replace("|", "\\|")
            title_cell = (
                f"[{title}]({link_base}{e.source_rel_path})" if link_base else title
            )
            summary = e.summary
            if len(summary) > _SUMMARY_MAX:
                summary = summary[:_SUMMARY_MAX] + "…"
            summary = summary.replace("|", "\\|")
            status = e.status.replace("|", "\\|")
            lines.append(f"| {title_cell} | {status} | {summary} |")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_render.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_render.py
git commit -m "feat(CCE-23): render month-grouped archive page with hybrid links

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Resolve the hybrid repo URL base

Resolution order: explicit override / `section['repo_url_base']` → derived `github.com/<owner>/<name>/blob/<ref>/` (via `detect_repo` + branch) → `None` (plain text). `detect_repo` is reused from `scripts/orchestrator_runner.py`.

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_resolve.py`

- [ ] **Step 1: Write the failing tests**

`tests/site/test_archive_resolve.py`:

```python
from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402


def test_explicit_override_wins_and_normalizes_trailing_slash(tmp_path):
    base = archive_indexes.resolve_repo_url_base(
        tmp_path, {}, override="https://x/blob/main"
    )
    assert base == "https://x/blob/main/"


def test_section_repo_url_base_used(tmp_path):
    section = {"repo_url_base": "https://y/blob/dev/"}
    assert (
        archive_indexes.resolve_repo_url_base(tmp_path, section) == "https://y/blob/dev/"
    )


def test_derived_github_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "o", "name": "n"}
    )
    monkeypatch.setattr(
        archive_indexes.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="feature\n", returncode=0),
    )
    base = archive_indexes.resolve_repo_url_base(tmp_path, {})
    assert base == "https://github.com/o/n/blob/feature/"


def test_unknown_repo_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "unknown", "name": "unknown"}
    )
    assert archive_indexes.resolve_repo_url_base(tmp_path, {}) is None


def test_detached_head_defaults_to_main(monkeypatch, tmp_path):
    monkeypatch.setattr(
        archive_indexes, "detect_repo", lambda r: {"owner": "o", "name": "n"}
    )
    monkeypatch.setattr(
        archive_indexes.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout="HEAD\n", returncode=0),
    )
    assert archive_indexes.resolve_repo_url_base(tmp_path, {}) == (
        "https://github.com/o/n/blob/main/"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_resolve.py -q`
Expected: FAIL with `AttributeError: module 'archive_indexes' has no attribute 'resolve_repo_url_base'` (or on `detect_repo` not yet imported).

- [ ] **Step 3: Implement**

Add to the top imports of `scripts/archive_indexes.py`:

```python
import subprocess
import sys
```

Add immediately below the imports (so `scripts/` is importable whether run as a script or imported):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator_runner import detect_repo  # noqa: E402
```

Append:

```python
def resolve_repo_url_base(
    repo_root: Path, section: dict, *, override: str | None = None
) -> str | None:
    """Base URL that source links hang off, or None for plain text.

    Order: explicit override / section['repo_url_base'] -> derived GitHub blob
    URL (detect_repo + current branch, default 'main') -> None.
    """
    explicit = override or section.get("repo_url_base")
    if explicit:
        base = str(explicit)
        return base if base.endswith("/") else base + "/"
    repo = detect_repo(repo_root)
    if repo.get("owner") == "unknown" or repo.get("name") == "unknown":
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    ref = proc.stdout.strip()
    if proc.returncode != 0 or ref in ("", "HEAD"):
        ref = "main"
    return f"https://github.com/{repo['owner']}/{repo['name']}/blob/{ref}/"
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_resolve.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_resolve.py
git commit -m "feat(CCE-23): hybrid repo-url-base resolution (explicit -> derived -> none)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: `generate_archive` — write pages, skip cleanly, overwrite

Finds the `generator: archive-index` section, resolves the link base once, and per source: skip (record) when the dir is missing or yields no entries, else **overwrite** `<docs_dir>/<archive-path>/<category>.md`. The output dir comes from the section's own `path`, not a hardcoded `archive/`. Returns `{"written": [...], "skipped": [...]}`.

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_generate.py`

- [ ] **Step 1: Write the failing tests**

`tests/site/test_archive_generate.py`:

```python
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import archive_indexes  # noqa: E402

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

SITE = {
    "docs_dir": "docs/site-src",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "archive",
            "path": "archive/",
            "title": "Decision Archive",
            "generator": "archive-index",
            "sources": [
                "docs/superpowers/specs",
                "docs/superpowers/plans",
                "docs/superpowers/measurements",  # absent -> skipped
            ],
        },
    ],
}


def _seed_sources(repo: Path):
    (repo / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", repo / "docs/superpowers/specs")
    shutil.copytree(_FIXTURES / "plans", repo / "docs/superpowers/plans")


def test_generate_writes_present_skips_absent(tmp_path):
    _seed_sources(tmp_path)
    # No git remote in tmp_path -> link_base resolves to None -> plain text.
    result = archive_indexes.generate_archive(tmp_path, SITE)
    assert (tmp_path / "docs/site-src/archive/specs.md").exists()
    assert (tmp_path / "docs/site-src/archive/plans.md").exists()
    assert "docs/site-src/archive/specs.md" in result["written"]
    assert "docs/site-src/archive/plans.md" in result["written"]
    assert "docs/site-src/archive/measurements.md" in result["skipped"]
    assert not (tmp_path / "docs/site-src/archive/measurements.md").exists()
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "Structured Docs Site" in page and "## 2026-05" in page


def test_generate_overwrites_stale_but_leaves_section_index(tmp_path):
    _seed_sources(tmp_path)
    archive_dir = tmp_path / "docs/site-src/archive"
    archive_dir.mkdir(parents=True)
    # S's section landing stub — D must not touch it.
    (archive_dir / "index.md").write_text("# Decision Archive\n\nLanding.\n")
    # a stale generated page — D must overwrite it.
    (archive_dir / "specs.md").write_text("STALE\n")
    archive_indexes.generate_archive(tmp_path, SITE)
    assert (archive_dir / "index.md").read_text() == "# Decision Archive\n\nLanding.\n"
    assert "STALE" not in (archive_dir / "specs.md").read_text()


def test_generate_noop_when_no_archive_section(tmp_path):
    site = {"docs_dir": "docs/site-src", "sections": [
        {"key": "home", "path": "index.md", "title": "Home"}]}
    assert archive_indexes.generate_archive(tmp_path, site) == {
        "written": [], "skipped": []
    }


def test_generate_uses_explicit_repo_url_base(tmp_path):
    _seed_sources(tmp_path)
    archive_indexes.generate_archive(
        tmp_path, SITE, repo_url_base="https://github.com/o/n/blob/main/"
    )
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "https://github.com/o/n/blob/main/docs/superpowers/specs/" in page
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_generate.py -q`
Expected: FAIL with `AttributeError: module 'archive_indexes' has no attribute 'generate_archive'`.

- [ ] **Step 3: Implement**

Append to `scripts/archive_indexes.py`:

```python
def _find_archive_section(site: dict) -> dict | None:
    for s in site.get("sections", []) or []:
        if s.get("generator") == "archive-index":
            return s
    return None


def generate_archive(
    repo_root: Path, site_config: dict, *, repo_url_base: str | None = None
) -> dict:
    """Generate one archive index page per configured source.

    Skips (records) a source whose dir is missing or has no dated .md; never
    emits an empty page. Generated pages are overwritten every run. Returns
    {"written": [...], "skipped": [...]} of repo-relative POSIX page paths.
    """
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []

    section = _find_archive_section(site_config)
    if section is None:
        return {"written": written, "skipped": skipped}
    sources = section.get("sources") or []
    if not sources:
        return {"written": written, "skipped": skipped}

    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")
    section_path = (section.get("path") or "").rstrip("/")
    out_dir = repo_root / docs_dir / section_path
    link_base = resolve_repo_url_base(repo_root, section, override=repo_url_base)

    for source in sources:
        category = Path(source).name
        out_rel = f"{docs_dir}/{section_path}/{category}.md"
        src_dir = repo_root / source
        if not src_dir.is_dir():
            print(f"warning: archive source not found: {source}", file=sys.stderr)
            skipped.append(out_rel)
            continue
        entries = collect_entries(src_dir, repo_root)
        if not entries:
            print(f"warning: no dated .md in source: {source}", file=sys.stderr)
            skipped.append(out_rel)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{category}.md").write_text(
            render_archive_page(category.capitalize(), entries, link_base=link_base),
            encoding="utf-8",
        )
        written.append(out_rel)

    return {"written": written, "skipped": skipped}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_generate.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_generate.py
git commit -m "feat(CCE-23): generate_archive — write/skip/overwrite per source

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: Config validation — `repo_url_base` schema + sources guard

Add `repo_url_base` to the section schema (needed because the section sets `additionalProperties: false`), and reject absolute / `..`-escaping `sources` entries in `_validate_site_sections` (read-safety). **No existence check** — existence is a runtime skip (Task 6).

**Files:**

- Modify: `templates/config.schema.json:108-130` (section `properties`)
- Modify: `scripts/state_io.py:75-108` (`_validate_site_sections`)
- Test: `tests/schemas/test_config_schema.py` (extend)
- Test: `tests/state_io/test_site_validation.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/schemas/test_config_schema.py`:

```python
def test_site_section_repo_url_base_allowed():
    cfg = yaml.safe_load("""
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: {}
sources: { git: { host: github } }
lint: {}
publishing: { base_url: https://x, build_workflow: deploy.yml, url_map_rule: standard }
notifications: {}
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Archive, generator: archive-index,
        sources: [docs/superpowers/specs], repo_url_base: https://h/blob/main/ }
""")
    validate(cfg, SCHEMA)
```

Append to `tests/state_io/test_site_validation.py`:

```python
def test_source_absolute_path_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Archive, generator: archive-index,
        sources: ["/etc/passwd"] }
""",
            )
        )
    assert "source" in str(exc.value).lower()


def test_source_traversal_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        load_config_validated(
            _write(
                tmp_path,
                """
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Archive, generator: archive-index,
        sources: ["../../secrets"] }
""",
            )
        )
    assert "source" in str(exc.value).lower()


def test_relative_sources_pass(tmp_path: Path):
    cfg = load_config_validated(
        _write(
            tmp_path,
            """
site:
  docs_dir: docs/site-src
  sections:
    - { key: archive, path: archive/, title: Archive, generator: archive-index,
        sources: [docs/superpowers/specs, docs/superpowers/plans] }
""",
        )
    )
    assert cfg["site"]["sections"][0]["key"] == "archive"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/schemas/test_config_schema.py tests/state_io/test_site_validation.py -q`
Expected: FAIL on all three new tests. The schema test fails because the section sets `additionalProperties: false`, so `repo_url_base` is rejected until added. The two guard tests fail because no `ConfigError` is raised yet for absolute/`..` sources.

- [ ] **Step 3: Implement the schema change**

In `templates/config.schema.json`, inside the section `properties` object (alongside `sources`), add:

```json
              "repo_url_base": { "type": "string" }
```

- [ ] **Step 4: Implement the sources guard**

In `scripts/state_io.py`, inside `_validate_site_sections`, after the existing per-section path loop (the `for s in sections:` block that ends with the traversal `raise`), add a second loop:

```python
    for s in sections:
        for src in s.get("sources", []) or []:
            sp = str(src)
            if sp.startswith("/") or ".." in PurePosixPath(sp).parts:
                raise ConfigError(
                    f"site.section '{s.get('key')}' source {sp!r} must be a "
                    "relative path inside the repo (no absolute or '..' paths)"
                )
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/schemas/test_config_schema.py tests/state_io/test_site_validation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/config.schema.json scripts/state_io.py tests/schemas/test_config_schema.py tests/state_io/test_site_validation.py
git commit -m "feat(CCE-23): repo_url_base schema + archive sources path-shape guard

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: CLI `main()`

Loads a full `config.yml` via `state_io.load_config_validated` (so the sources guard runs), extracts the `site:` block, calls `generate_archive`, prints JSON. Mirrors `scripts/setup_scaffold.py`.

**Files:**

- Modify: `scripts/archive_indexes.py`
- Test: `tests/site/test_archive_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/site/test_archive_cli.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI = _REPO_ROOT / "scripts" / "archive_indexes.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

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
    - { key: archive, path: archive/, title: Decision Archive,
        generator: archive-index, sources: [docs/superpowers/specs] }
"""


def test_cli_generates_and_reports_json(tmp_path):
    (tmp_path / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", tmp_path / "docs/superpowers/specs")
    cfg = tmp_path / "config.yml"
    cfg.write_text(_CONFIG)

    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path),
         "--config", str(cfg), "--repo-url-base", "https://github.com/o/n/blob/main/"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert "docs/site-src/archive/specs.md" in result["written"]
    page = (tmp_path / "docs/site-src/archive/specs.md").read_text()
    assert "https://github.com/o/n/blob/main/docs/superpowers/specs/" in page


def test_cli_missing_config_errors(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(_CLI), "--repo-root", str(tmp_path),
         "--config", str(tmp_path / "nope.yml")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "error" in proc.stderr.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/site/test_archive_cli.py -q`
Expected: FAIL — `argparse` errors / no `main`, nonzero exit with usage on stderr.

- [ ] **Step 3: Implement**

Add to the top imports of `scripts/archive_indexes.py`:

```python
import argparse
import json
```

Add to the sibling-imports block (next to `from orchestrator_runner import detect_repo`):

```python
from state_io import ConfigError, load_config_validated  # noqa: E402
```

Append:

```python
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument(
        "--config",
        type=Path,
        required=True,
        help="config.yml with a site: block (locates archive sources)",
    )
    ap.add_argument(
        "--repo-url-base",
        default=None,
        help="override base URL for source links (else derived from git)",
    )
    args = ap.parse_args(argv)

    try:
        config = load_config_validated(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    site = config.get("site")
    if not site:
        print("error: config has no site: block", file=sys.stderr)
        return 1

    result = generate_archive(args.repo_root, site, repo_url_base=args.repo_url_base)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/site/test_archive_cli.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/archive_indexes.py tests/site/test_archive_cli.py
git commit -m "feat(CCE-23): archive_indexes CLI (config-driven, JSON report)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: Build-gate smoke — S scaffold + D generate → `mkdocs build --strict`

Proves the full Phase-1 archive path builds: scaffold the site (S), seed a source dir, generate the archive (D), and build under `--strict`. Skipped when `mkdocs` is absent (doc-build dep), matching `tests/site/test_mkdocs_build_smoke.py`.

**Files:**

- Test: `tests/site/test_archive_build_smoke.py`

- [ ] **Step 1: Write the test**

`tests/site/test_archive_build_smoke.py`:

```python
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETUP_CLI = _REPO_ROOT / "scripts" / "setup_scaffold.py"
_ARCHIVE_CLI = _REPO_ROOT / "scripts" / "archive_indexes.py"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "archive_indexes"

pytestmark = pytest.mark.skipif(
    shutil.which("mkdocs") is None, reason="mkdocs not installed (doc-build dep)"
)

_SITE = {
    "docs_dir": "docs/site-src",
    "theme": "material",
    "sections": [
        {"key": "home", "path": "index.md", "title": "Home"},
        {
            "key": "archive",
            "path": "archive/",
            "title": "Decision Archive",
            "generator": "archive-index",
            "sources": ["docs/superpowers/specs"],
        },
    ],
}

_CONFIG = {
    "docs": {
        "framework": "mkdocs",
        "source_dir": "docs",
        "whats_new_file": "docs/site-src/whats-new.md",
        "agent_editable_paths": ["docs/site-src/**"],
        "lens_paths": {},
    },
    "sources": {"git": {"host": "github"}},
    "lint": {},
    "publishing": {
        "base_url": "https://x",
        "build_workflow": "ci.yml",
        "url_map_rule": "strip-ext",
    },
    "notifications": {},
    "site": _SITE,
}


def test_scaffold_plus_archive_builds_strict(tmp_path: Path):
    # source content for the archive
    (tmp_path / "docs/superpowers").mkdir(parents=True)
    shutil.copytree(_FIXTURES / "specs", tmp_path / "docs/superpowers/specs")

    site_yaml = tmp_path / "site.yaml"
    site_yaml.write_text(yaml.safe_dump(_SITE))
    config_yaml = tmp_path / "config.yml"
    config_yaml.write_text(yaml.safe_dump(_CONFIG))

    # S: scaffold
    subprocess.run(
        [sys.executable, str(_SETUP_CLI), "--repo-root", str(tmp_path),
         "--site-name", "Demo", "--config", str(site_yaml)],
        capture_output=True, text=True, check=True,
    )
    # D: generate archive pages
    subprocess.run(
        [sys.executable, str(_ARCHIVE_CLI), "--repo-root", str(tmp_path),
         "--config", str(config_yaml)],
        capture_output=True, text=True, check=True,
    )
    assert (tmp_path / "docs/site-src/archive/specs.md").exists()

    # build gate
    proc = subprocess.run(
        ["mkdocs", "build", "--strict"], cwd=tmp_path, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
```

- [ ] **Step 2: Run the smoke**

Run: `pytest tests/site/test_archive_build_smoke.py -q`
Expected: PASS, or SKIP if `mkdocs` is not installed locally. (If mkdocs is installed, it must PASS — `--strict` exit 0.)

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests; the smoke skips only if mkdocs is absent).

- [ ] **Step 4: Commit**

```bash
git add tests/site/test_archive_build_smoke.py
git commit -m "test(CCE-23): mkdocs --strict smoke for S-scaffold + D-archive

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Validation & Shipping

**Full validation is layered:**

1. **Per-task green:** every task ends with the relevant tests passing; Tasks 1 and 9 also run the full suite (`pytest -q`).
2. **Config validation (Task 7):** schema accepts `repo_url_base`; `_validate_site_sections` rejects absolute/`..` `sources`. Existence is a runtime skip, not a load-time failure (generic-first).
3. **Build-gate validation (Task 9):** `mkdocs build --strict` succeeds on a scaffolded + archive-generated site. Absolute/plain links are strict-safe; this is the gate that catches broken nav/links.

**Before shipping**, dispatch a final code-review subagent over the whole branch (`git diff feat/CCE-23-structured-docs-site...HEAD`), then ship:

- **`/ship`** runs: Stage 1 full `pytest`, Stage 2 verify-agent, Stage 4 code review, Stage 5 commit (already done per-task), Stage 6 push + **PR #25 with base `feat/CCE-23-structured-docs-site`** (stacked on #24), Stage 7 Jira comment on **CCE-23**.
- After PR #24 merges, retarget PR #25's base to `main`.
- Do **not** transition CCE-23 (already In Progress); add a comment summarizing D.

**Out of scope (do not implement here):** orchestrator stage wiring, publishing raw specs into the site, any non-`archive-index` generator. These belong to the later orchestrator-integration plan.

---

## Self-Review (controller checklist — completed)

**Spec coverage:**

- Hybrid linking → Task 5 (`resolve_repo_url_base`) + Task 4 (render), Task 6 wiring. ✓
- Status column from frontmatter → Task 2/3 (`status`), Task 4 (render). ✓
- Skip vs. validate → Task 6 (runtime skip), Task 7 (path-shape guard, no existence check). ✓
- No ADR special-case → category = source basename (Task 6); no `adr-*` glob. ✓
- Rewrite seed + replace test/fixtures → Task 1. ✓
- DATE_PREFIX filter excludes non-md/non-dated → Task 3 + fixtures (`notes.md`, `.txt`). ✓
- `written`/`skipped` return shape → Task 6. ✓
- Never touch S's `index.md`; coexist under section path → Task 6 test. ✓
- mkdocs `--strict` build gate → Task 9. ✓
- Schema `repo_url_base` → Task 7. ✓

**Type/name consistency:** `Entry(filename, title, status, summary, month, source_rel_path)` used identically in Tasks 3/4/6; `resolve_repo_url_base(repo_root, section, *, override)` and `generate_archive(repo_root, site_config, *, repo_url_base)` consistent across Tasks 5/6/8; return key `written` (not `created`) everywhere.

**Placeholder scan:** none — every code step is complete and copy-pastable.
