# Bootstrap fail-fast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `run_bootstrap_core` reject + delete pages with unparseable frontmatter or thin descriptions, and write a per-page progress file, so future canonical-core authoring runs don't need manual intervention.

**Architecture:** Add a new `dispatch_verified` wrapper around `dispatch_validated` that accepts a `post_write_check` callback; a generator-aware Tier-1 lint rule `description_quality` with a pure `check_fm` core function; a strict frontmatter parser sibling `parse_frontmatter_strict` that distinguishes "bad YAML" from "no frontmatter"; and a `_BootstrapProgress` helper that atomically writes `.engineering-docs-agent/bootstrap.progress.json` per page transition. `run_bootstrap_core` composes a callback combining the strict parser + `description_quality.check_fm` and passes it through `dispatch_verified`.

**Tech Stack:** Python 3.11+ stdlib + `pyyaml` (already present). No new runtime dependencies. Test runner: `python3 -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-28-bootstrap-fail-fast-design.md` (CCE-38).

**Branch:** `feat/CCE-38-bootstrap-fail-fast` (already exists, off `origin/main` at `da1446d`, currently 1 commit ahead carrying the spec).

**Standing constraints:**

- Never use `-f`/`--force`/`--no-verify`/`--amend`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- All work on this branch; do not commit to `main`.
- Branch protection on `main` requires `diagram-gate`, `pytest 3.11`, `pytest 3.12` green.

---

## File structure

| File                                            | Action           | Responsibility                                                                                                                                      |
| ----------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/archive_indexes.py`                    | Modify           | Add sibling `parse_frontmatter_strict` that raises `yaml.YAMLError` and `ValueError`; existing `parse_frontmatter` untouched.                       |
| `scripts/lint/description_quality.py`           | Create           | New Tier-1 lint rule. Pure `check_fm(fm, *, title, config)`; file-reading shim `check_path(path, config)`; CLI `main()`.                            |
| `scripts/lint/lint_runner.py`                   | Modify line 21   | Add `"description_quality"` to `TIER1_DEFAULT` list.                                                                                                |
| `scripts/orchestrator_runner.py`                | Modify           | Add `dispatch_verified` wrapper (after line 519). Add `_BootstrapProgress` helper class. Modify `run_bootstrap_core` (lines 1251-1353) to use both. |
| `tests/archive/test_archive_indexes.py`         | Create or extend | Tests for `parse_frontmatter_strict` (4 cases).                                                                                                     |
| `tests/lint/test_description_quality.py`        | Create           | 8 unit tests covering `check_fm` matrix + `check_path` + enabled_rules registration.                                                                |
| `tests/orchestrator/test_dispatch_verified.py`  | Create           | 4 unit tests for the wrapper (pass-through, success, failure deletes file, schema-invalid short-circuit).                                           |
| `tests/orchestrator/test_bootstrap_progress.py` | Create           | 4 unit tests for `_BootstrapProgress` (atomic write, transitions, error tolerance, cleanup).                                                        |
| `tests/orchestrator/test_bootstrap_core.py`     | Modify (append)  | Integration tests for fail-fast: bad YAML, thin description, ok-then-rerun retry.                                                                   |

---

## Task 1: `parse_frontmatter_strict` helper in `archive_indexes`

**Files:**

- Modify: `scripts/archive_indexes.py:44-56` (insert new function after the existing `parse_frontmatter`)
- Create (or extend): `tests/archive/test_archive_indexes.py`

This is the foundation for Task 7's bootstrap callback — it must land first so the callback can distinguish "bad YAML" from "no frontmatter".

- [ ] **Step 1.1: Check whether `tests/archive/test_archive_indexes.py` already exists**

Run:

```bash
ls tests/archive/ 2>/dev/null || echo "no tests/archive dir"
ls tests/archive/test_archive_indexes.py 2>/dev/null || echo "no existing test file"
```

If `tests/archive/` does not exist, create it with `mkdir -p tests/archive` and an empty `tests/archive/__init__.py` (so pytest discovers it consistently with siblings like `tests/orchestrator/`).

If `test_archive_indexes.py` exists, append the new tests at the end. If it doesn't, create a new file with the imports below.

- [ ] **Step 1.2: Write the four failing tests**

Append to (or create) `tests/archive/test_archive_indexes.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import archive_indexes  # noqa: E402


def test_parse_frontmatter_strict_returns_dict_on_valid_input():
    text = "---\ndescription: hello world\nstatus: draft\n---\n# Body\n"
    fm = archive_indexes.parse_frontmatter_strict(text)
    assert fm == {"description": "hello world", "status": "draft"}


def test_parse_frontmatter_strict_returns_empty_dict_on_empty_block():
    text = "---\n---\n# Body\n"
    assert archive_indexes.parse_frontmatter_strict(text) == {}


def test_parse_frontmatter_strict_raises_yaml_error_on_bad_yaml():
    # The CCE-15-style failure: a bare `: ` inside a backticked value
    # makes pyyaml treat it as a nested mapping separator.
    text = "---\ndescription: `additionalProperties: false`\n---\n"
    with pytest.raises(yaml.YAMLError):
        archive_indexes.parse_frontmatter_strict(text)


def test_parse_frontmatter_strict_raises_value_error_on_no_frontmatter():
    with pytest.raises(ValueError):
        archive_indexes.parse_frontmatter_strict("# No frontmatter here\n")
    # And on truncated frontmatter (missing closing fence).
    with pytest.raises(ValueError):
        archive_indexes.parse_frontmatter_strict("---\ndescription: x\n# Body\n")
```

- [ ] **Step 1.3: Run the tests to verify they fail**

Run: `python3 -m pytest tests/archive/test_archive_indexes.py -v`

Expected: `AttributeError: module 'archive_indexes' has no attribute 'parse_frontmatter_strict'` — 4 failures.

- [ ] **Step 1.4: Implement `parse_frontmatter_strict`**

Edit `scripts/archive_indexes.py`. After the existing `parse_frontmatter` function (which ends at line 56), insert:

```python
def parse_frontmatter_strict(text: str) -> dict:
    """Like ``parse_frontmatter``, but lets the caller distinguish failure modes.

    - Raises ``yaml.YAMLError`` on parse failure (original exception unwrapped).
    - Raises ``ValueError('no frontmatter')`` when the document does not start
      with ``---`` or lacks a closing fence.
    - Returns the parsed dict on success; an empty frontmatter block returns ``{}``.

    The lenient sibling ``parse_frontmatter`` stays for callers that intentionally
    want bad input to degrade to an empty dict (whats-new prepend, source_map,
    archive index collection).
    """
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("no frontmatter")
    data = yaml.safe_load(parts[1])
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data
```

- [ ] **Step 1.5: Run tests to verify they pass**

Run: `python3 -m pytest tests/archive/test_archive_indexes.py -v`

Expected: 4 passed.

Also run the full suite to confirm no regression in lenient-parser callers:

Run: `python3 -m pytest -q`

Expected: existing pass count + 4 new. No regressions.

- [ ] **Step 1.6: Commit**

```bash
git add scripts/archive_indexes.py tests/archive/
git commit -m "$(cat <<'EOF'
feat(CCE-38): add parse_frontmatter_strict to archive_indexes

