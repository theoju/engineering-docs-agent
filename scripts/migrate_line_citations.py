"""One-time migration: rewrite `path:line` code citations to `path:symbol`
(or bare `path`). CCE-122. Idempotent, fence-aware.

- .py + line inside a def/class    -> path:symbol (path:Class.method for methods)
- .py + line on a module assignment -> path:NAME
- .py + line elsewhere (imports, blank) -> bare path
- non-.py or unresolvable file      -> bare path
- bare filename, unique in tracked  -> resolved dir-qualified path (+ symbol)

Verify migrated pages with scripts/lint/citation_exists.check_path (the real
consumer), never test -f.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINE_PIN_RE = re.compile(r"^([\w.\-/]+\.\w{1,8}):(\d+)(?:-\d+)?$")


def _tracked_files(repo_root: Path) -> list[str]:
    r = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files"], capture_output=True, text=True
    )
    return r.stdout.splitlines() if r.returncode == 0 else []


def _resolve_path(cited: str, repo_root: Path, tracked: list[str]) -> str | None:
    """Repo-relative path for a cited token. Bare filenames resolve against
    tracked files only when the basename is unique; ambiguous -> None."""
    if "/" in cited:
        return cited if (repo_root / cited).exists() else None
    matches = [f for f in tracked if Path(f).name == cited]
    return matches[0] if len(matches) == 1 else None


def _enclosing_symbol(source: str, lineno: int) -> str | None:
    """Dotted name of the innermost def/class containing `lineno`, or the name
    of a module-level assignment on that exact line, else None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    best: tuple[int, str] | None = None  # (span_size, dotted_name), smallest span wins

    def visit(node: ast.AST, prefix: list[str]) -> None:
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = child.lineno
                end = getattr(child, "end_lineno", start)
                name_path = prefix + [child.name]
                if start <= lineno <= end:
                    span = end - start
                    if best is None or span < best[0]:
                        best = (span, ".".join(name_path))
                    visit(child, name_path)
            else:
                visit(child, prefix)

    visit(tree, [])
    if best is not None:
        return best[1]

    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and stmt.lineno == lineno:
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    return tgt.id
        if isinstance(stmt, ast.AnnAssign) and stmt.lineno == lineno:
            if isinstance(stmt.target, ast.Name):
                return stmt.target.id
    return None


def _rewrite_token(token: str, repo_root: Path, tracked: list[str]) -> str | None:
    """New spelling for a `path:line` token, or None if it is not one."""
    m = _LINE_PIN_RE.match(token)
    if not m:
        return None
    cited, line_s = m.group(1), m.group(2)
    rel = _resolve_path(cited, repo_root, tracked)
    if rel is None:
        return cited  # unresolvable: strip the :line from whatever path was written
    if rel.endswith(".py"):
        try:
            source = (repo_root / rel).read_text()
        except (UnicodeDecodeError, OSError):
            source = ""
        symbol = _enclosing_symbol(source, int(line_s)) if source else None
        if symbol:
            return f"{rel}:{symbol}"
    return rel  # non-.py or unresolvable symbol -> bare (resolved) path


def migrate_text(text: str, repo_root: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return (new_text, [(old_token, new_token), ...]). Fenced blocks skipped."""
    tracked = _tracked_files(repo_root)
    changes: list[tuple[str, str]] = []
    out_lines: list[str] = []
    in_fence = False
    fence = ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            out_lines.append(line)
            continue
        if in_fence:
            if stripped.startswith(fence):
                in_fence = False
            out_lines.append(line)
            continue

        def repl(match: re.Match) -> str:
            token = match.group(1).strip()
            new_token = _rewrite_token(token, repo_root, tracked)
            if new_token is None or new_token == token:
                return match.group(0)
            changes.append((token, new_token))
            return f"`{new_token}`"

        out_lines.append(_INLINE_CODE_RE.sub(repl, line))
    return "\n".join(out_lines), changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--docs-dir", type=Path, default=Path("docs/site-src"))
    parser.add_argument(
        "--apply", action="store_true", help="write changes (default dry-run)"
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    docs = (root / args.docs_dir) if not args.docs_dir.is_absolute() else args.docs_dir
    total = 0
    for md in sorted(docs.rglob("*.md")):
        original = md.read_text()
        new, changes = migrate_text(original, root)
        if changes:
            total += len(changes)
            rel = md.relative_to(root)
            for old, new_tok in changes:
                print(f"{rel}: `{old}` -> `{new_tok}`")
            if args.apply:
                md.write_text(new)
    print(
        f"\n{total} citation(s) {'rewritten' if args.apply else 'to rewrite (dry-run)'}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
