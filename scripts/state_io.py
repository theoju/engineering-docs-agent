"""State and config I/O with schema validation. Hard-fail on operator errors."""

from __future__ import annotations
from pathlib import Path, PurePosixPath
from typing import Any
import json
import sys
import jsonschema
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stderr_emit import _redact_credentials, emit_stderr  # noqa: E402

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class ConfigError(Exception):
    """Raised when config.yml fails schema validation."""


class StateError(Exception):
    """Raised when state.json fails schema validation."""


def _validate_lens_paths_are_editable(config: dict) -> None:
    """Cross-key check: every lens_paths entry must be covered by at least
    one agent_editable_paths glob.

    Compatibility rule: a lens at path P is covered by an editable glob G
    iff the glob's anchor (the portion before the first wildcard) and P
    are on the same path branch — i.e., one starts with the other.

    This lets a narrower editable scope satisfy a wider lens path
    (e.g., editable 'docs/site-src/**' covers lens 'core' at 'docs/site-src/':
    the glob and lens root are co-located; any path under site-src is writable).
    """
    docs = config.get("docs", {}) or {}
    lenses = docs.get("lens_paths", {}) or {}
    globs = docs.get("agent_editable_paths", []) or []

    if not lenses or not globs:
        return

    def _anchor(g: str) -> str:
        """Strip a glob to its literal prefix (everything before * ? [)."""
        for i, ch in enumerate(g):
            if ch in "*?[":
                return g[:i]
        return g

    anchors = [_anchor(g) for g in globs]

    uncovered: list[str] = []
    for lens_name, lens_path in lenses.items():
        if isinstance(lens_path, dict):
            p = str(lens_path.get("path", ""))
        else:
            p = str(lens_path)
        if not p:
            continue
        if not p.endswith("/"):
            p = p + "/"
        if not any(a.startswith(p) or p.startswith(a) for a in anchors):
            uncovered.append(f"{lens_name} ({p})")

    if uncovered:
        raise ConfigError(
            "lens_paths entries are not related to any "
            "agent_editable_paths glob: "
            + ", ".join(uncovered)
            + f". Configured editable globs: {globs}. "
            "Add a glob whose anchor shares a path branch with the lens "
            "(e.g., add '"
            + uncovered[0].split(" (")[1].rstrip(")")
            + "**' to docs.agent_editable_paths)."
        )


def _validate_site_sections(config: dict) -> None:
    """Cross-field checks for the optional site: block.

    - section keys are unique
    - every section path resolves *inside* docs_dir (no traversal/escape)
    Schema (templates/config.schema.json) already enforces presence/types
    and the generator enum; this covers what schema can't express.
    """
    site = config.get("site")
    if not site:
        return
    docs_dir = (site.get("docs_dir") or "").rstrip("/")
    sections = site.get("sections", []) or []

    seen: set[str] = set()
    dupes: list[str] = []
    for s in sections:
        k = s.get("key", "")
        if k in seen:
            dupes.append(k)
        seen.add(k)
    if dupes:
        raise ConfigError(f"site.sections has duplicate key(s): {sorted(set(dupes))}")

    base = PurePosixPath(docs_dir)
    for s in sections:
        rel = (s.get("path") or "").rstrip("/")
        full = base / rel
        # Reject any path that climbs out of docs_dir.
        if ".." in PurePosixPath(rel).parts or not str(full).startswith(docs_dir):
            raise ConfigError(
                f"site.section '{s.get('key')}' path {rel!r} resolves outside "
                f"docs_dir {docs_dir!r}"
            )

    for s in sections:
        for src in s.get("sources", []) or []:
            sp = str(src)
            if sp.startswith("/") or ".." in PurePosixPath(sp).parts:
                raise ConfigError(
                    f"site.section '{s.get('key')}' source {sp!r} must be a "
                    "relative path inside the repo (no absolute or '..' paths)"
                )


