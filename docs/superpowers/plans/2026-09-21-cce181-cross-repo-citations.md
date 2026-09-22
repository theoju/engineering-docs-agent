# Cross-Repo Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `page-author` reference a file in another repository without emitting a token that `citation_exists` blocks, by declaring external repos in config and rendering their prefixed tokens to links before the linter runs.

**Architecture:** A new pure stdlib module `scripts/external_refs.py` parses `lint.external_repos` and performs a deterministic prefix→link substitution on authored page text. The orchestrator calls it after the authoring loop and _before_ `_diagnose_citation_paths`, so the order is render → diagnose → validate. `citation_exists` itself is unchanged: links, URLs and slash-free backticked names already pass its grammar.

**Tech Stack:** Python 3.11/3.12, stdlib only (`re`, `pathlib`), pytest, `jsonschema` (already a dependency, used by `state_io.load_config_validated`).

**Spec:** `docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md` (commit `0d23142`)

## Global Constraints

- **Stdlib-first.** No new runtime dependencies.
- **Generic-first.** A host that declares no `external_repos` must be byte-identical to today. Behaviour is driven by config, never hardcoded paths.
- **`citation_exists` must not change.** Its grammar already passes the rendered forms. Any change to it is out of scope and a red flag.
- **Never name the config key `sibling_*`.** CCE-141 owns "sibling" in this subsystem for _a file written during the same run_ (`tests/orchestrator/fakes_sibling_citation/`). New fixtures use `fakes_external_repo/`.
- **`tests/scripts/` must NOT contain `__init__.py`** — `scripts/` is a PEP 420 namespace package; adding one shadows it and causes order-dependent `ModuleNotFoundError` (CCE-122).
- **Import lint modules by the established pattern:** `sys.path.append` the lint dir, then a bare import — exactly as `scripts/citation_repair.py` does. Never `sys.path.insert` the scripts dir (CCE-122).
- **Line-free citations.** Docs cite `` `path/file.py` `` or `` `path/file.py:symbol` ``, never `path:line` (CCE-122).
- **All work on `feat/CCE-181-cross-repo-citations`**, in the worktree `~/Projects/cce181`. Never commit to `main`.
- **Commit messages include `CCE-181`.**

---

## File Structure

| File                                              | Responsibility                                                                                                   |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `scripts/external_refs.py`                        | **New.** Pure, stdlib-only. Config parsing/validation + the text transform. No file I/O.                         |
| `tests/scripts/test_external_refs_config.py`      | **New.** Task 1 — `resolve_config` validation.                                                                   |
| `tests/scripts/test_external_refs_render.py`      | **New.** Task 2 — `render_external_refs` transform.                                                              |
| `templates/config.schema.json`                    | **Modify.** Declare `lint.external_repos`.                                                                       |
| `scripts/state_io.py`                             | **Modify.** Call `resolve_config` from `load_config_validated`, passing host dirs.                                         |
| `tests/scripts/test_state_io_external_repos.py`   | **New.** Task 3 — load-time rejection.                                                                           |
| `scripts/orchestrator_runner.py`                  | **Modify.** Render pass before the `_diagnose_citation_paths` loop; pass prefixes into the page-author dispatch. |
| `tests/orchestrator/test_external_refs_wiring.py` | **New.** Tasks 4 and 5 — ordering and payload.                                                                   |
| `agents/page-author.md`                           | **Modify.** Add the third escape to the grounding rule.                                                          |
| `tests/orchestrator/fakes_external_repo/`         | **New.** Task 6 fixtures.                                                                                        |
| `tests/orchestrator/test_external_refs_e2e.py`    | **New.** Task 6 — end-to-end and bare-host no-op.                                                                |

---

### Task 1: `resolve_config` — parse and validate `lint.external_repos`

**Files:**

- Create: `scripts/external_refs.py`
- Test: `tests/scripts/test_external_refs_config.py`

**Interfaces:**

