"""CCE-181: render citations that point into a declared EXTERNAL repository.

`citation_exists` is a Tier-1 block rule and correctly fails a backticked path
that does not exist in the host checkout. That is right for a confabulation and
wrong for an artifact which is real but lives in another repo -- a token that is
simultaneously true and uncitable. Post-CCE-140 such a page is not merely
blocked: the deferral skip abandons the PR and the page is silently never
written.

The escape is opt-in PER TOKEN. Only a token whose first segment is a declared
external repo is rewritten. Absence-of-resolution is deliberately NOT the
trigger: its entry condition is exactly the confabulation population the linter
exists to block, which would turn every BLOCK into a silent PASS (the CCE-141
class).

Pure and stdlib-only. No file I/O -- the orchestrator owns reading and writing.

Spec: docs/superpowers/specs/2026-09-21-cce181-cross-repo-citations-design.md
"""

from __future__ import annotations

import re
import sys
import urllib.parse
from pathlib import Path

# Same pattern as scripts/citation_repair.py: append (never insert) the lint
# dir, then import bare. Inserting the scripts dir poisons namespace resolution
# for the rest of the session (CCE-122).
_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

# _REPO_PATH_RE is imported, not duplicated (round-N review Critical 1): a
# hand-copied second definition can drift from the linter's without anyone
# noticing, and the whole point of the gate below is that it match what
# citation_exists itself would accept. Same precedent as _SUFFIX_RE.
from citation_exists import _REPO_PATH_RE, _SUFFIX_RE  # noqa: E402

DEFAULT_REF = "main"
DEFAULT_BLOB_TEMPLATE = "{url}/blob/{ref}/{path}"

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


class ExternalRepoConfigError(ValueError):
    """A lint.external_repos declaration is ambiguous or unsafe."""


def resolve_config(
    config: dict, *, host_dirs: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Normalize lint.external_repos, raising on any invalid declaration."""
    lint = config.get("lint") or {}
    raw = lint.get("external_repos") or {}
    if not isinstance(raw, dict):
        raise ExternalRepoConfigError("lint.external_repos must be a mapping")

    out: dict[str, dict] = {}
    for prefix, entry in raw.items():
        if not isinstance(entry, dict):
            raise ExternalRepoConfigError(f"{prefix}: entry must be a mapping")
        if "/" in prefix:
            raise ExternalRepoConfigError(f"{prefix}: prefix must be a single segment")
        if prefix in host_dirs:
            raise ExternalRepoConfigError(
                f"{prefix}: collides with a real directory in this repo"
            )
        url = entry.get("url")
        has_url = isinstance(url, str) and bool(url.strip())
        private = bool(entry.get("private"))
        if has_url and private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares both a url and private; pick exactly one"
            )
        if not has_url and not private:
            raise ExternalRepoConfigError(
                f"{prefix}: declares neither a url nor private; pick exactly one"
            )
        out[prefix] = {
            "url": url.strip() if has_url else None,
            "private": private,
            "ref": str(entry.get("ref") or DEFAULT_REF),
            "blob_template": str(entry.get("blob_template") or DEFAULT_BLOB_TEMPLATE),
        }
    return out


def _blob_url(entry: dict, path_in_repo: str) -> str:
    """Fill the blob template in one pass (whole-branch review Minor).

    Chained `.replace()` calls substitute into their OWN prior output: a
    `{path}` embedded in the configured `url` (`"https://h/{path}"`) got
    substituted a second time when the `{path}` replacement ran last,
    producing `https://h/a.md/blob/main/a.md` instead of the intended
    literal. `str.format_map` substitutes every placeholder against the
    ORIGINAL template in one pass, so a value that happens to contain
    another placeholder's spelling is never re-scanned.
    """
    return entry["blob_template"].format_map(
        {"url": entry["url"], "ref": entry["ref"], "path": path_in_repo}
    )


def render_external_refs(text: str, repos: dict[str, dict]) -> str:
    """Rewrite declared-prefix tokens to links (public) or names (private).

    Deterministic substitution on an explicitly declared string. No inference,
    no suffix matching, no corroboration -- that distinction is what separates
    this from the CCE-141 class. It runs BEFORE the linter, never on a page the
    linter has already blocked.
    """
    if not repos:
        return text

    def _one(match):
        token = match.group(1).strip()
        # Review Critical 1: `_INLINE_CODE_RE` matches ANY character but a
        # backtick, so an LLM-authored token can carry an unbalanced `)`, raw
        # HTML, or a stray space -- interpolated unvalidated into
        # ``[`text`](url)`` that is confirmed, by running it, to break out of
        # the CommonMark link destination and re-emit as live HTML outside
        # any code span. Gate on the SAME grammar `citation_exists` uses
        # (`_REPO_PATH_RE`, imported above) before doing anything else with
        # the token. A non-matching token is returned UNTOUCHED -- it keeps
        # its `/`, so it still reaches `citation_exists` exactly as an
        # ordinary undeclared-prefix citation would. Fail closed, same
        # posture as the rest of this feature. `_REPO_PATH_RE`'s character
        # class ([\w.\-/] plus the `.ext` and `:suffix` grammar) admits none
        # of `)`, `<`, `>`, or whitespace, so anything that passes this gate
        # is inert to interpolate as-is.
        if not _REPO_PATH_RE.match(token):
            return match.group(0)
        head, sep, rest = token.partition("/")
        if not sep or not rest:
            return match.group(0)
        entry = repos.get(head)
        if entry is None:
            return match.group(0)
        basename = rest.split("/")[-1]
        if entry["private"]:
            return "`" + basename + "`"
        # The :line/:symbol suffix is CITATION grammar, not a path on disk.
        # Left in the URL it 404s while PASSING the linter -- a silent dead
        # link. Keep it in the visible text, where it is slash-free and inert.
        url_path = _SUFFIX_RE.sub("", rest)
        # Defence in depth (review Critical 1): the grammar gate above already
        # restricts every character that reaches here, but quoting the URL
        # path is one line and costs nothing.
        quoted_path = urllib.parse.quote(url_path, safe="/")
        return "[`" + basename + "`](" + _blob_url(entry, quoted_path) + ")"

    # NOT IN SCOPE / known divergence (whole-branch review, parked): on an
    # UNTERMINATED fence, this loop treats every line to EOF as still fenced
    # (never rewritten, `in_fence` stays True) -- but citation_exists's own
    # `strip_fenced_blocks` deliberately fails CLOSED on the same input
    # (CCE-131): it does NOT cut the unterminated region back out, so those
    # lines are scanned as ordinary prose. A declared-prefix token inside an
    # unterminated fence is therefore left as its raw, un-rewritten
    # `prefix/path` form here, while the linter treats that same location as
    # prose and blocks it as an ordinary nonexistent-path citation. The
    # disagreement is SAFE in only one direction -- the token survives
    # unrendered, so the linter still sees and blocks it -- and changing
    # either side's fence handling to agree is deliberately out of scope
    # here; see the whole-branch review for the ruling.
    out: list[str] = []
    in_fence = False
    fence = ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence, fence = True, stripped[:3]
            out.append(line)
            continue
        if in_fence and stripped.startswith(fence):
            in_fence = False
            out.append(line)
            continue
        out.append(line if in_fence else _INLINE_CODE_RE.sub(_one, line))
    return "\n".join(out)
