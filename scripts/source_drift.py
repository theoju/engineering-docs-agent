"""doc↔source drift detector (capability M).

Given a set of changed files, reports which site pages declare a `source_files:`
glob that matches one of them. Read-only. Shares pattern collection + glob
translation with source_map.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_map import _collect_page_patterns, _glob_to_regex  # noqa: E402


def detect_drift(docs_dir: Path, changed_files: list[str]) -> dict:
    """Return {"drifted": [{"page", "changed_sources"}], "changed_files_seen"}.
    A page drifts when any of its source_files globs matches a changed file.
    """
    patterns = _collect_page_patterns(docs_dir)
    drifted: list[dict] = []
    for page in sorted(patterns):
        regexes = [_glob_to_regex(g) for g in patterns[page]]
        matched = [f for f in changed_files if any(r.fullmatch(f) for r in regexes)]
        if matched:
            drifted.append({"page": page, "changed_sources": sorted(matched)})
    return {"drifted": drifted, "changed_files_seen": len(changed_files)}


def _read_changed_from_stdin() -> list[str]:
    raw = sys.stdin.read()
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if isinstance(x, str)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Detect doc-source drift.")
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    args = ap.parse_args(argv)
    from state_io import ConfigError, load_config_validated

    try:
        config = load_config_validated(args.config)
    except (ConfigError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    changed = _read_changed_from_stdin()
    docs_dir = (config.get("site") or {}).get("docs_dir")
    if not docs_dir:
        print(json.dumps({"drifted": [], "changed_files_seen": len(changed)}, indent=2))
        return 0
    print(json.dumps(detect_drift(args.repo_root / docs_dir, changed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
