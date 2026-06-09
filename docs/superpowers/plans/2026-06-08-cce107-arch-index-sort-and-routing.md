# CCE-107 — Architecture index semantic sort + architecture-vs-archive routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Order every directory-section overview by freshness, and route decision/ADR narrative to the archive section via a testable `doc_kind` seam — then migrate the 5 mis-routed dogfood pages.

**Architecture:** Deliverable A extends `section_overview._scan_children` to sort children by a `last_reviewed`-derived freshness key (generic across all directory sections). Deliverable B adds a pure `doc_routing` module (agent emits `doc_kind`; code maps `decision` → the archive-index section by generator marker), wires it into the orchestrator's create-routing, and performs a one-time, link-safe file migration verified by `mkdocs build --strict`.

**Tech Stack:** Python 3 (stdlib + `yaml`, `jsonschema` for tests), pytest, mkdocs-material + mkdocs-literate-nav. Production agent dispatch is monkeypatched in unit tests; the dry-run pipeline harness lives in `tests/orchestrator/test_pipeline_integration.py`.

**Spec:** `docs/superpowers/specs/2026-06-08-cce107-arch-index-sort-and-routing-design.md`

---

## File Structure

| File                                              | Responsibility                                    | Change                                                             |
| ------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------ |
| `scripts/section_overview.py`                     | Overview block rendering + scan                   | Add `_freshness_key`; sort in `_scan_children`                     |
| `scripts/doc_routing.py`                          | **New.** Pure `doc_kind → section` mapping        | Create                                                             |
| `agents/schemas/pr_summarizer.schema.json`        | pr-summarizer output contract                     | Add optional `doc_kind` enum                                       |
| `agents/pr-summarizer.md`                         | pr-summarizer prompt + canonical schema block     | Mirror schema; document `doc_kind`                                 |
| `scripts/orchestrator_runner.py`                  | Routing + page authoring loop (`run`, ~1171-1230) | Apply `route_create_hint`; pass `doc_kind` to frontmatter template |
| `tests/site/test_section_overview.py`             | Overview tests                                    | Extend: freshness order + `_freshness_key`                         |
| `tests/site/test_doc_routing.py`                  | **New.** Routing unit tests                       | Create                                                             |
| `tests/schemas/test_pr_summarizer_schema.py`      | Schema tests                                      | Extend: `doc_kind` accept/reject                                   |
| `tests/orchestrator/test_pipeline_integration.py` | Pipeline dry-run                                  | Extend: decision target → archive                                  |
| `tests/orchestrator/fakes_routing/`               | **New.** Fakes for routing test                   | Create                                                             |
| `docs/site-src/{architecture,archive}/*.md`       | Dogfood content                                   | One-time migration (Task 5)                                        |

**Scope note (deviation from spec §B1, deliberate):** the spec says "page-author persists `doc_kind` into frontmatter." This plan passes `doc_kind` into the page-author frontmatter _template_ (best-effort guidance the real agent honors), but the **tested** going-forward behavior is _routing_ (the page physically lands in the archive section). The migration (Task 5) is what deterministically stamps `doc_kind` frontmatter on the 20 existing pages. Rationale: a new page's section _is_ its classification, and frontmatter written by the LLM page-author is not deterministically unit-testable. Flag to the operator if stronger frontmatter enforcement is wanted.

---

## Task 1: Freshness sort for directory-section overviews

**Files:**

- Modify: `scripts/section_overview.py` (add `_freshness_key`; rewrite `_scan_children` body, currently `:48-65`)
- Test: `tests/site/test_section_overview.py`

- [ ] **Step 1: Write the failing tests for the pure helper**

Add to `tests/site/test_section_overview.py`:

