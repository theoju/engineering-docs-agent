"""State and config I/O with schema validation. Hard-fail on operator errors."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import jsonschema
import yaml

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class ConfigError(Exception):
    """Raised when config.yml fails schema validation."""


class StateError(Exception):
    """Raised when state.json fails schema validation."""


def load_config_validated(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    schema = json.loads((TEMPLATES_DIR / "config.schema.json").read_text())
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as e:
        raise ConfigError(f"config invalid at {e.json_path}: {e.message}") from e
    return raw


def load_state_validated(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": "1"}
    raw = json.loads(path.read_text())
    schema = json.loads((TEMPLATES_DIR / "state.schema.json").read_text())
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as e:
        raise StateError(f"state invalid at {e.json_path}: {e.message}") from e
    return raw
