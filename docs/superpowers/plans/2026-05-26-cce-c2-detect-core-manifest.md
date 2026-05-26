# C2 — detect_core_manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stdlib detection that writes `.doc-core-manifest.json` (the declared core-page set + each page's `source_files` globs), wire it into setup, and close the sub-plan-1 path-frame handoff so `section_generator_for` resolves correctly in every frame.

**Architecture:** A new `scripts/core_manifest.py` mirrors `scripts/source_map.py` — it scans the `site:` config for the `generator: agent-authored` section, derives a deterministic page set (per-spec when specs exist, a single `system-overview` when code-only, nothing otherwise), drops entries whose globs match zero tracked files, and writes the artifact under `docs_dir`. `setup_scaffold.main` calls it after scaffolding. Separately, `frontmatter_contract.section_generator_for` gains a guarded docs_dir-relative fallback, and an end-to-end test pins the orchestrator's absolute-path frame.

**Tech Stack:** Python 3.9, stdlib-only (reuses `source_map._resolve_tracked_files` / `_glob_to_regex` and `setup_discover.detect_python`; `yaml` only transitively via those modules). pytest, TDD, `python3 -m pytest`. This sub-plan references **CCE-28** (C2 umbrella sub-task under CCE-26).

**Spec:** `docs/superpowers/specs/2026-05-26-cce-capability-c2-canonical-core-authoring-design.md` — sub-plan 2 under "Sequencing" (line 160), "The core manifest" (44-74), "Detection rules" (64-71), "Generic-first and graceful degradation" (121-127), "Testing strategy" (137-149), and the path-frame handoff in "Risks & open questions" (line 170).

---

## File Structure

- **Create `scripts/core_manifest.py`** — detection + artifact write. Two public functions: `detect_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict | None` (pure-ish: reads spec files + detects source root; returns the candidate manifest or None) and `write_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict` (drops empty-glob entries against tracked files, writes `.doc-core-manifest.json` under `docs_dir`, returns a ledger). Private helpers: `_agent_authored_section`, `_source_root_glob`, `_resolve_specs_dir`, `_spec_key`, `_title_from_key`, `_extract_source_globs`, `_dedupe_and_sort`. Placed beside `source_map.py` because it is the same kind of unit — scan config/repo, write a `.doc-*.json` sibling under `docs_dir` — and reuses that module's glob helpers. The spec's "stdlib, in setup_discover / site_structure" refers to _when_ it runs (setup); that is satisfied by `setup_scaffold` calling it.
- **Modify `scripts/setup_scaffold.py`** — `main()` calls `core_manifest.write_core_manifest(...)` after `apply_scaffold` + contracts and surfaces the ledger under the `core_manifest` key. (Nav + the agent-authored section's `index.md` stub are already produced by `apply_scaffold` for any directory section; no change there.)
- **Modify `scripts/frontmatter_contract.py`** — `section_generator_for` gains a guarded docs_dir-relative fallback. This is the only behavior change to a sub-plan-1 shared helper; its sole caller is `scripts/lint/frontmatter_schema.py:39` (verified by `grep -rn section_generator_for`), which is unaffected (it passes the same `path`/`config`).
- **Create `tests/site/test_core_manifest.py`** — detection (three shapes, ordering, collisions, extraction) + write (empty-glob drop, artifact shape) + setup-wiring (subprocess) tests.
- **Modify `tests/lint/test_frontmatter_contract.py`** — add docs_dir-relative / bare-path resolution tests for the hardened resolver.
- **Modify `tests/lint/test_frontmatter_schema.py`** — add the end-to-end orchestrator absolute-path-frame test (runs the real rule).

**Deferred to later sub-plans (do not implement):** `run_bootstrap_core` and the manifest-aware dry-run synthesizer (sub-plan 3); the flag-only drift stage and `draft → reviewed` lifecycle (sub-plan 4); any mermaid/diagram emission (waits on C3); `audit_docs.py` and per-package decomposition (deferred in the spec).

---

### Task 1: `core_manifest.py` module skeleton + section/source-root/specs-dir helpers

**Files:**

- Create: `scripts/core_manifest.py`
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/site/test_core_manifest.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import core_manifest as cm  # noqa: E402


def _site(generator="agent-authored", path="architecture/"):
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "home", "path": "index.md", "title": "Home"},
            {"key": "arch", "path": path, "title": "Architecture",
             "generator": generator},
        ],
    }


def test_agent_authored_section_found():
    s = cm._agent_authored_section(_site())
    assert s is not None and s["path"] == "architecture/"