Sibling of the existing lenient parser. Raises yaml.YAMLError on bad
YAML and ValueError on absent/truncated frontmatter, so callers can
record distinct ledger reasons (frontmatter_parse_error vs
frontmatter_missing).

The existing parse_frontmatter stays untouched per CLAUDE.md's
shared-helpers-are-contracts rule. New helper is the contract any
caller that needs the distinction can adopt.

Foundation for the bootstrap post-write verification callback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `description_quality.check_fm` pure core function

**Files:**

- Create: `scripts/lint/description_quality.py`
- Create: `tests/lint/test_description_quality.py`

Build the pure core first. The path-reading shim and CLI come in Task 3; this task focuses on the in-process function the bootstrap callback will call.

- [ ] **Step 2.1: Verify `tests/lint/` layout**

Run: `ls tests/lint/__init__.py 2>/dev/null && ls tests/lint/test_*.py | head -3`

If `tests/lint/__init__.py` is missing, create it as an empty file so pytest discovery matches siblings.

- [ ] **Step 2.2: Write the failing tests for `check_fm`**

Create `tests/lint/test_description_quality.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))
import description_quality  # noqa: E402


_DEFAULT_CONFIG: dict = {"lint": {"tier1": "default"}}


def test_check_fm_passes_for_substantial_description():
    fm = {"description": "Pulls merged PRs and Jira issues from the configured window."}
    ok, msg = description_quality.check_fm(fm, title="Source collector", config=_DEFAULT_CONFIG)
    assert ok, msg
    assert msg == "ok"


def test_check_fm_rejects_below_min_words():
    fm = {"description": "Source-collector capability."}  # 2 words
    ok, msg = description_quality.check_fm(fm, title="Source collector", config=_DEFAULT_CONFIG)
    assert not ok
    assert "min_words" in msg


def test_check_fm_rejects_equal_to_title():
    fm = {"description": "Source collector"}
    ok, msg = description_quality.check_fm(fm, title="Source collector", config=_DEFAULT_CONFIG)
    assert not ok
    assert "equal_to_title" in msg


def test_check_fm_rejects_trailing_colon():
    fm = {"description": "Pulls merged PRs and Jira issues from the window:"}
    ok, msg = description_quality.check_fm(fm, title="X", config=_DEFAULT_CONFIG)
    assert not ok
    assert "trailing_colon" in msg


def test_check_fm_rejects_missing_description_field():
    fm = {"status": "draft"}
    ok, msg = description_quality.check_fm(fm, title="X", config=_DEFAULT_CONFIG)
    assert not ok
    assert "missing" in msg


def test_check_fm_with_title_none_skips_equal_to_title_check():
    # When the title is unknown (e.g. body has no H1 yet), the equal-to-title
    # comparison is skipped; the other checks still apply.
    fm = {"description": "Pulls merged PRs and Jira issues from the configured window."}
    ok, msg = description_quality.check_fm(fm, title=None, config=_DEFAULT_CONFIG)
    assert ok, msg


def test_check_fm_respects_min_words_config_override():
    cfg = {"lint": {"tier1": {"description_quality": {"min_words": 2}}}}
    fm = {"description": "Two words."}  # 2 words, normally too short
    ok, msg = description_quality.check_fm(fm, title="X", config=cfg)
    assert ok, msg


def test_check_fm_respects_forbid_trailing_colon_disabled():
    cfg = {"lint": {"tier1": {"description_quality": {"forbid_trailing_colon": False}}}}
    fm = {"description": "Pulls merged PRs from the configured window:"}
    ok, msg = description_quality.check_fm(fm, title="X", config=cfg)
    assert ok, msg
```

- [ ] **Step 2.3: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_description_quality.py -v`

Expected: `ModuleNotFoundError: No module named 'description_quality'` — 8 errors.

- [ ] **Step 2.4: Implement `description_quality.check_fm`**

Create `scripts/lint/description_quality.py` with the pure core only (path-shim and CLI come in Task 3):

```python
"""Lint rule: description_quality. Enforces frontmatter `description` is a
substantive sentence, not a placeholder copied from the page title.

Applies only to agent-authored sections (the lens whose required fields
include ``description``). Other lenses have their own required-field set and
this rule is a no-op for them.
"""

from __future__ import annotations

from typing import Any

RULE_NAME = "description_quality"
SEVERITY = "block"

_DEFAULTS = {
    "min_words": 6,
    "forbid_equal_to_title": True,
    "forbid_trailing_colon": True,
}


def _resolve_config(config: dict[str, Any]) -> dict[str, Any]:
    """Merge defaults with the host's overrides under
    ``lint.tier1.description_quality``. ``lint.tier1`` may be the sentinel
    string ``"default"`` (then no overrides) or a dict carrying rule subkeys.
    """
    lint = (config or {}).get("lint") or {}
    tier1 = lint.get("tier1")
    if not isinstance(tier1, dict):
        return dict(_DEFAULTS)
    overrides = tier1.get(RULE_NAME) or {}
    if not isinstance(overrides, dict):
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in overrides.items() if k in _DEFAULTS})
    return merged


def check_fm(
    fm: dict[str, Any],
    *,
    title: str | None,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Pure check against the frontmatter dict.

    ``title`` is compared against ``description`` only when
    ``forbid_equal_to_title`` is enabled AND ``title`` is not None. Callers that
    don't know the title (e.g. running before the body's H1 is parsed) pass
    None to skip that check.

    Returns ``(True, "ok")`` on pass; ``(False, reason)`` on rejection.
    """
    cfg = _resolve_config(config)
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return False, "missing or empty description"
    stripped = desc.strip()

    if cfg["forbid_trailing_colon"] and stripped.endswith(":"):
        return False, f"forbid_trailing_colon: description ends in ':'"

    if cfg["forbid_equal_to_title"] and title is not None:
        if stripped.lower() == title.strip().lower():
            return False, f"forbid_equal_to_title: description == title ('{title}')"

    word_count = len(stripped.split())
    if word_count < cfg["min_words"]:
        return False, f"min_words: {word_count} < {cfg['min_words']}"

    return True, "ok"
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_description_quality.py -v`

Expected: 8 passed.

- [ ] **Step 2.6: Commit**

```bash
git add scripts/lint/description_quality.py tests/lint/test_description_quality.py
git commit -m "$(cat <<'EOF'
feat(CCE-38): add description_quality.check_fm pure core

New lint rule's pure core function. Enforces three quality gates on the
agent-authored `description` frontmatter field:
  - min_words: configurable, default 6
  - forbid_equal_to_title: configurable, default true (skipped when
    title is None so callers that don't know the title can opt out)
  - forbid_trailing_colon: configurable, default true

All thresholds overridable under lint.tier1.description_quality.

Path-reading shim and CLI follow in the next commit. Bootstrap callback
will import check_fm directly (in-process, no subprocess hop) so the
fail-fast path is fast.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `description_quality.check_path` + CLI wrapper + Tier-1 registration

**Files:**

- Modify: `scripts/lint/description_quality.py` (append the shim + main)
- Modify: `scripts/lint/lint_runner.py:21` (add `"description_quality"` to `TIER1_DEFAULT`)
- Append to: `tests/lint/test_description_quality.py`

This task makes the rule callable from the standard `lint_runner` path so `content-validator` exercises it on nightly authoring.

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/lint/test_description_quality.py`:

```python
import json
import subprocess

import yaml


_CONFIG_WITH_AGENT_AUTHORED = """
docs:
  source_dir: docs/site-src
