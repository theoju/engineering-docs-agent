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
from functools import lru_cache
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

# CCE-131: reserved illustrative namespace, RFC 2606's example.com precedent.
# The generic-first mandate requires fictional-host examples in docs; a token
# under this namespace is guaranteed never to resolve, so it is documentation,
# not a citation. Hosts with a real top-level example/ dir override the word.
DEFAULT_EXAMPLE_PREFIXES = ("example/",)

# CCE-131: tokens whose NON-EXISTENCE is the claim. Plugin-intrinsic entries
# ship here because every host that documents this lint hits them --
# test_snake_case is this module's own docstring placeholder. Host-specific
# invariants go in the host config and are unioned with these.
DEFAULT_EXEMPT_TOKENS = ("test_snake_case",)


def strip_fenced_blocks(text: str) -> str:
    """Drop fenced regions; return the remaining prose lines, in document order.

    CCE-131: an UNTERMINATED fence fails closed. Previously an unclosed fence
    swallowed every line to EOF, silently disabling this Tier-1 block rule for
    the rest of the file with no report.

    Lines are appended to ``out`` as they are read, fenced or not. On a
    properly terminated fence, the buffered fenced lines are cut back out
    (``del out[fence_start:]``) so a closed fence still strips cleanly. On an
    unterminated fence, nothing is ever cut, so the trailing lines stay in
    their original document position instead of being reordered to the end.
    """
    out: list[str] = []
    in_fence = False
    fence = ""
    fence_start = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            fence_start = len(out)
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            del out[fence_start:]
            continue
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
    """True if any tracked file defines or calls the named test.

    CCE-131: `def {name}_` also counts, so a test-FAMILY shorthand resolves —
    `test_lint_runner` is satisfied by test_lint_runner_missing_script_reports_block.
    The trailing underscore is the boundary: a confabulated `test_foo` passes
    only when a real `test_foo_*` exists, so the CCE-111 guard against wholly
    invented names is preserved.
    """
    for needle in (f"def {name}(", f"{name}(", f"def {name}_"):
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


def _docs_dir(config: dict) -> str:
    """site.docs_dir, slash-stripped. Empty when the host declares none."""
    return str((config.get("site") or {}).get("docs_dir") or "").strip("/")


@lru_cache(maxsize=None)
def _build_dir(repo_root: Path) -> str:
    """mkdocs site_dir (generated build output). Empty when there is no
    parseable mkdocs config -- skip NOTHING rather than reserving a prefix.

    CCE-131 review: the previous unconditional "site" fallback made site/ a
    permanently exempt prefix on every host, so an invented path under site/
    passed on a host that keeps real source there. And plain yaml.safe_load
    cannot read a mkdocs-material config -- Material standardly requires
    !!python/name: and !ENV tags, and `theme: material` is this plugin's own
    default -- so the parse branch never ran. A permissive multi-constructor
    degrades unknown tags to None instead of aborting the whole parse.

    Cached per repo_root: check_path calls this once per page and main()
    loops over every page in a run (91 on this host), and mkdocs.yml does not
    change mid-run.
    """

    class _LaxLoader(yaml.SafeLoader):
        pass

    _LaxLoader.add_multi_constructor("", lambda loader, suffix, node: None)
    try:
        mk = yaml.load((repo_root / "mkdocs.yml").read_text(), Loader=_LaxLoader) or {}
    except (OSError, yaml.YAMLError):
        return ""
    return str(mk.get("site_dir") or "site").strip("/")


def example_prefixes(config: dict) -> tuple[str, ...]:
    """Reserved illustrative-namespace prefixes, each with a trailing slash.

    Host config REPLACES the default rather than extending it: this is a
    namespace choice, and a host that picks `acme/` because it has a real
    `example/` directory must not keep the shadowed default.
    """
    lint = config.get("lint") or {}
    configured = lint.get("citation_example_prefixes")
    if configured is None:
        return DEFAULT_EXAMPLE_PREFIXES
    return tuple(f"{str(p).strip('/')}/" for p in configured if str(p).strip("/"))


def exempt_tokens(config: dict) -> set[str]:
    """Exact tokens citation_exists must not require to exist.

    Plugin defaults UNIONED with the host's lint.citation_exempt_tokens: host
    config extends, never replaces, so a host cannot silently lose a
    plugin-intrinsic entry by declaring one of its own.
    """
    lint = config.get("lint") or {}
    host = lint.get("citation_exempt_tokens") or []
    return set(DEFAULT_EXEMPT_TOKENS) | {str(t) for t in host}


def _resolves(
    rel: str, repo_root: Path, files: set[str], docs_dir: str, build_dir: str
) -> bool:
    """True when a cited repo-relative path names something real.

    Three ways to resolve, in order: it is generated build output; it is
    tracked or present on disk (the disk fallback covers same-run siblings not
    yet added to git); or it resolves under docs_dir, which is how a docs page
    naturally cites a sibling page.
    """
    if build_dir and (rel == build_dir or rel.startswith(build_dir + "/")):
        return True
    if rel in files or (repo_root / rel).exists():
        return True
    if docs_dir:
        alt = f"{docs_dir}/{rel}"
        if alt in files or (repo_root / alt).exists():
            return True
    return False


def check_path(
    path: Path, repo_root: Path | None, files: set[str], config: dict
) -> tuple[bool, str]:
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
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    problems: list[str] = []
    notes: list[str] = []
    for cited in cites["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if cited in exempt:
            if _resolves(rel, repo_root, files, docs_dir, build_dir):
                notes.append(f"stale exemption: '{cited}' now resolves")
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue  # reserved illustrative namespace, never expected to resolve
        if not _resolves(rel, repo_root, files, docs_dir, build_dir):
            problems.append(f"cites nonexistent path '{cited}'")
    for name in cites["tests"]:
        exists = cited_test_exists(repo_root, name)
        if name in exempt:
            if exists:
                notes.append(f"stale exemption: '{name}' now resolves")
            continue
        if not exists:
            problems.append(f"cites nonexistent test '{name}'")
    for bare, leaf in extract_symbol_citations(text):
        if bare in exempt:
            continue
        rel = _relativize(bare, repo_root)
        if rel is None:
            continue
        if any(rel.startswith(p) for p in prefixes):
            continue  # reserved illustrative namespace, never expected to resolve
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
        return False, "; ".join(problems + notes)
    return True, "; ".join(["ok"] + notes)


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
    config = _load_config(args.config)
    files = tracked_files(repo_root) if repo_root else set()
    arch = archive_dirs(config, repo_root) if repo_root else []
    results, any_block_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, repo_root, files, config)
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