- Consumes: nothing.
- Produces:
  - `class ExternalRepoConfigError(ValueError)`
  - `resolve_config(config: dict, *, host_dirs: frozenset[str] = frozenset()) -> dict[str, dict]` — returns `{prefix: {"url": str|None, "private": bool, "ref": str, "blob_template": str}}`. Raises `ExternalRepoConfigError` on any invalid declaration. Returns `{}` when `lint.external_repos` is absent.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_external_refs_config.py`:

```python
"""CCE-181: lint.external_repos must fail loud on every ambiguous declaration.

An entry declares EXACTLY one of `url` or `private: true`. Absence of `url` is
deliberately NOT an implicit "private": a typo would then silently downgrade a
public link, and -- worse -- a dropped `private` flag would silently publish a
URL for a repo that must not be advertised. Both directions are loud.
"""

import pytest

from scripts.external_refs import ExternalRepoConfigError, resolve_config

PUB = "https://github.com/theoju/engineering-docs-agent"


def test_absent_block_is_an_empty_mapping():
    assert resolve_config({}) == {}
    assert resolve_config({"lint": {}}) == {}


def test_a_public_entry_normalizes_with_defaults():
    out = resolve_config({"lint": {"external_repos": {"eda": {"url": PUB}}}})
    assert out == {
        "eda": {
            "url": PUB,
            "private": False,
            "ref": "main",
            "blob_template": "{url}/blob/{ref}/{path}",
        }
    }


def test_a_private_entry_carries_no_url():
    out = resolve_config({"lint": {"external_repos": {"ship": {"private": True}}}})
    assert out["ship"]["private"] is True
    assert out["ship"]["url"] is None


def test_overrides_survive_normalization():
    out = resolve_config(
        {
            "lint": {
                "external_repos": {
                    "gl": {
                        "url": "https://gitlab.com/o/r",
                        "ref": "master",
                        "blob_template": "{url}/-/blob/{ref}/{path}",
                    }
                }
            }
        }
    )
    assert out["gl"]["ref"] == "master"
    assert out["gl"]["blob_template"] == "{url}/-/blob/{ref}/{path}"


def test_both_url_and_private_is_rejected():
    with pytest.raises(ExternalRepoConfigError, match="both"):
        resolve_config(
            {"lint": {"external_repos": {"eda": {"url": PUB, "private": True}}}}
        )


def test_neither_url_nor_private_is_rejected():
    with pytest.raises(ExternalRepoConfigError, match="neither"):
        resolve_config({"lint": {"external_repos": {"eda": {"ref": "main"}}}})


def test_a_multi_segment_prefix_is_rejected():
    """Follows citation_source_roots: a nested tail is suffix-matching in
    disguise, and suffix-matching admits confabulated paths."""
    with pytest.raises(ExternalRepoConfigError, match="single segment"):
        resolve_config({"lint": {"external_repos": {"org/repo": {"url": PUB}}}})


def test_a_prefix_colliding_with_a_real_directory_is_rejected():
    """Without this, a host declaring `docs` while genuinely having docs/ would
    have real local paths rewritten into foreign links."""
    with pytest.raises(ExternalRepoConfigError, match="collides"):
        resolve_config(
            {"lint": {"external_repos": {"docs": {"url": PUB}}}},
            host_dirs=frozenset({"docs", "scripts"}),
        )


def test_a_non_colliding_prefix_passes_the_same_guard():
    out = resolve_config(
        {"lint": {"external_repos": {"eda": {"url": PUB}}}},
        host_dirs=frozenset({"docs", "scripts"}),
    )
    assert "eda" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_external_refs_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.external_refs'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/external_refs.py`:

