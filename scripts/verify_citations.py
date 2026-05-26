"""Verified file:line citations (capability C1).

A citation is an inline code span `path:line` immediately followed (whitespace
allowed) by an HTML-comment pin `<!--pin:TOKEN-->`. TOKEN is a short literal
expected on that line. The verifier resolves each citation against the cited
source file: token-at-line -> ok; token uniquely elsewhere -> relocated
(auto-fixable); token at multiple lines -> ambiguous; token gone / file
missing -> gone. Pure stdlib; never raises on bad input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# `path:line` code span, then optional whitespace, then <!--pin:TOKEN-->.
# path: anything but backtick/newline (non-greedy); line: trailing digits.
_CITATION_RE = re.compile(
    r"`(?P<path>[^`\n]+?):(?P<line>\d+)`\s*<!--\s*pin:\s*(?P<token>.*?)\s*-->"
)


def _iter_citations(text: str):
    """Yield (match, {path, line(int), token}) for every citation+pin pair in
    `text`. The match carries the span offsets so a caller can rewrite a single
    citation in place without disturbing identical text elsewhere on the page.
    Citations whose pin token is empty are skipped (a pin with no token can't
    be verified). Never raises.
    """
    for m in _CITATION_RE.finditer(text):
        token = m.group("token").strip()
        if not token:
            continue
        yield (
            m,
            {
                "path": m.group("path"),
                "line": int(m.group("line")),
                "token": token,
            },
        )


def _parse_page_citations(text: str) -> list[dict]:
    """Return [{path, line(int), token}] for every citation+pin pair in `text`.
    Citations whose pin token is empty are skipped (a pin with no token can't
    be verified). Never raises.
    """
    return [cit for _m, cit in _iter_citations(text)]


def _classify_citation(repo_root: Path, cit: dict) -> dict:
    """Classify one citation against its source file. Returns a dict with
    "status" in {"ok", "relocated", "ambiguous", "gone"}; "relocated" adds
    "new_line"; "ambiguous" adds "lines". Never raises.
    """
    try:
        lines = (
            (repo_root / cit["path"])
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )
    except OSError:
        return {"status": "gone"}
    token = cit["token"]
    line_no = cit["line"]
    if 1 <= line_no <= len(lines) and token in lines[line_no - 1]:
        return {"status": "ok"}
    hits = [i + 1 for i, ln in enumerate(lines) if token in ln]
    if len(hits) == 1:
        return {"status": "relocated", "new_line": hits[0]}
    if len(hits) > 1:
        return {"status": "ambiguous", "lines": hits}
    return {"status": "gone"}


def _empty_ledger() -> dict:
    return {
        "checked": 0,
        "ok": 0,
        "relocated": [],
        "ambiguous": [],
        "gone": [],
        "pages_review_needed": [],
    }


def verify_citations(
    docs_dir: Path,
    repo_root: Path,
    *,
    fix: bool = False,
    pages: set[str] | None = None,
) -> dict:
    """Scan every page under docs_dir for citations, classify each against
    its source file, and return a ledger. When fix=True, rewrite relocated
    citations in place (line number updated). When pages is given, only those
    page paths (POSIX, relative to docs_dir) are checked. Never raises.
    """
    ledger = _empty_ledger()
    if not docs_dir.is_dir():
        return ledger
    review: set[str] = set()
    for md in sorted(docs_dir.rglob("*.md")):
        page = md.relative_to(docs_dir).as_posix()
        if pages is not None and page not in pages:
            continue
        try:
            text = md.read_text()
        except OSError:
            continue
        # Rebuild the page from verbatim segments, splicing each relocated
        # citation only at its own match offsets. A page-global str.replace
        # would corrupt look-alikes: a second same-path citation whose line
        # equals this one's new line, or a bare `path:line` prose reference.
        pieces: list[str] = []
        last = 0
        for m, cit in _iter_citations(text):
            ledger["checked"] += 1
            res = _classify_citation(repo_root, cit)
            status = res["status"]
            if status == "ok":
                ledger["ok"] += 1
            elif status == "relocated":
                ledger["relocated"].append(
                    {
                        "page": page,
                        "path": cit["path"],
                        "old": cit["line"],
                        "new": res["new_line"],
                    }
                )
                if fix:
                    old_span = f"`{cit['path']}:{cit['line']}`"
                    new_span = f"`{cit['path']}:{res['new_line']}`"
                    # m.group(0) is `path:line`<ws><!--pin:...-->; the code span
                    # is at offset 0, so replace exactly that one occurrence.
                    pieces.append(text[last : m.start()])
                    pieces.append(m.group(0).replace(old_span, new_span, 1))
                    last = m.end()
            elif status == "ambiguous":
                ledger["ambiguous"].append(
                    {
                        "page": page,
                        "path": cit["path"],
                        "token": cit["token"],
                        "lines": res["lines"],
                    }
                )
                review.add(page)
            else:  # gone
                ledger["gone"].append(
                    {
                        "page": page,
                        "path": cit["path"],
                        "token": cit["token"],
                        "line": cit["line"],
                    }
                )
                review.add(page)
        if fix and pieces:
            pieces.append(text[last:])
            md.write_text("".join(pieces))
    ledger["pages_review_needed"] = sorted(review)
    return ledger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify file:line citations.")
    ap.add_argument("--docs-dir", type=Path, required=True)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--fix", action="store_true", help="rewrite relocated citations")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any gone/ambiguous citations remain",
    )
    ap.add_argument(
        "--json", action="store_true", help="emit the full JSON ledger to stdout"
    )
    args = ap.parse_args(argv)
    ledger = verify_citations(args.docs_dir, args.repo_root, fix=args.fix)
    if args.json:
        print(json.dumps(ledger, indent=2))
    else:
        print(
            f"checked={ledger['checked']} ok={ledger['ok']} "
            f"relocated={len(ledger['relocated'])} "
            f"ambiguous={len(ledger['ambiguous'])} gone={len(ledger['gone'])}"
        )
    if args.strict and (ledger["gone"] or ledger["ambiguous"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
