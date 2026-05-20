from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

VALID_CFG = """
docs:
  framework: mkdocs
  source_dir: docs/site-src
  whats_new_file: docs/whats-new.md
  agent_editable_paths: ["docs/**"]
  lens_paths: { core: docs/core }
sources:
  git: { host: github }
lint: { tier1: default }
publishing:
  base_url: https://example.com
  build_workflow: deploy.yml
  url_map_rule: standard
notifications: {}
"""


def test_load_config_validated_accepts_valid(tmp_path):
    from state_io import load_config_validated

    p = tmp_path / "config.yml"
    p.write_text(VALID_CFG)
    cfg = load_config_validated(p)
    assert cfg["docs"]["framework"] == "mkdocs"


def test_load_config_validated_rejects_missing_required(tmp_path):
    from state_io import load_config_validated, ConfigError

    p = tmp_path / "config.yml"
    p.write_text("docs:\n  framework: mkdocs\n")
    with pytest.raises(ConfigError):
        load_config_validated(p)


def test_load_config_validated_rejects_bad_enum(tmp_path):
    from state_io import load_config_validated, ConfigError

    bad = VALID_CFG.replace("framework: mkdocs", "framework: vuepress")
    p = tmp_path / "config.yml"
    p.write_text(bad)
    with pytest.raises(ConfigError):
        load_config_validated(p)


def test_load_config_validated_missing_file(tmp_path):
    from state_io import load_config_validated, ConfigError

    with pytest.raises(ConfigError):
        load_config_validated(tmp_path / "nope.yml")


def test_load_state_validated_missing_file_returns_default(tmp_path):
    from state_io import load_state_validated

    state = load_state_validated(tmp_path / "state.json")
    assert state == {"version": "1"}


def test_load_state_validated_rejects_bad_type(tmp_path):
    from state_io import load_state_validated, StateError
    import json as _json

    p = tmp_path / "state.json"
    p.write_text(_json.dumps({"version": 1}))  # int instead of string
    with pytest.raises(StateError):
        load_state_validated(p)


def test_load_state_validated_accepts_valid(tmp_path):
    from state_io import load_state_validated
    import json as _json

    p = tmp_path / "state.json"
    p.write_text(_json.dumps({"version": "1", "cursors": {}}))
    state = load_state_validated(p)
    assert state["version"] == "1"


def test_add_partial_creates_current_run_if_missing():
    from state_io import add_partial

    state = {"version": "1"}
    add_partial(state, "test_reason")
    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == ["test_reason"]


def test_add_partial_appends_when_current_run_exists():
    from state_io import add_partial

    state = {"current_run": {"partial": False, "partial_reasons": ["one"]}}
    add_partial(state, "two")
    assert state["current_run"]["partial"] is True
    assert state["current_run"]["partial_reasons"] == ["one", "two"]


def test_add_partial_idempotent_on_same_reason():
    from state_io import add_partial

    state = {"current_run": {"partial": True, "partial_reasons": ["dup"]}}
    add_partial(state, "dup")
    assert state["current_run"]["partial_reasons"] == ["dup"]


def test_cleanup_empty_parents_removes_empty_dirs(tmp_path):
    from state_io import cleanup_empty_parents

    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    f = deep / "leaf.md"
    f.write_text("x")
    f.unlink()

    cleanup_empty_parents(f, until=tmp_path)

    assert not (tmp_path / "a").exists()
    assert tmp_path.exists()


def test_cleanup_empty_parents_stops_at_non_empty(tmp_path):
    from state_io import cleanup_empty_parents

    (tmp_path / "a" / "b").mkdir(parents=True)
    sibling = tmp_path / "a" / "keep.md"
    sibling.write_text("x")
    f = tmp_path / "a" / "b" / "leaf.md"
    f.write_text("x")
    f.unlink()

    cleanup_empty_parents(f, until=tmp_path)

    assert (tmp_path / "a").exists()
    assert sibling.exists()
    assert not (tmp_path / "a" / "b").exists()


def test_cleanup_empty_parents_never_removes_until(tmp_path):
    from state_io import cleanup_empty_parents

    f = tmp_path / "leaf.md"
    f.write_text("x")
    f.unlink()
    cleanup_empty_parents(f, until=tmp_path)
    assert tmp_path.exists()