```python
"""CCE-181: render citations that point into a declared EXTERNAL repository.

`citation_exists` is a Tier-1 block rule and correctly fails a backticked path
that does not exist in the host checkout. That is right for a confabulation and
wrong for an artifact which is real but lives in another repo -- a token that is
simultaneously true and uncitable. Post-CCE-140 such a page is not merely
blocked: the deferral skip abandons the PR and the page is silently never
written.

The escape is opt-in PER TOKEN. Only a token whose first segment is a declared
external repo is rewritten. Absence-of-resolution is deliberately NOT the
trigger: its entry condition is exactly the confabulation population the linter
exists to block, which would turn every BLOCK into a silent PASS (the CCE-141
class).

Pure and stdlib-only. No file I/O -- the orchestrator owns reading and writing.

Spec: docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Same pattern as scripts/citation_repair.py: append (never insert) the lint
# dir, then import bare. Inserting the scripts dir poisons namespace resolution
# for the rest of the session (CCE-122).
_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

from citation_exists import _SUFFIX_RE  # noqa: E402

DEFAULT_REF = "main"
DEFAULT_BLOB_TEMPLATE = "{url}/blob/{ref}/{path}"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


class ExternalRepoConfigError(ValueError):
    """A lint.external_repos declaration is ambiguous or unsafe."""


def resolve_config(
    config: dict, *, host_dirs: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Normalize lint.external_repos, raising on any invalid declaration."""
    lint = config.get("lint") or {}
    raw = lint.get("external_repos") or {}
    if not isinstance(raw, dict):
        raise ExternalRepoConfigError("lint.external_repos must be a mapping")

    out: dict[str, dict] = {}
    for prefix, entry in raw.items():
        if not isinstance(entry, dict):
            raise ExternalRepoConfigError(f"{prefix}: entry must be a mapping")
        if "/" in prefix:
            raise ExternalRepoConfigError(f"{prefix}: prefix must be a single segment")
        if prefix in host_dirs:
            raise ExternalRepoConfigError(
                f"{prefix}: collides with a real directory in this repo"
            )
        url = entry.get("url")
        has_url = isinstance(url, str) and bool(url.strip())
        private = bool(entry.get("private"))
        if has_url and private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares both a url and private; pick exactly one"
            )
        if not has_url and not private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares neither a url nor private; pick exactly one"
            )
        out[prefix] = {
            "url": url.strip() if has_url else None,
            "private": private,
            "ref": str(entry.get("ref") or DEFAULT_REF),
            "blob_template": str(entry.get("blob_template") or DEFAULT_BLOB_TEMPLATE),
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_external_refs_config.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add scripts/external_refs.py tests/scripts/test_external_refs_config.py
git commit -m "feat(external-refs): validate lint.external_repos declarations — CCE-181"
```

---

### Task 2: `render_external_refs` — the pure transform

**Files:**

- Modify: `scripts/external_refs.py`
- Test: `tests/scripts/test_external_refs_render.py`

**Interfaces:**

- Consumes: `resolve_config` output shape from Task 1 — `{prefix: {"url", "private", "ref", "blob_template"}}`.
- Produces: `render_external_refs(text: str, repos: dict[str, dict]) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_external_refs_render.py`:

