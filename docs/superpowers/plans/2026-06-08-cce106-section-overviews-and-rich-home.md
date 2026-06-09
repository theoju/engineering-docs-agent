# CCE-106 — Section Overviews, Rich Home, repo_url + Root literate-nav SUMMARY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every docs-site section landing and the home page self-populate deterministically and clobber-safely (a generator owns one delimited region; author prose outside it survives), add a GitHub repo/edit widget, and replace `awesome-pages` with a generated root `SUMMARY.md` so the grouped API reference subtree finally appears in the nav.

**Architecture:** One new pure primitive (`managed_block.upsert_managed_block`) reverses the "never touch index.md" contract for a `<!-- docs-agent:overview:start --> … :end -->` region only. A new deterministic generator (`section_overview.generate_overviews`) upserts that region into each section landing + the home, building the body per section _type_ (directory scan / CCE-105 groups / home directory). `render_mkdocs_yaml` gains `repo_url`/`edit_uri` and drops `awesome-pages`; `plan_scaffold` emits a root `SUMMARY.md` (in section order) that `literate-nav` drives, cross-linking the api reference subtree so its grouped modules render in the nav. All generators stay pure-core / thin-I/O-shell and degrade gracefully on bare hosts.

**Tech Stack:** Python 3 (stdlib-first), pytest, mkdocs Material + `mkdocs-gen-files` + `mkdocs-literate-nav` + `mkdocstrings`. Spec: `docs/superpowers/specs/2026-06-08-cce106-section-overviews-and-rich-home-design.md`.

---

## Planning notes (read before Task 1)

**Spec ↔ plan reconciliation for 6d (the clobber test).** Spec 6d says "change `test_generate_overwrites_stale_but_leaves_section_index` first … rename to `test_overview_replaces_block_preserves_author_prose`." That test currently proves **`generate_archive` leaves `index.md` byte-for-byte** — a still-true, still-valuable guard (archive/contracts must remain sibling-only writers). Renaming-in-place would _delete_ that coverage. This plan therefore satisfies 6d's intent **additively**: it **keeps** `test_generate_overwrites_stale_but_leaves_section_index` (archive's contract intact) and **adds** the new `test_overview_replaces_block_preserves_author_prose` against `section_overview` (the new single owner of the managed block). Net: both halves of "single-writer ownership" are proven. This is a deliberate, safer refinement of the spec's literal wording, flagged here so the spec-reviewer reads it as intentional.

**Generic-first / degrade-gracefully (CLAUDE.md mandate).** Every new capability is detection/config-driven and skips cleanly on a bare host: a section with no children → a "No pages yet." block (never an empty file, never an error); no `groups` → a flat module count; no git origin → no `repo_url`; no python → root SUMMARY still valid (section landings only). Tests use inline tmp fixtures representing arbitrary hosts, not this repo's tree.

**Shared-helper discipline (CLAUDE.md).** `section_overview` **imports** `archive_indexes.parse_title_and_summary` / `_strip_inline_links` and `site_structure.assign_group` rather than re-implementing them. Before changing any of those signatures, `grep -rn` callers repo-wide (none should need changing here — we only call them).

**Run order matters (6g).** `generate_overviews` runs **after** `generate_archive` + `generate_contracts` so their generated child pages (`archive/specs.md`, `api/contracts/*.md`) are on disk to list.

**Per-task discharge (declare-then-discharge, CLAUDE.md).** After each task the controller verifies the implementer's report against external authority: Tier-0 `git diff`/`git status --porcelain` shows the claimed files actually changed; Tier-1 runs the real `python3 -m pytest <files>`; the build-guard tasks (8, 9) additionally run the real `mkdocs build --strict`. A `DONE` report with no on-disk delta is rejected.

**Branch:** all work on `feat/CCE-106-section-overviews-home` (already checked out, spec committed). Never commit to `main`. Commit messages end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer. Do not push/PR until the user asks.

---

## File Structure

**Create:**

- `scripts/managed_block.py` — pure `upsert_managed_block` + marker constants (6a).
- `scripts/section_overview.py` — pure body renderers + `generate_overviews` I/O shell (6c).
- `tests/site/test_managed_block.py` — primitive unit tests (6a).
- `tests/site/test_section_overview.py` — generator + body-renderer tests, incl. the renamed managed-block clobber test (6c/6d).

**Modify:**

- `templates/config.schema.json` — add `overview` boolean to section properties (6b).
- `scripts/site_structure.py` — `render_home` markers (6e); `render_mkdocs_yaml` `repo_url`/`edit_uri` + drop `awesome-pages` + unconditional `literate-nav` (6f/6i); `plan_scaffold` root `SUMMARY.md` instead of `.pages` (6i); `apply_scaffold` passes origin + (already) groups.
- `scripts/orchestrator_runner.py` — `run_site_generators` adds the overviews stage (6g).
- `scripts/setup_scaffold.py` — run `generate_overviews` after scaffold (6g).
- `.engineering-docs-agent/config.yml` — (live) no schema change needed; verify step only (6h).
- `tests/state_io/test_site_validation.py` — `overview: false` loads green (6b).
- `tests/site/test_site_structure.py` — home markers; mkdocs.yml repo_url/no-awesome-pages/literate-nav; root SUMMARY (6e/6f/6i).
- `tests/site/test_api_build_smoke.py` — flip the deferred nav-visibility guard to assert grouped reference modules **are** in the nav (6i real-consumer guard).
- `tests/site/test_archive_generate.py` — unchanged assertion kept (see Planning notes); no edit unless a fixture import is shared.

**Fixtures:** reuse `tests/fixtures/api/host` (already has `pkg/calc.py` + `pkg/util.py` — a named group + an "Other" bucket). No new fixture dirs required.

---

## Task 1: Managed-block primitive (6a)

**Files:**

