"""CLI: scaffold the site: structure into a host repo (idempotent).

Used by the engineering-docs-agent-setup skill. With no --config, uses the
shipped default template (templates/site.default.yaml). Detects Python in the
repo to decide whether to wire mkdocstrings into mkdocs.yml.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Run with scripts/ on the path so `import site_structure` resolves whether the
# CLI is launched as a script or imported. (Running it as a script already puts
# its own dir on sys.path[0]; this makes that explicit and import-safe too.)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_structure  # noqa: E402

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _python_detected(repo_root: Path) -> bool:
    # cheap heuristic: any .py outside common vendor dirs, or a pyproject.toml
    if (repo_root / "pyproject.toml").exists():
        return True
    for p in repo_root.rglob("*.py"):
        if not any(
            part in {".venv", "node_modules", "site", "__pycache__"} for part in p.parts
        ):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--site-name", default="Documentation")
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="site: YAML; defaults to templates/site.default.yaml",
    )
    args = ap.parse_args()

    site_path = args.config or (_TEMPLATES / "site.default.yaml")
    site = yaml.safe_load(site_path.read_text())

    result = site_structure.apply_scaffold(
        args.repo_root,
        site,
        site_name=args.site_name,
        python_detected=_python_detected(args.repo_root),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
