"""Lint rule: citation_exists (CCE-110, Tier-1).

Verifies that repo artifacts cited in a page's PROSE actually exist: inline
code spans naming repo paths (`scripts/foo.py`, optional `:line` /
`:start-end` suffix) or test identifiers (`test_snake_case`). Confabulated
pages cite tests/files that were never written; this rule blocks them.

Scope notes:
- Fenced code blocks are stripped first — fenced examples are legitimately
  hypothetical. Only inline code spans in prose are checked.
- Distinct from capability C1 (scripts/verify_citations.py), which verifies
  pinned `path:line` + `<!--pin:TOKEN-->` citations on existing pages. This
  rule needs no pins and checks bare existence on newly authored pages.
- Generic-first degradation: when the config's directory is not inside a git
  repo, every path passes trivially (we cannot verify; we never block).
- The extraction functions are imported by scripts/orchestrator_runner.py
  (fact-checker dispatch). They are a shared-helper contract: grep callers
  repo-wide before changing signatures (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

RULE_NAME = "citation_exists"
SEVERITY = "block"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_TEST_ID_RE = re.compile(r"^test_[a-z0-9_]+$")
# dir/file.ext with an optional :line, :start-end, or :symbol suffix.
_REPO_PATH_RE = re.compile(
    r"^[\w.\-/]+/[\w.\-]+\.\w{1,8}(?::(?:\d+(?:-\d+)?|[A-Za-z_][\w.]*))?$"
)
# strips either a :line/:start-end or a :symbol suffix to the bare path
_SUFFIX_RE = re.compile(r":(?:\d+(?:-\d+)?|[A-Za-z_][\w.]*)$")
_LINE_SUFFIX_RE = re.compile(r":\d+(?:-\d+)?$")
# advisory detector: any `path.ext:digits` span, slash optional (bare filenames
# like `orchestrator_runner.py:128` are the worst offenders — unlinted AND drifting)
_LINE_PIN_RE = re.compile(r"^[\w.\-/]+\.\w{1,8}:\d+(?:-\d+)?$")
_PLACEHOLDER_MARKERS = ("<", ">", "*", "{", "}", "YYYY", "...")


def strip_fenced_blocks(text: str) -> str:
    """Drop ``` / ~~~ fenced regions; return the remaining prose lines."""
    out: list[str] = []
    in_fence = False
    fence = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def _is_placeholder(token: str) -> bool:
    return (
        any(m in token for m in _PLACEHOLDER_MARKERS)
        or token.startswith(("~", "$"))
        or "://" in token
    )


def extract_citations(text: str) -> dict[str, list[str]]:
    """Citations in prose, deduped in document order.

    Returns {"paths": [...], "tests": [...]} — repo-path tokens have any
    trailing :line suffix stripped.
    """
    paths: list[str] = []
    tests: list[str] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if not token or _is_placeholder(token):
            continue
        if _TEST_ID_RE.match(token):
            if token not in tests:
                tests.append(token)
        elif _REPO_PATH_RE.match(token):
            bare = _SUFFIX_RE.sub("", token)
            if bare not in paths:
                paths.append(bare)
    return {"paths": paths, "tests": tests}


def extract_symbol_citations(text: str) -> list[tuple[str, str]]:
    """(bare_path, leaf_symbol) for every `path:symbol` citation in prose.

    leaf = last dotted component (`Cls.method` -> `method`). Line-number and
    bare-path citations yield nothing here. Used by check_path for the
    deterministic symbol-existence guard."""
    out: list[tuple[str, str]] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if not token or _is_placeholder(token) or not _REPO_PATH_RE.match(token):
            continue
        m = _SUFFIX_RE.search(token)
        if not m or _LINE_SUFFIX_RE.search(token):  # no suffix, or a :line suffix
            continue
        bare = _SUFFIX_RE.sub("", token)
        leaf = m.group(0)[1:].split(".")[-1]  # drop leading ':', take last component
        pair = (bare, leaf)
        if pair not in out:
            out.append(pair)
    return out


def line_pinned_citations(text: str) -> list[str]:
    """Inline `path:line` spans still using the fragile digit suffix (advisory).

    Broader than _REPO_PATH_RE on purpose: catches bare-filename `foo.py:12`
    too. Single source of the `:line` grammar for the citation_line_free rule."""
    out: list[str] = []
    for token in _INLINE_CODE_RE.findall(strip_fenced_blocks(text)):
        token = token.strip()
        if _is_placeholder(token):
            continue
        if _LINE_PIN_RE.match(token) and token not in out:
            out.append(token)
    return out


def repo_root_for(config_path: Path) -> Path | None:
    """Host repo root via git, anchored at the config's directory. None when
    the config does not live inside a git repo (degrade: never block)."""
    r = subprocess.run(
        ["git", "-C", str(config_path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    top = r.stdout.strip()
    return Path(top) if r.returncode == 0 and top else None


def tracked_files(repo_root: Path) -> set[str]:
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"],
        capture_output=True,
        text=True,
    )
    return set(r.stdout.splitlines()) if r.returncode == 0 else set()


def cited_test_exists(repo_root: Path, name: str) -> bool:
    """True if any tracked file defines or calls the named test."""
    for needle in (f"def {name}(", f"{name}("):
        r = subprocess.run(
            ["git", "-C", str(repo_root), "grep", "-l", "-F", needle],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
    return False


def _relativize(path_str: str, repo_root: Path) -> str | None:
    """Repo-relative form of a cited path; None when an absolute path falls
    outside the repo (an environment reference, not a repo citation)."""
    if not path_str.startswith("/"):
        return path_str
    try:
        return str(Path(path_str).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return None


def _symbol_defined(source: str, leaf: str) -> bool:
    """True if `leaf` is defined in the file source: a def/class (any indent,
    so methods count) or a module-level (column-0) assignment/annotation."""
    name = re.escape(leaf)
    pattern = re.compile(
        rf"(?m)^\s*(?:async\s+)?(?:def|class)\s+{name}\b|^{name}\s*[:=]"
    )
    return bool(pattern.search(source))


def check_path(path: Path, repo_root: Path | None, files: set[str]) -> tuple[bool, str]:
    if repo_root is None:
        return True, "no git repo detected; citation check skipped"
    if not path.exists():
        return False, "file not found"
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        return False, "file not decodable as UTF-8"
    except OSError as e:
        return False, f"file unreadable: {e}"
    cites = extract_citations(text)
    problems: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        # Disk-existence fallback: same-run siblings are not yet tracked.
        if rel not in files and not (repo_root / rel).exists():
            problems.append(f"cites nonexistent path '{cited}'")
    for name in cites["tests"]:
        if not cited_test_exists(repo_root, name):
            problems.append(f"cites nonexistent test '{name}'")
    for bare, leaf in extract_symbol_citations(text):
        rel = _relativize(bare, repo_root)
        if rel is None:
            continue
        target = repo_root / rel
        if not target.exists():
            continue  # nonexistent path already reported by the paths loop
        try:
            source = target.read_text()
        except (UnicodeDecodeError, OSError):
            continue  # unreadable cited file: do not false-block
        if not _symbol_defined(source, leaf):
            problems.append(f"cites nonexistent symbol '{leaf}' in '{bare}'")
    if problems:
        return False, "; ".join(problems)
    return True, "ok"


def resolve_cited_sources(text: str, repo_root: Path) -> list[str]:
    """Repo-relative cited paths that exist on disk — the fact-checker's
    cited_sources input. Ordered, deduped."""
    out: list[str] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel and (repo_root / rel).exists() and rel not in out:
            out.append(rel)
    return out


def _load_config(config_path: Path) -> dict:
    """Parse the host config YAML; degrade to {} on any read/parse error (the
    lint must never crash on a malformed config — it just loses archive-lens
    awareness and falls back to pure block)."""
    try:
        return yaml.safe_load(config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def archive_dirs(config: dict, repo_root: Path) -> list[Path]:
    """Resolved dirs of every ``archive-index``-generator section (CCE-124).

    Archive pages are historical records; their citations are true *as of
    archival* and legitimately name code that has since moved or been removed,
    so citation_exists is advisory (warn), not a build block, for pages under
    these dirs. Empty when the host declares no such section — generic-first:
    identical to the pre-CCE-124 pure-block behavior."""
    site = config.get("site") or {}
    docs_dir = site.get("docs_dir") or ""
    out: list[Path] = []
    for sec in site.get("sections") or []:
        if isinstance(sec, dict) and sec.get("generator") == "archive-index":
            out.append((repo_root / docs_dir / (sec.get("path") or "")).resolve())
    return out


def _under(path: Path, roots: list[Path]) -> bool:
    """True if ``path`` resolves inside one of ``roots``."""
    try:
        rp = path.resolve()
    except OSError:
        return False
    for r in roots:
        try:
            rp.relative_to(r)
            return True
        except ValueError:
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo_root = repo_root_for(args.config)
    files = tracked_files(repo_root) if repo_root else set()
    arch = archive_dirs(_load_config(args.config), repo_root) if repo_root else []
    results, any_block_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, repo_root, files)
        # Archive pages are historical records; citation existence there is
        # advisory (warn), not a build block (CCE-124). Live lenses keep block.
        severity = "warn" if _under(p, arch) else SEVERITY
        results.append(
            {"path": str(p), "ok": ok, "message": message, "severity": severity}
        )
        if not ok and severity == "block":
            any_block_failed = True
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": results}, sys.stdout
        )
    return 1 if any_block_failed else 0


if __name__ == "__main__":
    sys.exit(main())
