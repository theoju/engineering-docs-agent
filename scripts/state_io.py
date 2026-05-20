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


def add_partial(state: dict, reason: str) -> None:
    """Mark current_run as partial and append the reason. Idempotent."""
    if "current_run" not in state:
        state["current_run"] = {"partial": True, "partial_reasons": []}
    cr = state["current_run"]
    cr["partial"] = True
    cr.setdefault("partial_reasons", [])
    if reason not in cr["partial_reasons"]:
        cr["partial_reasons"].append(reason)


def cleanup_empty_parents(path: Path, *, until: Path) -> None:
    """Walk up from path.parent removing empty dirs; stop at `until` (exclusive)."""
    until_resolved = until.resolve()
    current = path.parent.resolve()
    while current != until_resolved and until_resolved in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
