"""CLI: scaffold the site: structure into a host repo (idempotent).

Used by the engineering-docs-agent-setup skill. With no --config, uses the
shipped default template (templates/site.default.yaml). Detects Python via
setup_discover.detect_python — scoping the gen-files recipe to the discovered
package/module dir — derives the OpenAPI path from the api-extract section's
openapi field, and runs the contracts generator, surfacing its ledger in the
JSON output.
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
import contracts_doc  # noqa: E402
import core_manifest  # noqa: E402
import setup_discover  # noqa: E402
import site_structure  # noqa: E402

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
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
    try:
        site = yaml.safe_load(site_path.read_text())
    except FileNotFoundError:
        print(f"error: config file not found: {site_path}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML in {site_path}: {exc}", file=sys.stderr)
        return 1

    py = setup_discover.detect_python(args.repo_root)

    openapi_path = next(
        (
            s.get("openapi")
            for s in (site.get("sections") or [])
            if s.get("generator") == "api-extract" and s.get("openapi")
        ),
        None,
    )

    result = site_structure.apply_scaffold(
        args.repo_root,
        site,
        site_name=args.site_name,
        python_detected=py["detected"],
        python_scan_dir=py["scan_dir"],
        python_path_root=py["path_root"],
        openapi_path=openapi_path,
    )

    result["contracts"] = contracts_doc.generate_contracts(args.repo_root, site)
    result["core_manifest"] = core_manifest.write_core_manifest(args.repo_root, site)
    import section_overview  # noqa: E402 - deferred to keep top-level imports minimal

    result["overviews"] = section_overview.generate_overviews(args.repo_root, site)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