````python
"""CCE-181: the transform, and the two traps the prototype found by RUNNING it.

Trap 1 -- link text must be slash-free. [`scripts/x.py`](url) STILL BLOCKS:
extract_citations scans backticked spans wherever they appear and markdown link
syntax exempts nothing. The obvious rendering is the broken one.

Trap 2 -- the :line/:symbol suffix is citation grammar, not a filesystem path.
Left in the address it yields a 404 that PASSES the linter, so nothing
downstream can catch it.

Both are asserted against the REAL grammar via extract_citations, not against a
hand-written expectation, so a change to the grammar surfaces here.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))

from citation_exists import extract_citations  # noqa: E402

from scripts.external_refs import render_external_refs, resolve_config  # noqa: E402

PUB = "https://github.com/theoju/engineering-docs-agent"
REPOS = resolve_config(
    {"lint": {"external_repos": {"eda": {"url": PUB}, "ship": {"private": True}}}}
)


def test_a_file_at_the_external_repo_root():
    out = render_external_refs("See `eda/CLAUDE.md`.", REPOS)
    assert out == "See [`CLAUDE.md`](" + PUB + "/blob/main/CLAUDE.md)."


def test_a_file_deep_in_the_external_repo():
    out = render_external_refs("See `eda/scripts/runner.py`.", REPOS)
    assert out == "See [`runner.py`](" + PUB + "/blob/main/scripts/runner.py)."


def test_the_link_text_is_slash_free_and_the_linter_sees_nothing():
    """TRAP 1. This is the regression guard. If someone 'improves' the link
    text back to the full path, extract_citations finds it again and the
    build blocks -- silently restoring the bug this ticket fixes."""
    out = render_external_refs("See `eda/scripts/runner.py`.", REPOS)
    link_text = out.split("[`")[1].split("`]")[0]
    assert "/" not in link_text, link_text
    assert extract_citations(out)["paths"] == []


def test_a_symbol_suffix_is_stripped_from_the_url_and_kept_in_the_text():
    """TRAP 2. Found by running the prototype, not by reading the design."""
    out = render_external_refs("See `eda/scripts/x.py:Klass.method`.", REPOS)
    assert out == "See [`x.py:Klass.method`](" + PUB + "/blob/main/scripts/x.py)."
    assert extract_citations(out)["paths"] == []


def test_a_line_suffix_is_stripped_from_the_url_too():
    out = render_external_refs("See `eda/scripts/x.py:128`.", REPOS)
    assert "(" + PUB + "/blob/main/scripts/x.py)" in out


def test_a_private_repo_names_the_file_and_never_the_repo():
    out = render_external_refs("See `ship/spokes/pre-flight.md`.", REPOS)
    assert out == "See `pre-flight.md`."
    assert "ship" not in out
    assert "http" not in out
    assert extract_citations(out)["paths"] == []


def test_an_undeclared_prefix_is_untouched_and_still_blocks():
    """The escape is opt-in per token. A confabulation has no declared prefix,
    so nothing rewrites it and citation_exists still sees it."""
    src = "See `scripts/does_not_exist.py`."
    out = render_external_refs(src, REPOS)
    assert out == src
    assert extract_citations(out)["paths"] == ["scripts/does_not_exist.py"]


def test_a_fenced_sample_is_never_rewritten():
    src = "Example:\n\n```\n`eda/CLAUDE.md`\n```\n"
    assert render_external_refs(src, REPOS) == src


def test_rendering_is_idempotent():
    once = render_external_refs("See `eda/CLAUDE.md`.", REPOS)
    assert render_external_refs(once, REPOS) == once


def test_no_declarations_is_a_true_no_op():
    src = "See `eda/CLAUDE.md` and `scripts/x.py`."
    assert render_external_refs(src, {}) == src


def test_a_ref_and_template_override_reach_the_url():
    repos = resolve_config(
        {
            "lint": {
                "external_repos": {
                    "gl": {
                        "url": "https://gitlab.com/o/r",
                        "ref": "master",
                        "blob_template": "{url}/-/blob/{ref}/{path}",
                    }
                }
            }
        }
    )
    out = render_external_refs("See `gl/a/b.py`.", repos)
    assert "https://gitlab.com/o/r/-/blob/master/a/b.py" in out
````

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_external_refs_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_external_refs'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/external_refs.py`:

````python
def _blob_url(entry: dict, path_in_repo: str) -> str:
    return (
        entry["blob_template"]
        .replace("{url}", entry["url"])
        .replace("{ref}", entry["ref"])
        .replace("{path}", path_in_repo)
    )


def render_external_refs(text: str, repos: dict[str, dict]) -> str:
    """Rewrite declared-prefix tokens to links (public) or names (private).

    Deterministic substitution on an explicitly declared string. No inference,
    no suffix matching, no corroboration -- that distinction is what separates
    this from the CCE-141 class. It runs BEFORE the linter, never on a page the
    linter has already blocked.
    """
    if not repos:
        return text

    def _one(match):
        token = match.group(1).strip()
        head, sep, rest = token.partition("/")
        if not sep or not rest:
            return match.group(0)
        entry = repos.get(head)
        if entry is None:
            return match.group(0)
        basename = rest.split("/")[-1]
        if entry["private"]:
            return "`" + basename + "`"
        # The :line/:symbol suffix is CITATION grammar, not a path on disk.
        # Left in the URL it 404s while PASSING the linter -- a silent dead
        # link. Keep it in the visible text, where it is slash-free and inert.
        url_path = _SUFFIX_RE.sub("", rest)
        return "[`" + basename + "`](" + _blob_url(entry, url_path) + ")"

    out: list[str] = []
    in_fence = False
    fence = ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            out.append(line)
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            out.append(line)
            continue
        out.append(line if in_fence else _INLINE_CODE_RE.sub(_one, line))
    return "\n".join(out)
````

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_external_refs_render.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add scripts/external_refs.py tests/scripts/test_external_refs_render.py
git commit -m "feat(external-refs): render declared-prefix tokens to links or names — CCE-181"
```

---

### Task 3: Schema declaration and load-time rejection

**Files:**

- Modify: `templates/config.schema.json` — add `external_repos` under `properties.lint.properties`
- Modify: `scripts/state_io.py` — inside `load_config_validated`, after `_validate_lens_paths_are_editable(raw)`
- Test: `tests/scripts/test_state_io_external_repos.py`

**Interfaces:**

- Consumes: `resolve_config(config, host_dirs=...)` and `ExternalRepoConfigError` from Task 1.
- Produces: `load_config_validated` raises `ConfigError` for an invalid `lint.external_repos`.

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_state_io_external_repos.py`:

```python
"""CCE-181: an invalid external_repos declaration must stop the run at load.

