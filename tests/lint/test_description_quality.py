from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "lint"))
import description_quality  # noqa: E402


_DEFAULT_CONFIG: dict = {"lint": {"tier1": "default"}}


def test_check_fm_passes_for_substantial_description():
    fm = {"description": "Pulls merged PRs and Jira issues from the configured window."}
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
    assert ok, msg
    assert msg == "ok"


def test_check_fm_rejects_below_min_words():
    fm = {"description": "Source-collector capability."}  # 2 words
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
    assert not ok
    assert "min_words" in msg


def test_check_fm_rejects_equal_to_title():
    fm = {"description": "Source collector"}
    ok, msg = description_quality.check_fm(
        fm, title="Source collector", config=_DEFAULT_CONFIG
    )
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


def _write_page(
    tmp_path: Path, rel: str, *, description: str, title: str = "API"
) -> Path:
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
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "lint"
        / "description_quality.py"
    )
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--config",
            str(cfg_path),
            "--paths",
            str(page),
            "--json",
        ],
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
