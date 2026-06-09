"""CCE-105: the live host config wires API grouping + json-schema contracts."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from state_io import load_config_validated  # noqa: E402


def test_live_config_api_section_has_groups_and_contracts():
    cfg = load_config_validated(_REPO_ROOT / ".engineering-docs-agent" / "config.yml")
    api = next(s for s in cfg["site"]["sections"] if s["key"] == "api")
    assert "json-schema" in api["extractors"]
    assert "agents/schemas" in api["sources"]
    assert api["groups"], "api section must declare service/component groups"
    names = {g["name"] for g in api["groups"]}
    assert {"Orchestrator", "Generators", "Lint"} <= names