site:
  docs_dir: docs/site-src
  sections:
    - key: home
      path: index.md
      title: Home
    - key: core
      path: core/
      title: Core
      generator: agent-authored
lint: { tier1: default, tier2: {}, tier3: {} }
"""


def _write_config(tmp_path: Path) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(_CONFIG_WITH_AGENT_AUTHORED)
    return p


def _write_page(tmp_path: Path, rel: str, *, description: str, title: str = "API") -> Path:
    (tmp_path / "docs" / "site-src" / "core").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "docs" / "site-src" / rel
    p.write_text(f"---\ndescription: {description}\n---\n# {title}\n\nBody.\n")
    return p


def test_check_path_skips_non_agent_authored_lens(tmp_path):
    cfg_path = _write_config(tmp_path)
    config = yaml.safe_load(cfg_path.read_text())
    # index.md is under "home" section (no generator); rule is a no-op.
    page = tmp_path / "docs" / "site-src" / "index.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("---\ndescription: x\n---\n# Home\n")
    ok, msg = description_quality.check_path(page, config)
    assert ok
    assert "skipped" in msg


def test_check_path_uses_body_h1_for_equal_to_title(tmp_path):
    cfg_path = _write_config(tmp_path)
    config = yaml.safe_load(cfg_path.read_text())
    page = _write_page(tmp_path, "core/api.md", description="API", title="API")
    ok, msg = description_quality.check_path(page, config)
    assert not ok
    assert "equal_to_title" in msg


def test_check_path_passes_for_substantial_agent_authored_page(tmp_path):
    cfg_path = _write_config(tmp_path)
    config = yaml.safe_load(cfg_path.read_text())
    page = _write_page(
        tmp_path,
        "core/api.md",
        description="Routes HTTP requests to handlers and serialises responses.",
        title="API",
    )
    ok, msg = description_quality.check_path(page, config)
    assert ok, msg


def test_cli_emits_json_and_returns_1_on_failure(tmp_path):
    cfg_path = _write_config(tmp_path)
    page = _write_page(tmp_path, "core/api.md", description="API", title="API")
    script = Path(__file__).resolve().parents[2] / "scripts" / "lint" / "description_quality.py"
    r = subprocess.run(
        [sys.executable, str(script), "--config", str(cfg_path), "--paths", str(page), "--json"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1, r.stderr
    payload = json.loads(r.stdout)
    assert payload["rule"] == "description_quality"
    assert payload["severity"] == "block"
    assert payload["results"][0]["ok"] is False


def test_lint_runner_includes_description_quality_in_tier1_default():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))
    import lint_runner  # noqa: WPS433 — late import after sys.path fix

    rules = lint_runner.enabled_rules({"lint": {"tier1": "default"}})
    assert "description_quality" in rules
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `python3 -m pytest tests/lint/test_description_quality.py -v -k "check_path or cli or runner"`

Expected: 5 failures — `AttributeError: module 'description_quality' has no attribute 'check_path'` and `lint_runner` assertion.

- [ ] **Step 3.3: Implement `check_path`, `main`, and CLI plumbing**

Append to `scripts/lint/description_quality.py`:

```python


# Path-reading shim ---------------------------------------------------------

import argparse
import json
import sys
from pathlib import Path

import yaml

# Sibling-script import pattern: place the parent scripts/ on sys.path so the
# in-repo frontmatter_contract and archive_indexes modules resolve. Mirrors
# frontmatter_schema.py:10.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive_indexes  # noqa: E402
import frontmatter_contract as fc  # noqa: E402


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    """Read ``path``, resolve its section generator, and apply ``check_fm`` only
    to agent-authored pages. Non-agent-authored sections are silent no-ops.

    Frontmatter parse errors are reported as failures so this rule can also
    surface gap-3-class defects when invoked through ``lint_runner`` rather
    than the bootstrap callback. (The bootstrap path uses
    ``parse_frontmatter_strict`` directly so it can record distinct reasons.)
    """
    if not path.exists():
        return False, "file not found"
    generator = fc.section_generator_for(path, config)
    if generator != "agent-authored":
        return True, "not agent-authored; skipped"
    text = path.read_text()
    try:
        fm = archive_indexes.parse_frontmatter_strict(text)
    except yaml.YAMLError:
        return False, "frontmatter YAML parse error"
    except ValueError:
        return False, "no frontmatter block"
    title, _ = archive_indexes.parse_title_and_summary(text)
    return check_fm(fm, title=title or None, config=config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, config)
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

- [ ] **Step 3.4: Register in `lint_runner.TIER1_DEFAULT`**

Edit `scripts/lint/lint_runner.py:21-29`. Change:

```python
TIER1_DEFAULT = [
    "frontmatter_schema",
    "internal_links",
    "markdown_hygiene",
    "footnotes",
    "diagrams",
    "framework_build",
    "stub_redirect",
]
```

to:

```python
TIER1_DEFAULT = [
    "frontmatter_schema",
    "internal_links",
    "markdown_hygiene",
    "footnotes",
    "diagrams",
    "framework_build",
    "stub_redirect",
    "description_quality",
]
```

- [ ] **Step 3.5: Run tests to verify they pass**

Run: `python3 -m pytest tests/lint/test_description_quality.py -v`

Expected: 13 passed (8 from Task 2 + 5 new).

Also run the full suite:

Run: `python3 -m pytest -q`

Expected: prior count + 13. No regressions. If a test in `tests/lint/test_lint_runner.py` (or wherever the Tier-1 list is enumerated) expects exactly 7 rules, update its expected count. Search for it:

Run: `grep -rn "TIER1_DEFAULT\|tier1.*default" tests/ scripts/ --include='*.py'`

Update any hard-coded length assertion accordingly.

- [ ] **Step 3.6: Commit**

```bash
git add scripts/lint/description_quality.py scripts/lint/lint_runner.py tests/lint/test_description_quality.py
git commit -m "$(cat <<'EOF'
feat(CCE-38): description_quality CLI + Tier-1 registration

- check_path: file-reading shim. Resolves generator via
  frontmatter_contract.section_generator_for; non-agent-authored
  sections are silent no-ops. Body H1 supplies the title for the
  equal-to-title check. parse_frontmatter_strict failures surface as
  rule failures so content-validator catches gap-3-class defects too.
- main: standard --config --paths --json CLI matching frontmatter_schema.
- TIER1_DEFAULT extended from 7 to 8. Hosts that don't want it drop
  tier1: default and enumerate the seven they want.

The bootstrap callback (next commit) bypasses check_path and calls
check_fm directly, so the failure reason is distinguishable from the
generic "frontmatter YAML parse error" string this rule produces.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `dispatch_verified` wrapper

**Files:**

- Modify: `scripts/orchestrator_runner.py` (append after `dispatch_validated`, which ends at line 519)
- Create: `tests/orchestrator/test_dispatch_verified.py`

The wrapper is the contract layer that lets any caller request post-write verification. Bootstrap is the first caller; nightly authoring is a deliberate future opt-in.

- [ ] **Step 4.1: Write the failing tests**

Create `tests/orchestrator/test_dispatch_verified.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def _fake_dispatch_validated_ok(name, inputs, *, dry_run_dir, cwd=None):
    return ({"ok": True, "path": inputs["target_path"]}, [])


def _fake_dispatch_validated_invalid(name, inputs, *, dry_run_dir, cwd=None):
    return (None, ["schema_invalid: page-author: bad shape"])


def test_dispatch_verified_passes_through_when_post_write_check_is_none(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")
    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=None,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out == {"ok": True, "path": str(target)}
    assert reasons == []
    assert target.exists()  # not deleted


def test_dispatch_verified_short_circuits_on_dispatch_validated_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_invalid)
    target = tmp_path / "page.md"
    target.write_text("body")
    sentinel = {"called": False}

    def check(_target, _page):
        sentinel["called"] = True
        return False, ["should_not_run"]

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out is None
    assert reasons == ["schema_invalid: page-author: bad shape"]
    assert sentinel["called"] is False
    assert target.exists()  # untouched on schema-invalid


def test_dispatch_verified_returns_output_when_check_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")

    def check(t, _p):
        return True, []

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out == {"ok": True, "path": str(target)}
    assert reasons == []
    assert target.exists()


def test_dispatch_verified_deletes_target_and_returns_reasons_when_check_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "dispatch_validated", _fake_dispatch_validated_ok)
    target = tmp_path / "page.md"
    target.write_text("body")

    def check(t, _p):
        return False, [f"description_quality: {t.name}: min_words: 2 < 6"]

    out, reasons = runner.dispatch_verified(
        "page-author",
        {"target_path": str(target)},
        dry_run_dir=None,
        cwd=tmp_path,
        post_write_check=check,
        target_path=target,
        manifest_page={"page": "page.md"},
    )
    assert out is None
    assert any("description_quality" in r for r in reasons)
    assert not target.exists()  # deleted so next bootstrap run retries it
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_verified.py -v`

Expected: 4 errors — `AttributeError: module 'orchestrator_runner' has no attribute 'dispatch_verified'`.

- [ ] **Step 4.3: Implement `dispatch_verified`**

Edit `scripts/orchestrator_runner.py`. After the existing `dispatch_validated` (ends at line 519), insert:

```python


def dispatch_verified(
    name: str,
    inputs: dict,
    *,
    dry_run_dir: Path | None,
    cwd: Path | None = None,
    post_write_check: Callable[[Path, dict], tuple[bool, list[str]]] | None = None,
    target_path: Path | None = None,
    manifest_page: dict | None = None,
) -> tuple[dict | None, list[str]]:
    """Dispatch a subagent through ``dispatch_validated``, then run an optional
    post-write check against the artifact the agent produced.

    On check failure, ``target_path`` is unlinked so the next bootstrap run
    retries this page (the orchestrator's existing
    ``if target_path.exists(): skip`` idempotency is the retry mechanism). The
    augmented reason list is returned alongside ``out=None`` so the caller's
    ledger receives the rejection.

    ``post_write_check=None`` is a pure pass-through — callers that haven't
    opted in see no behavior change.
    """
    out, reasons = dispatch_validated(
        name, inputs, dry_run_dir=dry_run_dir, cwd=cwd
    )
    if out is None or post_write_check is None:
        return out, reasons
    assert target_path is not None, (
        "dispatch_verified: target_path is required when post_write_check is set"
    )
    ok, check_reasons = post_write_check(target_path, manifest_page or {})
    if ok:
        return out, reasons
    # Reject: delete the artifact and roll up the new reasons.
    try:
        target_path.unlink(missing_ok=True)
    except OSError as e:
        check_reasons.append(f"unlink_failed: {target_path}: {e}")
    return None, reasons + check_reasons
```

Also ensure `Callable` is importable at the top of the file. Check the current imports:

Run: `grep -n "from typing\|^import typing\|Callable" scripts/orchestrator_runner.py | head -10`

If `Callable` is not already imported, add it to the existing `from typing import …` block, or insert `from typing import Callable` near the top of the imports (after the existing `from typing import …` line if any; otherwise group with other stdlib imports).

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_dispatch_verified.py -v`

Expected: 4 passed.

Also run the full suite:

Run: `python3 -m pytest -q`

Expected: prior count + 4. No regressions.

- [ ] **Step 4.5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_verified.py
git commit -m "$(cat <<'EOF'
feat(CCE-38): dispatch_verified wrapper around dispatch_validated

Thin wrapper that runs an optional post_write_check callback after a
successful dispatch. On callback failure: unlinks target_path, returns
(None, reasons + check_reasons). Bootstrap's existing
target_path.exists() idempotency naturally retries the rejected page on
re-run.

post_write_check=None is pass-through so the wrapper can replace
dispatch_validated callsites without behavior change, then have
callbacks added incrementally.

Bootstrap wires its callback in a later commit; nightly authoring stays
on bare dispatch_validated until a gap-3-class defect is observed
there.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `_BootstrapProgress` helper class

**Files:**

- Modify: `scripts/orchestrator_runner.py` (append after `dispatch_verified` from Task 4)
- Create: `tests/orchestrator/test_bootstrap_progress.py`

Atomic-write progress file. Best-effort: write failures degrade to stderr but never abort bootstrap.

- [ ] **Step 5.1: Write the failing tests**

Create `tests/orchestrator/test_bootstrap_progress.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_progress_start_writes_initial_state(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=3)
    p.start()
    payload = json.loads((tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text())
    assert payload["phase"] == "bootstrap"
    assert payload["total"] == 3
    assert payload["current_index"] == 0
    assert payload["current_page"] is None
    assert payload["completed"] == []
    assert payload["skipped_existing"] == []
    assert payload["failed"] == []


def test_progress_transitions_advance_current_and_record_completion(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=2)
    p.start()
    p.begin_page("core/api.md")
    p.mark_completed("core/api.md")
    p.begin_page("core/storage.md")
    p.mark_skipped("core/storage.md")
    payload = json.loads((tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text())
    assert payload["current_index"] == 2
    assert payload["current_page"] == "core/storage.md"
    assert payload["completed"] == ["core/api.md"]
    assert payload["skipped_existing"] == ["core/storage.md"]


def test_progress_records_failure_reason(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=1)
    p.start()
    p.begin_page("core/bad.md")
    p.mark_failed("core/bad.md", reason="frontmatter_parse_error: core/bad.md: ScannerError")
    payload = json.loads((tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").read_text())
    assert payload["failed"] == [
        {"path": "core/bad.md", "reason": "frontmatter_parse_error: core/bad.md: ScannerError"}
    ]


def test_progress_finish_unlinks_file(tmp_path):
    (tmp_path / ".engineering-docs-agent").mkdir()
    p = runner._BootstrapProgress(tmp_path, total=0)
    p.start()
    assert (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").exists()
    p.finish()
    assert not (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").exists()


def test_progress_write_failures_are_swallowed(tmp_path, capsys):
    # Point the helper at a directory that doesn't exist; every write should
    # log to stderr but not raise.
    p = runner._BootstrapProgress(tmp_path / "does-not-exist", total=1)
    p.start()  # would fail to write the initial file
    p.begin_page("x.md")
    p.mark_completed("x.md")
    p.finish()
    err = capsys.readouterr().err
    assert "bootstrap.progress.json" in err
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_progress.py -v`

Expected: 5 errors — `AttributeError: module 'orchestrator_runner' has no attribute '_BootstrapProgress'`.

- [ ] **Step 5.3: Implement `_BootstrapProgress`**

Append to `scripts/orchestrator_runner.py` (after `dispatch_verified` from Task 4):

```python


class _BootstrapProgress:
    """Best-effort per-page progress file for ``run_bootstrap_core``.

    Path: ``<repo_root>/.engineering-docs-agent/bootstrap.progress.json``.
    Write cadence: atomic (temp-file + ``os.replace``) on every transition.
    File is unlinked at end of run; an existing file is itself a signal that
    a run is in progress or crashed mid-flight.

    All write failures are logged to stderr; the bootstrap loop never aborts
    because of progress-file I/O errors.
    """

    def __init__(self, repo_root: Path, *, total: int) -> None:
        self._path = repo_root / ".engineering-docs-agent" / "bootstrap.progress.json"
        self._state: dict = {
            "phase": "bootstrap",
            "started_at": None,
            "total": total,
            "current_index": 0,
            "current_page": None,
            "current_page_started_at": None,
            "completed": [],
            "skipped_existing": [],
            "failed": [],
        }

    def _write(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(self._state, indent=2))
            os.replace(tmp, self._path)
        except OSError as e:
            print(f"bootstrap.progress.json write failed: {e}", file=sys.stderr)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def start(self) -> None:
        self._state["started_at"] = datetime.now(timezone.utc).isoformat()
        self._write()

    def begin_page(self, rel_posix: str) -> None:
        self._state["current_index"] += 1
        self._state["current_page"] = rel_posix
        self._state["current_page_started_at"] = datetime.now(timezone.utc).isoformat()
        self._write()

    def mark_completed(self, rel_posix: str) -> None:
        self._state["completed"].append(rel_posix)
        self._write()

    def mark_skipped(self, rel_posix: str) -> None:
        # Skipped pages still advance current_index because they're a real
        # iteration of the loop, just not a dispatch.
        self._state["skipped_existing"].append(rel_posix)
        self._state["current_index"] += 1
        self._state["current_page"] = rel_posix
        self._write()

    def mark_failed(self, rel_posix: str, *, reason: str) -> None:
        self._state["failed"].append({"path": rel_posix, "reason": reason})
        self._write()

    def finish(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError as e:
            print(f"bootstrap.progress.json cleanup failed: {e}", file=sys.stderr)
```

Verify `os`, `datetime`, `timezone` are already imported at the top of the file:

Run: `head -30 scripts/orchestrator_runner.py | grep -E "^import os|datetime|timezone"`

If `os` is missing, add `import os` to the imports. The file already uses `datetime.now(timezone.utc).date().isoformat()` at line 1289, so those imports are present.

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_progress.py -v`

Expected: 5 passed.

Note on the `mark_skipped` test assertion: the test expects `current_index == 2` after one `begin_page` (advances to 1) + one `mark_skipped` (advances to 2). Both `begin_page` and `mark_skipped` advance the index because they represent real iterations of the bootstrap loop.

- [ ] **Step 5.5: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_bootstrap_progress.py
git commit -m "$(cat <<'EOF'
feat(CCE-38): _BootstrapProgress per-page atomic progress file

Writes .engineering-docs-agent/bootstrap.progress.json atomically
(temp + os.replace) on each transition. Schema:
  phase, started_at, total, current_index, current_page,
  current_page_started_at, completed[], skipped_existing[], failed[]

File is unlinked at finish(); an existing file means a run is in
progress or crashed mid-flight — useful for monitors and humans.

All write failures degrade to stderr; bootstrap never aborts on I/O
problems with the progress file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire `run_bootstrap_core` to use `dispatch_verified` + `_BootstrapProgress`

**Files:**

- Modify: `scripts/orchestrator_runner.py:1251-1353` (`run_bootstrap_core`)

The existing integration tests in `tests/orchestrator/test_bootstrap_core.py` are the regression net — they exercise the happy path, idempotency, dispatch failure, non-editable rejection, manifest variants, and CLI routing. New behaviour will be covered by Task 7's tests; this task's success criterion is **all existing tests still pass** after the rewrite.

- [ ] **Step 6.1: Confirm existing tests pass before rewrite**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -v`

Expected: all pass (10 tests including the e2e CLI ones). Record this count as the regression baseline.

- [ ] **Step 6.2: Rewrite the per-page loop body**

Edit `scripts/orchestrator_runner.py`. Replace the existing `run_bootstrap_core` body (lines 1251-1353) with the version below. Three changes from the original:

1. Add `import description_quality` after the existing `import frontmatter_contract as fmc` (line 1264).
2. Define the `_check` closure once and pass it as `post_write_check` to a new `dispatch_verified` call.
3. Instantiate `_BootstrapProgress`, call `start()`/`begin_page()`/`mark_completed()`/`mark_skipped()`/`mark_failed()`/`finish()` at the matching transitions.

Replace the existing function body with:

```python
def run_bootstrap_core(
    repo_root: Path,
    *,
    dry_run_dir: Path | None,
    today: str | None = None,
) -> int:
    """C2 bootstrap authoring entry. Reads <docs_dir>/.doc-core-manifest.json and
    authors each declared core page that has no file yet, via the unchanged
    page-author agent. Idempotent (create-missing only), diagram-free, best-effort
    per page (a dispatch failure or post-write verification failure records a
    reason and continues; the rejected file is deleted so re-run retries it).
    No-op when there is no config docs_dir, no manifest, or an empty manifest.
    Returns 0 on success/no-op, 2 on unreadable config. Prints a JSON ledger
    to stdout.

    Post-write verification (CCE-38): after each dispatch the orchestrator
    re-parses the frontmatter the agent wrote and runs
    ``description_quality.check_fm`` against it. Bad YAML, missing frontmatter,
    or a thin description rejects the page (file deleted, reason recorded).
    """
    import frontmatter_contract as fmc
    import archive_indexes
    import description_quality

    cfg_path = repo_root / ".engineering-docs-agent" / "config.yml"
    if not cfg_path.exists():
        print("no config", file=sys.stderr)
        return 2
    try:
        config = load_config_validated(cfg_path)
    except ConfigError as e:
        print(f"config invalid: {e}", file=sys.stderr)
        return 2

    docs_dir = _resolve_docs_dir(config)
    if docs_dir is None:
        print("no docs_dir; nothing to bootstrap", file=sys.stderr)
        return 0

    manifest_path = repo_root / docs_dir / ".doc-core-manifest.json"
    if not manifest_path.exists():
        print("no core manifest; run setup first", file=sys.stderr)
        return 0
    pages = _load_core_manifest_pages(repo_root, docs_dir)
    if not pages:
        return 0

    today = today or datetime.now(timezone.utc).date().isoformat()
    voice_samples = load_voice_samples(repo_root, config)
    editable_globs = config.get("docs", {}).get("agent_editable_paths", [])
    section = next(
        (
            s
            for s in ((config.get("site") or {}).get("sections") or [])
            if isinstance(s, dict) and s.get("generator") == "agent-authored"
        ),
        None,
    )
    lens = (section or {}).get("key") or "core"

    def _check(target_path: Path, page: dict) -> tuple[bool, list[str]]:
        try:
            rel_inner = target_path.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel_inner = target_path.as_posix()
        try:
            fm = archive_indexes.parse_frontmatter_strict(target_path.read_text())
        except yaml.YAMLError as e:
            return False, [
                f"frontmatter_parse_error: {rel_inner}: {e.__class__.__name__}"
            ]
        except ValueError:
            return False, [f"frontmatter_missing: {rel_inner}"]
        ok, msg = description_quality.check_fm(
            fm, title=page.get("title"), config=config
        )
        if not ok:
            return False, [f"description_quality: {rel_inner}: {msg}"]
        return True, []

    progress = _BootstrapProgress(repo_root, total=len(pages))
    progress.start()

    ledger: dict = {"authored": [], "skipped_existing": [], "reasons": []}
    try:
        for page in pages:
            if not isinstance(page, dict) or "page" not in page:
                ledger["reasons"].append("manifest_page_invalid")
                continue
            target_path = repo_root / docs_dir / page["page"]
            try:
                rel = target_path.resolve().relative_to(repo_root.resolve())
            except ValueError:
                ledger["reasons"].append(f"unsafe_page_path: {page['page']}")
                continue
            rel_posix = rel.as_posix()
            if not _page_target_is_editable(str(rel), editable_globs):
                ledger["reasons"].append(f"unsafe_page_path: {rel}")
                continue
            if target_path.exists():
                ledger["skipped_existing"].append(str(rel))
                progress.mark_skipped(rel_posix)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            progress.begin_page(rel_posix)
            out, reasons = dispatch_verified(
                "page-author",
                {
                    "target_path": str(target_path),
                    "action": "create",
                    "lens": lens,
                    "summaries": [],
                    "voice_samples": voice_samples,
                    "frontmatter_template": fmc.agent_authored_frontmatter_dict(
                        description=page.get("title") or page.get("key") or "",
                        source_files=page.get("source_files") or [],
                        last_reviewed=today,
                        status="draft",
                    ),
                    "manifest_page": page,
                },
                dry_run_dir=dry_run_dir,
                cwd=repo_root,
                post_write_check=_check,
                target_path=target_path,
                manifest_page=page,
            )
            ledger["reasons"].extend(reasons)
            if out is None:
                if not reasons:
                    ledger["reasons"].append(f"page_author_invalid: {rel}")
                # Find the matching reason (if any) for the progress file.
                progress.mark_failed(
                    rel_posix, reason=reasons[-1] if reasons else "page_author_invalid"
                )
                continue
            if out.get("ok"):
                if dry_run_dir and not target_path.exists():
                    _synthesize_core_page(target_path, page, today)
                ledger["authored"].append(str(rel))
                progress.mark_completed(rel_posix)
            else:
                err = out.get("error") or "page-author returned ok=false"
                msg = f"page_author_error: {rel}: {err}"
                ledger["reasons"].append(msg)
                progress.mark_failed(rel_posix, reason=msg)
    finally:
        progress.finish()

    print(json.dumps(ledger, indent=2))
    return 0
```

Also add `import yaml` to the module's top-level imports if it's not already there:

Run: `grep -nE '^import yaml|^from yaml' scripts/orchestrator_runner.py | head -3`

If absent, add `import yaml` near the other stdlib imports.

**Note on dry-run synth ordering**: the existing flow runs `_synthesize_core_page` _after_ `dispatch_validated` succeeds and only when `dry_run_dir is not None and not target_path.exists()`. In the new flow, `dispatch_verified` runs `_check` _before_ control returns to the loop body. In dry-run mode, the agent fixture itself does not write a file — the file appears only via `_synthesize_core_page` in the loop body. So `_check` would run against a non-existent file and fail with `frontmatter_missing`.

To preserve dry-run behaviour, the `_check` callback must early-exit when `target_path` does not exist (because in dry-run the synth happens later). Add this guard at the top of `_check`:

```python
        if not target_path.exists():
            # Dry-run path: _synthesize_core_page writes the body after dispatch
            # returns. The integration tests cover the synth case separately.
            return True, []
```

Place that block as the first statement of `_check`, before the parse attempt.

- [ ] **Step 6.3: Run existing bootstrap tests to verify no regression**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -v`

Expected: same 10 tests pass.

If any test that previously inspected the existence of `.engineering-docs-agent/` fails because the progress file is now written there, update the test's fixture to tolerate it (most fixtures use `tmp_path / ".engineering-docs-agent"` already; the helper auto-creates the directory if missing, but our progress class assumes it exists — verify by running the e2e test specifically).

If the e2e test (`test_bootstrap_core_e2e_creates_then_idempotent`) fails because `.engineering-docs-agent/bootstrap.progress.json.tmp` leaks, that's a bug in `_write` — `os.replace` should remove the temp atomically. Double-check.

- [ ] **Step 6.4: Run the full suite**

Run: `python3 -m pytest -q`

Expected: prior count + 0 (this task adds no new tests; it relies on Task 7's new tests for new-behavior coverage).

- [ ] **Step 6.5: Commit**

```bash
git add scripts/orchestrator_runner.py
git commit -m "$(cat <<'EOF'
feat(CCE-38): wire run_bootstrap_core to dispatch_verified + progress file

Per-page loop now:
  - Instantiates _BootstrapProgress(repo_root, total) and start()s it.
  - On each iteration: begin_page / mark_skipped / mark_completed /
    mark_failed at the matching transition.
  - Replaces dispatch_validated with dispatch_verified, passing a local
    _check closure that runs parse_frontmatter_strict +
    description_quality.check_fm against the agent's written
    frontmatter. Rejection: file deleted, reason recorded, loop
    continues.
  - finish()s the progress file in a finally clause so it's removed
    even on unexpected errors.

Dry-run mode is preserved: _check early-exits when the target file
doesn't exist, because in dry-run _synthesize_core_page writes the body
after dispatch returns (control flow inversion from production where
the agent writes via its Write tool before dispatch returns).

Existing tests (idempotency, dispatch failure, non-editable, manifest
variants, CLI routing) all still pass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Integration tests for bootstrap fail-fast

**Files:**

- Modify: `tests/orchestrator/test_bootstrap_core.py` (append new tests)

New behaviour proof: bad YAML and thin descriptions are rejected, the file is deleted, the ledger carries the reason, and re-run retries only the rejected pages.

- [ ] **Step 7.1: Write the failing integration tests**

Append to `tests/orchestrator/test_bootstrap_core.py`:

```python
def _spy_with_body_writer(calls, body_writer, result=({"ok": True}, [])):
    """A fake dispatch_validated that ALSO writes the page body, mimicking
    the production page-author (which uses its Write tool before returning).
    body_writer(target_path: Path, page: dict, today: str) -> str writes the
    text to disk; the spy returns the same ok=True payload regardless.
    """

    def fake(name, inputs, *, dry_run_dir, cwd=None):
        calls.append({"name": name, "inputs": inputs})
        target = Path(inputs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body_writer(target, inputs))
        return result

    return fake


def _body_with_bad_yaml(target: Path, inputs: dict) -> str:
    # The CCE-15-style failure: an unescaped colon inside a backticked value.
    return (
        "---\n"
        "description: `additionalProperties: false`\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def _body_with_thin_description(target: Path, inputs: dict) -> str:
    return (
        "---\n"
        "description: API\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def _body_ok(target: Path, inputs: dict) -> str:
    return (
        "---\n"
        "description: Routes HTTP requests to handlers and serialises responses.\n"
        "source_files: []\n"
        "last_reviewed: '2026-05-26'\n"
        "status: draft\n"
        "---\n"
        "# Body\n"
    )


def test_bootstrap_rejects_and_deletes_bad_yaml(tmp_path, monkeypatch, capsys):
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
    ]})
    calls = []
    monkeypatch.setattr(
        runner, "dispatch_validated",
        _spy_with_body_writer(calls, _body_with_bad_yaml),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any("frontmatter_parse_error" in r for r in ledger["reasons"]), ledger
    # The file the spy wrote was deleted so re-run will retry.
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rejects_and_deletes_thin_description(tmp_path, monkeypatch, capsys):
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
    ]})
    calls = []
    monkeypatch.setattr(
        runner, "dispatch_validated",
        _spy_with_body_writer(calls, _body_with_thin_description),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == []
    assert any("description_quality" in r for r in ledger["reasons"]), ledger
    assert not (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_accepts_substantial_description(tmp_path, monkeypatch, capsys):
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
    ]})
    calls = []
    monkeypatch.setattr(
        runner, "dispatch_validated",
        _spy_with_body_writer(calls, _body_ok),
    )
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger = _json.loads(capsys.readouterr().out)
    assert ledger["authored"] == ["docs/site-src/core/api.md"]
    assert not any("description_quality" in r for r in ledger["reasons"])
    assert (tmp_path / "docs/site-src/core/api.md").exists()


def test_bootstrap_rerun_retries_only_rejected_pages(tmp_path, monkeypatch, capsys):
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
        {"key": "storage", "title": "Storage", "page": "core/storage.md", "source_files": []},
    ]})
    # First run: api gets thin desc, storage gets ok.
    state = {"page_to_body": {"core/api.md": _body_with_thin_description,
                              "core/storage.md": _body_ok}}

    def fake1(name, inputs, *, dry_run_dir, cwd=None):
        rel = Path(inputs["target_path"]).relative_to(tmp_path).as_posix().split("docs/site-src/", 1)[-1]
        body = state["page_to_body"][f"core/{rel.rsplit('/', 1)[-1]}"](Path(inputs["target_path"]), inputs)
        Path(inputs["target_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(inputs["target_path"]).write_text(body)
        return ({"ok": True}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake1)
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger_1 = _json.loads(capsys.readouterr().out)
    assert ledger_1["authored"] == ["docs/site-src/core/storage.md"]
    assert any("description_quality" in r for r in ledger_1["reasons"])
    assert not (tmp_path / "docs/site-src/core/api.md").exists()
    assert (tmp_path / "docs/site-src/core/storage.md").exists()

    # Second run: api retries with a substantial description; storage is
    # skipped_existing (idempotency).
    state["page_to_body"]["core/api.md"] = _body_ok
    calls2: list = []
    monkeypatch.setattr(runner, "dispatch_validated",
                        _spy_with_body_writer(calls2, _body_ok))
    rc = runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert rc == 0
    ledger_2 = _json.loads(capsys.readouterr().out)
    assert ledger_2["authored"] == ["docs/site-src/core/api.md"]
    assert ledger_2["skipped_existing"] == ["docs/site-src/core/storage.md"]
    # Only the previously-rejected page was retried.
    assert len(calls2) == 1
    assert calls2[0]["inputs"]["target_path"].endswith("core/api.md")


def test_bootstrap_progress_file_is_removed_at_end_of_run(tmp_path, monkeypatch):
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
    ]})
    calls = []
    monkeypatch.setattr(
        runner, "dispatch_validated",
        _spy_with_body_writer(calls, _body_ok),
    )
    runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert not (tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json").exists()


def test_bootstrap_progress_file_records_inflight_state(tmp_path, monkeypatch):
    """During a run, capture the progress file's state at the moment of dispatch
    so we can assert current_page reflects live state.
    """
    _host(tmp_path, manifest={"version": 1, "pages": [
        {"key": "api", "title": "Api", "page": "core/api.md", "source_files": []},
        {"key": "storage", "title": "Storage", "page": "core/storage.md", "source_files": []},
    ]})
    captured: list = []

    def fake_capture(name, inputs, *, dry_run_dir, cwd=None):
        progress_path = tmp_path / ".engineering-docs-agent" / "bootstrap.progress.json"
        captured.append(_json.loads(progress_path.read_text()))
        target = Path(inputs["target_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_body_ok(target, inputs))
        return ({"ok": True}, [])

    monkeypatch.setattr(runner, "dispatch_validated", fake_capture)
    runner.run_bootstrap_core(tmp_path, dry_run_dir=None, today="2026-05-26")
    assert captured[0]["current_index"] == 1
    assert captured[0]["current_page"] == "docs/site-src/core/api.md"
    assert captured[1]["current_index"] == 2
    assert captured[1]["current_page"] == "docs/site-src/core/storage.md"
    # Final state after the run is gone (test above covers it).
```

- [ ] **Step 7.2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -v -k "bad_yaml or thin_description or substantial or rerun_retries or progress_file"`

Expected: depends on what landed in Tasks 4-6. If Task 6 is in, these should pass already (the implementation enables them). If you reach this task with the implementation incomplete, expect 6 failures showing the gap.

- [ ] **Step 7.3: Run the full bootstrap test file**

Run: `python3 -m pytest tests/orchestrator/test_bootstrap_core.py -v`

Expected: 16 passed (10 pre-existing + 6 new).

- [ ] **Step 7.4: Run the entire suite**

Run: `python3 -m pytest -q`

Expected: prior baseline + 4 (Task 1) + 8 (Task 2) + 5 (Task 3) + 4 (Task 4) + 5 (Task 5) + 6 (Task 7) = +32 new tests passing.

- [ ] **Step 7.5: Commit**

```bash
git add tests/orchestrator/test_bootstrap_core.py
git commit -m "$(cat <<'EOF'
test(CCE-38): integration tests for bootstrap fail-fast

Six new tests covering:
  - bad-YAML rejection (file deleted, ledger reason)
  - thin-description rejection (file deleted, ledger reason)
  - substantial-description acceptance
  - re-run after rejection: rejected page retried, ok page skipped
  - bootstrap.progress.json removed at end of run
  - bootstrap.progress.json reflects live current_page during run

Spy helper _spy_with_body_writer mimics the production page-author by
writing the page body before returning ok=true (in production the
agent uses its Write tool; in dry-run mode _synthesize_core_page does
the equivalent later in the loop).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Validate on this host (dogfood)

The plan's spec mandates running the integrated suite against the merge target before merging. This task adds a manual exercise against this very repo to confirm the system catches a real CCE-15-style defect.

- [ ] **Step 8.1: Merge `main` into the branch and run the integrated suite**

Run:

```bash
git fetch origin main
git merge --no-edit origin/main
python3 -m pytest -q
```

Expected: full suite green on the combined tree.

- [ ] **Step 8.2: Build a synthetic bad page and assert the gate catches it**

Run (one-off, not committed):

```bash
python3 -m pytest tests/orchestrator/test_bootstrap_core.py::test_bootstrap_rejects_and_deletes_bad_yaml \
                  tests/orchestrator/test_bootstrap_core.py::test_bootstrap_rejects_and_deletes_thin_description -v
```

Expected: both pass.

Also exercise the CLI rule against a deliberately bad file in this repo's existing canonical-core lens:

```bash
mkdir -p /tmp/cce38-dogfood
cat >/tmp/cce38-dogfood/bad.md <<'MD'
---
description: API
---
# API
MD
python3 scripts/lint/description_quality.py \
  --config .engineering-docs-agent/config.yml \
  --paths /tmp/cce38-dogfood/bad.md --json
echo "exit: $?"
```

Expected: JSON output where `results[0].ok == false` with a `forbid_equal_to_title` or `min_words` reason; exit code 1. Note: `/tmp/cce38-dogfood/bad.md` is outside the host's `docs/site-src/` tree, so `section_generator_for` returns None and the rule will SKIP it. To force the agent-authored path, instead use a temporary file inside `docs/site-src/architecture/`:

```bash
cat >/tmp/cce38-dogfood/bad.md <<'MD'
---
description: API
last_reviewed: '2026-05-28'
status: draft
source_files: []
---
# API
MD
mkdir -p docs/site-src/architecture/_dogfood
cp /tmp/cce38-dogfood/bad.md docs/site-src/architecture/_dogfood/api.md
python3 scripts/lint/description_quality.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/architecture/_dogfood/api.md --json
echo "exit: $?"
rm -rf docs/site-src/architecture/_dogfood
```

Expected: `ok: false` with `forbid_equal_to_title` reason; exit 1. The cleanup `rm -rf` is scoped to the temp dir.

- [ ] **Step 8.3: Verify the existing canonical-core pages still pass the new rule**

Run:

```bash
python3 scripts/lint/description_quality.py \
  --config .engineering-docs-agent/config.yml \
  --paths docs/site-src/architecture/*.md --json | python3 -m json.tool | head -80
```

Expected: each result's `ok: true` (or the skipped message for non-agent-authored pages like `index.md`). If any of the 17 architecture pages fails, the description there is still thin — surface it; do not adjust the rule's defaults to accommodate.

If a real existing page fails, the choice is:

- (a) rewrite that page's description to meet the rule (preferred — matches the rule's purpose);
- (b) widen `min_words` in `.engineering-docs-agent/config.yml` under `lint.tier1.description_quality` (only if you believe the rule's default is too strict for this repo).

Pick (a) for any failures; the CCE-36 manual rewrites already aimed at this bar.

- [ ] **Step 8.4: Push the branch**

```bash
git push -u origin feat/CCE-38-bootstrap-fail-fast
```

Expected: branch pushed; no PR opened yet (the `/ship` flow will open the PR).

The plan ends here; the next step in the user's chain is `/ship`, which handles test → simplify → review → commit → push → PR with human gates.

---

## Self-review notes

**Spec coverage:**

- Gap 2 (observability) — Task 5 + Task 6 + Task 7 (progress file + in-flight assertion) ✓
- Gap 3 (unparseable YAML) — Task 1 + Task 4 + Task 6 + Task 7 (bad-YAML integration test) ✓
- Gap 4 (thin descriptions) — Task 2 + Task 3 + Task 4 + Task 6 + Task 7 (thin-desc integration test) ✓
- `parse_frontmatter_strict` (new helper) — Task 1 ✓
- `dispatch_verified` wrapper — Task 4 ✓
- `description_quality` lint rule (pure check_fm + path shim + CLI + Tier-1 registration) — Tasks 2 + 3 ✓
- `_BootstrapProgress` (atomic write, transitions, delete-on-completion) — Task 5 ✓
- Wiring `run_bootstrap_core` — Task 6 ✓
- Bootstrap-time vs lint-time enforcement (both call same `check_fm`) — Tasks 3 (lint path) + 6 (bootstrap path) ✓
- Re-run retries rejected pages — Task 7 ✓
- Acceptance criteria all map to tests in Tasks 1, 2, 3, 4, 5, 7. ✓

**Type consistency:**

- `parse_frontmatter_strict` returns `dict`; raises `yaml.YAMLError | ValueError`. Used consistently in Task 6's `_check` and Task 3's `check_path`.
- `check_fm(fm: dict, *, title: str | None, config: dict) -> tuple[bool, str]`. Both callers (`check_path` from Task 3 and `_check` from Task 6) use this signature.
- `dispatch_verified` signature matches the spec. Same return type as `dispatch_validated`.
- `_BootstrapProgress` methods take `rel_posix: str` consistently; Task 6 always passes `rel.as_posix()`.

**Placeholder scan:** Every step shows the actual code or command. No "TBD", no "implement appropriately", no "similar to Task N" references that omit code.