def _validate_api_sections(config: dict) -> None:
    """Cross-field checks for api-extract sections (CCE-23 capability API).

    - an api-extract section must declare a non-empty `extractors`
    - its `sources` must be repo-relative (no absolute or '..' paths)
    - the `openapi` extractor requires a repo-relative `openapi:` path
    Schema enforces the extractor enum and the `openapi` field type.
    """
    site = config.get("site")
    if not site:
        return
    for s in site.get("sections", []) or []:
        if s.get("generator") != "api-extract":
            continue
        extractors = s.get("extractors") or []
        if not extractors:
            raise ConfigError(
                f"site.section '{s.get('key')}' uses generator api-extract but "
                "declares no extractors"
            )
        for src in s.get("sources") or []:
            sp = str(src)
            if sp.startswith("/") or ".." in PurePosixPath(sp).parts:
                raise ConfigError(
                    f"site.section '{s.get('key')}' source {sp!r} must be relative "
                    "to the repo (no absolute or '..' paths)"
                )
        seen_groups: set[str] = set()
        for g in s.get("groups") or []:
            name = g.get("name", "")
            if name in seen_groups:
                raise ConfigError(
                    f"site.section '{s.get('key')}' has a duplicate group name {name!r}"
                )
            seen_groups.add(name)
        if "openapi" in extractors:
            path = s.get("openapi")
            if not path:
                raise ConfigError(
                    f"site.section '{s.get('key')}' lists the openapi extractor "
                    "but has no `openapi:` schema path"
                )
            if path.startswith("/") or ".." in PurePosixPath(path).parts:
                raise ConfigError(
                    f"site.section '{s.get('key')}' openapi path {path!r} must be "
                    "relative to the repo (no absolute or '..' paths)"
                )


def load_config_validated(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"config YAML invalid in {path}: {e}") from e
    schema = json.loads((TEMPLATES_DIR / "config.schema.json").read_text())
    try:
        jsonschema.validate(raw, schema)
    except jsonschema.ValidationError as e:
        raise ConfigError(f"config invalid at {e.json_path}: {e.message}") from e
    _validate_lens_paths_are_editable(raw)
    _validate_site_sections(raw)
    _validate_api_sections(raw)
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


_EPHEMERAL_KEYS = ("current_run",)


def save_persistent_state(path: Path, state: dict[str, Any]) -> None:
    """Write only persistent fields of `state` to `path` as JSON.

    Ephemeral fields (current_run) are dropped before writing. The on-disk
    copy is the source of truth promoted by merging the docs-agent PR.
    """
    persistent = {k: v for k, v in state.items() if k not in _EPHEMERAL_KEYS}
    path.write_text(json.dumps(persistent, indent=2) + "\n")


def save_current_run(path: Path, state: dict[str, Any]) -> None:
    """Sync the ephemeral current_run to <path's parent>/current_run.json.

    The sibling file is gitignored (see .gitignore) and not part of the
    merge-as-promotion path — only state.json is committed. When `state`
    carries a `current_run`, write the sibling. When it doesn't, remove
    any stale sibling so on-disk state matches in-memory state.
    """
    target = path.parent / "current_run.json"
    cr = state.get("current_run")
    if cr is None:
        target.unlink(missing_ok=True)
        return
    target.write_text(json.dumps({"current_run": cr}, indent=2) + "\n")


def add_partial(state: dict, reason: str, *, info_only: bool = False) -> None:
    """Append a partial reason to current_run.partial_reasons.

    When info_only is False (default), also flip current_run.partial to True.
    When info_only is True, leave current_run.partial unchanged — the reason
    is informational, not a degradation of the run's data quality.

    Idempotent for state: a reason already present (after redaction) is not
    appended again.

    Side effect (CCE-74): writes one line to stderr via stderr_emit.emit_stderr
    on EVERY call (NOT only newly-appended) so retry-loop sequencing is visible.
    Reason string is redacted via stderr_emit._redact_credentials BEFORE being
    stored in state AND before being emitted; state.json never carries raw
    credentials regardless of which call site recorded the reason. Stderr emit
    is best-effort (OSError-swallowed); state mutation always succeeds.
    """
    safe_reason = _redact_credentials(reason)
    if "current_run" not in state:
        state["current_run"] = {"partial": False, "partial_reasons": []}
    cr = state["current_run"]
    cr.setdefault("partial_reasons", [])
    if safe_reason not in cr["partial_reasons"]:
        cr["partial_reasons"].append(safe_reason)
    if not info_only:
        cr["partial"] = True
    emit_stderr(safe_reason, info_only=info_only)


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
    # The host voice override leads: read first, it survives the cap intact.
    override = repo_root / "docs-agent-voice.md"
    if override.exists():
        sources.append(override)
    for rel in voice_cfg.get("sample_paths") or []:
        sources.append(repo_root / rel)
    claude_md = repo_root / "CLAUDE.md"
    if claude_md.exists():
        sources.append(claude_md)
    seen: set[Path] = set()
    for src in sources:
        if not src.exists() or not src.is_file():
            continue
        # CLAUDE.md is appended implicitly and is also a common sample_paths
        # entry; without this a host config listing it burns the budget twice.
        key = src.resolve()
        if key in seen:
            continue
        seen.add(key)
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
