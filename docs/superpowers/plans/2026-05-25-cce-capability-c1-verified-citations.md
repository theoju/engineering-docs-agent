# Capability C1 — Verified `file:line` Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, stdlib-only verification of `file:line` citations in site pages — citations carry a pin token, and a verifier resolves each (ok / auto-relocate / ambiguous / gone), wired as an orchestrator stage sibling to M's source-map plus a standalone CLI.

**Architecture:** A new `scripts/verify_citations.py` (pure stdlib) parses `` `path:line` `` + `<!--pin:TOKEN-->` pairs from each page, classifies each against the cited source file, optionally rewrites relocated citations, and emits a JSON ledger. The orchestrator runs it as a `verify-citations` stage right after the source-map (M) stage: it auto-fixes relocated citations in place (committed with the run's other doc edits) and surfaces `gone`/`ambiguous` pages as "Pages to review (citation drift)" in the What's-New entry and notifier digest — mirroring M's `compute_source_drift` / `_drift_whats_new_lines`.

**Tech Stack:** Python stdlib only (`re`, `argparse`, `json`, `pathlib`). pytest, fixture-driven. No new runtime deps.

**Spec reference:** `docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md` — sections "C1 — Verified `file:line` citations".

**Branch:** C1 implementation branches off `main` as its own ticket (a C1 sub-ticket created under CCE-26 at ship time — see coda). Do NOT implement on the `docs/CCE-26-capability-c-design` branch.

**Patterns to mirror (read before starting):** `scripts/source_drift.py` (`detect_drift`, stdin/CLI), `scripts/source_map.py` (`_collect_page_patterns`, `generate_source_map`, `.doc-source-map.json` shape), `scripts/orchestrator_runner.py` (`compute_source_drift` ~522, `_drift_whats_new_lines` ~547, the best-effort stage ~843-849, What's-New extend ~898, digest key `"source_drift"` ~938), and `tests/orchestrator/test_source_map_stage.py`.

---

## File Structure

- **Create:** `scripts/verify_citations.py` — parser (`_parse_page_citations`), classifier (`_classify_citation`), scanner (`verify_citations`), CLI (`main`). One file, one responsibility (citation verification). Mirrors `source_drift.py`'s size and shape.
- **Modify:** `scripts/orchestrator_runner.py` — add `compute_citation_drift`, `_changed_pages_from_map`, `_citation_drift_whats_new_lines` near the M helpers (~522-555); add the `verify-citations` stage after the source-map stage (~849); extend the What's-New entry (~898); add the digest key (~938).
- **Test (create):** `tests/orchestrator/test_verify_citations.py` — unit tests for the parser, classifier, scanner, and CLI.
- **Test (create):** `tests/orchestrator/test_verify_citations_stage.py` — orchestrator-stage tests, mirroring `test_source_map_stage.py`.

The citation format (the contract): an inline code span `` `repo/relative/path:LINE` `` immediately followed (whitespace allowed) by an HTML comment `<!--pin:TOKEN-->`, where `TOKEN` is a short literal expected on that line. A `path:line` code span with NO following pin is an ordinary code reference, not a citation — it is ignored.

---

## Task 1: Citation+pin parser

**Files:**

- Create: `scripts/verify_citations.py`
- Test: `tests/orchestrator/test_verify_citations.py`

- [ ] **Step 1: Write the failing test**

Create `tests/orchestrator/test_verify_citations.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_citations as vc  # noqa: E402


def test_parse_finds_citation_with_pin():
    text = "Defined at `backend/connectors/base.py:148` <!--pin:class BaseConnector-->.\n"
    cits = vc._parse_page_citations(text)
    assert cits == [
        {"path": "backend/connectors/base.py", "line": 148, "token": "class BaseConnector"}
    ]


def test_parse_ignores_codespan_without_pin():
    # A path:line code span with no following pin is NOT a citation.
    text = "See `backend/connectors/base.py:148` for details.\n"
    assert vc._parse_page_citations(text) == []


def test_parse_trims_pin_whitespace_and_skips_empty():
    text = (
        "A `a.py:1` <!--pin:  foo  --> and "
        "B `b.py:2` <!--pin:  --> (empty pin skipped)\n"
    )
    assert vc._parse_page_citations(text) == [
        {"path": "a.py", "line": 1, "token": "foo"}
    ]


def test_parse_multiple_citations_one_page():
    text = (
        "`x.py:10` <!--pin:def x--> then `y/z.py:20` <!--pin:class Z-->\n"
    )
    assert vc._parse_page_citations(text) == [
        {"path": "x.py", "line": 10, "token": "def x"},
        {"path": "y/z.py", "line": 20, "token": "class Z"},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'verify_citations'`.

- [ ] **Step 3: Write the minimal implementation**

Create `scripts/verify_citations.py`:

```python
"""Verified file:line citations (capability C1).

A citation is an inline code span `path:line` immediately followed (whitespace
allowed) by an HTML-comment pin `<!--pin:TOKEN-->`. TOKEN is a short literal
expected on that line. The verifier resolves each citation against the cited
source file: token-at-line -> ok; token uniquely elsewhere -> relocated
(auto-fixable); token at multiple lines -> ambiguous; token gone / file
missing -> gone. Pure stdlib; never raises on bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# `path:line` code span, then optional whitespace, then <!--pin:TOKEN-->.
# path: anything but backtick/newline (non-greedy); line: trailing digits.
_CITATION_RE = re.compile(
    r"`(?P<path>[^`\n]+?):(?P<line>\d+)`\s*<!--\s*pin:\s*(?P<token>.*?)\s*-->"
)


def _parse_page_citations(text: str) -> list[dict]:
    """Return [{path, line(int), token}] for every citation+pin pair in `text`.
    Citations whose pin token is empty are skipped (a pin with no token can't
    be verified). Never raises.
    """
    out: list[dict] = []
    for m in _CITATION_RE.finditer(text):
        token = m.group("token").strip()
        if not token:
            continue
        out.append(
            {"path": m.group("path"), "line": int(m.group("line")), "token": token}
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_citations.py tests/orchestrator/test_verify_citations.py
git commit -m "$(cat <<'EOF'
feat(C1): citation+pin parser for verify_citations

Parses `path:line` <!--pin:TOKEN--> pairs from page text. Code spans
without a following pin are ordinary references, not citations. Empty
pins are skipped (unverifiable).

Refs: docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md (C1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Citation classifier

**Files:**

- Modify: `scripts/verify_citations.py`
- Test: `tests/orchestrator/test_verify_citations.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_verify_citations.py`:

```python
def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_classify_ok_when_token_at_line(tmp_path):
    _write(tmp_path / "src/a.py", "import os\nclass BaseConnector:\n    pass\n")
    cit = {"path": "src/a.py", "line": 2, "token": "class BaseConnector"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "ok"


def test_classify_relocated_when_token_moved(tmp_path):
    # token is now on line 4, citation says line 2
    _write(tmp_path / "src/a.py", "# new\n# lines\nimport os\nclass BaseConnector:\n")
    cit = {"path": "src/a.py", "line": 2, "token": "class BaseConnector"}
    res = vc._classify_citation(tmp_path, cit)
    assert res["status"] == "relocated"
    assert res["new_line"] == 4


def test_classify_ambiguous_when_token_multiple_lines(tmp_path):
    _write(tmp_path / "src/a.py", "x = 1\nx = 1\n")
    cit = {"path": "src/a.py", "line": 5, "token": "x = 1"}
    res = vc._classify_citation(tmp_path, cit)
    assert res["status"] == "ambiguous"
    assert res["lines"] == [1, 2]


def test_classify_gone_when_token_absent(tmp_path):
    _write(tmp_path / "src/a.py", "totally different\n")
    cit = {"path": "src/a.py", "line": 1, "token": "class BaseConnector"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "gone"


def test_classify_gone_when_file_missing(tmp_path):
    cit = {"path": "src/nope.py", "line": 1, "token": "anything"}
    assert vc._classify_citation(tmp_path, cit)["status"] == "gone"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k classify -v`
Expected: FAIL — `AttributeError: module 'verify_citations' has no attribute '_classify_citation'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `scripts/verify_citations.py` (after `_parse_page_citations`):

```python
def _classify_citation(repo_root: Path, cit: dict) -> dict:
    """Classify one citation against its source file. Returns a dict with
    "status" in {"ok", "relocated", "ambiguous", "gone"}; "relocated" adds
    "new_line"; "ambiguous" adds "lines". Never raises.
    """
    try:
        lines = (repo_root / cit["path"]).read_text().splitlines()
    except OSError:
        return {"status": "gone"}
    token = cit["token"]
    line_no = cit["line"]
    if 1 <= line_no <= len(lines) and token in lines[line_no - 1]:
        return {"status": "ok"}
    hits = [i + 1 for i, ln in enumerate(lines) if token in ln]
    if len(hits) == 1:
        return {"status": "relocated", "new_line": hits[0]}
    if len(hits) > 1:
        return {"status": "ambiguous", "lines": hits}
    return {"status": "gone"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k classify -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_citations.py tests/orchestrator/test_verify_citations.py
git commit -m "$(cat <<'EOF'
feat(C1): citation classifier (ok / relocated / ambiguous / gone)

Reads the cited source file: token at the cited line -> ok; token
uniquely elsewhere -> relocated (with new_line); token at multiple
lines -> ambiguous; token absent or file missing -> gone.

Refs: docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md (C1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Page scanner + ledger + `--fix` rewrite

**Files:**

- Modify: `scripts/verify_citations.py`
- Test: `tests/orchestrator/test_verify_citations.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_verify_citations.py`:

```python
def test_verify_citations_builds_ledger(tmp_path):
    repo = tmp_path
    _write(repo / "src/a.py", "class BaseConnector:\n")          # ok
    _write(repo / "src/b.py", "# pad\n# pad\ndef handler():\n")   # relocated -> 3
    _write(repo / "src/c.py", "gone now\n")                       # gone
    docs = repo / "docs/site-src"
    _write(
        docs / "core/x.md",
        "A `src/a.py:1` <!--pin:class BaseConnector-->\n"
        "B `src/b.py:1` <!--pin:def handler-->\n"
        "C `src/c.py:1` <!--pin:class Missing-->\n",
    )
    ledger = vc.verify_citations(docs, repo, fix=False)
    assert ledger["checked"] == 3
    assert ledger["ok"] == 1
    assert ledger["relocated"] == [
        {"page": "core/x.md", "path": "src/b.py", "old": 1, "new": 3}
    ]
    assert ledger["gone"] == [
        {"page": "core/x.md", "path": "src/c.py", "token": "class Missing", "line": 1}
    ]
    assert ledger["pages_review_needed"] == ["core/x.md"]


def test_verify_citations_fix_rewrites_relocated(tmp_path):
    repo = tmp_path
    _write(repo / "src/b.py", "# pad\n# pad\ndef handler():\n")
    docs = repo / "docs/site-src"
    page = _write(docs / "core/x.md", "B `src/b.py:1` <!--pin:def handler-->\n")
    vc.verify_citations(docs, repo, fix=True)
    assert "`src/b.py:3`" in page.read_text()
    assert "`src/b.py:1`" not in page.read_text()


def test_verify_citations_empty_when_no_docs_dir(tmp_path):
    ledger = vc.verify_citations(tmp_path / "nope", tmp_path, fix=False)
    assert ledger == {
        "checked": 0, "ok": 0, "relocated": [],
        "ambiguous": [], "gone": [], "pages_review_needed": [],
    }


def test_verify_citations_scopes_to_pages_arg(tmp_path):
    repo = tmp_path
    _write(repo / "src/c.py", "gone now\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    _write(docs / "core/y.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    # Only x.md is in scope; y.md must be untouched/unchecked.
    ledger = vc.verify_citations(docs, repo, fix=False, pages={"core/x.md"})
    assert ledger["checked"] == 1
    assert ledger["pages_review_needed"] == ["core/x.md"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k verify_citations -v`
Expected: FAIL — `AttributeError: module 'verify_citations' has no attribute 'verify_citations'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `scripts/verify_citations.py` (after `_classify_citation`):

```python
def _empty_ledger() -> dict:
    return {
        "checked": 0,
        "ok": 0,
        "relocated": [],
        "ambiguous": [],
        "gone": [],
        "pages_review_needed": [],
    }


def verify_citations(
    docs_dir: Path,
    repo_root: Path,
    *,
    fix: bool = False,
    pages: set[str] | None = None,
) -> dict:
    """Scan every page under docs_dir for citations, classify each against
    its source file, and return a ledger. When fix=True, rewrite relocated
    citations in place (line number updated). When pages is given, only those
    page paths (POSIX, relative to docs_dir) are checked. Never raises.
    """
    ledger = _empty_ledger()
    if not docs_dir.is_dir():
        return ledger
    review: set[str] = set()
    for md in sorted(docs_dir.rglob("*.md")):
        page = md.relative_to(docs_dir).as_posix()
        if pages is not None and page not in pages:
            continue
        try:
            text = md.read_text()
        except OSError:
            continue
        new_text = text
        for cit in _parse_page_citations(text):
            ledger["checked"] += 1
            res = _classify_citation(repo_root, cit)
            status = res["status"]
            if status == "ok":
                ledger["ok"] += 1
            elif status == "relocated":
                ledger["relocated"].append(
                    {"page": page, "path": cit["path"],
                     "old": cit["line"], "new": res["new_line"]}
                )
                if fix:
                    old_span = f"`{cit['path']}:{cit['line']}`"
                    new_span = f"`{cit['path']}:{res['new_line']}`"
                    new_text = new_text.replace(old_span, new_span)
            elif status == "ambiguous":
                ledger["ambiguous"].append(
                    {"page": page, "path": cit["path"],
                     "token": cit["token"], "lines": res["lines"]}
                )
                review.add(page)
            else:  # gone
                ledger["gone"].append(
                    {"page": page, "path": cit["path"],
                     "token": cit["token"], "line": cit["line"]}
                )
                review.add(page)
        if fix and new_text != text:
            md.write_text(new_text)
    ledger["pages_review_needed"] = sorted(review)
    return ledger
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k verify_citations -v`
Expected: 4 passed.

- [ ] **Step 5: Run the whole file + full suite**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -q && python3 -m pytest -q 2>&1 | tail -2`
Expected: file all green; full suite shows the prior baseline + the new tests, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_citations.py tests/orchestrator/test_verify_citations.py
git commit -m "$(cat <<'EOF'
feat(C1): page scanner + JSON ledger + --fix relocation rewrite

verify_citations() scans docs_dir pages, classifies each citation, and
returns {checked, ok, relocated[], ambiguous[], gone[], pages_review_needed[]}.
fix=True rewrites relocated citations in place (line number updated).
pages= scopes the scan to a subset (the orchestrator's changed-pages fast path).
Empty/degenerate inputs return an empty ledger; never raises.

Refs: docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md (C1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: CLI (`main`)

**Files:**

- Modify: `scripts/verify_citations.py`
- Test: `tests/orchestrator/test_verify_citations.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_verify_citations.py`:

```python
import json as _json


def test_cli_json_output_and_exit_zero(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/a.py", "class BaseConnector:\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "A `src/a.py:1` <!--pin:class BaseConnector-->\n")
    rc = vc.main(["--docs-dir", str(docs), "--repo-root", str(repo), "--json"])
    assert rc == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["ok"] == 1 and out["checked"] == 1


def test_cli_strict_exits_nonzero_on_gone(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/c.py", "gone\n")
    docs = repo / "docs/site-src"
    _write(docs / "core/x.md", "C `src/c.py:1` <!--pin:class Missing-->\n")
    rc = vc.main(
        ["--docs-dir", str(docs), "--repo-root", str(repo), "--json", "--strict"]
    )
    assert rc == 1
    capsys.readouterr()


def test_cli_fix_rewrites_and_exits_zero(tmp_path, capsys):
    repo = tmp_path
    _write(repo / "src/b.py", "# pad\ndef handler():\n")
    docs = repo / "docs/site-src"
    page = _write(docs / "core/x.md", "B `src/b.py:1` <!--pin:def handler-->\n")
    rc = vc.main(
        ["--docs-dir", str(docs), "--repo-root", str(repo), "--fix", "--json"]
    )
    assert rc == 0
    assert "`src/b.py:2`" in page.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k cli -v`
Expected: FAIL — `AttributeError: module 'verify_citations' has no attribute 'main'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `scripts/verify_citations.py` (at the end):

```python
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify file:line citations.")
    ap.add_argument("--docs-dir", type=Path, required=True)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--fix", action="store_true", help="rewrite relocated citations")
    ap.add_argument(
        "--strict", action="store_true",
        help="exit non-zero if any gone/ambiguous citations remain",
    )
    ap.add_argument(
        "--json", action="store_true", help="emit the full JSON ledger to stdout"
    )
    args = ap.parse_args(argv)
    ledger = verify_citations(args.docs_dir, args.repo_root, fix=args.fix)
    if args.json:
        print(json.dumps(ledger, indent=2))
    else:
        print(
            f"checked={ledger['checked']} ok={ledger['ok']} "
            f"relocated={len(ledger['relocated'])} "
            f"ambiguous={len(ledger['ambiguous'])} gone={len(ledger['gone'])}"
        )
    if args.strict and (ledger["gone"] or ledger["ambiguous"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations.py -k cli -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_citations.py tests/orchestrator/test_verify_citations.py
git commit -m "$(cat <<'EOF'
feat(C1): verify_citations.py CLI (--docs-dir/--repo-root/--fix/--strict/--json)

Standalone CLI for CI: scans docs_dir, prints the ledger (JSON with
--json, else a one-line summary), exits non-zero under --strict when
gone/ambiguous citations remain. --fix rewrites relocated citations.

Refs: docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md (C1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Orchestrator `verify-citations` stage

**Files:**

- Modify: `scripts/orchestrator_runner.py` — add helpers near the M helpers (~522-555); add the stage after the source-map stage (~849); extend What's-New (~898); add the digest key (~938).
- Test: `tests/orchestrator/test_verify_citations_stage.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/orchestrator/test_verify_citations_stage.py`:

```python
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import orchestrator_runner as orun  # noqa: E402


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_compute_citation_drift_flags_gone(tmp_path):
    _write(tmp_path / "scripts/auth.py", "def login():\n    pass\n")
    _write(
        tmp_path / "docs/site-src/core/auth.md",
        "Login `scripts/auth.py:1` <!--pin:class Missing-->\n",
    )
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    ledger = orun.compute_citation_drift(tmp_path, config, prs)
    assert ledger["pages_review_needed"] == ["core/auth.md"]
    assert ledger["gone"][0]["path"] == "scripts/auth.py"


def test_compute_citation_drift_autofixes_relocated(tmp_path):
    _write(tmp_path / "scripts/auth.py", "# pad\ndef login():\n    pass\n")
    page = _write(
        tmp_path / "docs/site-src/core/auth.md",
        "Login `scripts/auth.py:1` <!--pin:def login-->\n",
    )
    config = {"site": {"docs_dir": "docs/site-src"}}
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    ledger = orun.compute_citation_drift(tmp_path, config, prs)
    assert ledger["relocated"][0]["new"] == 2
    assert "`scripts/auth.py:2`" in page.read_text()  # rewritten in place


def test_compute_citation_drift_no_site_is_empty(tmp_path):
    ledger = orun.compute_citation_drift(tmp_path, {}, [])
    assert ledger["checked"] == 0 and ledger["pages_review_needed"] == []


def test_citation_drift_whats_new_lines():
    empty = {
        "checked": 0, "ok": 0, "relocated": [], "ambiguous": [],
        "gone": [], "pages_review_needed": [],
    }
    assert orun._citation_drift_whats_new_lines(empty) == []
    lines = orun._citation_drift_whats_new_lines({
        "gone": [{"page": "core/a.md", "path": "x.py", "token": "class X", "line": 5}],
        "ambiguous": [{"page": "core/b.md", "path": "y.py", "token": "t", "lines": [1, 2]}],
        "pages_review_needed": ["core/a.md", "core/b.md"],
    })
    assert lines[0] == "### Pages to review (citation drift)"
    assert "- core/a.md — citation gone: x.py (class X)" in lines
    assert "- core/b.md — ambiguous: y.py (t)" in lines


def test_changed_pages_from_map_scopes_via_map(tmp_path):
    docs_rel = "docs/site-src"
    mp = tmp_path / docs_rel / ".doc-source-map.json"
    mp.parent.mkdir(parents=True)
    mp.write_text(
        '{"version":1,"map":{"scripts/auth.py":["core/auth.md"],'
        '"scripts/other.py":["core/other.md"]},"patterns":{}}'
    )
    prs = [{"number": 1, "files": [{"path": "scripts/auth.py"}]}]
    pages = orun._changed_pages_from_map(tmp_path, docs_rel, prs)
    assert pages == {"core/auth.md"}


def test_changed_pages_from_map_none_when_no_map(tmp_path):
    assert orun._changed_pages_from_map(tmp_path, "docs/site-src", []) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations_stage.py -v`
Expected: FAIL — `AttributeError: module 'orchestrator_runner' has no attribute 'compute_citation_drift'`.

- [ ] **Step 3: Add the helpers**

In `scripts/orchestrator_runner.py`, immediately AFTER `_drift_whats_new_lines` (ends ~line 554), add:

```python
def _changed_pages_from_map(
    repo_root: Path, docs_dir_rel: str, prs: list[dict]
) -> set[str] | None:
    """Pages (POSIX, relative to docs_dir) whose mapped source files changed in
    this batch, read from <docs_dir>/.doc-source-map.json. Returns None when the
    map is absent/unreadable (caller then verifies all pages).
    """
    map_path = repo_root / docs_dir_rel.rstrip("/") / ".doc-source-map.json"
    try:
        artifact = json.loads(map_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    source_to_pages = artifact.get("map")
    if not isinstance(source_to_pages, dict):
        return None
    changed = {
        (f["path"] if isinstance(f, dict) else f)
        for pr in prs
        for f in (pr.get("files") or [])
        if isinstance(f, (dict, str)) and (f.get("path") if isinstance(f, dict) else f)
    }
    pages: set[str] = set()
    for src, page_list in source_to_pages.items():
        if src in changed and isinstance(page_list, list):
            pages.update(p for p in page_list if isinstance(p, str))
    return pages


def compute_citation_drift(repo_root: Path, config: dict, prs: list[dict]) -> dict:
    """Verify file:line citations for this batch and return the C1 ledger.
    Auto-fixes relocated citations in place (committed with the run's other doc
    edits). Scopes to pages whose mapped sources changed (via .doc-source-map.json),
    falling back to a full scan when no map exists. Empty ledger when no docs_dir.
    """
    import verify_citations as _vc

    docs_dir_rel = (config.get("site") or {}).get("docs_dir")
    if not docs_dir_rel:
        return _vc._empty_ledger()
    pages = _changed_pages_from_map(repo_root, docs_dir_rel, prs)
    return _vc.verify_citations(
        repo_root / docs_dir_rel, repo_root, fix=True, pages=pages
    )


def _citation_drift_whats_new_lines(ledger: dict) -> list[str]:
    """What's-New block for citation drift (empty list -> no block)."""
    pages = ledger.get("pages_review_needed") or []
    if not pages:
        return []
    lines = ["### Pages to review (citation drift)"]
    for g in ledger.get("gone", []):
        lines.append(f"- {g['page']} — citation gone: {g['path']} ({g['token']})")
    for a in ledger.get("ambiguous", []):
        lines.append(f"- {a['page']} — ambiguous: {a['path']} ({a['token']})")
    return lines
```

- [ ] **Step 4: Wire the stage, What's-New, and digest**

In `scripts/orchestrator_runner.py`, immediately AFTER the source-map stage block (the lines ending with `state["current_run"]["source_drift"] = drifted_pages`, ~line 849), add:

```python
    # Citation verification + drift (C1) — best-effort; auto-fixes relocated
    # citations in place (committed with the run's other doc edits).
    try:
        citation_ledger = compute_citation_drift(repo_root, config, prs)
    except Exception as exc:  # noqa: BLE001 - advisory stage, never block the PR
        import verify_citations as _vc

        citation_ledger = _vc._empty_ledger()
        add_partial(state, f"verify_citations_failed: {exc}", info_only=True)
    state["current_run"]["citation_drift"] = citation_ledger
```

Then, in the What's-New block, immediately AFTER the existing `entry_lines.extend(_drift_whats_new_lines(drifted_pages))` line (~898), add:

```python
        entry_lines.extend(_citation_drift_whats_new_lines(citation_ledger))
```

Then, in the digest dict, immediately AFTER the existing `"source_drift": drifted_pages,` line (~938), add:

```python
        "citation_drift": citation_ledger,
```

- [ ] **Step 5: Run the stage tests**

Run: `python3 -m pytest tests/orchestrator/test_verify_citations_stage.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: prior baseline + all new C1 tests, 0 failures. (If a `dry_run` run-path fixture test asserts an exact digest-key set and now fails because `citation_drift` was added, update that fixture's expected keys to include `citation_drift` — surface which test changed and the one-line update.)

- [ ] **Step 7: Commit**

```bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_verify_citations_stage.py
git commit -m "$(cat <<'EOF'
feat(C1): verify-citations orchestrator stage (sibling to source-map)

Runs after the source-map (M) stage: auto-fixes relocated citations in
place and surfaces gone/ambiguous pages as "Pages to review (citation
drift)" in the What's-New entry + notifier digest. Scopes to pages whose
mapped sources changed via .doc-source-map.json (full scan when no map).
Best-effort: an exception adds an info-only partial reason, never blocks.

Refs: docs/superpowers/specs/2026-05-25-cce-capability-c-canonical-core-citations-design.md (C1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Spec coverage check

C1 acceptance criteria from the spec:

- [x] Citation format `` `path:line` `` + `<!--pin:TOKEN-->` — Task 1 parser defines/enforces it.
- [x] `verify_citations.py` CLI `--docs-dir/--repo-root/--fix/--strict/--json` — Task 4.
- [x] Four-way classification (ok / relocated-auto-fix / ambiguous / gone) + JSON ledger — Tasks 2-3.
- [x] Orchestrator `verify-citations` stage after source-map; auto-fix relocated; surface gone/ambiguous in What's-New + digest; best-effort/info-only — Task 5.
- [x] Reuse `.doc-source-map.json` to scope to changed pages — Task 5 (`_changed_pages_from_map`).
- [x] Generic-first/degradation (no docs_dir → empty ledger; no citations → empty ledger; no map → full scan) — Tasks 3, 5.
- [x] stdlib-only, fixture-driven TDD — every task.

No gaps.

## Risk and YAGNI

- This plan does NOT author any citations (that's C2). It only verifies the format C2 will emit.
- The `--fix` rewrite uses a literal `` `path:line` `` span replacement; if the identical span appears twice on one page they both update to the same correct line (harmless). No AST/structured rewrite — YAGNI.
- Scoping via the map is an optimization with a clean fallback (full scan); it never changes correctness, only the page set scanned in the nightly fast path.
- No new runtime dependency: pure stdlib `re`/`json`/`argparse`/`pathlib`.

---

## Execution coda

1. **Per-task execution** via superpowers:subagent-driven-development — fresh implementer per task, two-stage review (spec-compliance then code-quality), model-tiered: haiku for Tasks 1-2 (pure parser/classifier), sonnet for Tasks 3-5 (scanner/CLI/orchestrator integration).
2. **Final whole-branch review** after all five tasks (dedicated reviewer over the full C1 diff).
3. **`/ship` with full gate** — branch off `main` (e.g. `feat/CCE-<C1>-verified-citations`), PR base **`main`** (NOT the `docs/CCE-26-capability-c-design` branch).
4. **Jira:** create a C1 sub-ticket under CCE-26 (Story/Task), then comment + transition per repo convention (comment-only at PR open; transition to Done after merge).
5. After C1 ships, proceed to the C2 plan (Canonical Core authoring) and C3 plan (diagram render gate) per the spec's sequencing.