```python
import datetime


def test_freshness_key_prefers_last_reviewed():
    assert so._freshness_key({"last_reviewed": "2026-05-01"}, "foo.md") == "2026-05-01"


def test_freshness_key_coerces_date_object():
    # YAML parses an unquoted `last_reviewed: 2026-05-01` to a datetime.date;
    # comparing that against the "" fallback during sort would raise TypeError.
    assert (
        so._freshness_key({"last_reviewed": datetime.date(2026, 5, 1)}, "foo.md")
        == "2026-05-01"
    )


def test_freshness_key_falls_back_to_filename_date():
    assert so._freshness_key({}, "2026-03-15-foo.md") == "2026-03-15"


def test_freshness_key_empty_when_no_date():
    assert so._freshness_key({}, "foo.md") == ""
```

- [ ] **Step 2: Run them; verify they fail**

Run: `python3 -m pytest tests/site/test_section_overview.py -k freshness_key -v`
Expected: FAIL — `AttributeError: module 'section_overview' has no attribute '_freshness_key'`.

- [ ] **Step 3: Implement `_freshness_key`**

Add to `scripts/section_overview.py` (above `_scan_children`):

```python
def _freshness_key(frontmatter: dict, filename: str) -> str:
    """ISO date string used to order a child page, newest first. Prefers the
    ``last_reviewed`` frontmatter field (coerced to str — an unquoted YAML date
    parses to ``datetime.date``, which must not reach a string comparison), then
    a ``YYYY-MM-DD-`` filename prefix, then ``""`` (sorts last)."""
    lr = frontmatter.get("last_reviewed")
    if lr:
        return str(lr)
    if archive_indexes.DATE_PREFIX.match(filename):
        return filename[:10]
    return ""
```

- [ ] **Step 4: Run; verify the helper tests pass**

Run: `python3 -m pytest tests/site/test_section_overview.py -k freshness_key -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Write the failing ordering tests**

Add to `tests/site/test_section_overview.py` (reuses existing `_dir_site`/`_seed_landing` helpers in that file):

```python
def test_overview_orders_by_last_reviewed_desc(tmp_path):
    site = _dir_site()  # home + architecture (directory section)
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/old.md",
        "---\nlast_reviewed: '2026-01-01'\n---\n\n# Old Page\n\nold.\n",
    )
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/new.md",
        "---\nlast_reviewed: '2026-05-01'\n---\n\n# New Page\n\nnew.\n",
    )
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("New Page") < out.index("Old Page")