- Create: `scripts/managed_block.py`
- Test: `tests/site/test_managed_block.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_managed_block.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import managed_block as mb  # noqa: E402


def test_append_when_absent_preserves_author_prose():
    existing = "---\ntitle: Architecture\n---\n\n# Architecture\n\nAuthor intro.\n"
    out = mb.upsert_managed_block(existing, "GENERATED")
    # author content survives byte-for-byte at the head
    assert out.startswith(existing.rstrip("\n") + "\n\n")
    assert mb.START in out and mb.END in out
    assert "GENERATED" in out
    # exactly one region
    assert out.count(mb.START) == 1 and out.count(mb.END) == 1


def test_replace_preserves_prose_above_and_below():
    existing = (
        "# Title\n\nABOVE\n\n"
        f"{mb.START}\nOLD BODY\n{mb.END}\n\n"
        "BELOW\n"
    )
    out = mb.upsert_managed_block(existing, "NEW BODY")
    assert "ABOVE" in out and "BELOW" in out
    assert "OLD BODY" not in out
    assert "NEW BODY" in out
    # text outside the markers is preserved exactly
    assert out.startswith("# Title\n\nABOVE\n\n")
    assert out.rstrip("\n").endswith("BELOW")
    assert out.count(mb.START) == 1 and out.count(mb.END) == 1


def test_idempotent_same_body():
    existing = "# T\n\nintro\n"
    once = mb.upsert_managed_block(existing, "BODY")
    twice = mb.upsert_managed_block(once, "BODY")
    assert once == twice


def test_append_into_empty_text():
    out = mb.upsert_managed_block("", "BODY")
    assert out == f"{mb.START}\nBODY\n{mb.END}\n"


def test_double_start_raises():
    bad = f"{mb.START}\nx\n{mb.START}\ny\n{mb.END}\n"
    with pytest.raises(ValueError):
        mb.upsert_managed_block(bad, "BODY")


def test_end_before_start_raises():
    bad = f"{mb.END}\nstray\n{mb.START}\nbody\n"  # one each, wrong order
    with pytest.raises(ValueError):
        mb.upsert_managed_block(bad, "BODY")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_managed_block.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'managed_block'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/managed_block.py
"""Clobber-safe managed-region upsert for generated docs blocks.

Pure (no I/O). A generator owns the delimited START..END region of a file;
author prose outside the markers survives every regeneration. This is the
single place the docs-agent's "never rewrite an authored index.md" rule is
reversed -- for the delimited block only (CCE-106).
"""
from __future__ import annotations

MARKER = "docs-agent:overview"
START = f"<!-- {MARKER}:start -->"
END = f"<!-- {MARKER}:end -->"


def upsert_managed_block(existing_text: str, block_body: str) -> str:
    """Return ``existing_text`` with the START..END region's body replaced by
    ``block_body``. If no region exists, append one at end-of-file (preceded by
    a blank line). Text outside the markers is preserved byte-for-byte.

    Raises ValueError on a malformed file (more than one START/END, an unbalanced
    pair, or END before START) so the caller can record an ``info_only`` partial
    rather than crash the run.
    """
    n_start = existing_text.count(START)
    n_end = existing_text.count(END)
    if n_start > 1 or n_end > 1:
        raise ValueError(
            f"managed block markers must appear at most once "
            f"(start={n_start}, end={n_end})"
        )
    if n_start != n_end:
        raise ValueError(
            f"unbalanced managed block markers (start={n_start}, end={n_end})"
        )

    block = f"{START}\n{block_body}\n{END}"

    if n_start == 0:
        if not existing_text.strip():
            return block + "\n"
        return existing_text.rstrip("\n") + "\n\n" + block + "\n"

    start_idx = existing_text.index(START)
    end_idx = existing_text.index(END)
    if end_idx < start_idx:
        raise ValueError("END marker precedes START marker")
    before = existing_text[:start_idx]
    after = existing_text[end_idx + len(END) :]
    return f"{before}{block}{after}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_managed_block.py -v`
Expected: PASS (6/6).

- [ ] **Step 5: Commit**

```bash
git add scripts/managed_block.py tests/site/test_managed_block.py
git commit -m "feat(CCE-106): clobber-safe upsert_managed_block primitive (6a)"
```

---

## Task 2: Schema `overview` opt-out (6b)

**Files:**

- Modify: `templates/config.schema.json:123-162` (section `properties`)
- Test: `tests/state_io/test_site_validation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/state_io/test_site_validation.py` (match the file's existing helper style — it builds a config dict and calls `load_config_validated` on a written temp file; mirror the nearest existing test for setup):

```python
def test_section_overview_false_loads_green(tmp_path):
    # overview:false is a valid per-section opt-out; the loader must accept it.
    cfg = _base_config()  # reuse the module's existing minimal-config helper
    cfg["site"]["sections"].append(
        {"key": "ops", "path": "operations/", "title": "Operations", "overview": False}
    )
    path = _write_config(tmp_path, cfg)  # reuse the module's existing writer helper
    loaded = load_config_validated(path)
    ops = next(s for s in loaded["site"]["sections"] if s["key"] == "ops")
    assert ops["overview"] is False
```

If `_base_config`/`_write_config` helpers do not exist under those names, inline the smallest valid config with a `site:` block and `load_config_validated` call following the patterns already in this test module.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/state_io/test_site_validation.py::test_section_overview_false_loads_green -v`
Expected: FAIL — schema rejects the unknown `overview` key (`additionalProperties: false`) → `ConfigError`.

- [ ] **Step 3: Add `overview` to the schema**

In `templates/config.schema.json`, inside the section `items.properties` object (alongside `groups`), add:

```json
"overview": { "type": "boolean", "default": true },
```

(Place it after the `"repo_url_base"` line and before `"groups"`, keeping valid JSON — add the trailing comma on the preceding property.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/state_io/test_site_validation.py -v`
Expected: PASS (new test green; existing validation tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add templates/config.schema.json tests/state_io/test_site_validation.py
git commit -m "feat(CCE-106): per-section overview opt-out in config schema (6b)"
```

---

## Task 3: Overview generator — directory sections + the managed-block clobber test (6c/6d)

**Files:**

- Create: `scripts/section_overview.py`
- Test: `tests/site/test_section_overview.py`

This task ships the pure directory-section body renderer and the `generate_overviews` shell for directory sections only. The API-section variant is Task 4; home is Task 5.

- [ ] **Step 1: Write the failing tests**

```python
# tests/site/test_section_overview.py
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import managed_block as mb  # noqa: E402
import section_overview as so  # noqa: E402


def _dir_site():
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "architecture", "path": "architecture/", "title": "Architecture"},
        ],
    }


def _seed_landing(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --- pure renderer -----------------------------------------------------------

def test_render_directory_overview_lists_children_with_count():
    body = so.render_directory_overview(
        [("Routing", "How requests flow."), ("Storage", "Where state lives.")]
    )
    assert "**Routing** — How requests flow." in body
    assert "**Storage** — Where state lives." in body
    assert "2 pages" in body


def test_render_directory_overview_empty_is_no_pages():
    body = so.render_directory_overview([])
    assert body.strip() == "_No pages yet._"


# --- generator (directory section) -------------------------------------------

def test_generate_overviews_directory_section(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md",
                  "---\ntitle: Architecture\n---\n\n# Architecture\n\nAuthor intro.\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/routing.md",
                  "---\ntitle: Routing\n---\n\n# Routing\n\nHow requests flow.\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/_draft.md",
                  "# Draft\n\nhidden.\n")  # underscore -> excluded
    result = so.generate_overviews(tmp_path, site)
    assert "docs/site-src/architecture/index.md" in result["written"]
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert "Author intro." in out                 # prose preserved
    assert "**Routing** — How requests flow." in out
    assert "_draft" not in out and "hidden" not in out
    assert out.count(mb.START) == 1


def test_overview_false_section_is_skipped(tmp_path):
    site = _dir_site()
    site["sections"][1]["overview"] = False
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/routing.md",
                  "# Routing\n\nx.\n")
    result = so.generate_overviews(tmp_path, site)
    assert "docs/site-src/architecture/index.md" not in result["written"]
    assert mb.START not in (tmp_path / "docs/site-src/architecture/index.md").read_text()


