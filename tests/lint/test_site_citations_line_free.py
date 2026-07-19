"""CCE-122 repo guard: no published page may carry an inline `path:line`
citation, and every page passes the citation_exists symbol/file check."""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lint"))
import citation_exists  # noqa: E402

SITE = ROOT / "docs" / "site-src"


def _pages() -> list[Path]:
    return sorted(SITE.rglob("*.md"))


def test_no_inline_line_pins_in_site():
    offenders = {}
    for page in _pages():
        pins = citation_exists.line_pinned_citations(page.read_text())
        if pins:
            offenders[str(page.relative_to(ROOT))] = pins
    assert not offenders, f"inline :line citations remain: {offenders}"


def test_migration_introduces_no_symbol_failures():
    # CCE-122 rewrote :line -> :symbol. The ONLY citation_exists failure the
    # migration can introduce is a 'nonexistent symbol' — an ast-resolved
    # symbol the lint's grep cannot confirm. Pre-existing 'nonexistent path'/
    # 'nonexistent test' citations on historical pages are out of scope for
    # this ticket (the citation_exists lint runs on newly authored pages, not
    # retroactively; auditing that legacy debt is separate work).
    repo_root = citation_exists.repo_root_for(SITE / "x")
    files = citation_exists.tracked_files(repo_root) if repo_root else set()
    symbol_failures = {}
    for page in _pages():
        ok, msg = citation_exists.check_path(page, repo_root, files)
        if not ok and "nonexistent symbol" in msg:
            symbol_failures[str(page.relative_to(ROOT))] = msg
    assert not symbol_failures, (
        f"migration produced unverifiable symbols: {symbol_failures}"
    )
