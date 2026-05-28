"""Lint rule: description_quality. Enforces frontmatter `description` is a
substantive sentence, not a placeholder copied from the page title.

Applies only to agent-authored sections (the lens whose required fields
include ``description``). Other lenses have their own required-field set and
this rule is a no-op for them.
"""

from __future__ import annotations

from typing import Any

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
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in overrides.items() if k in _DEFAULTS})
    return merged


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

    if cfg["forbid_trailing_colon"] and stripped.endswith(":"):
        return False, f"forbid_trailing_colon: description ends in ':'"

    if cfg["forbid_equal_to_title"] and title is not None:
        if stripped.lower() == title.strip().lower():
            return False, f"forbid_equal_to_title: description == title ('{title}')"

    word_count = len(stripped.split())
    if word_count < cfg["min_words"]:
        return False, f"min_words: {word_count} < {cfg['min_words']}"

    return True, "ok"
