"""Auto-discover host repo settings for the setup skill."""

from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path


def detect_framework(cwd: Path) -> str | None:
    if (cwd / "mkdocs.yml").exists():
        return "mkdocs"
    if (cwd / "docusaurus.config.js").exists() or (
        cwd / "docusaurus.config.ts"
    ).exists():
        return "docusaurus"
    return None


def detect_source_dir(cwd: Path, framework: str | None) -> str | None:
    if framework == "mkdocs":
        if (cwd / "docs" / "site-src").is_dir():
            return "docs/site-src"
        if (cwd / "docs").is_dir():
            return "docs"
    if framework == "docusaurus":
        if (cwd / "docs").is_dir():
            return "docs"
    return None


def detect_lens_paths(cwd: Path, source_dir: str | None) -> dict[str, str]:
    if not source_dir:
        return {}
    src = cwd / source_dir
    out: dict[str, str] = {}
    if not src.exists():
        return out
    for child in sorted(src.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            out[child.name] = str(child.relative_to(cwd))
    return out


def detect_ci(cwd: Path) -> str | None:
    if (cwd / ".github" / "workflows").is_dir():
        return "github_actions"
    if (cwd / ".gitlab-ci.yml").exists():
        return "gitlab_ci"
    return None


_LOOSE_DIRS = ("src", "scripts")
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "build", "dist", "tests", "test"}


def detect_python(cwd: Path) -> dict:
    """Resolve a Python source root generically.

    Returns {"detected", "scan_dir", "path_root"}: scan_dir is walked for
    *.py; path_root goes on mkdocstrings' `paths` so a module identifier is
    its path relative to path_root. A top-level package (a dir with
    __init__.py) wins; else a conventional loose-module dir (src/scripts).
    """
    for child in sorted(cwd.iterdir()):
        if (
            child.is_dir()
            and child.name not in _SKIP_DIRS
            and not child.name.startswith(".")
            and (child / "__init__.py").exists()
        ):
            return {"detected": True, "scan_dir": child.name, "path_root": "."}
    for name in _LOOSE_DIRS:
        d = cwd / name
        if d.is_dir() and any(d.glob("*.py")):
            return {"detected": True, "scan_dir": name, "path_root": name}
    return {"detected": False, "scan_dir": None, "path_root": None}


def detect_openapi_hint(cwd: Path) -> str | None:
    """Return an OpenAPI schema filename at the repo root, or None.

    Checks repo-root openapi.json/.yaml/.yml only — a hint, not a deep search.
    """
    for name in ("openapi.json", "openapi.yaml", "openapi.yml"):
        if (cwd / name).exists():
            return name
    return None


def detect_toolchain(cwd: Path) -> dict:
    """Detect JavaScript / TypeScript toolchain hints.

    Returns a dict with:
      - node: package.json present
      - bun: bun.lockb present
      - deno: deno.json or deno.jsonc present
      - package_manager: "npm" | "yarn" | "pnpm" | "bun" | None
        (lockfile-derived; bun.lockb beats every npm-family lockfile)
      - docusaurus_dep: any @docusaurus/* in package.json deps/devDeps/peerDeps

    Malformed package.json is tolerated — docusaurus_dep falls back to False.
    """
    import json

    node = (cwd / "package.json").exists()
    bun = (cwd / "bun.lockb").exists()
    deno = (cwd / "deno.json").exists() or (cwd / "deno.jsonc").exists()

    package_manager: str | None = None
    if bun:
        package_manager = "bun"
    elif (cwd / "pnpm-lock.yaml").exists():
        package_manager = "pnpm"
    elif (cwd / "yarn.lock").exists():
        package_manager = "yarn"
    elif (cwd / "package-lock.json").exists():
        package_manager = "npm"

    docusaurus_dep = False
    if node:
        pj = cwd / "package.json"
        try:
            # 32KB cap — package.json files larger than that are pathological.
            text = pj.read_text(errors="ignore")[:32_768]
            data = json.loads(text)
            for block in ("dependencies", "devDependencies", "peerDependencies"):
                deps = data.get(block) or {}
                if any(k.startswith("@docusaurus/") for k in deps):
                    docusaurus_dep = True
                    break
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    return {
        "node": node,
        "bun": bun,
        "deno": deno,
        "package_manager": package_manager,
        "docusaurus_dep": docusaurus_dep,
    }


