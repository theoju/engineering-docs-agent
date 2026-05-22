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


def add_partial(state: dict, reason: str, *, info_only: bool = False) -> None:
    """Append a partial reason to current_run.partial_reasons.

    When info_only is False (default), also flip current_run.partial to True.
    When info_only is True, leave current_run.partial unchanged — the reason
    is informational, not a degradation signal. Examples of info-only reasons:
    stale_current_run_cleared, push_tracking_setup_failed (CCE-21).

    Idempotent: a reason already present is not appended again.
    """
    if "current_run" not in state:
        state["current_run"] = {"partial": False, "partial_reasons": []}
    cr = state["current_run"]
    cr.setdefault("partial_reasons", [])
    if reason not in cr["partial_reasons"]:
        cr["partial_reasons"].append(reason)
    if not info_only:
        cr["partial"] = True


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


def load_voice_samples(repo_root: Path, config: dict) -> list[dict]:
    """Read voice samples + host CLAUDE.md, capped at ~20KB total."""
    samples: list[dict] = []
    total = 0
    cap = 20_000
    sources: list[Path] = []
    voice_cfg = config.get("voice") or {}
    for rel in voice_cfg.get("sample_paths") or []:
        sources.append(repo_root / rel)
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        sources.append(claude_md)
    for src in sources:
        if not src.exists() or not src.is_file():
            continue
        try:
            text = src.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        snippet = text[: max(0, cap - total)]
        if not snippet:
            break
        samples.append({"path": str(src.relative_to(repo_root)), "content": snippet})
        total += len(snippet)
        if total >= cap:
            break
    return samples


def resolve_lens(config: dict, lens: str) -> tuple[Path, dict]:
    """Normalize lens_paths entry to (Path, options_dict)."""
    value = config["docs"]["lens_paths"][lens]
    if isinstance(value, str):
        return Path(value), {}
    return Path(value["path"]), {k: v for k, v in value.items() if k != "path"}