The collision guard needs the repo tree. load_config_validated takes only the config
path -- but that path is <repo>/.engineering-docs-agent/config.yml, so the repo
root is path.parent.parent. Deriving it there keeps the guard at load time, as
the spec requires, without changing load_config_validated's signature.
"""

import pytest
import yaml

from scripts.state_io import ConfigError, load_config_validated

BASE = {
    "docs": {
        "framework": "mkdocs",
        "source_dir": "docs",
        "agent_editable_paths": ["docs/**"],
        "lens_paths": {"core": "docs/"},
    }
}


def _write(tmp_path, lint):
    repo = tmp_path
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    cfg_dir = repo / ".engineering-docs-agent"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / "config.yml"
    cfg.write_text(yaml.safe_dump({**BASE, "lint": lint}))
    return cfg


def test_a_valid_declaration_loads(tmp_path):
    cfg = _write(tmp_path, {"external_repos": {"eda": {"url": "https://x.example/r"}}})
    loaded = load_config_validated(cfg)
    assert loaded["lint"]["external_repos"]["eda"]["url"] == "https://x.example/r"


def test_both_url_and_private_is_refused_at_load(tmp_path):
    cfg = _write(
        tmp_path,
        {"external_repos": {"eda": {"url": "https://x.example/r", "private": True}}},
    )
    with pytest.raises(ConfigError):
        load_config_validated(cfg)


def test_a_prefix_colliding_with_a_real_repo_directory_is_refused(tmp_path):
    """`docs/` exists in the fixture repo, so declaring `docs` as external
    would rewrite real local paths into foreign links."""
    cfg = _write(tmp_path, {"external_repos": {"docs": {"url": "https://x.example/r"}}})
    with pytest.raises(ConfigError, match="collides"):
        load_config_validated(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_state_io_external_repos.py -v`
Expected: FAIL — the collision and both-fields cases load without raising.

- [ ] **Step 3: Write minimal implementation**

In `templates/config.schema.json`, add to `properties.lint.properties`:

```json
"external_repos": {
  "type": "object",
  "description": "Repositories OTHER than this host that pages may cite (CCE-181). Keyed by the single-segment path prefix an author writes: `<prefix>/<path in that repo>`. A public entry declares `url` and renders to a markdown link; a private entry declares `private: true` and renders to the bare filename with the repo never named. Exactly one of url/private per entry. Empty by default, so a host that declares nothing is unaffected.",
  "additionalProperties": {
    "type": "object",
    "properties": {
      "url": {"type": "string"},
      "private": {"type": "boolean"},
      "ref": {"type": "string"},
      "blob_template": {"type": "string"}
    },
    "additionalProperties": false
  },
  "propertyNames": {"pattern": "^[A-Za-z0-9_][A-Za-z0-9._-]*$"}
}
```

In `scripts/state_io.py`, add beside the other module imports at the top:

```python
from external_refs import ExternalRepoConfigError, resolve_config
```

and inside `load_config_validated`, immediately after `_validate_lens_paths_are_editable(raw)`:

```python
    # CCE-181: the collision guard needs the repo tree. The config always lives
    # at <repo>/.engineering-docs-agent/config.yml, so the repo root is two
    # levels up. An empty host_dirs simply means the collision arm cannot fire;
    # every other arm (both/neither, multi-segment) still does.
    _repo_root = path.resolve().parent.parent
    _host_dirs = (
        frozenset(p.name for p in _repo_root.iterdir() if p.is_dir())
        if _repo_root.is_dir()
        else frozenset()
    )
    try:
        resolve_config(raw, host_dirs=_host_dirs)
    except ExternalRepoConfigError as e:
        raise ConfigError(f"config invalid at $.lint.external_repos: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts/test_state_io_external_repos.py -v`
Expected: PASS — 3 passed

Then confirm nothing else regressed:
Run: `cd ~/Projects/cce181 && python3 -m pytest tests/scripts -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add templates/config.schema.json scripts/state_io.py tests/scripts/test_state_io_external_repos.py
git commit -m "feat(config): declare and validate lint.external_repos at load — CCE-181"
```

---

### Task 4: Orchestrator wiring — render before diagnose

**Files:**

- Modify: `scripts/orchestrator_runner.py` — the `for _authored_page in authored:` loop that calls `_diagnose_citation_paths`
- Test: `tests/orchestrator/test_external_refs_wiring.py`

**Interfaces:**

- Consumes: `render_external_refs(text, repos)` and `resolve_config(config)` from Tasks 1–2.
- Produces: `_render_external_refs_for_pages(authored: list[str], config: dict) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_external_refs_wiring.py`:

```python
"""CCE-181: ordering is load-bearing -- render, THEN diagnose, THEN validate.

