from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOKS = _REPO_ROOT / "docs" / "runbooks"

# Markdown inline links: [text](target). Captures the target. Link text may
# contain backticks (e.g. [`file.md`](file.md)), so [^\]]+ is correct. The
# (?<!!) lookbehind excludes image syntax ![alt](src) — image srcs are not
# link targets and would otherwise trip the resolver on a future screenshot.
_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def _relative_link_targets(md_path: Path) -> list[str]:
    """Relative Markdown link targets in a file (skips http(s)/mailto and anchors)."""
    text = md_path.read_text(encoding="utf-8")
    targets: list[str] = []
    for raw in _LINK_RE.findall(text):
        target = raw.split("#", 1)[0].strip()  # drop any #anchor fragment
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        targets.append(target)
    return targets


def test_release_runbook_exists():
    assert (_RUNBOOKS / "release-and-rollback.md").is_file()


def test_runbook_relative_links_resolve():
    # Every relative Markdown link inside docs/runbooks/*.md must resolve to a real
    # file. Guards the cross-links between cce80-host-migration.md and
    # release-and-rollback.md against rot (e.g. a rename).
    broken: list[str] = []
    for md in sorted(_RUNBOOKS.glob("*.md")):
        for target in _relative_link_targets(md):
            if not (md.parent / target).resolve().is_file():
                broken.append(f"{md.name} -> {target}")
    assert not broken, f"broken runbook links: {broken}"


def test_cce80_runbook_links_to_release_runbook():
    cce80 = (_RUNBOOKS / "cce80-host-migration.md").read_text(encoding="utf-8")
    assert "release-and-rollback.md" in cce80, (
        "cce80-host-migration.md must cross-link to the release runbook"
    )


def test_claude_md_points_to_release_runbook():
    claude = (_REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    rel = "docs/runbooks/release-and-rollback.md"
    assert rel in claude, "CLAUDE.md is missing the release-runbook pointer"
    assert (_REPO_ROOT / rel).is_file()