def detect_jira_hint(cwd: Path) -> dict | None:
    """Detect Jira hints from CI workflow files or .env.example.

    Returns a dict with `base_url` if found, else None.
    """
    import re

    wf_dir = cwd / ".github" / "workflows"
    base_url: str | None = None
    has_jira_marker = False
    if wf_dir.is_dir():
        for p in wf_dir.glob("*"):
            try:
                text = p.read_text(errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            if "JIRA_" in text:
                has_jira_marker = True
                m = re.search(r"JIRA_BASE_URL:\s*(\S+)", text)
                if m:
                    base_url = m.group(1).strip().strip('"').strip("'")
                    break
        if base_url:
            return {"base_url": base_url}
    env_example = cwd / ".env.example"
    if env_example.exists():
        try:
            text = env_example.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            text = ""
        if "JIRA_" in text:
            has_jira_marker = True
            m = re.search(r"JIRA_BASE_URL\s*=\s*(\S+)", text)
            if m:
                base_url = m.group(1).strip().strip('"').strip("'")
                return {"base_url": base_url}
    if base_url:
        return {"base_url": base_url}
    if has_jira_marker:
        return {"base_url": None}
    return None


def derive_pages_base_url(owner: str, repo: str, cname: str | None = None) -> str:
    """Project site -> https://<owner>.github.io/<repo>/; user/org site
    (repo named <owner>.github.io) -> https://<owner>.github.io/; custom
    domain (CNAME) -> https://<cname>/."""
    if cname:
        return f"https://{cname.strip().rstrip('/')}/"
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def detect_pages_publishable(framework: str | None, ci: str | None) -> bool:
    """True when the host can be auto-scaffolded for Pages deploy: MkDocs on
    GitHub Actions. Other frameworks need a config build_command (handled by
    the setup skill), so they are not auto-publishable here."""
    return ci == "github_actions" and framework == "mkdocs"


_REMOTE_PATTERN = re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?/?$")


def discover_git_origin(repo_root: Path) -> dict | None:
    """Return {owner, repo} parsed from `git remote get-url origin`, or None.

    Returns None if no `origin` remote exists, or the URL doesn't match the
    github.com pattern. Caller (SKILL.md) falls back to AskUserQuestion.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    m = _REMOTE_PATTERN.search(result.stdout.strip())
    if not m:
        return None
    return {"owner": m.group(1), "repo": m.group(2)}


def discover(cwd: Path) -> dict:
    """Discover host repo settings. Returns a structured dict with optional warnings."""
    warnings: list[dict] = []
    framework = detect_framework(cwd)
    if framework == "docusaurus":
        warnings.append(
            {
                "code": "docusaurus_v0.1_unsupported",
                "message": (
                    "Docusaurus detected; v0.1 only validates mkdocs builds. "
                    "Other lint rules still run."
                ),
            }
        )
    source_dir = detect_source_dir(cwd, framework)
    lens_paths = detect_lens_paths(cwd, source_dir)
    ci = detect_ci(cwd)
    jira_hint = detect_jira_hint(cwd)
    out: dict = {
        "framework": framework,
        "source_dir": source_dir,
        "lens_paths": lens_paths,
        "ci": ci,
        "jira_hint": jira_hint,
        "python": detect_python(cwd),
        "openapi_hint": detect_openapi_hint(cwd),
        "toolchain": detect_toolchain(cwd),
        "pages_publishable": detect_pages_publishable(framework, ci),
        "git": discover_git_origin(cwd),
    }
    if warnings:
        out["warnings"] = warnings
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cwd = Path.cwd()
    out = discover(cwd)
    if args.json:
        json.dump(out, sys.stdout)
    else:
        for k, v in out.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