_diagnose_citation_paths reports what a BLOCKED citation was probably shortened
from. Run before the render it would see `eda/CLAUDE.md`, fail to resolve it,
and emit suffix-match noise for a token that is about to become a link. Render
first and that false-positive class does not exist.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import orchestrator_runner as orun  # noqa: E402


def test_the_renderer_runs_before_the_diagnostic(tmp_path, monkeypatch):
    page = tmp_path / "page.md"
    page.write_text("See `eda/CLAUDE.md`.")
    seen: list[str] = []

    def _spy(path, repo_root, config, state, source_paths=None):
        seen.append(Path(path).read_text())

    monkeypatch.setattr(orun, "_diagnose_citation_paths", _spy)
    config = {"lint": {"external_repos": {"eda": {"url": "https://x.example/r"}}}}
    orun._render_external_refs_for_pages([str(page)], config)
    orun._diagnose_citation_paths(str(page), tmp_path, config, {}, source_paths=set())

    assert seen == ["See [`CLAUDE.md`](https://x.example/r/blob/main/CLAUDE.md)."]


def test_a_bare_host_leaves_the_file_byte_identical(tmp_path):
    page = tmp_path / "page.md"
    original = "See `eda/CLAUDE.md` and `scripts/x.py`."
    page.write_text(original)
    before = page.stat().st_mtime_ns
    orun._render_external_refs_for_pages([str(page)], {"lint": {}})
    assert page.read_text() == original
    assert page.stat().st_mtime_ns == before, "an unchanged page must not be rewritten"