def test_empty_directory_section_writes_no_pages_block(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert "_No pages yet._" in out
    assert "docs/site-src/architecture/index.md" in result["written"]


def test_malformed_landing_is_recorded_not_raised(tmp_path):
    site = _dir_site()
    bad = f"# A\n\n{mb.START}\nx\n{mb.START}\ny\n{mb.END}\n"  # double START
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", bad)
    _seed_landing(tmp_path, "docs/site-src/architecture/p.md", "# P\n\ns.\n")
    result = so.generate_overviews(tmp_path, site)  # must not raise
    assert "docs/site-src/architecture/index.md" in result["skipped"]


# --- renamed clobber test (spec 6d): single-writer of the managed block ------

def test_overview_replaces_block_preserves_author_prose(tmp_path):
    site = _dir_site()
    landing = _seed_landing(
        tmp_path, "docs/site-src/architecture/index.md",
        "# Architecture\n\nHAND-WRITTEN INTRO.\n\n"
        f"{mb.START}\nSTALE GENERATED\n{mb.END}\n\nHAND-WRITTEN FOOTER.\n",
    )
    _seed_landing(tmp_path, "docs/site-src/architecture/r.md", "# R\n\nrouting.\n")
    so.generate_overviews(tmp_path, site)
    out = landing.read_text()
    assert "HAND-WRITTEN INTRO." in out
    assert "HAND-WRITTEN FOOTER." in out
    assert "STALE GENERATED" not in out
    assert "**R** — routing." in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_section_overview.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'section_overview'`.

- [ ] **Step 3: Write the implementation**

```python
# scripts/section_overview.py
"""Upsert a clobber-safe overview block into each section landing + the home.

Pure renderers build the block body per section *type*; ``generate_overviews``
is the only function that touches the filesystem. It owns exactly one managed
region per landing (via managed_block) -- author prose outside the markers
survives every run. Best-effort per section: a malformed landing is recorded
and skipped, never raised, so an advisory generation failure never blocks the
nightly PR. Degrades gracefully: an empty section yields a "No pages yet."
block, never an empty file and never an error.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_indexes  # noqa: E402
import managed_block  # noqa: E402

_NO_PAGES = "_No pages yet._"


# --- pure renderers ----------------------------------------------------------

def render_directory_overview(children: list[tuple[str, str]]) -> str:
    """children: list of (title, summary). Render an "In this section" list +
    a count footer, or a "No pages yet." line when empty."""
    if not children:
        return _NO_PAGES
    lines = ["**In this section**", ""]
    for title, summary in children:
        lines.append(f"- **{title}** — {summary}" if summary else f"- **{title}**")
    lines.append("")
    lines.append(f"_{len(children)} pages · regenerated nightly_")
    return "\n".join(lines)


# --- I/O helpers -------------------------------------------------------------

def _scan_children(section_dir: Path) -> list[tuple[str, str]]:
    """(title, summary) per child *.md, excluding index.md and _*-prefixed.
    Best-effort: a child that fails to read/parse is skipped, not raised."""
    out: list[tuple[str, str]] = []
    if not section_dir.is_dir():
        return out
    for md in sorted(section_dir.glob("*.md")):
        if md.name == "index.md" or md.name.startswith("_"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        title, summary = archive_indexes.parse_title_and_summary(text)
        title = archive_indexes._strip_inline_links(title) or md.stem
        summary = archive_indexes._strip_inline_links(summary)
        out.append((title, summary))
    return out


def _upsert(landing: Path, body: str, rel: str, written: list, skipped: list) -> None:
    existing = landing.read_text(encoding="utf-8") if landing.exists() else ""
    try:
        new = managed_block.upsert_managed_block(existing, body)
    except ValueError:
        skipped.append(rel)
        return
    if new != existing:
        landing.parent.mkdir(parents=True, exist_ok=True)
        landing.write_text(new, encoding="utf-8")
        written.append(rel)
    else:
        skipped.append(rel)


def _is_page(section: dict) -> bool:
    return section.get("path", "").endswith(".md")


def generate_overviews(repo_root: Path, site_config: dict) -> dict:
    """Upsert an overview block into every eligible section landing + the home.
    Returns {"written": [...], "skipped": [...]} of repo-relative POSIX paths."""
    repo_root = Path(repo_root)
    written: list[str] = []
    skipped: list[str] = []
    docs_dir = (site_config.get("docs_dir") or "").rstrip("/")

    home_section = None
    for section in site_config.get("sections", []) or []:
        if section.get("overview") is False:
            continue
        if section.get("key") == "home":
            home_section = section
            continue
        # API section is handled in Task 4; single-page non-home sections (e.g.
        # changelog) are self-managing -> skipped here.
        if section.get("generator") == "api-extract":
            continue  # Task 4 replaces this branch
        if _is_page(section):
            continue
        path = section["path"].rstrip("/")
        section_dir = repo_root / docs_dir / path
        rel = f"{docs_dir}/{path}/index.md"
        body = render_directory_overview(_scan_children(section_dir))
        _upsert(repo_root / docs_dir / path / "index.md", body, rel, written, skipped)

    # Home handled in Task 5 (left intentionally unprocessed here).
    _ = home_section
    return {"written": written, "skipped": skipped}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_section_overview.py -v`
Expected: PASS (8/8).

- [ ] **Step 5: Confirm the archive guard still holds (no regression)**

Run: `python3 -m pytest tests/site/test_archive_generate.py -v`
Expected: PASS — `test_generate_overwrites_stale_but_leaves_section_index` still green (archive remains a sibling-only writer; see Planning notes).

- [ ] **Step 6: Commit**

```bash
git add scripts/section_overview.py tests/site/test_section_overview.py
git commit -m "feat(CCE-106): section_overview generator for directory landings + clobber-safe block (6c/6d)"
```

---

## Task 4: Overview generator — API section variant (6c)

**Files:**

- Modify: `scripts/section_overview.py`
- Test: `tests/site/test_section_overview.py`

The API overview lists CCE-105 `groups` by name with each group's real module count (computed by scanning the api source modules and applying `site_structure.assign_group`), plus links to on-disk `contracts/` pages. It does **not** disk-scan `api/reference/` (build-time only). Module idents come from `setup_discover.detect_python` (detection-driven, generic) — monkeypatched in tests.

- [ ] **Step 1: Write the failing tests**

Add to `tests/site/test_section_overview.py`:

```python
import setup_discover  # noqa: E402  (add to the import block at top)


def test_render_api_overview_groups_with_counts():
    groups = [{"name": "Math", "modules": ["pkg.calc"]}]
    body = so.render_api_overview(
        idents=["pkg.calc", "pkg.util"],
        groups=groups,
        contract_links=[("Widget", "contracts/widget.md")],
    )
    assert "**Math** — 1 module" in body
    assert "**Other** — 1 module" in body          # pkg.util falls through
    assert "[Widget](contracts/widget.md)" in body


def test_render_api_overview_flat_when_no_groups():
    body = so.render_api_overview(idents=["a", "b", "c"], groups=[], contract_links=[])
    assert "3 modules" in body


def test_generate_overviews_api_section(tmp_path, monkeypatch):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {
                "key": "api", "path": "api/", "title": "API reference",
                "generator": "api-extract",
                "groups": [{"name": "Math", "modules": ["pkg.calc"]}],
            },
        ],
    }
    # api landing + an on-disk contracts page (as generate_contracts would leave)
    _seed_landing(tmp_path, "docs/site-src/api/index.md", "# API reference\n")
    _seed_landing(tmp_path, "docs/site-src/api/contracts/widget.md",
                  "# Widget\n\nA widget.\n")
    # two source modules on disk
    _seed_landing(tmp_path, "pkg/calc.py", "def add(a, b):\n    return a + b\n")
    _seed_landing(tmp_path, "pkg/util.py", "def slug(s):\n    return s\n")
    monkeypatch.setattr(
        setup_discover, "detect_python",
        lambda root: {"detected": True, "scan_dir": "pkg", "path_root": "."},
    )
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/api/index.md").read_text()
    assert "docs/site-src/api/index.md" in result["written"]
    assert "**Math** — 1 module" in out
    assert "**Other** — 1 module" in out
    assert "[Widget](contracts/widget.md)" in out


def test_generate_overviews_api_no_python_degrades(tmp_path, monkeypatch):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "api", "path": "api/", "title": "API", "generator": "api-extract"},
        ],
    }
    _seed_landing(tmp_path, "docs/site-src/api/index.md", "# API\n")
    monkeypatch.setattr(
        setup_discover, "detect_python",
        lambda root: {"detected": False, "scan_dir": None, "path_root": None},
    )
    result = so.generate_overviews(tmp_path, site)  # must not raise
    out = (tmp_path / "docs/site-src/api/index.md").read_text()
    assert mb.START in out                 # a block is still written
    assert "_No pages yet._" in out or "modules" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_section_overview.py -k api -v`
Expected: FAIL — `render_api_overview` undefined / api branch is the Task-3 `continue` stub.

- [ ] **Step 3: Implement the API variant**

In `scripts/section_overview.py`, add the import and the pure renderer + scan helper, and replace the Task-3 `api-extract` `continue` branch:

```python
# add to the import block:
import setup_discover  # noqa: E402
import site_structure  # noqa: E402
```

```python
def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def render_api_overview(
    idents: list[str], groups: list, contract_links: list[tuple[str, str]]
) -> str:
    """Render the API landing block: CCE-105 groups + counts (or a flat module
    count when no groups), then links to the on-disk contracts pages."""
    lines: list[str] = []
    if groups:
        counts: dict[str, int] = {}
        for ident in idents:
            name = site_structure.assign_group(ident, groups) or "Other"
            counts[name] = counts.get(name, 0) + 1
        order = [g["name"] for g in groups] + ["Other"]
        lines.append("**Components**")
        lines.append("")
        for name in order:
            if counts.get(name):
                lines.append(f"- **{name}** — {_plural(counts[name], 'module')}")
        lines.append("")
    elif idents:
        lines.append(f"_{_plural(len(idents), 'module')} documented · regenerated nightly_")
        lines.append("")
    if contract_links:
        lines.append("**Contracts**")
        lines.append("")
        for title, rel in contract_links:
            lines.append(f"- [{title}]({rel})")
        lines.append("")
    body = "\n".join(lines).rstrip("\n")
    return body or _NO_PAGES


def _api_idents(repo_root: Path) -> list[str]:
    """Dotted idents of the host's python modules, mirroring gen_ref_pages'
    rglob + filter. Empty when no python is detected (degrade-gracefully)."""
    py = setup_discover.detect_python(repo_root)
    if not py.get("detected"):
        return []
    scan_dir = repo_root / (py.get("scan_dir") or ".")
    root = repo_root / (py.get("path_root") or ".")
    idents: list[str] = []
    for path in sorted(scan_dir.rglob("*.py")):
        if path.name.startswith("_") or any(p in ("tests", "test") for p in path.parts):
            continue
        try:
            parts = path.relative_to(root).with_suffix("").parts
        except ValueError:
            continue
        if parts:
            idents.append(".".join(parts))
    return idents


def _contract_links(repo_root: Path, docs_dir: str, api_path: str) -> list[tuple[str, str]]:
    contracts_dir = repo_root / docs_dir / api_path / "contracts"
    links: list[tuple[str, str]] = []
    if not contracts_dir.is_dir():
        return links
    for md in sorted(contracts_dir.glob("*.md")):
        if md.name == "index.md":
            continue
        try:
            title, _ = archive_indexes.parse_title_and_summary(
                md.read_text(encoding="utf-8")
            )
        except OSError:
            title = ""
        links.append((title or md.stem, f"contracts/{md.name}"))
    return links
```

Replace the Task-3 stub branch:

```python
        if section.get("generator") == "api-extract":
            api_path = section["path"].rstrip("/")
            rel = f"{docs_dir}/{api_path}/index.md"
            body = render_api_overview(
                _api_idents(repo_root),
                section.get("groups") or [],
                _contract_links(repo_root, docs_dir, api_path),
            )
            _upsert(repo_root / docs_dir / api_path / "index.md",
                    body, rel, written, skipped)
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_section_overview.py -v`
Expected: PASS (all, including the 4 new API tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/section_overview.py tests/site/test_section_overview.py
git commit -m "feat(CCE-106): API overview variant (CCE-105 groups + contracts links) (6c)"
```

---

## Task 5: Rich home (6e)

**Files:**

- Modify: `scripts/site_structure.py` (`render_home`, lines 87-102)
- Modify: `scripts/section_overview.py` (home branch)
- Test: `tests/site/test_site_structure.py`, `tests/site/test_section_overview.py`

`render_home` emits an author-intro zone **plus empty start/end markers**; `generate_overviews` fills the home block with a section directory (each non-home section: title + count, linking to its landing). The grid-cards layout lives **inside** the managed block (now generator-owned). Existing scaffolded homes (no markers) get a block appended.

- [ ] **Step 1: Write the failing tests**

Add to `tests/site/test_site_structure.py`:

```python
def test_render_home_has_author_zone_and_empty_markers():
    site = SITE  # module-level fixture with home + api sections
    out = site_structure.render_home(site)
    assert "docs-agent:overview:start" in out
    assert "docs-agent:overview:end" in out
    # the managed region is empty at scaffold time (generator fills it)
    start = out.index("docs-agent:overview:start")
    end = out.index("docs-agent:overview:end")
    between = out[start:end]
    assert "grid cards" not in between  # cards come from the generator, not the stub
```

Add to `tests/site/test_section_overview.py`:

```python
def test_generate_overviews_fills_home_block(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "architecture", "path": "architecture/", "title": "Architecture"},
            {"key": "ops", "path": "operations/", "title": "Operations"},
        ],
    }
    # home WITH markers (post-6e scaffold) + an author intro above
    _seed_landing(
        tmp_path, "docs/site-src/index.md",
        "---\ntitle: Home\n---\n\n# Documentation\n\nWELCOME INTRO.\n\n"
        f"{mb.START}\n{mb.END}\n",
    )
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(tmp_path, "docs/site-src/operations/index.md", "# Operations\n")
    result = so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/index.md").read_text()
    assert "WELCOME INTRO." in out                       # author zone survives
    assert "docs/site-src/index.md" in result["written"]
    assert "Architecture" in out and "Operations" in out
    assert "architecture/index.md" in out                # links to landings


def test_generate_overviews_home_without_markers_appends(tmp_path):
    site = {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "ops", "path": "operations/", "title": "Operations"},
        ],
    }
    # legacy scaffolded home: no markers
    _seed_landing(tmp_path, "docs/site-src/index.md",
                  "---\ntitle: Home\n---\n\n# Documentation\n\nOld cards.\n")
    _seed_landing(tmp_path, "docs/site-src/operations/index.md", "# Operations\n")
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/index.md").read_text()
    assert "Old cards." in out                            # legacy content preserved
    assert mb.START in out and "Operations" in out        # block appended
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_site_structure.py -k home tests/site/test_section_overview.py -k home -v`
Expected: FAIL — `render_home` has no markers; `generate_overviews` ignores the home section (Task-3 left it unprocessed).

- [ ] **Step 3: Update `render_home`**

Replace `render_home` in `scripts/site_structure.py` so it emits the author intro + an **empty** managed region (import the markers from `managed_block`):

```python
# add near the other imports at the top of site_structure.py:
from managed_block import START as _OVERVIEW_START, END as _OVERVIEW_END
```

> Note: `site_structure.py` is imported with `scripts/` on `sys.path` (every caller inserts it). `from managed_block import ...` resolves the same way `archive_indexes` already imports `orchestrator_runner`. If a circular-import surfaces, fall back to a local literal `_OVERVIEW_START = "<!-- docs-agent:overview:start -->"` — but prefer the import to keep one source of truth.

```python
def render_home(site: dict) -> str:
    return (
        "---\ntitle: Home\nhide:\n  - toc\n---\n\n"
        "# Documentation\n\n"
        "Pick a section to get started.\n\n"
        f"{_OVERVIEW_START}\n{_OVERVIEW_END}\n"
    )
```

- [ ] **Step 4: Add the home renderer + branch to `section_overview.py`**

Pure renderer:

```python
def render_home_overview(entries: list[tuple[str, str]]) -> str:
    """entries: list of (title, target). Render the grid-cards section directory
    that lives inside the home's managed block."""
    if not entries:
        return _NO_PAGES
    cards = [f"-   __{title}__\n\n    [Open →]({target})" for title, target in entries]
    return '<div class="grid cards" markdown>\n\n' + "\n\n".join(cards) + "\n\n</div>"
```

Process the home section at the end of `generate_overviews` (replace the `_ = home_section` placeholder). Build one `(title, target)` per non-home section, reusing `render_home`'s target rule:

```python
    if home_section is not None:
        entries: list[tuple[str, str]] = []
        for section in site_config.get("sections", []) or []:
            if section.get("key") == "home":
                continue
            path = section["path"]
            target = path if _is_page(section) else f"{path.rstrip('/')}/index.md"
            entries.append((section["title"], target))
        rel = f"{docs_dir}/{home_section['path'].rstrip('/')}"
        _upsert(repo_root / rel, render_home_overview(entries), rel, written, skipped)

    return {"written": written, "skipped": skipped}
```

(Remove the `_ = home_section` line.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_site_structure.py tests/site/test_section_overview.py -v`
Expected: PASS. Note: `test_page_section_has_no_directory` and other `plan_scaffold` home tests still pass (render_home still returns a single home page).

- [ ] **Step 6: Commit**

```bash
git add scripts/site_structure.py scripts/section_overview.py tests/site/test_site_structure.py tests/site/test_section_overview.py
git commit -m "feat(CCE-106): rich home — author zone + generator-filled section directory (6e)"
```

---

## Task 6: repo_url / edit_uri widget (6f)

**Files:**

- Modify: `scripts/site_structure.py` (`render_mkdocs_yaml` lines 257-275, `apply_scaffold` lines 278-309, `_MKDOCS_TEMPLATE`)
- Test: `tests/site/test_site_structure.py`

`render_mkdocs_yaml` gains optional `repo_url` / `edit_uri`. `apply_scaffold` derives them from the git origin via `setup_discover.discover_git_origin`. When no origin resolves, both are omitted (Material's "Edit this page" + repo links simply don't render).

- [ ] **Step 1: Write the failing tests**

Add to `tests/site/test_site_structure.py`:

```python
def test_render_mkdocs_yaml_includes_repo_url_when_given():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=False,
        repo_url="https://github.com/o/n", edit_uri="edit/main/docs/site-src/",
    )
    assert "repo_url: https://github.com/o/n" in out
    assert "edit_uri: edit/main/docs/site-src/" in out


def test_render_mkdocs_yaml_omits_repo_url_when_absent():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "repo_url:" not in out
    assert "edit_uri:" not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_site_structure.py -k repo_url -v`
Expected: FAIL — `render_mkdocs_yaml` has no `repo_url` kwarg → `TypeError`.

- [ ] **Step 3: Implement**

Add a `{repo_block}` slot to `_MKDOCS_TEMPLATE` immediately after the `site_dir: site` line:

```python
site_name: {site_name}
docs_dir: {docs_dir}
site_dir: site
{repo_block}
theme:
```

Update `render_mkdocs_yaml`:

```python
def render_mkdocs_yaml(
    site: dict,
    *,
    site_name: str,
    python_detected: bool,
    python_path_root: str | None = None,
    openapi_enabled: bool = False,
    repo_url: str | None = None,
    edit_uri: str | None = None,
) -> str:
    plugins = ""
    if python_detected:
        plugins += _python_plugins_block(python_path_root or ".")
    if openapi_enabled:
        plugins += _RENDER_SWAGGER_PLUGIN
    repo_lines = ""
    if repo_url:
        repo_lines = f"repo_url: {_yaml_scalar(repo_url)}\n"
        if edit_uri:
            repo_lines += f"edit_uri: {_yaml_scalar(edit_uri)}\n"
    return _MKDOCS_TEMPLATE.format(
        site_name=_yaml_scalar(site_name),
        docs_dir=site["docs_dir"].rstrip("/"),
        theme=site.get("theme", "material"),
        mkdocstrings_plugin=plugins,
        repo_block=repo_lines,
    )
```

In `apply_scaffold`, derive origin and pass it through (add near the top of the function, before building the mkdocs `ScaffoldFile`):

```python
    origin = setup_discover.discover_git_origin(repo_root)
    repo_url = edit_uri = None
    if origin:
        repo_url = f"https://github.com/{origin['owner']}/{origin['repo']}"
        edit_uri = f"edit/main/{site['docs_dir'].rstrip('/')}/"
```

and add `repo_url=repo_url, edit_uri=edit_uri` to the `render_mkdocs_yaml(...)` call. Add `import setup_discover` to `site_structure.py`'s imports.

> Edit-URI branch note: `edit/main/<docs_dir>/` assumes the default branch is `main` — correct for this plugin's hosts. A non-`main` default still produces a valid (if branch-mismatched) link; refining to the detected default branch is out of scope (YAGNI). The repo_link itself is branch-independent.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_site_structure.py -v`
Expected: PASS. The existing `test_*` mkdocs-render tests still pass (the new slot is empty when `repo_url` is None — verify `_MKDOCS_TEMPLATE.format` produces no blank-line regression; if a stray blank line breaks an exact-match test, set `repo_block` default to `""` and ensure the template line collapses cleanly).

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py
git commit -m "feat(CCE-106): repo_url/edit_uri widget derived from git origin (6f)"
```

---

## Task 7: Drop awesome-pages, make literate-nav unconditional (6i, part 1)

**Files:**

- Modify: `scripts/site_structure.py` (`_MKDOCS_TEMPLATE`, `_python_plugins_block`, `render_mkdocs_yaml`)
- Test: `tests/site/test_site_structure.py`

`awesome-pages` cannot expand a subdirectory `SUMMARY.md`, so it is removed; `literate-nav` becomes the single nav driver and must be present **unconditionally** (it drives the nav from the root `SUMMARY.md`, which `plan_scaffold` always emits in Task 8). `gen-files` + `mkdocstrings` stay python-only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/site/test_site_structure.py`:

```python
def test_mkdocs_yaml_drops_awesome_pages():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "awesome-pages" not in out


def test_mkdocs_yaml_has_literate_nav_even_without_python():
    out = site_structure.render_mkdocs_yaml(SITE, site_name="X", python_detected=False)
    assert "literate-nav" in out
    assert "nav_file: SUMMARY.md" in out


def test_mkdocs_yaml_python_still_has_gen_files_and_mkdocstrings():
    out = site_structure.render_mkdocs_yaml(
        SITE, site_name="X", python_detected=True, python_path_root="."
    )
    assert "gen-files" in out and "mkdocstrings" in out
    assert out.count("literate-nav") == 1   # not duplicated
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/site/test_site_structure.py -k "awesome or literate or gen_files" -v`
Expected: FAIL — template still lists `awesome-pages`; `literate-nav` only appears under python.

- [ ] **Step 3: Implement**

In `_MKDOCS_TEMPLATE`, change the `plugins:` block so `search` + `literate-nav` are always present and `awesome-pages` is gone:

```python
plugins:
  - search
  - literate-nav:
      nav_file: SUMMARY.md
{mkdocstrings_plugin}
```

Remove the `- literate-nav:` lines from `_python_plugins_block` (it now only contributes `gen-files`, `mkdocstrings`):

```python
def _python_plugins_block(path_root: str) -> str:
    root = path_root or "."
    return (
        "  - gen-files:\n"
        "      scripts:\n"
        "        - gen_ref_pages.py\n"
        "  - mkdocstrings:\n"
        "      handlers:\n"
        "        python:\n"
        f"          paths: [{json.dumps(root)}]\n"
        "          options:\n"
        "            show_source: false\n"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/site/test_site_structure.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py
git commit -m "feat(CCE-106): literate-nav is the sole nav driver; drop awesome-pages (6i)"
```

---

## Task 8: Root SUMMARY generation + real-consumer nav guard (6i, part 2)

**Files:**

- Modify: `scripts/site_structure.py` (`plan_scaffold` lines 105-149)
- Test: `tests/site/test_site_structure.py` (unit), `tests/site/test_api_build_smoke.py` (real consumer)

This is the integration-heavy task. `plan_scaffold` stops emitting `.pages` files and instead emits a single root `<docs_dir>/SUMMARY.md` listing sections **in config order**. The discriminating source of truth is the `mkdocs build --strict` guard that asserts the grouped reference modules render in the nav and no orphan `api/reference/SUMMARY/` page remains. **The exact literate-nav cross-link syntax is settled by making that build guard green — iterate the SUMMARY content against the real consumer, do not treat the snippet below as final.**

- [ ] **Step 1: Write the failing unit tests (deterministic part)**

Replace the now-obsolete `.pages` assertions. Update `test_plan_scaffold_emits_index_and_section_dirs` and add SUMMARY tests in `tests/site/test_site_structure.py`:

```python
def test_plan_scaffold_emits_root_summary_not_pages():
    files = {f.path: f for f in site_structure.plan_scaffold(SITE)}
    assert "docs/site-src/SUMMARY.md" in files
    # no awesome-pages artifacts anymore
    assert "docs/site-src/.pages" not in files
    assert "docs/site-src/api/.pages" not in files


def test_root_summary_lists_sections_in_config_order():
    summary = next(
        f for f in site_structure.plan_scaffold(SITE) if f.path.endswith("SUMMARY.md")
    ).content
    # home first, then api (config order), each as a literate-nav bullet
    assert summary.index("Home") < summary.index("API reference")
    assert "(index.md)" in summary            # home landing
    assert "api/index.md" in summary          # directory-section landing
```

Update the existing `test_empty_sections_emits_only_root_pages` and `test_title_with_colon_produces_parseable_yaml` (they assert `.pages` output). For empty sections, assert the root SUMMARY is emitted (possibly empty body) and no `.pages`. For the colon test, assert the title survives in `SUMMARY.md` markdown (titles in SUMMARY are link text, not YAML — a colon needs no quoting there; drop the `.pages` YAML-parse assertions). Keep `test_section_index_stub_has_title_and_draft_frontmatter` and `test_page_section_has_no_directory` as-is (those don't depend on `.pages`).

- [ ] **Step 2: Write the failing real-consumer guard**

In `tests/site/test_api_build_smoke.py`, flip the deferred guard in `test_api_site_builds_strict_with_groups` so it now asserts the grouped reference modules **are** in the rendered nav and there is **no** orphan SUMMARY page. Replace the final assertions (and the docstring's "deferred" note) with:

```python
    proc = _build(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    built = tmp_path / "site"
    # pages still generate
    assert (built / "api" / "reference" / "pkg" / "calc" / "index.html").exists()
    assert (built / "api" / "reference" / "pkg" / "util" / "index.html").exists()
    # CCE-106: the grouped reference modules now appear in the rendered nav, and
    # the orphan reference SUMMARY page is gone.
    calc_html = (built / "api" / "reference" / "pkg" / "calc" / "index.html").read_text()
    assert "Math" in calc_html          # the group label renders in the nav sidebar
    assert "Other" in calc_html         # pkg.util's fall-through bucket
    assert not (built / "api" / "reference" / "SUMMARY" / "index.html").exists()
```

Also extend `_SITE_GROUPED` to exercise the home + api sections through `apply_scaffold` (it already does). Confirm `apply_scaffold` now writes a root `SUMMARY.md` (Task-8 plan_scaffold change) so the build has a nav file.

- [ ] **Step 3: Run both to verify they fail**

Run: `python3 -m pytest tests/site/test_site_structure.py -k "summary or scaffold" tests/site/test_api_build_smoke.py::test_api_site_builds_strict_with_groups -v`
Expected: FAIL — `plan_scaffold` still emits `.pages`; the build guard's "Math"/"Other" nav assertions fail (the pre-existing orphan-SUMMARY gap).

- [ ] **Step 4: Implement `plan_scaffold` root SUMMARY**

Rewrite the nav-emission part of `plan_scaffold` (keep the per-section index/page stub emission; remove both the root `.pages` and per-directory `.pages`). Starting-point SUMMARY generation — **iterate against the Step-2 build guard until green**:

```python
def _summary_line(section: dict, *, indent: int = 0) -> str:
    pad = "    " * indent
    if _is_page(section):
        target = section["path"]
    else:
        target = f"{section['path'].rstrip('/')}/index.md"
    return f"{pad}* [{section['title']}]({target})"


def plan_scaffold(site: dict) -> list[ScaffoldFile]:
    docs_dir = site["docs_dir"].rstrip("/")
    sections = site.get("sections", [])
    files: list[ScaffoldFile] = []

    summary_lines: list[str] = []
    for s in sections:
        summary_lines.append(_summary_line(s))
        # For the api-extract section, cross-link the build-time reference subtree
        # so literate-nav expands its grouped SUMMARY under this section. The
        # contracts/ subtree is listed similarly. (Exact nesting is validated by
        # the mkdocs --strict guard — adjust here until that test is green.)
        if s.get("generator") == "api-extract":
            api = s["path"].rstrip("/")
            summary_lines.append(f"    * [Code reference]({api}/reference/)")
            summary_lines.append(f"    * [Contracts]({api}/contracts/)")

    files.append(
        ScaffoldFile(
            f"{docs_dir}/SUMMARY.md", "\n".join(summary_lines) + "\n", "root-pages"
        )
    )

    for s in sections:
        if s["key"] == "home":
            files.append(
                ScaffoldFile(
                    f"{docs_dir}/{s['path'].rstrip('/')}", render_home(site), "home"
                )
            )
            continue
        path = s["path"].rstrip("/")
        if _is_page(s):
            files.append(
                ScaffoldFile(f"{docs_dir}/{path}", _page_stub(s), "section-index")
            )
            continue
        files.append(
            ScaffoldFile(
                f"{docs_dir}/{path}/index.md", _section_index_stub(s), "section-index"
            )
        )
    return files
```

**Iteration guidance (the finicky part):** if the build guard shows the reference modules still don't appear, the likely fixes (try in order, re-running the guard each time) are: (a) the directory cross-link must be a bare `dir/` literate-nav entry vs a `dir/SUMMARY.md` explicit link — test both forms; (b) `api/contracts/` has no `SUMMARY.md` (only `index.md`) so literate-nav may need an explicit `* [Contracts](api/contracts/index.md)` instead of a directory link, or a `* api/contracts/*.md` glob; (c) the home/section landings may need `index.md` vs directory form to satisfy `navigation.indexes`. Consult the `mkdocs-literate-nav` docs via context7 (`resolve-library-id` → `query-docs`) for the SUMMARY directory-expansion + glob syntax before guessing. **Do not** declare the task done on a green _unit_ test alone — the `mkdocs build --strict` guard is the acceptance gate (CLAUDE.md: verify with the real consumer).

- [ ] **Step 5: Run both suites to verify they pass**

Run: `python3 -m pytest tests/site/test_site_structure.py tests/site/test_api_build_smoke.py -v`
Expected: PASS — unit SUMMARY tests green AND the real-consumer build guard shows "Math"/"Other" in the nav with no orphan SUMMARY page. (If `mkdocs`/plugins aren't in the env, `test_api_build_smoke.py` self-skips — in that case run the build manually per Step 6 before claiming done.)

- [ ] **Step 6: Manually confirm the real build (if the smoke test skipped)**

Run against the live dogfood tree to be certain the consumer agrees:

```bash
python3 -m pytest tests/site/test_api_build_smoke.py -v   # must NOT skip in CI env
```

If it skips locally, the implementer must note it explicitly and the controller runs the build in an env with the mkdocs plugins (the discharge step for this task is a real `mkdocs build --strict`, not a unit pass).

- [ ] **Step 7: Commit**

```bash
git add scripts/site_structure.py tests/site/test_site_structure.py tests/site/test_api_build_smoke.py
git commit -m "feat(CCE-106): generated root SUMMARY surfaces grouped API reference in nav (6i)"
```

---

## Task 9: Wiring + live-config apply + end-to-end verify (6g/6h)

**Files:**

- Modify: `scripts/orchestrator_runner.py` (`run_site_generators` lines 966-996)
- Modify: `scripts/setup_scaffold.py` (after `apply_scaffold`)
- Modify: `.engineering-docs-agent/` live tree (generated landings + SUMMARY; remove stale `.pages`)
- Test: `tests/orchestrator/` (the existing `run_site_generators` test module) + a setup-scaffold test

- [ ] **Step 1: Write the failing wiring tests**

Find the existing `run_site_generators` test (grep `run_site_generators` under `tests/`) and add a case asserting the overviews stage runs after archive/contracts and records an `info_only` partial on raise:

```python
def test_run_site_generators_runs_overviews_after_archive(monkeypatch, tmp_path):
    # build a config whose site: has a directory section with a child page, then
    # assert generate_overviews wrote the landing block AND the result dict has
    # an "overviews" key. Mirror the existing archive/contracts test setup in
    # this module.
    ...
    result = orchestrator_runner.run_site_generators(repo_root, config, state)
    assert "overviews" in result
    assert result["overviews"] is not None


def test_run_site_generators_swallows_overview_failure(monkeypatch, tmp_path):
    import section_overview
    monkeypatch.setattr(
        section_overview, "generate_overviews",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    state = {"current_run": {"partial_reasons": []}}
    # must not raise; records an info_only partial
    orchestrator_runner.run_site_generators(repo_root, config, state)
    reasons = state["current_run"]["partial_reasons"]
    assert any("overview" in str(r).lower() for r in reasons)
```

Add a setup-scaffold test (mirror the existing `tests/setup/` scaffold test) asserting a freshly-scaffolded directory section landing carries a managed block after `setup_scaffold.main`-equivalent flow, or that `setup_scaffold` calls `generate_overviews` (assert `result["overviews"]` present in the JSON output).

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/orchestrator -k "overview or site_generators" tests/setup -k "scaffold" -v`
Expected: FAIL — `run_site_generators` returns no `"overviews"` key; `setup_scaffold` doesn't call the generator.

- [ ] **Step 3: Wire `run_site_generators`**

In `scripts/orchestrator_runner.py`, extend the stage (after the contracts try/except), keeping the best-effort `info_only` pattern:

```python
    import section_overview
    ...
    result: dict = {"archive": None, "contracts": None, "overviews": None}
    ...
    try:
        result["overviews"] = section_overview.generate_overviews(repo_root, site)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        add_partial(state, f"overview_generate_failed: {exc}", info_only=True)
    return result
```

Update the docstring's `Returns` line to include `"overviews"`.

- [ ] **Step 4: Wire `setup_scaffold`**

In `scripts/setup_scaffold.py`, after `result["core_manifest"] = ...`, add:

```python
    import section_overview  # local import keeps the module list explicit
    result["overviews"] = section_overview.generate_overviews(args.repo_root, site)
```

(Run it after `apply_scaffold` + `generate_contracts` so the fresh stubs and contract pages exist for the block.)

- [ ] **Step 5: Run wiring tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator -k "overview or site_generators" tests/setup -k "scaffold" -v`
Expected: PASS.

- [ ] **Step 6: Apply to the live dogfood tree (6h)**

```bash
# regenerate the live site landings + home block + SUMMARY against live config
python3 scripts/setup_scaffold.py --repo-root . --config .engineering-docs-agent/config.yml --site-name "engineering-docs-agent" 2>&1 | tail -5 || true
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
from pathlib import Path
import yaml, section_overview, archive_indexes, contracts_doc
cfg = yaml.safe_load(Path(".engineering-docs-agent/config.yml").read_text())["site"]
print("archive:", archive_indexes.generate_archive(Path("."), cfg))
print("contracts:", contracts_doc.generate_contracts(Path("."), cfg))
print("overviews:", section_overview.generate_overviews(Path("."), cfg))
PY
# remove stale awesome-pages artifacts now that literate-nav drives the nav
git rm -q --ignore-unmatch docs/site-src/.pages docs/site-src/**/.pages 2>/dev/null || true
```

Then **manually reconcile the live home**: the live `docs/site-src/index.md` was rendered by the old `render_home` (static grid, no markers); the generator appended a block. Trim it so it reads: frontmatter + `# Documentation` + a one-line author intro + the single managed block. (Hand-edit; commit as part of this task.)

- [ ] **Step 7: Run the real consumer over the live tree**

```bash
mkdocs build --strict 2>&1 | tail -20
```

Expected: exit 0; the API tab shows grouped reference modules; Architecture / API / Operations / Decision Archive landings all render populated overview blocks; the home shows the section directory. If `mkdocs`/plugins are absent locally, state that explicitly and have the controller run it in an env with the doc-build deps (this is the task's discharge gate).

- [ ] **Step 8: Full suite + commit**

```bash
python3 -m pytest -q
```

Expected: all green (≥ the prior 900-passed baseline, plus the new CCE-106 tests; 0 failures).

```bash
git add scripts/orchestrator_runner.py scripts/setup_scaffold.py tests/ docs/site-src/ .engineering-docs-agent/
git commit -m "feat(CCE-106): wire overviews into orchestrator + setup; regenerate live site (6g/6h)"
```

---

## Final review (after all tasks)

- [ ] Dispatch a final code-reviewer subagent over the whole `feat/CCE-106-section-overviews-home` diff (controller-side, declare-then-discharge: the reviewer's findings are cross-checked against the actual diff + a real `mkdocs build --strict` + full `python3 -m pytest`).
- [ ] Run `/simplify` over the new/changed modules (`managed_block.py`, `section_overview.py`, the `site_structure.py` deltas) — keep pure-core/thin-shell, remove any incidental duplication, preserve all behavior + tests green.
- [ ] Confirm acceptance criteria 1-7 from the spec are each satisfied by a concrete test or the live build:
  1. `managed_block.py` pure + unit-tested (Task 1).
  2. schema accepts `overview: false`; generator skips (Tasks 2, 3).
  3. clobber-safe block on every landing + home, author prose preserved (Tasks 3-5).
  4. `repo_url`/`edit_uri` present with origin, omitted without (Task 6).
  5. `generate_overviews` wired into `run_site_generators` (after archive/contracts) + setup (Task 9).
  6. every landing + home populated; `mkdocs build --strict` green; full pytest green (Tasks 5, 9).
  7. generated root `SUMMARY.md` drives nav; grouped API reference in nav; no orphan `api/reference/SUMMARY/`; proven by the real-consumer build guard (Tasks 7, 8).
- [ ] Use `superpowers:finishing-a-development-branch` only when the user authorizes the PR/merge (do not push or open a PR unprompted).

## Self-review (plan author)

- **Spec coverage:** 6a→T1, 6b→T2, 6c→T3+T4, 6d→T3 (additive, see Planning notes), 6e→T5, 6f→T6, 6g→T9, 6h→T9, 6i→T7+T8. All deliverables mapped.
- **Type/name consistency:** `upsert_managed_block(existing_text, block_body)`, `generate_overviews(repo_root, site_config) -> {"written","skipped"}`, `render_directory_overview(list[(title,summary)])`, `render_api_overview(idents, groups, contract_links)`, `render_home_overview(list[(title,target)])`, `render_mkdocs_yaml(..., repo_url=None, edit_uri=None)` — used identically across tasks.
- **Placeholder scan:** Task 8's literate-nav cross-link is intentionally framed as TDD-against-the-real-consumer with a concrete starting snippet + ordered iteration guidance (not a "TODO") — this is the honest treatment of finicky third-party-plugin integration the spec mandates, not an unfilled blank.
- **Risk note:** Task 8 is the only task whose exact output the unit tests cannot fully pin; its acceptance gate is the `mkdocs build --strict` guard. If the root-SUMMARY approach cannot surface the grouped subtree under `--strict` after reasonable iteration, fall back to an explicit `nav:` for the reference subtree (the spec's named alternative) and record the decision — do not ship a half-verified nav.
