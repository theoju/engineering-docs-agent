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
