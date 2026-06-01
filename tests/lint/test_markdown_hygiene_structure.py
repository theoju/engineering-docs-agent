from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent
    / "scripts"
    / "lint"
    / "markdown_hygiene_structure.py"
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


def test_fenced_yaml_comment_does_not_trigger_hierarchy_jump(tmp_path):
    """CCE-68: a `# ` comment inside a fenced code block must not be
    counted as a heading. The bootstrap-style pattern is real h1 → h2 →
    fenced YAML with `# comment` → real h3. Without fence-aware scanning,
    the YAML comment counts as h1 and the real h3 reads as an h1→h3 jump."""
    p = tmp_path / "fenced.md"
    p.write_text(
        "# Real H1\n\nintro prose\n\n## Real H2\n\nconfig example:\n\n"
        "```yaml\n"
        "# lens and page mappings (this is a YAML comment, not a heading)\n"
        "key: value\n"
        "```\n\n"
        "### Real H3\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, f"fence-aware scanning should not flag this; got {out}"
    assert out["results"][0]["ok"] is True


def test_heading_inside_fenced_block_is_ignored(tmp_path):
    """CCE-68 (variant): a literal `#` heading line inside a fenced markdown
    example must not contribute to hierarchy tracking. Demonstrative
    snippets are valid. Here a `# Document title` example inside a fenced
    block resets prev_level to h1, making the subsequent real h3 look like
    an h1→h3 jump."""
    p = tmp_path / "fenced-heading.md"
    p.write_text(
        "# Real H1\n\n## Real H2\n\nAn example markdown document:\n\n"
        "```markdown\n# Document title\nSome content\n```\n\n"
        "### Real H3\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0
