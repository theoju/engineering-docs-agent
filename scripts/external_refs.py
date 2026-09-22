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

# _REPO_PATH_RE and _is_placeholder are imported, not duplicated (whole-branch
# review Critical 1 and round-2 Minor 1): a hand-copied second definition can
# drift from the linter's without anyone noticing, and the whole point of the
# gate below is that it match what citation_exists itself would accept or
# exempt. Same precedent as _SUFFIX_RE.
from citation_exists import _REPO_PATH_RE, _SUFFIX_RE, _is_placeholder  # noqa: E402

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
        blob_template = str(entry.get("blob_template") or DEFAULT_BLOB_TEMPLATE)
        # Round-2 review Minor 3: fail at LOAD, not at render. `_blob_url`
        # fills exactly {url}/{ref}/{path} via `format_map` -- the only three
        # keys it ever supplies -- so an extra placeholder
        # ("{url}/{repo}/blob/{ref}/{path}") or a stray unmatched brace
        # ("...{path") raises KeyError/ValueError there, once PER PAGE, on
        # every run, for what is a one-time config typo. `resolve_config`
        # already validates everything else about this declaration at load;
        # formatting against dummy values here catches this the same way,
        # the same principle that justified the `url` schema pattern.
        try:
            blob_template.format_map({"url": "u", "ref": "r", "path": "p"})
        except (KeyError, ValueError) as e:
            raise ExternalRepoConfigError(
                f"{prefix}: blob_template is invalid: {e}"
            ) from e
        out[prefix] = {
            "url": url.strip() if has_url else None,
            "private": private,
            "ref": str(entry.get("ref") or DEFAULT_REF),
            "blob_template": blob_template,
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
        # any code span. Gate on the SAME predicate `citation_exists` uses --
        # NOT placeholder (round-2 Minor 1: `YYYY`/`...` etc. are
        # documentation placeholders the linter deliberately exempts; without
        # this half the gate rendered a live link to a file that is only a
        # dated-filename example, e.g. `eda/docs/YYYY-MM-DD-slug.md`) AND
        # matches `_REPO_PATH_RE` (imported above, same as `_is_placeholder`)
        # -- before doing anything else with the token. `_REPO_PATH_RE`'s
        # character class ([\w.\-/] plus the `.ext` and `:suffix` grammar)
        # admits none of `)`, `<`, `>`, or whitespace, so anything that
        # passes THIS half of the gate is inert to interpolate as markup.
        #
        # Round-2 review Important: `_REPO_PATH_RE` also admits `.` and `/`,
        # so it does not by itself reject a `..` path segment -- confirmed by
        # running it:
        #   `eda/../../../../evil-org/evil-repo.md` rendered to
        #   `[eda/../../../../evil-org/evil-repo.md]
        #    (https://github.com/o/eda/blob/main/../../../../evil-org/evil-repo.md)`,
        #   and every browser applies RFC 3986 dot-segment removal before the
        #   request:
        #   urljoin('https://github.com/o/eda/blob/main/',
        #           '../../../../evil-org/evil-repo.md')
        #     -> 'https://github.com/evil-org/evil-repo.md'
        # -- a published link, under ordinary-looking filename text, that
        # points at an arbitrary repository on the configured forge. Origin
        # is bounded by the operator-configured `url`, so this is a
        # link-retargeting primitive, not XSS -- but it falsifies "anything
        # that passes the grammar gate is safe to interpolate as a URL", so
        # it is rejected explicitly rather than folded into the grammar: no
        # legitimate citation of a real path in an external repo ever needs
        # a `..` segment (page-author is asked to cite `prefix/path IN that
        # repo`, never a path relative to somewhere else), so this can never
        # reject a token the pipeline legitimately produces.
        # What a REJECTED token's safety actually rests on (round-2 review
        # Minor 2a correction -- an earlier version of this comment claimed
        # it "still reaches citation_exists exactly as an ordinary
        # undeclared-prefix citation would," which is false for every one of
        # these three arms: `citation_exists`'s own citable-path predicate is
        # `not _is_placeholder(token) and _REPO_PATH_RE.match(token)`, a
        # strict subset of what this gate accepts, so nothing this gate
        # rejects for being a placeholder or bad grammar was ever going to be
        # recognized as a citation downstream either -- and even the `..`
        # arm, which DOES match citation_exists's grammar, hits CCE-171's
        # `_relativize` escape guard and is silently skipped (`rel is None`
        # -> `continue`), not blocked. Measured directly:
        # `check_path` on the untouched traversal token above returns
        # `(True, 'ok')`. The actual safety for every rejected token is that
        # the page text never changes: it stays inside its original backtick
        # code span, which markdown escapes and never lets become a link.
        if (
            _is_placeholder(token)
            or not _REPO_PATH_RE.match(token)
            or ".." in token.split("/")
        ):
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
