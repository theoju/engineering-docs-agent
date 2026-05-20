from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "lint" / "stub_redirect.py"
FIX = Path(__file__).parent.parent / "fixtures" / "stub_redirect"


def _run(paths, cfg):
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--config",
            str(cfg),
            "--paths",
            *[str(p) for p in paths],
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    return r.returncode, json.loads(r.stdout)


def test_good(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"lint:\n  tier1:\n    stub_paths: ['{FIX}/*.md']\n")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0


def test_bad(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text(f"lint:\n  tier1:\n    stub_paths: ['{FIX}/*.md']\n")
    rc, out = _run([FIX / "bad.md"], cfg)
    assert rc == 1


def test_not_a_stub_path_skipped(tmp_path):
    p = tmp_path / "regular.md"
    p.write_text("# regular page, not a stub")
    cfg = tmp_path / "c.yml"
    cfg.write_text("lint:\n  tier1:\n    stub_paths: ['/somewhere/else/*.md']\n")
    rc, _ = _run([p], cfg)
    assert rc == 0


def test_stub_redirect_reads_paths_from_lint_stub_paths_when_tier1_is_default(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "lint"))
    import stub_redirect

    cfg = tmp_path / "config.yml"
    cfg.write_text("""
lint:
  tier1: default
  stub_paths: [legacy/old-page.md]
""")
    stub = tmp_path / "legacy" / "old-page.md"
    stub.parent.mkdir()
    # Stub WITHOUT a redirect_to frontmatter -> should fail
    stub.write_text("# old page\n")

    cfg_loaded = stub_redirect.load_config(cfg)
    paths = stub_redirect.configured_stub_paths(cfg_loaded)
    assert paths == ["legacy/old-page.md"]
