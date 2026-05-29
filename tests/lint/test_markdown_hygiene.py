from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "lint" / "markdown_hygiene.py"
)
FIX = Path(__file__).parent.parent / "fixtures" / "markdown_hygiene"


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
    cfg.write_text("{}")
    rc, out = _run([FIX / "good.md"], cfg)
    assert rc == 0
    assert out["rule"] == "markdown_hygiene_structure"
    assert out["severity"] == "block"


def test_does_not_flag_missing_lang_tag(tmp_path):
    # The lang rule handles missing-language fences (warn severity).
    # The structure rule must NOT flag them, otherwise we re-introduce
    # the page-drop regression CCE-46 is fixing.
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_no_lang.md"], cfg)
    assert rc == 0
    assert out["rule"] == "markdown_hygiene_structure"


def test_hierarchy(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([FIX / "bad_hierarchy.md"], cfg)
    assert rc == 1
    assert out["rule"] == "markdown_hygiene_structure"
    assert out["severity"] == "block"
    assert "hierarchy" in out["results"][0]["message"].lower()


def test_missing_file_returns_failure(tmp_path):
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    nonexistent = tmp_path / "does-not-exist.md"
    rc, out = _run([nonexistent], cfg)
    assert rc == 1
    assert "not found" in out["results"][0]["message"].lower()


def test_unpaired_fence_detected(tmp_path):
    p = tmp_path / "unpaired.md"
    # 3 fences total: opener with lang, closer, opener with lang (no closer)
    p.write_text("# x\n\n```python\ncode\n```\n\n```ruby\nmore\n")
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 1
    assert out["rule"] == "markdown_hygiene_structure"
    assert out["severity"] == "block"
    assert "unpaired" in out["results"][0]["message"].lower()
