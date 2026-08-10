from __future__ import annotations
import json
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


def test_load_voice_samples_reads_configured_paths(tmp_path):
    from state_io import load_voice_samples

    sample = tmp_path / "voice" / "tone.md"
    sample.parent.mkdir()
    sample.write_text("Use second person.")
    cfg = {"voice": {"sample_paths": ["voice/tone.md"]}}

    samples = load_voice_samples(tmp_path, cfg)

    assert samples == [{"path": "voice/tone.md", "content": "Use second person."}]


def test_load_voice_samples_includes_claude_md(tmp_path):
    from state_io import load_voice_samples

    (tmp_path / "CLAUDE.md").write_text("Host CLAUDE")
    samples = load_voice_samples(tmp_path, {})

    assert len(samples) == 1
    assert samples[0]["path"] == "CLAUDE.md"


def test_load_voice_samples_caps_at_20kb(tmp_path):
    from state_io import load_voice_samples

    big = tmp_path / "big.md"
    big.write_text("x" * 30_000)
    cfg = {"voice": {"sample_paths": ["big.md"]}}

    samples = load_voice_samples(tmp_path, cfg)

    assert len(samples) == 1
    assert len(samples[0]["content"]) == 20_000


def test_load_voice_samples_skips_missing(tmp_path):
    from state_io import load_voice_samples

    cfg = {"voice": {"sample_paths": ["does-not-exist.md"]}}
    samples = load_voice_samples(tmp_path, cfg)
    assert samples == []


def test_load_voice_samples_includes_docs_agent_voice_override(tmp_path):
    from state_io import load_voice_samples

    (tmp_path / "docs-agent-voice.md").write_text("Prefer terse sentences.")
    samples = load_voice_samples(tmp_path, {})

    assert [s["path"] for s in samples] == ["docs-agent-voice.md"]


def test_load_voice_samples_override_takes_precedence(tmp_path):
    """The override is read first, so it survives the 20KB cap intact."""
    from state_io import load_voice_samples

    (tmp_path / "docs-agent-voice.md").write_text("Override voice.")
    (tmp_path / "CLAUDE.md").write_text("Host CLAUDE")
    cfg = {"voice": {"sample_paths": ["CLAUDE.md"]}}

    samples = load_voice_samples(tmp_path, cfg)

    assert samples[0]["path"] == "docs-agent-voice.md"


def test_load_voice_samples_does_not_duplicate_claude_md(tmp_path):
    """CLAUDE.md in sample_paths must not also be appended by the implicit rule."""
    from state_io import load_voice_samples

    (tmp_path / "CLAUDE.md").write_text("Host CLAUDE")
    cfg = {"voice": {"sample_paths": ["CLAUDE.md"]}}

    samples = load_voice_samples(tmp_path, cfg)

    assert [s["path"] for s in samples] == ["CLAUDE.md"]


def test_resolve_lens_string_form():
    from state_io import resolve_lens

    cfg = {"docs": {"lens_paths": {"core": "docs/core"}}}
    path, opts = resolve_lens(cfg, "core")
    assert str(path) == "docs/core"
    assert opts == {}


def test_resolve_lens_dict_form():
    from state_io import resolve_lens

    cfg = {
        "docs": {
            "lens_paths": {"archive": {"path": "docs/archive", "archive_index": True}}
        }
    }
    path, opts = resolve_lens(cfg, "archive")
    assert str(path) == "docs/archive"
    assert opts == {"archive_index": True}


def test_save_persistent_state_strips_current_run(tmp_path):
    from state_io import save_persistent_state

    state = {
        "version": "1",
        "last_successful_run": {"head_sha": "abc123"},
        "current_run": {
            "started_at": "2026-05-28T20:00:00+00:00",
            "head_sha": "def456",
        },
    }
    p = tmp_path / "state.json"
    save_persistent_state(p, state)
    written = json.loads(p.read_text())
    assert "current_run" not in written
    assert written["last_successful_run"]["head_sha"] == "abc123"
    assert written["version"] == "1"


def test_save_persistent_state_preserves_other_fields(tmp_path):
    from state_io import save_persistent_state

    state = {
        "version": "1",
        "last_successful_run": {"head_sha": "abc"},
        "dismissed_gap_flags": {"foo/bar#1": "wontfix"},
        "cursors": {"some": "data"},
    }
    p = tmp_path / "state.json"
    save_persistent_state(p, state)
    written = json.loads(p.read_text())
    assert written == state


def test_save_persistent_state_writes_trailing_newline(tmp_path):
    from state_io import save_persistent_state

    p = tmp_path / "state.json"
    save_persistent_state(p, {"version": "1"})
    raw = p.read_text()
    assert raw.endswith("\n"), f"expected trailing newline, got {raw!r}"


def test_save_current_run_writes_sibling(tmp_path):
    from state_io import save_current_run

    state_path = tmp_path / "state.json"
    state = {
        "version": "1",
        "current_run": {
            "started_at": "2026-05-28T00:00:00+00:00",
            "partial": False,
            "partial_reasons": [],
        },
    }
    save_current_run(state_path, state)
    sibling = tmp_path / "current_run.json"
    assert sibling.exists(), "save_current_run must write a sibling current_run.json"
    data = json.loads(sibling.read_text())
    assert data == {"current_run": state["current_run"]}


def test_save_current_run_noop_when_absent(tmp_path):
    from state_io import save_current_run

    state_path = tmp_path / "state.json"
    save_current_run(state_path, {"version": "1"})
    sibling = tmp_path / "current_run.json"
    assert not sibling.exists(), (
        "save_current_run must not create a file when state has no current_run"
    )


def test_save_current_run_clears_stale_sibling(tmp_path):
    """When in-memory state has no current_run, an existing sibling is removed
    so on-disk state matches memory (no orphaned ephemeral data)."""
    from state_io import save_current_run

    state_path = tmp_path / "state.json"
    sibling = tmp_path / "current_run.json"
    sibling.write_text(json.dumps({"current_run": {"started_at": "stale"}}) + "\n")

    save_current_run(state_path, {"version": "1"})

    assert not sibling.exists(), (
        "save_current_run must remove a stale sibling when state has no current_run"
    )