def test_agent_authored_section_absent_returns_none():
    assert cm._agent_authored_section(_site(generator="changelog")) is None
    assert cm._agent_authored_section({}) is None
    assert cm._agent_authored_section("notadict") is None


def test_source_root_glob_python_package(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm._source_root_glob(tmp_path) == "pkg/**/*.py"


def test_source_root_glob_none_when_no_python(tmp_path):
    assert cm._source_root_glob(tmp_path) is None


def test_resolve_specs_dir_explicit_arg(tmp_path):
    d = tmp_path / "myspecs"
    d.mkdir()
    assert cm._resolve_specs_dir(tmp_path, _site(), "myspecs") == d


def test_resolve_specs_dir_from_archive_sources(tmp_path):
    specs = tmp_path / "docs" / "superpowers" / "specs"
    specs.mkdir(parents=True)
    site = _site()
    site["sections"].append(
        {"key": "archive", "path": "archive/", "generator": "archive-index",
         "sources": ["docs/superpowers/specs", "docs/superpowers/plans"]}
    )
    assert cm._resolve_specs_dir(tmp_path, site, None) == specs


def test_resolve_specs_dir_none_when_absent(tmp_path):
    assert cm._resolve_specs_dir(tmp_path, _site(), None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core_manifest'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/core_manifest.py`:

```python
"""Detect the canonical-core page set and write .doc-core-manifest.json (C2).

Detection is stdlib-only and deterministic. The artifact is a sibling to
.doc-source-map.json under docs_dir; it declares each core page and the
source_files globs M uses for file-drift. Never raises on bad input.

`site_config` is the `site:` block itself (the {docs_dir, sections, ...} dict),
matching what setup_scaffold loads from the site YAML.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discover  # noqa: E402
import source_map  # noqa: E402  reuse _resolve_tracked_files / _glob_to_regex

_CODE_EXTS = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")
_SLUG_NONWORD = re.compile(r"[^a-z0-9]+")
_BACKTICK = re.compile(r"`([^`\n]+)`")


def _agent_authored_section(site_config) -> dict | None:
    """The site section whose generator is agent-authored, or None. Never raises."""
    if not isinstance(site_config, dict):
        return None
    for s in site_config.get("sections") or []:
        if isinstance(s, dict) and s.get("generator") == "agent-authored":
            return s
    return None


def _source_root_glob(repo_root: Path) -> str | None:
    """A recursive *.py glob rooted at the detected Python scan dir, or None."""
    py = setup_discover.detect_python(Path(repo_root))
    if py.get("detected") and py.get("scan_dir"):
        return f"{py['scan_dir']}/**/*.py"
    return None


def _resolve_specs_dir(repo_root: Path, site_config, specs_dir=None) -> Path | None:
    """Resolve the specs directory: explicit arg wins; else the archive
    section's spec-like source; else docs/superpowers/specs. None if none exist.
    """
    repo_root = Path(repo_root)
    if specs_dir is not None:
        p = Path(specs_dir)
        p = p if p.is_absolute() else repo_root / p
        return p if p.is_dir() else None
    sections = site_config.get("sections") if isinstance(site_config, dict) else None
    for s in sections or []:
        if isinstance(s, dict) and s.get("generator") == "archive-index":
            for src in s.get("sources") or []:
                if isinstance(src, str) and "spec" in src.lower():
                    cand = repo_root / src
                    if cand.is_dir():
                        return cand
    default = repo_root / "docs" / "superpowers" / "specs"
    return default if default.is_dir() else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/core_manifest.py tests/site/test_core_manifest.py
git commit -m "feat(CCE-28): core_manifest helpers — section/source-root/specs-dir detection (C2 sub-plan 2)"
```

---

### Task 2: `detect_core_manifest` — specs-present shape (per-spec pages)

**Files:**

- Modify: `scripts/core_manifest.py`
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_core_manifest.py`:

```python
def test_spec_key_strips_date_and_suffix():
    assert cm._spec_key("2026-05-26-payments-api-design") == "payments-api"
    assert cm._spec_key("2026-01-02-foo-plan") == "foo"
    assert cm._spec_key("Storage Layer") == "storage-layer"


def test_title_from_key():
    assert cm._title_from_key("payments-api") == "Payments Api"
    assert cm._title_from_key("system-overview") == "System Overview"


def test_extract_source_globs_keeps_code_paths_drops_prose():
    text = (
        "See `backend/app/api/routes.py:12` and `scripts/x.py`.\n"
        "Glob `backend/**/*.py`. Prose `docs/superpowers/specs/foo` and "
        "a url `https://example.com/x` and a bare word `Connector`.\n"
    )
    assert cm._extract_source_globs(text) == [
        "backend/**/*.py",
        "backend/app/api/routes.py",
        "scripts/x.py",
    ]


def test_detect_specs_present_one_page_per_spec(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-05-26-payments-design.md").write_text(
        "Payments live in `pkg/payments.py`.\n"
    )
    (specs / "2026-05-26-storage-design.md").write_text("No code refs here.\n")

    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert manifest["version"] == 1
    pages = manifest["pages"]
    assert [p["key"] for p in pages] == ["payments", "storage"]
    payments = pages[0]
    assert payments["page"] == "architecture/payments.md"
    assert payments["title"] == "Payments"
    assert payments["source_files"] == ["pkg/payments.py"]
    # storage had no extractable refs -> falls back to the detected source root
    assert pages[1]["source_files"] == ["pkg/**/*.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: FAIL — `AttributeError: module 'core_manifest' has no attribute '_spec_key'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/core_manifest.py` (after `_resolve_specs_dir`):

```python
def _spec_key(stem: str) -> str:
    """Derive a slug key from a spec filename stem: strip a leading YYYY-MM-DD-
    and a trailing -design/-plan, then slugify. Never empty for a non-empty stem.
    """
    s = _DATE_PREFIX.sub("", stem)
    for suf in ("-design", "-plan"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    slug = _SLUG_NONWORD.sub("-", s.lower()).strip("-")
    return slug or _SLUG_NONWORD.sub("-", stem.lower()).strip("-")


def _title_from_key(key: str) -> str:
    words = key.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words) if words else key


def _extract_source_globs(text: str) -> list[str]:
    """Backtick-wrapped tokens that look like source paths: contain '/', no
    whitespace, and either carry a glob '*' or end in a code extension. A
    trailing ':line' citation suffix is stripped. Sorted + deduped. Never raises.
    """
    out: set[str] = set()
    for m in _BACKTICK.finditer(text):
        tok = m.group(1).strip()
        if not tok or " " in tok or "\t" in tok or "/" not in tok:
            continue
        base = tok.split(":", 1)[0]
        if "*" in base or base.endswith(_CODE_EXTS):
            out.add(base)
    return sorted(out)


def detect_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict | None:
    """Return {"version": 1, "pages": [...]} of candidate core pages, or None
    when there is no agent-authored section or nothing to document. Pure
    detection — no tracked-file filtering (write_core_manifest does that).
    """
    repo_root = Path(repo_root)
    section = _agent_authored_section(site_config)
    if section is None:
        return None
    section_path = section.get("path")
    section_path = section_path.strip("/") if isinstance(section_path, str) else ""
    if not section_path:
        return None

    root_glob = _source_root_glob(repo_root)
    specs = _resolve_specs_dir(repo_root, site_config, specs_dir)

    pages: list[dict] = []
    if specs is not None:
        for sp in sorted(p for p in specs.glob("*.md") if p.is_file()):
            key = _spec_key(sp.stem)
            try:
                globs = _extract_source_globs(
                    sp.read_text(encoding="utf-8", errors="replace")
                )
            except OSError:
                globs = []
            if not globs and root_glob:
                globs = [root_glob]
            pages.append(
                {
                    "key": key,
                    "title": _title_from_key(key),
                    "page": f"{section_path}/{key}.md",
                    "source_files": globs,
                }
            )

    if not pages:
        if root_glob is None:
            return None  # code-only with no detectable source root -> nothing
        key = "system-overview"
        pages = [
            {
                "key": key,
                "title": _title_from_key(key),
                "page": f"{section_path}/{key}.md",
                "source_files": [root_glob],
            }
        ]

    pages = _dedupe_and_sort(pages, section_path)
    if not pages:
        return None
    return {"version": 1, "pages": pages}
```

Add a temporary pass-through `_dedupe_and_sort` so the module imports (Task 4 replaces it):

```python
def _dedupe_and_sort(pages, section_path):
    return sorted(pages, key=lambda p: p["key"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/core_manifest.py tests/site/test_core_manifest.py
git commit -m "feat(CCE-28): detect_core_manifest specs-present shape — per-spec pages (C2 sub-plan 2)"
```

---

### Task 3: `detect_core_manifest` — code-only and nothing-detected shapes

**Files:**

- Modify: `tests/site/test_core_manifest.py` (no `core_manifest.py` change — covered by Task 2)
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_core_manifest.py`:

```python
def test_detect_code_only_single_system_overview(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir=None)
    assert [p["key"] for p in manifest["pages"]] == ["system-overview"]
    p = manifest["pages"][0]
    assert p["page"] == "architecture/system-overview.md"
    assert p["source_files"] == ["pkg/**/*.py"]


def test_detect_empty_specs_dir_falls_back_to_overview(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "specs").mkdir()  # exists but contains no *.md
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert [p["key"] for p in manifest["pages"]] == ["system-overview"]


def test_detect_nothing_when_no_agent_authored_section(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm.detect_core_manifest(tmp_path, _site(generator="changelog")) is None


def test_detect_nothing_when_no_source_root_and_no_specs(tmp_path):
    # agent-authored section exists, but no Python source and no specs
    assert cm.detect_core_manifest(tmp_path, _site()) is None


def test_detect_none_when_section_path_blank(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert cm.detect_core_manifest(tmp_path, _site(path="/")) is None
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS — these shapes are already implemented in Task 2. (If any fail, fix `detect_core_manifest` to satisfy them; do not add new behavior beyond the spec's three shapes.)

- [ ] **Step 3: No implementation needed**

Task 2's `detect_core_manifest` already covers code-only, empty-specs fallback, and the two None cases. This task locks them with tests.

- [ ] **Step 4: Re-run to confirm green**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/site/test_core_manifest.py
git commit -m "test(CCE-28): pin code-only + nothing-detected manifest shapes (C2 sub-plan 2)"
```

---

### Task 4: Deterministic ordering + key collision disambiguation

**Files:**

- Modify: `scripts/core_manifest.py:_dedupe_and_sort`
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_core_manifest.py`:

```python
def test_dedupe_and_sort_orders_by_key():
    pages = [
        {"key": "zebra", "title": "Z", "page": "arch/zebra.md", "source_files": []},
        {"key": "alpha", "title": "A", "page": "arch/alpha.md", "source_files": []},
    ]
    out = cm._dedupe_and_sort(pages, "arch")
    assert [p["key"] for p in out] == ["alpha", "zebra"]


def test_dedupe_and_sort_disambiguates_colliding_keys():
    pages = [
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["a"]},
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["b"]},
        {"key": "api", "title": "API", "page": "arch/api.md", "source_files": ["c"]},
    ]
    out = cm._dedupe_and_sort(pages, "arch")
    assert [p["key"] for p in out] == ["api", "api-2", "api-3"]
    assert [p["page"] for p in out] == [
        "arch/api.md",
        "arch/api-2.md",
        "arch/api-3.md",
    ]
    # disambiguation rewrites key + page but preserves the rest of the entry
    assert out[1]["source_files"] == ["b"]


def test_detect_collision_when_two_specs_slug_same_key(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-01-01-api-design.md").write_text("`pkg/a.py`\n")
    (specs / "2026-02-02-api-design.md").write_text("`pkg/b.py`\n")
    manifest = cm.detect_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert [p["key"] for p in manifest["pages"]] == ["api", "api-2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: FAIL — the temporary `_dedupe_and_sort` does not disambiguate (two `api` keys remain).

- [ ] **Step 3: Write the real implementation**

Replace the temporary `_dedupe_and_sort` in `scripts/core_manifest.py` with:

```python
def _dedupe_and_sort(pages: list[dict], section_path: str) -> list[dict]:
    """Sort pages by key; disambiguate a colliding key deterministically by
    appending -2, -3, ... (in sorted order) and rewriting its page path to match.
    """
    out: list[dict] = []
    seen: dict[str, int] = {}
    for p in sorted(pages, key=lambda x: x["key"]):
        k = p["key"]
        if k in seen:
            seen[k] += 1
            nk = f"{k}-{seen[k]}"
            out.append({**p, "key": nk, "page": f"{section_path}/{nk}.md"})
        else:
            seen[k] = 1
            out.append(p)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/core_manifest.py tests/site/test_core_manifest.py
git commit -m "feat(CCE-28): deterministic ordering + key collision disambiguation (C2 sub-plan 2)"
```

---

### Task 5: `write_core_manifest` — empty-glob drop + artifact write

**Files:**

- Modify: `scripts/core_manifest.py`
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_core_manifest.py`:

```python
import json as _json


def test_write_drops_empty_glob_entries_and_writes_artifact(tmp_path):
    # Source tree (no git -> _resolve_tracked_files falls back to rglob).
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "payments.py").write_text("# pay\n")
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    specs = tmp_path / "specs"
    specs.mkdir()
    # payments.md -> matches a tracked file; ghost.md -> matches nothing (dropped)
    (specs / "2026-05-26-payments-design.md").write_text("`pkg/payments.py`\n")
    (specs / "2026-05-26-ghost-design.md").write_text("`pkg/does_not_exist.py`\n")

    ledger = cm.write_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert ledger["written"] == ["docs/site-src/.doc-core-manifest.json"]
    assert ledger["pages"] == 1
    assert ledger["dropped"] == ["ghost"]

    art = _json.loads(
        (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").read_text()
    )
    assert art["version"] == 1
    assert [p["key"] for p in art["pages"]] == ["payments"]
    assert art["pages"][0]["source_files"] == ["pkg/payments.py"]


def test_write_no_manifest_when_detection_returns_none(tmp_path):
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    ledger = cm.write_core_manifest(tmp_path, _site())  # no source, no specs
    assert ledger == {"written": [], "pages": 0, "dropped": []}
    assert not (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").exists()


def test_write_no_manifest_when_all_entries_dropped(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "docs" / "site-src").mkdir(parents=True)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "2026-05-26-ghost-design.md").write_text("`pkg/missing.py`\n")
    # Force the overview/per-spec glob to match nothing by removing the only .py
    (tmp_path / "pkg" / "__init__.py").unlink()
    ledger = cm.write_core_manifest(tmp_path, _site(), specs_dir="specs")
    assert ledger["written"] == []
    assert not (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: FAIL — `AttributeError: module 'core_manifest' has no attribute 'write_core_manifest'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/core_manifest.py` (after `detect_core_manifest`):

```python
def write_core_manifest(repo_root, site_config, *, specs_dir=None) -> dict:
    """Detect the manifest, drop entries whose globs match zero tracked files,
    and write <docs_dir>/.doc-core-manifest.json. Returns a ledger
    {"written": [...], "pages": N, "dropped": [keys]}. Writes nothing when
    detection yields None, docs_dir is unusable, or every entry is dropped.
    """
    repo_root = Path(repo_root)
    ledger: dict = {"written": [], "pages": 0, "dropped": []}
    manifest = detect_core_manifest(repo_root, site_config, specs_dir=specs_dir)
    if manifest is None:
        return ledger
    docs_dir = site_config.get("docs_dir") if isinstance(site_config, dict) else None
    if not isinstance(docs_dir, str) or not docs_dir.strip("/"):
        return ledger

    tracked = source_map._resolve_tracked_files(repo_root)
    kept: list[dict] = []
    for p in manifest["pages"]:
        regexes = [source_map._glob_to_regex(g) for g in p["source_files"]]
        if regexes and any(r.fullmatch(f) for r in regexes for f in tracked):
            kept.append(p)
        else:
            ledger["dropped"].append(p["key"])
    if not kept:
        return ledger

    artifact = {"version": 1, "pages": kept}
    out_rel = f"{docs_dir.rstrip('/')}/.doc-core-manifest.json"
    (repo_root / out_rel).write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )
    ledger["written"] = [out_rel]
    ledger["pages"] = len(kept)
    return ledger
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/core_manifest.py tests/site/test_core_manifest.py
git commit -m "feat(CCE-28): write_core_manifest — empty-glob drop + artifact write (C2 sub-plan 2)"
```

---

### Task 6: Setup wiring — `setup_scaffold.main` writes the manifest

**Files:**

- Modify: `scripts/setup_scaffold.py:24-26` (imports), `scripts/setup_scaffold.py:74-75` (after contracts)
- Test: `tests/site/test_core_manifest.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/site/test_core_manifest.py`:

```python
import subprocess


def test_setup_scaffold_main_writes_manifest(tmp_path):
    """End-to-end: running setup_scaffold against a host with an agent-authored
    section + Python source writes .doc-core-manifest.json and reports it."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("# core\n")
    cfg = tmp_path / "site.yaml"
    cfg.write_text(
        "docs_dir: docs/site-src\n"
        "theme: material\n"
        "sections:\n"
        "  - {key: home, path: index.md, title: Home}\n"
        "  - key: architecture\n"
        "    path: architecture/\n"
        "    title: Architecture\n"
        "    generator: agent-authored\n"
    )
    scaffold = Path(__file__).resolve().parents[2] / "scripts" / "setup_scaffold.py"
    r = subprocess.run(
        [sys.executable, str(scaffold), "--repo-root", str(tmp_path),
         "--config", str(cfg)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    assert out["core_manifest"]["written"] == [
        "docs/site-src/.doc-core-manifest.json"
    ]
    art = _json.loads(
        (tmp_path / "docs" / "site-src" / ".doc-core-manifest.json").read_text()
    )
    assert [p["key"] for p in art["pages"]] == ["system-overview"]
    assert art["pages"][0]["source_files"] == ["pkg/**/*.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/site/test_core_manifest.py::test_setup_scaffold_main_writes_manifest -q`
Expected: FAIL — `KeyError: 'core_manifest'` (the key is not yet in the output).

- [ ] **Step 3: Write minimal implementation**

In `scripts/setup_scaffold.py`, add the import alongside the others (after `import site_structure`):

```python
import core_manifest  # noqa: E402
```

Then, in `main()`, immediately after the line `result["contracts"] = contracts_doc.generate_contracts(args.repo_root, site)`:

```python
    result["core_manifest"] = core_manifest.write_core_manifest(args.repo_root, site)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/site/test_core_manifest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_scaffold.py tests/site/test_core_manifest.py
git commit -m "feat(CCE-28): setup writes .doc-core-manifest.json (C2 sub-plan 2)"
```

---

### Task 7: Path-frame handoff — guarded docs_dir-relative fallback in `section_generator_for`

**Files:**

- Modify: `scripts/frontmatter_contract.py:24-63`
- Test: `tests/lint/test_frontmatter_contract.py`

**Context (spec line 170):** `section_generator_for` matches `docs_dir/section` as a segment-bounded substring of the page path. Absolute and repo-relative paths (the orchestrator's real frame) work because the repo-relative section suffix is embedded in them. A docs_dir-relative or bare page path silently yields the default field set — a silent wrong-answer. This task makes the match robust to those frames with a **purely additive** fallback: it runs only when the full `docs_dir/section` match found nothing **and** the `docs_dir` segment is absent from the page path, so no currently-matching path can change. Its sole caller is `scripts/lint/frontmatter_schema.py:39` (verified via `grep -rn section_generator_for scripts/`); the caller is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/lint/test_frontmatter_contract.py`:

```python
def test_section_generator_for_docs_dir_relative_page():
    # docs_dir absent from the page path -> resolves via the section path alone.
    assert fc.section_generator_for("core/api.md", _CONFIG) == "agent-authored"
    assert fc.section_generator_for(Path("core/api.md"), _CONFIG) == "agent-authored"


def test_section_generator_for_bare_file_section_page():
    assert fc.section_generator_for("whats-new.md", _CONFIG) == "changelog"


def test_section_generator_for_docs_dir_relative_no_section_is_none():
    assert fc.section_generator_for("elsewhere/x.md", _CONFIG) is None


def test_section_generator_for_under_docs_dir_no_section_stays_none():
    # docs_dir IS present but no section contains the page -> None (no fallback).
    assert fc.section_generator_for("/r/docs/site-src/elsewhere/x.md", _CONFIG) is None


def test_section_generator_for_docs_dir_relative_longest_match_wins():
    cfg = {
        "site": {
            "docs_dir": "docs/site-src",
            "sections": [
                {"key": "arch", "path": "architecture/", "title": "A",
                 "generator": "agent-authored"},
                {"key": "home", "path": "index.md", "title": "H"},
            ],
        }
    }
    # bare-frame page under architecture/ still resolves agent-authored
    assert fc.section_generator_for("architecture/index.md", cfg) == "agent-authored"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py -q`
Expected: FAIL — docs_dir-relative pages currently return None (the silent wrong-answer).

- [ ] **Step 3: Write the implementation**

Replace the body of `section_generator_for` in `scripts/frontmatter_contract.py` (keep the signature and the leading docstring; update the docstring's frame paragraph). New implementation:

```python
def section_generator_for(page: Path | str, config: dict) -> str | None:
    """Return the generator of the site section that contains ``page``, or None.

    Matches the section whose ``docs_dir/path`` is a path-segment prefix of the
    page (longest match wins, so a nested section beats its parent). Returns
    None when there is no ``site:`` block, no ``docs_dir``, or no match — which
    yields the default field set. Never raises (malformed config -> None).

    Frame-robust: absolute and repo-relative pages match via the embedded
    ``docs_dir/path`` suffix. A docs_dir-relative or bare page (one lacking the
    ``docs_dir`` segment entirely) falls back to matching the section ``path``
    alone, so callers in any frame resolve correctly. The fallback fires only
    when the full match found nothing AND ``docs_dir`` is absent from the page,
    so it cannot change the result for any path that already matches.
    """
    site = config.get("site") if isinstance(config, dict) else None
    if not isinstance(site, dict):
        return None
    docs_dir = site.get("docs_dir")
    docs_dir = docs_dir.strip("/") if isinstance(docs_dir, str) else ""
    sections = site.get("sections")
    if not docs_dir or not isinstance(sections, list):
        return None
    try:
        page_posix = Path(page).as_posix()
    except TypeError:
        return None
    bounded = f"/{page_posix}/"  # segment-bounded haystack

    def _best(needle_for) -> tuple[int, str | None]:
        best_len, best_gen = -1, None
        for s in sections:
            if not isinstance(s, dict):
                continue
            rel = s.get("path")
            rel = rel.strip("/") if isinstance(rel, str) else ""
            if not rel:
                continue
            needle = needle_for(rel)
            if f"/{needle}/" in bounded and len(needle) > best_len:
                best_len = len(needle)
                best_gen = s.get("generator")
        return best_len, best_gen

    # Frame 1 — absolute / repo-relative: page embeds docs_dir/section.
    full_len, full_gen = _best(lambda rel: str(PurePosixPath(docs_dir) / rel))
    if full_len >= 0:
        return full_gen
    # Frame 2 — docs_dir-relative / bare: only when docs_dir is truly absent,
    # so a page under docs_dir that matched no section stays None.
    if f"/{docs_dir}/" in bounded:
        return None
    return _best(lambda rel: rel)[1]
```

- [ ] **Step 4: Run test to verify it passes (and no regression)**

Run: `python3 -m pytest tests/lint/test_frontmatter_contract.py tests/lint/test_frontmatter_schema.py -q`
Expected: PASS — all new tests plus the existing absolute/repo-relative, segment-bounded, and malformed-config tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/frontmatter_contract.py tests/lint/test_frontmatter_contract.py
git commit -m "fix(CCE-28): section_generator_for resolves docs_dir-relative pages — close sub-plan-1 path-frame handoff (C2 sub-plan 2)"
```

---

### Task 8: End-to-end orchestrator absolute-path-frame test

**Files:**

- Modify: `tests/lint/test_frontmatter_schema.py`
- Test: `tests/lint/test_frontmatter_schema.py`

**Context:** The orchestrator authors each page at the absolute path `repo_root / lens_path / hint` (`scripts/orchestrator_runner.py:763`) and hands those absolute paths to the `frontmatter_schema` block rule via `lint_runner.run_rule` (subprocess: `--config <cfg> --paths <abs> --json`). This test pins that real frame end-to-end: with a `site:` block carrying an `agent-authored` section, a C2-frontmatter page authored at the absolute frame must resolve `agent-authored` and **pass** the rule; the same page missing a C2 field must **fail** — proving the rule fires at this frame rather than silently defaulting.

- [ ] **Step 1: Write the failing test**

First check the existing import header at the top of `tests/lint/test_frontmatter_schema.py` and reuse it. Append this test (it invokes the real rule script as a subprocess, exactly as `lint_runner` does):

```python
import json as _json
import subprocess as _sp
import sys as _sys

_RULE = (
    Path(__file__).resolve().parents[2] / "scripts" / "lint" / "frontmatter_schema.py"
)


def _run_rule(config_path: Path, page: Path) -> dict:
    r = _sp.run(
        [_sys.executable, str(_RULE), "--config", str(config_path),
         "--paths", str(page), "--json"],
        capture_output=True, text=True,
    )
    return _json.loads(r.stdout)


def test_orchestrator_absolute_path_frame_resolves_agent_authored(tmp_path):
    # Config with a real site: block and an agent-authored section.
    config = tmp_path / "config.yml"
    config.write_text(
        "site:\n"
        "  docs_dir: docs/site-src\n"
        "  sections:\n"
        "    - key: architecture\n"
        "      path: architecture/\n"
        "      title: Architecture\n"
        "      generator: agent-authored\n"
    )
    # Page at the orchestrator's real frame: repo_root / docs_dir / section / file
    page = tmp_path / "docs" / "site-src" / "architecture" / "system-overview.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "description: System overview\n"
        "source_files:\n"
        "  - scripts/**/*.py\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# System overview\n"
    )
    out = _run_rule(config, page)
    assert out["results"][0]["ok"] is True, out["results"][0]["message"]

    # Negative: drop a C2-required field -> rule must block at this same frame.
    page.write_text(
        "---\n"
        "source_files:\n"
        "  - scripts/**/*.py\n"
        "last_reviewed: 2026-05-26\n"
        "status: draft\n"
        "---\n\n# System overview\n"
    )
    out = _run_rule(config, page)
    assert out["results"][0]["ok"] is False
    assert "description" in out["results"][0]["message"]
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py::test_orchestrator_absolute_path_frame_resolves_agent_authored -q`
Expected: PASS — Task 7's resolver already handles the absolute frame (the full-match pass), so this is a regression guard locking it. (If it fails, the frame is broken; fix the resolver before proceeding.)

- [ ] **Step 3: No implementation needed**

The behavior is provided by Task 7. This test exists to pin the orchestrator's real absolute-path frame so a future refactor that breaks it fails loudly.

- [ ] **Step 4: Re-run to confirm green**

Run: `python3 -m pytest tests/lint/test_frontmatter_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/lint/test_frontmatter_schema.py
git commit -m "test(CCE-28): pin orchestrator absolute-path frame for agent-authored resolution (C2 sub-plan 2)"
```

---

### Task 9: Full-suite verification

**Files:**

- None (verification only)

- [ ] **Step 1: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS — all prior tests plus the new `core_manifest`, resolver, and frame tests. Baseline before this sub-plan was 432 passed, 3 skipped; expect that plus the new tests, 0 failures.

- [ ] **Step 2: Confirm no stray artifacts and stdlib-only**

Run: `git status --porcelain` (expect clean after commits) and visually confirm `scripts/core_manifest.py` imports only `json`, `re`, `sys`, `pathlib`, and the sibling `setup_discover` / `source_map` modules — no new third-party runtime dependency.

- [ ] **Step 3: Commit (only if Step 1/2 surfaced a fix)**

```bash
git add -A
git commit -m "test(CCE-28): full-suite green for detect_core_manifest (C2 sub-plan 2)"
```

---

## Self-Review

**1. Spec coverage:**

- "Detection → `.doc-core-manifest.json` artifact under `docs_dir`" → Tasks 5, 6.
- Artifact shape `{version, pages:[{key,title,page,source_files}]}` (spec 48-60) → Task 2/5 (`{"version": 1, "pages": [...]}`).
- Specs-present → one page per spec; source_files from referenced paths else source root (spec 66) → Task 2.
- Code-only → single `system-overview` (spec 67) → Task 3.
- Nothing detected → no manifest, never empty (spec 68, 123) → Task 3 + Task 5 (`detect` None and all-dropped both skip the write).
- Empty-glob entries dropped at build (spec 69, 124) → Task 5.
- Deterministic sorted order + colliding keys disambiguated (spec 70) → Task 4.
- Section identity by `generator: agent-authored`, never `core`/`architecture` (spec 72-74) → Task 1 `_agent_authored_section`; the section's own `path` supplies the page prefix.
- Setup writes the manifest; nav + index stub (spec 160) → Task 6 (manifest); nav + index stub already produced by `apply_scaffold` for the agent-authored directory section (noted in File Structure; scaffold stubs are not frontmatter-gated, per the shipped home page).
- Path-frame handoff: normalize/robust + e2e absolute-frame test (spec 170) → Tasks 7, 8.
- Deferred items (bootstrap, drift, mermaid, audit_docs, per-package) → explicitly excluded in File Structure.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N". Every code step shows complete code; every run step shows the command and expected result.

**3. Type consistency:** `detect_core_manifest`/`write_core_manifest` signatures `(repo_root, site_config, *, specs_dir=None)` are identical across Tasks 2/5/6. Page dict keys `{key, title, page, source_files}` consistent across Tasks 2/4/5. `_dedupe_and_sort(pages, section_path)` signature matches its caller in `detect_core_manifest`. Ledger shape `{"written", "pages", "dropped"}` consistent across Task 5/6. `_best`/`needle_for` are local to Task 7's function. `site_config` is the `site:` block (the `{docs_dir, sections}` dict) everywhere — matching `setup_scaffold`'s `site`.

---

## Execution Coda

After all tasks are green:

1. **Execute via subagent-driven-development.** Fresh implementer subagent per task on branch `feat/CCE-28-detect-core-manifest` (created off `main`); two-stage review after each task (spec-compliance, then code-quality); fix loops until both pass. Mechanical tasks (1-6, 8, 9) use a fast model; Task 7 (the shared-helper contract change) uses a standard model. Tasks 7/8 touch `frontmatter_contract.py` — a sub-plan-1 shared helper — so confirm `grep -rn section_generator_for scripts/` shows only `frontmatter_schema.py` as caller before changing it.
2. **Final whole-branch review.** Dispatch a final code reviewer over the full branch diff (`origin/main..HEAD`).
3. **Ship.** Run `/ship` with base `main`. Stages 2-4 (verify-agent / simplify / code-review) fold into the subagent-driven reviews already performed; the mechanical stages (test, commit, push+PR, Jira) still run. PR base `main`.
4. **Reference CCE-28.** PR title and commits include `CCE-28`; comment on PR open. Merge to `main` and the Jira transition require explicit user authorization — surface them, do not self-authorize. On merge, update CCE-28's description marking sub-plan 2 landed (sub-plans 3-4 remain).