def test_overview_undated_page_sinks_last(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(
        tmp_path,
        "docs/site-src/architecture/dated.md",
        "---\nlast_reviewed: '2026-05-01'\n---\n\n# Dated Page\n\nd.\n",
    )
    _seed_landing(
        tmp_path, "docs/site-src/architecture/undated.md", "# Undated Page\n\nu.\n"
    )
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("Dated Page") < out.index("Undated Page")


def test_overview_title_tiebreak_when_equal_freshness(tmp_path):
    site = _dir_site()
    _seed_landing(tmp_path, "docs/site-src/architecture/index.md", "# Architecture\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/b.md", "# Banana\n\nb.\n")
    _seed_landing(tmp_path, "docs/site-src/architecture/a.md", "# Apple\n\na.\n")
    so.generate_overviews(tmp_path, site)
    out = (tmp_path / "docs/site-src/architecture/index.md").read_text()
    assert out.index("Apple") < out.index("Banana")  # both undated -> title asc
```

- [ ] **Step 6: Run; verify they fail**

Run: `python3 -m pytest tests/site/test_section_overview.py -k "orders_by or sinks_last or tiebreak" -v`
Expected: FAIL — current `_scan_children` sorts by filename, so `Old Page` (file `old.md`) precedes `New Page`, and undated/title order is wrong.

- [ ] **Step 7: Rewrite `_scan_children` to sort by freshness**

Replace the body of `_scan_children` in `scripts/section_overview.py` (the loop currently at `:54-65`) with:

```python
def _scan_children(section_dir: Path) -> list[tuple[str, str]]:
    """(title, summary) per child *.md, excluding index.md and _*-prefixed,
    ordered newest-``last_reviewed``-first (undated last), title-ascending as the
    stable tiebreak. Best-effort: a child that fails to read is skipped, not raised."""
    scanned: list[tuple[str, str, str]] = []  # (freshness, title, summary)
    if not section_dir.is_dir():
        return []
    for md in section_dir.glob("*.md"):
        if md.name == "index.md" or md.name.startswith("_"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        title, summary = archive_indexes.parse_title_and_summary(text)
        title = archive_indexes._strip_inline_links(title) or md.stem
        summary = archive_indexes._strip_inline_links(summary)
        freshness = _freshness_key(archive_indexes.parse_frontmatter(text), md.name)
        scanned.append((freshness, title, summary))
    scanned.sort(key=lambda c: c[1].lower())        # title asc (stable tiebreak)
    scanned.sort(key=lambda c: c[0], reverse=True)   # freshness desc; "" sinks last
    return [(title, summary) for _f, title, summary in scanned]
```

- [ ] **Step 8: Run the full section-overview suite**

Run: `python3 -m pytest tests/site/test_section_overview.py -v`
Expected: PASS (all prior tests + the 7 new ones). The earlier `test_generate_overviews_directory_section` etc. still pass — return shape is unchanged.

- [ ] **Step 9: Commit**

```bash
git add scripts/section_overview.py tests/site/test_section_overview.py
git commit -m "feat(CCE-107): freshness-order directory overviews by last_reviewed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `doc_routing` pure module

**Files:**

- Create: `scripts/doc_routing.py`
- Test: `tests/site/test_doc_routing.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/site/test_doc_routing.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import doc_routing as dr  # noqa: E402


def _site(archive_path="archive/"):
    return {
        "docs_dir": "docs/site-src",
        "sections": [
            {"key": "architecture", "path": "architecture/", "generator": "agent-authored"},
            {"key": "archive", "path": archive_path, "generator": "archive-index"},
        ],
    }


def test_archive_section_leaf_finds_generator_marker():
    assert dr.archive_section_leaf(_site()) == "archive"


def test_archive_section_leaf_honors_custom_name():
    assert dr.archive_section_leaf(_site("decisions/")) == "decisions"


def test_archive_section_leaf_none_when_absent():
    assert dr.archive_section_leaf({"sections": [{"key": "x", "path": "x/"}]}) is None
    assert dr.archive_section_leaf({}) is None


def test_route_decision_rewrites_to_archive():
    assert (
        dr.route_create_hint("architecture/foo.md", "decision", "archive", ["architecture", "archive"])
        == "archive/foo.md"
    )


def test_route_decision_honors_custom_archive_name():
    assert (
        dr.route_create_hint("architecture/foo.md", "decision", "decisions", ["architecture", "decisions"])
        == "decisions/foo.md"
    )


def test_route_architecture_unchanged():
    assert (
        dr.route_create_hint("architecture/foo.md", "architecture", "archive", ["architecture", "archive"])
        == "architecture/foo.md"
    )


def test_route_absent_doc_kind_unchanged():
    assert (
        dr.route_create_hint("architecture/foo.md", None, "archive", ["architecture", "archive"])
        == "architecture/foo.md"
    )


def test_route_no_archive_section_unchanged():
    assert (
        dr.route_create_hint("architecture/foo.md", "decision", None, ["architecture"])
        == "architecture/foo.md"
    )


def test_route_archive_not_available_unchanged():
    # generic-first: archive declared in config but its dir not yet on disk
    assert (
        dr.route_create_hint("architecture/foo.md", "decision", "archive", ["architecture"])
        == "architecture/foo.md"
    )


def test_route_preserves_filename_only():
    assert (
        dr.route_create_hint("architecture/sub/bar.md", "decision", "archive", ["architecture", "archive"])
        == "archive/bar.md"
    )
```

- [ ] **Step 2: Run; verify they fail**

Run: `python3 -m pytest tests/site/test_doc_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'doc_routing'`.

- [ ] **Step 3: Implement `scripts/doc_routing.py`**

```python
"""Deterministic architecture-vs-archive routing (CCE-107).

The pr-summarizer emits a per-target ``doc_kind`` ("architecture" | "decision").
``route_create_hint`` maps a *decision* page to the host's archive-index section
(discovered by generator marker via ``archive_indexes._find_archive_section`` —
never a hardcoded name); every other case keeps the agent's chosen hint. Pure
functions: no I/O, no agent dependence, so the routing decision is unit-testable
unlike the agent's semantic judgment. Generic-first: a host with no archive-index
section (``archive_section`` is None) leaves all hints untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_indexes  # noqa: E402


def archive_section_leaf(site_config: dict) -> str | None:
    """Leaf directory name of the section whose generator is ``archive-index``,
    or None when the host declares no such section."""
    section = archive_indexes._find_archive_section(site_config or {})
    if not section:
        return None
    path = str(section.get("path") or "").rstrip("/")
    return path.rsplit("/", 1)[-1] or None


def route_create_hint(
    page_hint: str,
    doc_kind: str | None,
    archive_section: str | None,
    available_sections: list[str],
) -> str:
    """Rewrite a *decision* create-target's hint into the archive section.

    ``doc_kind == "decision"`` AND an archive section exists AND it is present in
    ``available_sections`` -> ``"<archive_section>/<filename>"``. Any other case
    (architecture/unknown/absent ``doc_kind``, no archive section, or the archive
    dir not yet on disk) returns ``page_hint`` unchanged.
    """
    if (
        doc_kind == "decision"
        and archive_section
        and archive_section in available_sections
    ):
        filename = page_hint.rsplit("/", 1)[-1]
        return f"{archive_section}/{filename}"
    return page_hint
```

- [ ] **Step 4: Run; verify they pass**

Run: `python3 -m pytest tests/site/test_doc_routing.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/doc_routing.py tests/site/test_doc_routing.py
git commit -m "feat(CCE-107): doc_routing — deterministic decision->archive mapping

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: pr-summarizer `doc_kind` contract (schema + prompt)

**Files:**

- Modify: `agents/schemas/pr_summarizer.schema.json` (`doc_targets` item properties)
- Modify: `agents/pr-summarizer.md` (the `## Output schema (canonical)` block + Procedure step 6)
- Test: `tests/schemas/test_pr_summarizer_schema.py`

- [ ] **Step 1: Write the failing schema tests**

Add to `tests/schemas/test_pr_summarizer_schema.py`:

```python
def test_doc_kind_decision_accepted(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "architecture/foo.md",
             "doc_kind": "decision"}
        ],
    }
    validator.validate(doc)  # must NOT raise


def test_doc_kind_architecture_accepted(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "architecture/foo.md",
             "doc_kind": "architecture"}
        ],
    }
    validator.validate(doc)


def test_doc_kind_invalid_value_rejected(validator: Draft7Validator) -> None:
    doc = {
        "pr_number": 1,
        "doc_targets": [
            {"lens": "core", "action": "create", "page_hint": "architecture/foo.md",
             "doc_kind": "ops"}
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)
```

- [ ] **Step 2: Run; verify they fail**

Run: `python3 -m pytest tests/schemas/test_pr_summarizer_schema.py -k doc_kind -v`
Expected: FAIL — `doc_kind` is rejected by `additionalProperties: false` (so the "decision accepted" tests fail).

- [ ] **Step 3: Add `doc_kind` to the JSON schema**

In `agents/schemas/pr_summarizer.schema.json`, inside the `doc_targets.items.properties` object, add the `doc_kind` key after `page_hint` (do NOT add it to the item's `required`):

```json
          "page_hint": {
            "type": "string",
            "allOf": [
              { "pattern": "^[^/].*\\.md$" },
              {
                "not": {
                  "pattern": "\\.(py|json|yml|yaml|ts|tsx|js|sh|toml|rs|go|java|cpp|c|h|hpp)$"
                }
              }
            ]
          },
          "doc_kind": { "type": "string", "enum": ["architecture", "decision"] }
```

- [ ] **Step 4: Mirror the schema into the agent `.md` canonical block**

The drift test `tests/agents/test_schema_md_sync.py` requires the `## Output schema (canonical)` fenced JSON in `agents/pr-summarizer.md` to be `json.loads`-equal to the schema file. Read the current block in `agents/pr-summarizer.md` and add the identical `"doc_kind": { "type": "string", "enum": ["architecture", "decision"] }` line in the same `doc_targets.items.properties` position. (The two files must be JSON-equivalent — copy the whole updated schema if easier.)

- [ ] **Step 5: Document `doc_kind` in Procedure step 6**

In `agents/pr-summarizer.md`, in the `action: create` rules under step 6, add a bullet after the section-matching list:

```markdown
- `doc_kind` (optional): set `decision` when the page is an investigation,
  postmortem, ADR, roadmap, or release note (it documents _why/what we
  decided at a point in time_); set `architecture` for an evergreen "how it
  works today" reference. Omit when unsure — the orchestrator treats a
  missing value as `architecture`. A `decision` page is routed to the
  archive section automatically; you need not change `page_hint` for it.
```

- [ ] **Step 6: Run the schema + sync tests**

Run: `python3 -m pytest tests/schemas/test_pr_summarizer_schema.py tests/agents/test_schema_md_sync.py -v`
Expected: PASS — all prior schema tests, the 3 new `doc_kind` tests, and `test_md_schema_block_matches_canonical_schema_file[pr-summarizer]`.

- [ ] **Step 7: Commit**

```bash
git add agents/schemas/pr_summarizer.schema.json agents/pr-summarizer.md tests/schemas/test_pr_summarizer_schema.py
git commit -m "feat(CCE-107): pr-summarizer doc_kind contract (architecture|decision)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire `doc_routing` into the orchestrator

**Files:**

- Modify: `scripts/orchestrator_runner.py` (the page-authoring block, `:1171-1217`)
- Create: `tests/orchestrator/fakes_routing/` (5 fake JSON files)
- Test: `tests/orchestrator/test_pipeline_integration.py`

- [ ] **Step 1: Create the routing fakes directory**

Create these five files (the dry-run harness reads one per subagent; all but pr-summarizer mirror `tests/orchestrator/fakes/`):

`tests/orchestrator/fakes_routing/fake_source_collector.json`:

```json
{
  "prs": [
    {
      "number": 1,
      "title": "Investigate parse failure",
      "url": "https://github.com/o/n/pull/1",
      "body": "root cause sweep",
      "jira_keys": [],
      "files": ["scripts/orchestrator_runner.py"]
    }
  ],
  "jira_issues": []
}
```

`tests/orchestrator/fakes_routing/fake_pr_summarizer.json`:

```json
{
  "pr_number": 1,
  "what_changed": "Root-cause sweep",
  "why": "Parsing failed",
  "breaking": false,
  "doc_targets": [
    {
      "lens": "core",
      "action": "create",
      "page_hint": "architecture/root-cause-sweep.md",
      "doc_kind": "decision"
    }
  ],
  "notes": null
}
```

`tests/orchestrator/fakes_routing/fake_page_author.json`:

```json
{ "ok": true, "notes": "authored" }
```

`tests/orchestrator/fakes_routing/fake_content_validator.json`:

```json
{ "results": [], "ok": true }
```

`tests/orchestrator/fakes_routing/fake_gap_detector.json`:

```json
{ "gaps": [] }
```

(No notifier/publish-verifier needed for `no_pr=True`; copy `fake_notifier.json` / `fake_gap_detector.json` from `tests/orchestrator/fakes/` verbatim if the run requests them.)

- [ ] **Step 2: Write the failing integration test**

Add to `tests/orchestrator/test_pipeline_integration.py`:

```python
FAKES_ROUTING = Path(__file__).parent / "fakes_routing"

# lens form `docs/site-src/` (trailing slash) mirrors the real dogfood config,
# which is proven to satisfy the lens-paths-covered-by-agent_editable_paths
# invariant against the "docs/site-src/**" glob.
CONFIG_YAML_ROUTING = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/site-src/whats-new.md
  agent_editable_paths: ["docs/site-src/**"]
  lens_paths:
    core: docs/site-src/
sources:
  git: { host: github }
trigger: { cron: "0 7 * * *", on_pr_merge: false }
gap_detection:
  allowlist_paths: ["scripts/**"]
  size_filter: { min_loc: 50, min_files: 3 }
lint: { tier1: default, tier2: {}, tier3: {} }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
  verify_timeout_seconds: 60
notifications:
  slack: { enabled: false }
  email: { enabled: false }
site:
  docs_dir: docs/site-src
  theme: material
  sections:
    - { key: architecture, path: "architecture/", title: Architecture, generator: agent-authored }
    - { key: archive, path: "archive/", title: Decision Archive, generator: archive-index }
"""


def test_decision_target_routed_to_archive(tmp_path):
    import json
    import subprocess

    # Seed config + state + the two section dirs so available_sections discovers
    # them; git init so run()'s `git rev-parse HEAD` succeeds (mirrors the other
    # pipeline tests' seed helper).
    eda = tmp_path / ".engineering-docs-agent"
    eda.mkdir(parents=True)
    (eda / "config.yml").write_text(CONFIG_YAML_ROUTING)
    (eda / "state.json").write_text(
        json.dumps({"version": "1", "dismissed_gap_flags": {}, "cursors": {}})
    )
    (tmp_path / "docs/site-src/architecture").mkdir(parents=True)
    (tmp_path / "docs/site-src/archive").mkdir(parents=True)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True,
    )

    _run_inproc(tmp_path, FAKES_ROUTING)

    # The decision-kind create target must land under archive/, not architecture/.
    assert (tmp_path / "docs/site-src/archive/root-cause-sweep.md").exists()
    assert not (tmp_path / "docs/site-src/architecture/root-cause-sweep.md").exists()
```

> If the site-block schema requires more fields than shown, mirror the dogfood
> `site:` block in `.engineering-docs-agent/config.yml`. The validator and the
> seeding above match the existing passing pipeline tests' convention.

- [ ] **Step 3: Run; verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py::test_decision_target_routed_to_archive -v`
Expected: FAIL — without routing the page is authored at `architecture/root-cause-sweep.md`.

- [ ] **Step 4: Apply routing in the authoring loop**

In `scripts/orchestrator_runner.py`, replace the block at `:1171-1178` (`# Page authoring: batch doc_targets ...` through the `per_target` build) with:

```python
        # Page authoring: batch doc_targets per (lens, page_hint).
        import frontmatter_contract as fmc
        import doc_routing

        archive_section = doc_routing.archive_section_leaf(config.get("site") or {})
        editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
        per_target: dict[tuple[str, str], list[dict]] = {}
        doc_kind_by_target: dict[tuple[str, str], str] = {}
        for s in summaries:
            for t in s.get("doc_targets", []):
                hint = t["page_hint"]
                dk = t.get("doc_kind")
                if t.get("action") == "create":
                    hint = doc_routing.route_create_hint(
                        hint,
                        dk,
                        archive_section,
                        available_sections_by_lens.get(t["lens"], []),
                    )
                key = (t["lens"], hint)
                per_target.setdefault(key, []).append(s)
                if dk and key not in doc_kind_by_target:
                    doc_kind_by_target[key] = dk
```

- [ ] **Step 5: Pass `doc_kind` into the page-author frontmatter template**

In the authoring loop (`:1198-1217`), build the template before the dispatch and merge `doc_kind` in. Replace the inline `"frontmatter_template": fmc.default_frontmatter_dict([...])` with:

```python
            fm_template = fmc.default_frontmatter_dict(
                [
                    pr.get("url")
                    for s in batch_summaries
                    for pr in prs
                    if pr.get("number") == s.get("pr_number")
                ]
            )
            _dk = doc_kind_by_target.get((lens, hint))
            if _dk:
                fm_template["doc_kind"] = _dk
            out, reasons = dispatch_validated(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": action,
                    "lens": lens,
                    "summaries": batch_summaries,
                    "voice_samples": voice_samples,
                    "frontmatter_template": fm_template,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
            )
```

- [ ] **Step 6: Run the routing test + the whole orchestrator suite**

Run: `python3 -m pytest tests/orchestrator/test_pipeline_integration.py -v`
Expected: PASS — the new routing test plus all existing pipeline tests (the `fakes` fixture has no `doc_kind`, so `route_create_hint` returns hints unchanged → no regression).

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/fakes_routing/ tests/orchestrator/test_pipeline_integration.py
git commit -m "feat(CCE-107): route decision-kind create targets to the archive section

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: One-time dogfood migration

This is a data migration, not library code — the verification commands ARE its tests. No new unit tests; correctness is proven by frontmatter lint + `mkdocs build --strict` + presence checks.

**Files:**

- Move: 5 pages `docs/site-src/architecture/*.md` → `docs/site-src/archive/*.md`
- Modify: frontmatter of all 20 architecture-origin pages (add `doc_kind`)
- Modify: `docs/site-src/architecture/index.md`, `docs/site-src/archive/index.md` (regenerated overviews)

- [ ] **Step 1: Confirm the move-set and a clean tree**

```bash
cd /Users/theo/Projects/engineering-docs-agent
git status --porcelain   # expect clean (Tasks 1-4 already committed)
ls docs/site-src/architecture/*.md | wc -l   # expect 21 (20 pages + index.md)
```

Decision pages to move (5): `cce14-source-collector-prompt-hardening.md`, `cce15-source-collector-root-cause-sweep.md`, `cce5-9-batch-prep-roadmap.md`, `v0-1-1-hardening.md`, `2026-05-29-orchestrator-fence-strip.md`.

- [ ] **Step 2: Stamp `doc_kind` on all 20 pages (idempotent)**

Run this migration snippet (stdlib-only; preserves all existing frontmatter, adds `doc_kind`, and back-fills the archive-index required set on moved pages so they satisfy their new section's contract):

```bash
python3 - <<'PY'
from pathlib import Path
import yaml

ROOT = Path("docs/site-src/architecture")
DECISION = {
    "cce14-source-collector-prompt-hardening.md",
    "cce15-source-collector-root-cause-sweep.md",
    "cce5-9-batch-prep-roadmap.md",
    "v0-1-1-hardening.md",
    "2026-05-29-orchestrator-fence-strip.md",
}

def split_fm(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return (yaml.safe_load(parts[1]) or {}), parts[2]

for md in sorted(ROOT.glob("*.md")):
    if md.name == "index.md":
        continue
    fm, body = split_fm(md.read_text(encoding="utf-8"))
    fm["doc_kind"] = "decision" if md.name in DECISION else "architecture"
    if md.name in DECISION:
        # archive-index required set (status/sources/synthesized_into) as a
        # superset; last_reviewed/description/source_files are preserved for the
        # freshness sort and the citation contract.
        fm.setdefault("status", "draft")
        fm.setdefault("sources", [])
        fm.setdefault("synthesized_into", [])
    new = "---\n" + yaml.safe_dump(fm, sort_keys=False).rstrip("\n") + "\n---" + body
    md.write_text(new, encoding="utf-8")
    print(f"stamped {md.name}: doc_kind={fm['doc_kind']}")
PY
```

- [ ] **Step 3: Move the 5 decision pages with `git mv`**

```bash
for f in cce14-source-collector-prompt-hardening cce15-source-collector-root-cause-sweep cce5-9-batch-prep-roadmap v0-1-1-hardening 2026-05-29-orchestrator-fence-strip; do
  git mv "docs/site-src/architecture/$f.md" "docs/site-src/archive/$f.md"
done
ls docs/site-src/architecture/*.md | wc -l   # expect 16 (15 pages + index.md)
ls docs/site-src/archive/*.md                # expect specs.md, plans.md, index.md + 5 moved
```

- [ ] **Step 4: Regenerate the section overviews (no URL leak)**

`generate_overviews` writes only title/summary lists (no GitHub blob URLs), so it is branch-safe — unlike `generate_archive`, do NOT regenerate the archive index tables here (that would bake `blob/feat/...` URLs; they regenerate correctly at merge time on `main`).

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "scripts")
import yaml, section_overview
config = yaml.safe_load(open(".engineering-docs-agent/config.yml"))
result = section_overview.generate_overviews(".", config["site"])
print(result)
PY
```

Expect `architecture/index.md` and `archive/index.md` in `written` (or `skipped` if already current).

- [ ] **Step 5: Verify — frontmatter lint on the moved pages**

```bash
python3 scripts/lint/frontmatter_schema.py --config .engineering-docs-agent/config.yml --json \
  --paths docs/site-src/archive/cce14-source-collector-prompt-hardening.md \
          docs/site-src/archive/cce15-source-collector-root-cause-sweep.md \
          docs/site-src/archive/cce5-9-batch-prep-roadmap.md \
          docs/site-src/archive/v0-1-1-hardening.md \
          docs/site-src/archive/2026-05-29-orchestrator-fence-strip.md ; echo "exit=$?"
```

Expected: `exit=0` (every moved page satisfies the `archive-index` required set).

- [ ] **Step 6: Verify — real consumer (`mkdocs build --strict`)**

```bash
mkdocs build --strict 2>&1 | tail -5 ; echo "exit=${PIPESTATUS[0]}"
```

Expected: `exit=0`. The moved pages resolve in nav under `archive/`; no orphaned-link or missing-target errors. (`mkdocs` is on PATH at `~/.local/bin/mkdocs`.)

- [ ] **Step 7: Verify — overview content reflects the migration**

```bash
grep -c "Root Cause Sweep\|Prompt Hardening" docs/site-src/architecture/index.md   # expect 0
grep -c "Root Cause Sweep\|Prompt Hardening" docs/site-src/archive/index.md         # expect >=1
```

- [ ] **Step 8: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all pass (no test references the moved page paths; `test_section_overview`/`test_doc_routing`/schema/pipeline tests all green).

- [ ] **Step 9: Commit**

```bash
git add docs/site-src/architecture/ docs/site-src/archive/
git commit -m "feat(CCE-107): migrate 5 decision pages architecture/ -> archive/; stamp doc_kind

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (after all tasks)

- [ ] Full integrated suite green: `python3 -m pytest -q`
- [ ] Real consumer green: `mkdocs build --strict` exit 0
- [ ] Spec acceptance criteria 1-7 each map to a landed task (see cross-check below)
- [ ] Dispatch a final code-reviewer subagent over the whole branch diff

**Acceptance-criteria cross-check:** AC1 → Task 1; AC2 → Task 2; AC3 → Task 3; AC4 → Task 4; AC5 → Task 5 (steps 2-3, 7); AC6 → Task 5 step 6; AC7 → Task 2 (no-archive/absent-doc_kind tests) + Task 1 (`_freshness_key` empty) + Task 4 (unchanged-hint regression).

## Known cosmetic outcome (not a blocker)

After migration, `archive/index.md`'s overview lists the auto-generated `Specs`/`Plans` index pages _last_ (they carry no `last_reviewed` and no date-prefixed filename → freshness `""` → sink to the bottom), below the migrated decision pages. This follows directly from the chosen freshness rule. If the Specs/Plans tables should lead the archive landing, that is a follow-up tuning (e.g., a per-section sort override) — out of scope here.
