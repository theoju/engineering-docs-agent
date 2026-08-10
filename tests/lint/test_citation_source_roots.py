"""CCE-139: lint.citation_source_roots — the nested-monorepo resolution widening.

A flat host (this plugin) cites `scripts/foo.py` and resolves from the repo
root. A nested monorepo cites `app/core/destination_engine.py` — the
import-path form the code uses for itself — which is repo-relative only from
inside `backend/`. Declared roots are tried AFTER the repo root and docs_dir,
so a root can only widen resolution; it can never redirect a path that already
resolves.

Every test here pairs a widening with a control proving an invented path under
the SAME declared root still blocks. A widened resolver without its control is
a block rule that has quietly stopped blocking.
"""

from __future__ import annotations
import subprocess
from pathlib import Path

from scripts.lint import citation_exists


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _monorepo(tmp_path: Path) -> Path:
    """A nested host: two package roots holding a real module, a retired one and
    a component, plus a docs tree. Mirrors the shape of the ADIS host."""
    repo = tmp_path / "host"
    (repo / "backend" / "app" / "core").mkdir(parents=True)
    (repo / "backend" / "app" / "core" / "real_module.py").write_text(
        "def real_fn():\n    return 1\n"
    )
    (repo / "backend" / "app" / "core" / "legacy.py").write_text("LEGACY = 1\n")
    (repo / "frontend" / "components").mkdir(parents=True)
    (repo / "frontend" / "components" / "widget.tsx").write_text(
        "export function Widget() { return null }\n"
    )
    (repo / "docs" / "site-src").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _page(repo: Path, body: str) -> Path:
    p = repo / "docs" / "site-src" / "page.md"
    p.write_text(body)
    return p


CFG = {"lint": {"citation_source_roots": ["backend", "frontend"]}}


# ---------- source_roots(): the config accessor ----------


def test_source_roots_defaults_to_empty():
    """Generic-first: a host that declares nothing keeps today's behavior."""
    assert citation_exists.source_roots({}) == ()
    assert citation_exists.source_roots({"lint": {}}) == ()
    assert citation_exists.source_roots({"lint": {"citation_source_roots": []}}) == ()


def test_source_roots_reads_declared_roots_in_order():
    cfg = {"lint": {"citation_source_roots": ["backend", "frontend"]}}
    assert citation_exists.source_roots(cfg) == ("backend", "frontend")


def test_source_roots_strips_surrounding_slashes():
    cfg = {"lint": {"citation_source_roots": ["/backend/", "frontend/"]}}
    assert citation_exists.source_roots(cfg) == ("backend", "frontend")


def test_source_roots_drops_nested_tails_and_dot_entries():
    """Spec: roots must be PACKAGE roots, never a tail like `backend/storage`.
    A root list deep enough to catch tails is suffix-matching in disguise, and
    suffix-matching admits confabulated paths. Dropping fails CLOSED (no
    widening), which is the correct degradation for a block rule."""
    cfg = {
        "lint": {"citation_source_roots": ["backend", "backend/storage", "..", ".", ""]}
    }
    assert citation_exists.source_roots(cfg) == ("backend",)


# ---------- site 1 + site 2a: _resolves() and the paths loop ----------


def test_import_relative_path_resolves_under_a_declared_root(tmp_path):
    """The reported failure class: a nested monorepo cites the import-path form
    (`app/core/real_module.py`) that only resolves from inside backend/."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The entry point is `app/core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg


def test_second_declared_root_also_resolves(tmp_path):
    """Roots are tried in declaration order; the list is not single-valued."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The widget is `components/widget.tsx`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is True, msg


def test_invented_path_under_a_declared_root_still_blocks(tmp_path):
    """CONTROL for sites 1 and 2a. Widening resolution must not become a blanket
    pass: a file that exists under NO declared root is still a confabulation."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `app/core/nonexistent_module.py` for the logic.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, CFG)
    assert ok is False
    assert "cites nonexistent path 'app/core/nonexistent_module.py'" in msg


def test_undeclared_root_does_not_resolve(tmp_path):
    """CONTROL: only DECLARED roots widen. A host that declares only backend must
    not get frontend/ for free."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The widget is `components/widget.tsx`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_source_roots": ["backend"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "cites nonexistent path 'components/widget.tsx'" in msg


def test_no_declared_roots_keeps_todays_behavior(tmp_path):
    """CONTROL: generic-first. A host with no roots is byte-identical to today.
    This is the guard that makes Track C safe to merge before Track D."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The entry point is `app/core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    ok, msg = citation_exists.check_path(page, repo, files, {})
    assert ok is False
    assert "cites nonexistent path 'app/core/real_module.py'" in msg


def test_nested_tail_root_does_not_widen(tmp_path):
    """CONTROL for the package-roots-only constraint at the rule level: declaring
    `backend/app` must not make `core/real_module.py` resolve."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "See `core/real_module.py`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {"lint": {"citation_source_roots": ["backend/app"]}}
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is False
    assert "cites nonexistent path 'core/real_module.py'" in msg


# ---------- site 2b: the stale-exemption call site ----------


def test_exempt_token_that_resolves_under_a_root_reports_drift(tmp_path):
    """Site 2b. An exempt token whose file has appeared under a declared package
    root must surface as `stale exemption`, or the host's exemption list rots
    with no signal. This is the ONLY assertion that distinguishes the two
    _resolves() call sites."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "The retired shim `app/core/legacy.py` is gone.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {
        "lint": {
            "citation_source_roots": ["backend", "frontend"],
            "citation_exempt_tokens": ["app/core/legacy.py"],
        }
    }
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg
    assert "stale exemption: 'app/core/legacy.py' now resolves" in msg


def test_exempt_token_that_resolves_nowhere_reports_no_drift(tmp_path):
    """CONTROL for site 2b: the drift note must not be fabricated for a token
    that genuinely resolves under no root."""
    repo = _monorepo(tmp_path)
    page = _page(repo, "There is deliberately no `app/core/never_there.py`.\n")
    files = citation_exists.tracked_files(repo)
    cfg = {
        "lint": {
            "citation_source_roots": ["backend", "frontend"],
            "citation_exempt_tokens": ["app/core/never_there.py"],
        }
    }
    ok, msg = citation_exists.check_path(page, repo, files, cfg)
    assert ok is True, msg
    assert "stale exemption" not in msg
