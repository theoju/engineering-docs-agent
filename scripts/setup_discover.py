"""Auto-discover host repo settings for the setup skill."""

from __future__ import annotations
import argparse, json, sys
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


def detect_jira_hint(cwd: Path) -> bool:
    wf_dir = cwd / ".github" / "workflows"
    if wf_dir.is_dir():
        for p in wf_dir.glob("*"):
            try:
                if "JIRA_" in p.read_text(errors="ignore"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
    env_example = cwd / ".env.example"
    if env_example.exists():
        try:
            if "JIRA_" in env_example.read_text(errors="ignore"):
                return True
        except (OSError, UnicodeDecodeError):
            pass
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cwd = Path.cwd()
    framework = detect_framework(cwd)
    source_dir = detect_source_dir(cwd, framework)
    lens_paths = detect_lens_paths(cwd, source_dir)
    ci = detect_ci(cwd)
    jira_hint = detect_jira_hint(cwd)
    out = {
        "framework": framework,
        "source_dir": source_dir,
        "lens_paths": lens_paths,
        "ci": ci,
        "jira_hint": jira_hint,
    }
    if args.json:
        json.dump(out, sys.stdout)
    else:
        for k, v in out.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
