"""Lint rule: internal_links. Verifies internal Markdown links resolve.

Scope notes:
- Code is stripped before links are matched — fenced blocks AND inline code
  spans. A link shown inside code is an ILLUSTRATION, not navigation, and a
  page documenting anything link-shaped cannot be written without one.
  `citation_exists` has stripped fences since CCE-110 on the same reasoning
  ("fenced examples are legitimately hypothetical"); this rule did not, until
  a page documenting a markdown-link parser was blocked twice on the example
  links quoted out of its own source material (2026-08-21, host runs
  32460602658 / 32495019606: `docs/runbook.md`, then `docs/foo.md`).
  `strip_fenced_blocks` is IMPORTED from `citation_exists`, not reimplemented —
  it is a documented shared-helper contract, and it carries the CCE-131
  unterminated-fence fail-closed behaviour that a local copy would lose.
- Inline spans are stripped here rather than in the shared helper because
  `citation_exists` needs them: its citations ARE inline code spans. The two
  rules read the same document through deliberately different filters.
- KNOWN LIMIT: indented (4-space) code blocks are NOT stripped. They are
  ambiguous with list continuation, and telling them apart needs a real
  markdown parser; stripping them heuristically would risk silently skipping
  genuine broken links. An example link in an indented block therefore still
  blocks — loudly and visibly, which is the safe direction to fail.
"""

from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from typing import Any
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from citation_exists import strip_fenced_blocks  # noqa: E402

RULE_NAME = "internal_links"
SEVERITY = "block"
LINK_RE = re.compile(r"\[(?:[^\]]+)\]\(([^)#?\s]+)(?:#[^)]*)?\)")
# A code span is a RUN of backticks closed by an equal run — the spec form
# `` `[x](docs/foo.md)` `` needs the run, not a single tick, or the outer
# delimiters are missed and the link leaks straight back to LINK_RE. An
# unmatched run simply does not match, leaving the text in place: unbalanced
# backticks fail closed (still linted) rather than blanking the rest of a file.
CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)[\s\S]*?(?P=ticks)")


def strip_code(text: str) -> str:
    """Drop fenced blocks and inline code spans, leaving prose links only."""
    return CODE_SPAN_RE.sub(" ", strip_fenced_blocks(text))


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text()) or {}


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "tel:"))


def check_path(path: Path, config: dict[str, Any]) -> tuple[bool, str]:
    if not path.exists():
        return False, "file not found"
    broken = []
    for m in LINK_RE.finditer(strip_code(path.read_text())):
        target = m.group(1)
        if is_external(target):
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            broken.append(target)
    if broken:
        return False, f"broken internal link(s): {', '.join(broken)}"
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    results, any_failed = [], False
    for p in args.paths:
        ok, message = check_path(p, config)
        results.append({"path": str(p), "ok": ok, "message": message})
        if not ok:
            any_failed = True
    if args.json:
        json.dump(
            {"rule": RULE_NAME, "severity": SEVERITY, "results": results}, sys.stdout
        )
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
