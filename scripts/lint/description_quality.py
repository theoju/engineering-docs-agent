"""Lint rule: description_quality. Enforces frontmatter `description` is a
substantive sentence, not a placeholder copied from the page title.

Applies only to agent-authored sections (the lens whose required fields
include ``description``). Other lenses have their own required-field set and
this rule is a no-op for them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Sibling-script import pattern: place the parent scripts/ on sys.path so the
# in-repo frontmatter_contract and archive_indexes modules resolve. Mirrors
# frontmatter_schema.py:10.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive_indexes  # noqa: E402
import frontmatter_contract as fc  # noqa: E402

RULE_NAME = "description_quality"
SEVERITY = "block"

_DEFAULTS = {
    "min_words": 6,
    "forbid_equal_to_title": True,
    "forbid_trailing_colon": True,
}


def _resolve_config(config: dict[str, Any]) -> dict[str, Any]:
    """Merge defaults with the host's overrides under
    ``lint.tier1.description_quality``. ``lint.tier1`` may be the sentinel
    string ``"default"`` (then no overrides) or a dict carrying rule subkeys.
    """
    lint = (config or {}).get("lint") or {}
    tier1 = lint.get("tier1")
    if not isinstance(tier1, dict):
        return dict(_DEFAULTS)
    overrides = tier1.get(RULE_NAME) or {}
    if not isinstance(overrides, dict):
        return dict(_DEFAULTS)
    return {**_DEFAULTS, **{k: v for k, v in overrides.items() if k in _DEFAULTS}}


def resolve_min_words(config: dict[str, Any]) -> int:
    """The effective ``min_words`` floor for ``config`` — the host override
    under ``lint.tier1.description_quality`` if present, else the default.
    Single source of truth for callers that must satisfy this floor (CCE-119
    Item B); the synthesized agent-authored description pads to it.
    """
    return int(_resolve_config(config)["min_words"])


def check_fm(
    fm: dict[str, Any],
    *,
    title: str | None,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Pure check against the frontmatter dict.

    ``title`` is compared against ``description`` only when
    ``forbid_equal_to_title`` is enabled AND ``title`` is not None. Callers that
    don't know the title (e.g. running before the body's H1 is parsed) pass
    None to skip that check.

    Returns ``(True, "ok")`` on pass; ``(False, reason)`` on rejection.
    """
    cfg = _resolve_config(config)
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return False, "missing or empty description"
    stripped = desc.strip()

    # Check order is cheapest-first: trailing-colon is a single endswith();
    # equal-to-title needs a strip+lower on the title; min_words splits the
    # whole description. Common failures reject without doing extra work.
    if cfg["forbid_trailing_colon"] and stripped.endswith(":"):
        return False, "forbid_trailing_colon: description ends in ':'"

    if cfg["forbid_equal_to_title"] and title is not None:
        if stripped.lower() == title.strip().lower():
            return False, f"forbid_equal_to_title: description == title ('{title}')"

    word_count = len(stripped.split())
    if word_count < cfg["min_words"]:
        return False, f"min_words: {word_count} < {cfg['min_words']}"

    return True, "ok"


# Path-reading shim ---------------------------------------------------------


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    """Read ``path``, resolve its section generator, and apply ``check_fm`` only
    to agent-authored pages. Non-agent-authored sections are silent no-ops.

    Frontmatter parse errors are reported as failures so this rule can also
    surface gap-3-class defects when invoked through ``lint_runner`` rather
    than the bootstrap callback. (The bootstrap path uses
    ``parse_frontmatter_strict`` directly so it can record distinct reasons.)
    """
    if not path.exists():
        return False, "file not found"
    generator = fc.section_generator_for(path, config)
    if generator != "agent-authored":
        return True, "not agent-authored; skipped"
    text = path.read_text()
    try:
        fm = archive_indexes.parse_frontmatter_strict(text)
    except yaml.YAMLError:
        return False, "frontmatter YAML parse error"
    except ValueError:
        return False, "no frontmatter block"
    title, _ = archive_indexes.parse_title_and_summary(text)
    # parse_title_and_summary returns "" for no H1; coerce to None so check_fm
    # skips the equal-to-title comparison rather than comparing against "".
    return check_fm(fm, title=title or None, config=config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, config)
        results.append({"path": str(p), "ok": ok, "message": message})
        if not ok:
            any_failed = True
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": results}, sys.stdout
        )
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