def test_a_missing_page_is_skipped_not_raised(tmp_path):
    orun._render_external_refs_for_pages([str(tmp_path / "gone.md")], {"lint": {}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/orchestrator/test_external_refs_wiring.py -v`
Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_render_external_refs_for_pages'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/orchestrator_runner.py`, add beside `from state_io import (...)`:

```python
from external_refs import render_external_refs, resolve_config
```

Add this helper immediately above `def _diagnose_citation_paths(`:

```python
def _render_external_refs_for_pages(authored: list[str], config: dict) -> None:
    """CCE-181: rewrite declared-prefix citations before anything reads them.

    Runs AHEAD of _diagnose_citation_paths so the diagnostic never sees a token
    that is about to become a link -- otherwise it reports suffix-match noise
    for a citation that was never shortened.

    Writes only when the text actually changed: an unchanged page must not get
    a new mtime, or every bare host would show spurious churn.
    """
    repos = resolve_config(config)
    if not repos:
        return
    for rel in authored:
        p = Path(rel)
        if not p.exists():
            continue
        before = p.read_text()
        after = render_external_refs(before, repos)
        if after != before:
            p.write_text(after)
```

Then, in `run()`, immediately **before** the `for _authored_page in authored:` loop that calls `_diagnose_citation_paths`, insert:

```python
        # CCE-181: render -> diagnose -> validate. Placement is load-bearing;
        # see the helper's docstring.
        _render_external_refs_for_pages(authored, config)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/orchestrator/test_external_refs_wiring.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add scripts/orchestrator_runner.py tests/orchestrator/test_external_refs_wiring.py
git commit -m "feat(orchestrator): render external refs before the citation diagnostic — CCE-181"
```

---

### Task 5: `page-author` contract and dispatch payload

**Files:**

- Modify: `agents/page-author.md` — the "Ground before you write (CCE-110)" rule
- Modify: `scripts/orchestrator_runner.py` — the `dispatch_validated("page-author", {...})` payload
- Test: `tests/orchestrator/test_external_refs_wiring.py` (append)

**Interfaces:**

- Consumes: `resolve_config` from Task 1.
- Produces: `_external_repo_prefixes(config: dict) -> list[str]`; the page-author payload gains `external_repos` — declared prefixes only, never URLs.

- [ ] **Step 1: Write the failing test**

Append to `tests/orchestrator/test_external_refs_wiring.py`:

```python
def test_the_payload_carries_declared_prefixes_only():
    """An agent that cannot see the declaration cannot use it. Prefixes only --
    the agent must never construct the URL itself, so it is not given one."""
    config = {
        "lint": {
            "external_repos": {
                "eda": {"url": "https://x.example/r"},
                "ship": {"private": True},
            }
        }
    }
    assert orun._external_repo_prefixes(config) == ["eda", "ship"]


def test_a_bare_host_offers_no_prefixes():
    assert orun._external_repo_prefixes({"lint": {}}) == []


def test_the_contract_documents_the_third_escape():
    """The grounding rule offered only `example/` (fictional) and fenced blocks
    (dead names). Real-but-elsewhere was the missing third case."""
    text = (
        Path(__file__).resolve().parents[2] / "agents" / "page-author.md"
    ).read_text()
    assert "declared as external" in text
    assert "Never construct the URL yourself" in text
    assert "exists in the HOST repo" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/orchestrator/test_external_refs_wiring.py -v`
Expected: FAIL with `AttributeError: module 'orchestrator_runner' has no attribute '_external_repo_prefixes'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/orchestrator_runner.py`, beside `_render_external_refs_for_pages`:

```python
def _external_repo_prefixes(config: dict) -> list[str]:
    """Declared prefixes for the page-author prompt. PREFIXES ONLY.

    The agent must never build the URL itself -- guessing the default branch or
    a host's blob grammar produces dead links that pass the linter. It gets the
    vocabulary; the pipeline owns the address.
    """
    return sorted(resolve_config(config))
```

In the `dispatch_validated("page-author", {...})` payload, add one key after `"source_paths": sorted(grounding),`:

```python
                    "external_repos": _external_repo_prefixes(config),
```

In `agents/page-author.md`, inside the "Ground before you write (CCE-110)" rule, immediately after the sentence introducing the reserved `example/` namespace, insert:

> A backticked path asserts the artifact **exists in the HOST repo**. When the artifact lives in a repository the host has **declared as external** (the `external_repos` list in your input), cite it with the declared prefix: `` `<repo>/<path within that repo>` ``. The pipeline renders it into a link, or, for a private repo, into the bare filename. Never construct the URL yourself. Never use a prefix that is not in that list — an undeclared prefix is an ordinary repo path and will block, which is correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/orchestrator/test_external_refs_wiring.py -v`
Expected: PASS — 6 passed

Confirm the agent contract's fenced JSON block is untouched (output shape is unchanged, so this must still pass):
Run: `cd ~/Projects/cce181 && python3 -m pytest tests/agents/test_schema_md_sync.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add agents/page-author.md scripts/orchestrator_runner.py tests/orchestrator/test_external_refs_wiring.py
git commit -m "feat(page-author): teach the third citation escape for external repos — CCE-181"
```

---

### Task 6: End-to-end, and proving the bare-host path is truly inert

**Files:**

- Create: `tests/orchestrator/fakes_external_repo/` (copied fake agent JSON files)
- Create: `tests/orchestrator/test_external_refs_e2e.py`

**Interfaces:**

- Consumes: everything from Tasks 1–5.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Create the fixture directory from an existing multi-PR fixture set:

```bash
cd ~/Projects/cce181
mkdir -p tests/orchestrator/fakes_external_repo
cp tests/orchestrator/fakes_multi/*.json tests/orchestrator/fakes_external_repo/
```

Overwrite `tests/orchestrator/fakes_external_repo/fake_page_author.json`:

```json
{
  "path": "docs/core/page.md",
  "action": "create",
  "diff_summary": "cites a declared external repo",
  "ok": true
}
```

Create `tests/orchestrator/test_external_refs_e2e.py`:

```python
"""CCE-181 end-to-end, on the shape production actually runs.

time_budget_seconds=0 -- no truncation. Per CCE-179, a test that reaches its
assertion by a different code path than production is not coverage.

The second test inverts CCE-141's "disabling it left the suite green"
measurement: prove the INERT path is genuinely inert, so a host that declares
nothing is byte-identical to today.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))

import orchestrator_runner as orun  # noqa: E402
from citation_exists import extract_citations  # noqa: E402
from external_refs import render_external_refs  # noqa: E402

FAKES = Path(__file__).parent / "fakes_external_repo"
PUB = "https://github.com/theoju/engineering-docs-agent"


def test_a_page_citing_a_declared_external_repo_publishes(tmp_path):
    """The whole point: this page would block today and be silently discarded."""
    config = {"lint": {"external_repos": {"eda": {"url": PUB}}}}
    page = tmp_path / "page.md"
    page.write_text("The gate is in `eda/scripts/orchestrator_runner.py`.")

    orun._render_external_refs_for_pages([str(page)], config)

    assert extract_citations(page.read_text())["paths"] == []
    assert PUB + "/blob/main/scripts/orchestrator_runner.py" in page.read_text()


def test_a_bare_host_run_is_byte_identical(tmp_path, init_host):
    """No external_repos declared -> the renderer is a no-op across a whole
    run. A host that declares nothing keeps today's exact behaviour."""
    init_host({"version": "1", "last_successful_run": {}})
    rc = orun.run(tmp_path, dry_run_dir=FAKES, no_pr=True, time_budget_seconds=0)
    assert rc == 0
    pages = list((tmp_path / "docs").rglob("*.md"))
    assert pages, "the fixture run must author at least one page"
    for p in pages:
        assert render_external_refs(p.read_text(), {}) == p.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/cce181 && python3 -m pytest tests/orchestrator/test_external_refs_e2e.py -v`
Expected: FAIL — the fixture directory does not exist yet, or `_render_external_refs_for_pages` is missing if Tasks 4–5 were skipped.

- [ ] **Step 3: Adjust fixtures only**

No production code in this task. If the fixture run fails, edit only `tests/orchestrator/fakes_external_repo/fake_pr_summarizer.json` so its `doc_targets` entry names the `core` lens with `page_hint: "page.md"`, matching `fake_page_author.json` above. If a change under `scripts/` seems necessary, STOP and report it — it means an earlier task is incomplete.

- [ ] **Step 4: Run the full suite**

Run: `cd ~/Projects/cce181 && python3 -m pytest -q`
Expected: PASS — the pre-existing baseline (1558 passed, 4 skipped at `77c6894`) plus the new tests, zero failures.

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/cce181
git add tests/orchestrator/fakes_external_repo tests/orchestrator/test_external_refs_e2e.py
git commit -m "test(external-refs): end-to-end and bare-host inertness — CCE-181"
```

---

## Self-Review

**Spec coverage.** Config shape → Tasks 1 and 3. The rendering rule and its three load-bearing properties → Task 2. Placement (render → diagnose → validate) → Task 4. The `page-author` contract change and prompt payload → Task 5. Collision guard → Tasks 1 and 3. Bare-host degradation → Tasks 2, 4 and 6. The spec's nine-item test plan maps across Tasks 1, 2, 3, 4 and 6. The `external_repos` naming decision is enforced by the Global Constraints and the `fakes_external_repo/` directory name.

**Placeholder scan.** No `TBD`/`TODO`. Every code step carries runnable code. Task 6 Step 3 has no production code by design and states exactly what to do instead of leaving it vague.

**Type consistency.** `resolve_config(config, *, host_dirs)` returns `{prefix: {"url", "private", "ref", "blob_template"}}` in Task 1 and is consumed with exactly those keys in Task 2 (`entry["private"]`, `entry["blob_template"]`, `entry["ref"]`, `entry["url"]`), Task 3 and Task 5. `render_external_refs(text, repos)` keeps that signature in Tasks 2, 4 and 6. `_render_external_refs_for_pages(authored, config)` and `_external_repo_prefixes(config)` are defined in Tasks 4 and 5 and used only there and in Task 6.

**Two gaps found and closed during review.**

1. Task 4's helper originally wrote every page unconditionally, giving unchanged pages a new mtime on every host including bare ones. It now writes only on an actual change, and `test_a_bare_host_leaves_the_file_byte_identical` asserts the mtime is untouched.
2. `_INLINE_CODE_RE` and `import re` were introduced in Task 2's snippet but belong to the module created in Task 1. Both moved into Task 1's implementation so Task 2 is a pure append and neither task leaves the module in a non-importable state.
