"""CCE-22: load_config_validated must reject configs where any
lens_paths entry is not covered by agent_editable_paths.

The original tension: defining a lens (`superpowers: docs/superpowers/`)
that the agent can never write to (`agent_editable_paths` was
`[docs/_agent-sandbox/**]`) silently filtered every superpowers-lens
proposal at runtime. Catching this at config load instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import load_config_validated  # noqa: E402


# Minimum schema-required top-level keys outside of `docs`. Pulled from
# templates/config.schema.json so fixtures exercise the new lens-vs-editable
# validation without tripping on unrelated required-property errors first.
_SCHEMA_TAIL = """
sources:
  git:
    host: github.com
lint: {}
publishing:
  base_url: "https://example.com"
  build_workflow: "ci.yml"
  url_map_rule: "strip-ext"
notifications: {}
"""


def _write_config(tmp_path: Path, docs_body: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(docs_body + _SCHEMA_TAIL)
    return p


def test_lens_path_covered_by_editable_passes(tmp_path: Path):
    """Happy path: every lens path matches at least one editable glob."""
    cfg_path = _write_config(
        tmp_path,
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths:
    - "docs/_agent-sandbox/**"
    - "docs/superpowers/**"
  lens_paths:
    core: docs/
    superpowers: docs/superpowers/
""",
    )
    config = load_config_validated(cfg_path)
    assert config["docs"]["lens_paths"]["superpowers"] == "docs/superpowers/"


def test_lens_path_not_in_editable_globs_raises(tmp_path: Path):
    """Failure case mirroring the actual repo config: lens 'superpowers' exists
    at docs/superpowers/, but agent_editable_paths is sandbox-only.
    Validation must reject this."""
    cfg_path = _write_config(
        tmp_path,
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths:
    - "docs/_agent-sandbox/**"
  lens_paths:
    core: docs/
    superpowers: docs/superpowers/
""",
    )
    with pytest.raises(ValueError) as exc_info:
        load_config_validated(cfg_path)
    msg = str(exc_info.value)
    assert "lens_paths" in msg or "editable" in msg, (
        f"error must mention the config keys in tension; got: {msg}"
    )
    assert "superpowers" in msg, f"error must name the offending lens; got: {msg}"


def test_multiple_uncovered_lenses_all_named(tmp_path: Path):
    """When multiple lenses are uncovered, the error must list all of them
    so an operator fixing the config doesn't have to play whack-a-mole."""
    cfg_path = _write_config(
        tmp_path,
        """
docs:
  framework: mkdocs
  source_dir: docs
  whats_new_file: docs/whats-new.md
  agent_editable_paths:
    - "docs/_agent-sandbox/**"
  lens_paths:
    core: docs/
    superpowers: docs/superpowers/
    archive: docs/archive/
""",
    )
    with pytest.raises(ValueError) as exc_info:
        load_config_validated(cfg_path)
    msg = str(exc_info.value)
    assert "superpowers" in msg, msg
    assert "archive" in msg, msg
