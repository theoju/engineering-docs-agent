"""Read-only pre-flight readiness check for a host repo.

Runs setup discovery, prints the config the setup skill would write, the
secrets the shipped workflow needs, and any warnings about host shape.
Does not modify the host repo.

Usage:
    python scripts/preflight_host.py --repo-root /path/to/host [--format text|json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Run with scripts/ on the path so `import setup_discover` resolves whether
# the CLI is launched as a script or imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_discover  # noqa: E402

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_TEMPLATE = _PLUGIN_ROOT / "templates" / "workflow-run.yml"


def proposed_config(discovery: dict) -> dict:
    """Compute the config dict the setup skill would write, without writing it.

    Read-only: derives values from discovery alone. The actual setup skill
    asks user questions for the notification/lint blocks; preflight stubs
    those with safe defaults so the user sees the shape before answering.
    """
    framework = discovery.get("framework")
    source_dir = discovery.get("source_dir") or "docs"
    lens_paths = discovery.get("lens_paths") or {"core": source_dir}
    jira_hint = discovery.get("jira_hint") or {}
    return {
        "docs": {
            "framework": framework or "none",
            "source_dir": source_dir,
            "whats_new_file": f"{source_dir}/whats-new.md",
            "agent_editable_paths": [f"{source_dir}/**"],
            "lens_paths": lens_paths,
        },
        "sources": {
            "git": {"host": "github"},
            "jira": {
                "enabled": bool(jira_hint),
                "base_url": jira_hint.get("base_url") if jira_hint else None,
                "project_keys": [],
            },
        },
        "voice": {"sample_paths": ["CLAUDE.md", "README.md"]},
        "lint": {"tier1": "default"},
        "publishing": {
            "base_url": None,
            "build_workflow": (
                "docs-agent-pages.yml" if discovery.get("pages_publishable") else None
            ),
            "url_map_rule": "standard",
            "verify_timeout_seconds": 60,
        },
        "notifications": {
            "slack": {"enabled": False},
            "email": {"enabled": False},
        },
    }


def secrets_from_workflow(workflow_text: str) -> list[dict]:
    """Extract `secrets.X` references from the workflow template.

    Returns a sorted, de-duplicated list of {name, required} dicts. Required
    is True for the three workflow-blocking secrets, False for optional ones.
    GITHUB_TOKEN is filtered out (always injected by Actions).
    """
    found = sorted(set(re.findall(r"secrets\.([A-Z_]+)", workflow_text)))
    required = {
        "CLAUDE_CODE_OAUTH_TOKEN",
        "DOCS_AGENT_APP_ID",
        "DOCS_AGENT_APP_PRIVATE_KEY",
    }
    found = [n for n in found if n != "GITHUB_TOKEN"]
    # Ensure the three blocking secrets are always present even if the
    # shipped template happens to omit one (defense-in-depth for the runbook).
    for n in sorted(required):
        if n not in found:
            found.append(n)
    return [{"name": n, "required": n in required} for n in sorted(set(found))]


def compute_warnings(discovery: dict) -> list[dict]:
    warnings = list(discovery.get("warnings", []))
    if not discovery.get("framework"):
        # severity: "info" | "warn" | "block" — informal convention shared with
        # lint result severity (see orchestrator_runner). Absent severity is
        # treated as block by default for backward compatibility with the
        # pre-CCE-64 warning shape.
        warnings.append(
            {
                "code": "framework_none",
                "severity": "info",
                "message": (
                    "No mkdocs.yml or docusaurus.config.* found at the repo root. "
                    "Config will write framework: none. The framework_build lint "
                    "rule and the publish-verifier skip cleanly; PR summaries, "
                    "page authoring, and what's-new updates run normally. "
                    "If you want strict build-time link checking, scaffold mkdocs "
                    "(`mkdocs init`) and re-run preflight."
                ),
            }
        )
    if discovery.get("framework") == "docusaurus" and not discovery.get(
        "pages_publishable"
    ):
        warnings.append(
            {
                "code": "pages_not_auto_scaffolded",
                "message": (
                    "Docusaurus hosts are not auto-scaffolded for GitHub Pages. "
                    "Set publishing.build_command (e.g. `npm run build`) and "
                    "publishing.site_dir (e.g. `build`) in config.yml to enable."
                ),
            }
        )
    toolchain = discovery.get("toolchain") or {}
    python_state = discovery.get("python") or {}
    if toolchain.get("node") and not python_state.get("detected"):
        warnings.append(
            {
                "code": "node_only_host",
                "message": (
                    "Node detected with no Python package. The orchestrator runs "
                    "Python from .docs-agent-plugin/; this is expected for JS/TS hosts."
                ),
            }
        )
    return warnings


def render_text(report: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("engineering-docs-agent host pre-flight")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Discovery")
    lines.append("-" * 60)
    for k, v in report["discovery"].items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("Proposed config (.engineering-docs-agent/config.yml)")
    lines.append("-" * 60)
    lines.append(json.dumps(report["proposed_config"], indent=2))
    lines.append("")
    lines.append(
        "Secrets checklist (set in repo Settings -> Secrets and variables -> Actions)"
    )
    lines.append("-" * 60)
    for s in report["secrets_checklist"]:
        marker = "[required]" if s["required"] else "[optional]"
        lines.append(f"  [ ] {s['name']} {marker}")
    lines.append("")
    if report["warnings"]:
        lines.append("Warnings")
        lines.append("-" * 60)
        for w in report["warnings"]:
            lines.append(f"  - {w['code']}: {w['message']}")
        lines.append("")
    lines.append("Pre-flight read-only. No files modified.")
    return "\n".join(lines)


def build_report(repo_root: Path) -> dict:
    discovery = setup_discover.discover(repo_root)
    try:
        workflow_text = _WORKFLOW_TEMPLATE.read_text()
    except OSError:
        workflow_text = ""
    return {
        "discovery": discovery,
        "proposed_config": proposed_config(discovery),
        "secrets_checklist": secrets_from_workflow(workflow_text),
        "warnings": compute_warnings(discovery),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, required=True)
    ap.add_argument("--format", choices=("text", "json"), default="text")
    args = ap.parse_args()

    if not args.repo_root.exists():
        print(
            f"error: --repo-root does not exist: {args.repo_root}",
            file=sys.stderr,
        )
        return 1

    report = build_report(args.repo_root)
    if args.format == "json":
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
