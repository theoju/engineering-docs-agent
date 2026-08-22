"""Deterministic repair of shortened citation paths (CCE-141).

`page-author` sometimes emits a citation as a bare relative path — the
committed page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites and
the rewrite shortened it to `references/checklist.md`. `citation_exists`
correctly finds nothing at the repo root and blocks the page; post-CCE-140 the
deferral skip then abandons the PR, so the page is silently never written.

This module repairs the observable defect regardless of what causes it. The
safety claim is set-invariance, NOT correctness: repair never introduces a
reference to a file the pipeline had not already accepted a reference to. The
set of files the finished page points at is invariant under repair; only the
spelling of an existing pointer changes.

Uniqueness alone does not deliver that. A unique suffix match establishes only
that the candidate exists — never that the cited token was a shortening of it —
and "does not resolve" is exactly the confabulation population citation_exists
exists to block. Corroboration is therefore the ENTRY CONDITION: the candidate
must already be vouched for by a source the authoring agent did not write.
Ambiguity, zero-match and uncorroborated all leave the page untouched and
blocking.

Set-invariance also requires that the repaired citation stay UNDER THE LINT.
A rewrite that lands the citation somewhere `citation_exists` does not verify
turns a blocked page into a permanently `ok` one, and the pointer stops being
checked even after the file it names is deleted. So a candidate is admitted
only if the linter would both SEE it and verify it BY EXISTENCE once written —
a positive gate, asked of the linter itself, so a class nobody anticipated
declines. See `_candidate_rejection`.

Spec: docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path, PurePosixPath

_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

# Imported, never reimplemented: citation_exists declares these a shared-helper
# contract. Repair must agree with check_path on what a citation IS and what
# resolves, or the two drift and repair starts "fixing" tokens the linter
# deliberately skips.
from citation_exists import (  # noqa: E402
    _INLINE_CODE_RE,
    _SUFFIX_RE,
    _build_dir,
    _docs_dir,
    _is_gitignored,
    _relativize,
    _resolves,
    check_path,
    example_prefixes,
    exempt_tokens,
    extract_citations,
    source_roots,
    strip_fenced_blocks,
    tracked_files,
)

__all__ = [
    "suffix_candidates",
    "rewrite_token",
    "repair_text",
    "tracked_files",
    "build_corroborators",
]


_GLOB_CHARS = ("*", "?", "[", "{")


def build_corroborators(
    prior_text: str | None, source_paths: set[str], files: set[str]
) -> set[str]:
    """Tracked paths corroborated by a source the authoring agent did not write.

    Rung 1 (edits, git-authoritative): the LINTER'S OWN VIEW of the prior
    committed page — `extract_citations(prior_text)["paths"]` intersected with
    the tracked set. Only a path `citation_exists` actually VALIDATED on that
    page evidences that the pipeline accepted a reference to that file.

    Deliberately NOT a raw substring scan of the prior text. A raw scan sees
    more path tokens than extract_citations does, and that surplus is exactly
    what disqualifies it: those tokens are invisible to extract_citations
    BECAUSE citation_exists never validates them — inside fenced blocks
    ("fenced examples are legitimately hypothetical", its own docstring),
    inside URL bodies, inside HTML comments, and as substrings of longer
    paths. A token the linter never checked evidences nothing about
    acceptance. Concretely: a prior page naming a path only inside a ```text
    fence would corroborate a new page's invented citation of the same tail,
    turning a block into a pass — the defect this module exists to prevent.
    Calling extract_citations also inherits the linter's fence semantics for
    free, satisfying import-never-reimplement rather than straining it.

    Rung 2 (every authoring): the batch's source set — `grounding =
    _pr_changed_files(batch_prs)` (orchestrator_runner.py:2372), handed here as
    `source_paths` (orchestrator_runner.py:1608). Glob entries are excluded:
    expanding them would make the gate ceremony.

    NOT "orchestrator-authoritative", which is what this docstring claimed
    until 2026-08-21. `batch_prs` traces to
    `dispatch_validated("source-collector", …)`
    (orchestrator_runner.py:2048-2050), and source-collector is itself an LLM
    subagent (`agents/source-collector.md`, `model: sonnet`). Its schema types
    `files` as a bare `{"type": "array"}` with no item shape
    (agents/schemas/source_collector.schema.json:22), and nothing under
    scripts/ checks `pr["files"]` against git: the one orchestrator-side git
    safety net, `_clip_prs_to_window`, validates `merge_sha` and never reads
    `files`, and `GhClient.pr_view_files` is called only from
    verify_runner.py:40, off this path. Rung 2's provenance is therefore A
    DIFFERENT AGENT, not the orchestrator.

    The doctrine still holds LITERALLY: source-collector is not the AUTHORING
    agent, so a page-author that confabulates a citation cannot also mint its
    own corroborator. The residual is that a confabulating source-collector
    can — an invented entry in `files[]` becomes a corroborator. What bounds it
    is that a corroborator must be a TRACKED file, and that bound IS enforced
    in code, twice: `p in files` below, and `suffix_candidates` iterating
    `files`, where `files` is `git ls-files` (`citation_exists.tracked_files`,
    called at orchestrator_runner.py:1607). So an injected path can only
    repoint a citation at some OTHER file that really is in the repo; it can
    never introduce an untracked or nonexistent one. Concretely it widens
    rung 2 from a batch's true 5–15 files to any of this host's 887 tracked
    files — a widening of the surface, not a hole in the invariant.

    `_enforce_agent_frontmatter` is deliberately NOT cited as the reason this
    works; the claim that it was has been removed. It runs only when
    `agent_fields is not None` (orchestrator_runner.py:2454), which requires
    `action == "create"` AND `section_generator_for(rel, config) ==
    "agent-authored"` (orchestrator_runner.py:2384-2386) — and the reference
    host's config declares no `site:` block at all, so `section_generator_for`
    returns None there and that call never runs. Corroboration on a create
    comes from `source_paths` being passed to this function directly, never
    from reading a page's frontmatter back.

    evidence.files_read is deliberately NOT a source — an author that
    confabulates a citation can equally confabulate a files_read entry.
    """
    out = {
        p for p in source_paths if p in files and not any(c in p for c in _GLOB_CHARS)
    }
    if prior_text:
        out |= set(extract_citations(prior_text)["paths"]) & files
    return out


def _excluded_reason(
    token: str,
    rel: str,
    repo_root: Path,
    exempt: set[str],
    prefixes: tuple[str, ...],
) -> str | None:
    """Which class `citation_exists.check_path` declines to CHECK this path as.

    The skips that live in check_path's OWN paths loop — an exempt token, a
    reserved `example/` prefix, a gitignored path. Distinct from the skips
    inside `_resolves`, which `_candidate_rejection` PROBES for rather than
    enumerating. Every class here is unresolvable BY DESIGN, so a path in one
    of them evidences nothing and must never be written into a page.

    Applied to BOTH ends of a repair: directly to the cited token, and through
    `_candidate_rejection` to the candidate. Named rather than probed because
    these three live in the branch structure of check_path rather than in a
    resolution result, and naming them is what gives the digest one reason per
    class. `_candidate_rejection`'s final probe is what stops an UNNAMED class
    from failing open.

    `_resolves` is deliberately not one of these classes. On the cited side it
    is the entry condition (a token that resolves needs no repair); on the
    candidate side the question is not "does it resolve" — a tracked candidate
    always does — but "does it resolve BECAUSE IT EXISTS", which
    `_resolves_absent` asks. Callers apply both themselves.

    Ordering: on the cited side this runs AFTER `_resolves`, so the
    `_is_gitignored` subprocess is only paid for paths that do not resolve.
    """
    if token in exempt:
        return "exempt_token"
    if any(rel.startswith(p) for p in prefixes):
        return "example_namespace"
    if _is_gitignored(repo_root, rel):
        return "gitignored"
    return None


_ABSENT_TWIN_STEM = "__citation_repair_absent_twin__"


def _extractor_sees(candidate: str) -> bool:
    r"""True when the LINTER'S OWN extractor returns `candidate` from the inline
    code span `rewrite_token` would write for it.

    Round-tripping instead of re-deriving is the whole point: this inherits
    `_INLINE_CODE_RE`, `_REPO_PATH_RE`, `_is_placeholder` and any future
    extractor change for free. Re-deriving those rules here would be the
    blacklist mistake in miniature, and the first of them has already been
    made: `_REPO_PATH_RE` admits only `[\w.\-/]`, so a tracked candidate containing a
    space, `(`, `)`, `@`, `+`, `~`, `,` or `&` gets written into the page and
    is then not SEEN by extract_citations at all: the page flips from BLOCK to
    `ok`, and stays `ok` after the file it names is deleted.
    `app/(marketing)/guides/setup.md` is that shape, and so are the reference
    host's own `app/dimensions/[id]/page.tsx` and `app/tips/[n]/page.tsx`.

    Probing the BARE candidate is equivalent to probing the span actually
    written for a `path:line` or `path:symbol` citation. The suffix on the
    cited token already matched `_REPO_PATH_RE`'s optional group and already
    passed `_is_placeholder`, or extract_citations would not have produced the
    cited token in the first place; joining two marker-free strings with `:`
    introduces no marker; and extract_citations strips the suffix before
    returning either way.
    """
    return candidate in extract_citations(f"`{candidate}`")["paths"]


def _resolves_absent(
    rel: str, files: set[str], docs_dir: str, build_dir: str, roots: tuple[str, ...]
) -> bool:
    """Would `_resolves` still say yes if the file `rel` names did not exist?

    Asked by running the linter's own `_resolves` against a world where the
    file is gone: an EMPTY repo root, so every on-disk probe misses, and the
    tracked set minus `rel`. The path STRING is untouched, so every arm keyed
    on it — a prefix, an extension, the whole string — is evaluated exactly as
    it would be for the real candidate.

    True means the candidate's location resolves UNCONDITIONALLY, so repair
    would park the citation where existence is never tested. Three of the four
    arms of `_resolves` test existence today — of `rel` itself, or of `rel`
    rebased under docs_dir or under a declared source root — and one, the
    mkdocs `build_dir` prefix, returns True with no existence test whatsoever.
    That arm is structurally identical to the `example/` namespace and is what
    this probe catches. It catches the NEXT such arm too, without this module
    being told about it.

    A candidate that resolves only because a DIFFERENT real file sits at the
    docs_dir- or root-rebased location also reads True here and is declined.
    That decline is conservative rather than exact — the verification would not
    be attributable to the candidate — and it leaves the page blocking, which
    is the safe direction.
    """
    with tempfile.TemporaryDirectory() as empty:
        return _resolves(rel, Path(empty), files - {rel}, docs_dir, build_dir, roots)


def _linter_reports_an_absent_file(
    rel: str, repo_root: Path, files: set[str], config: dict
) -> bool:
    """Would `citation_exists` BLOCK a page citing a file that does NOT exist,
    in this candidate's directory and with its extension?

    The catch-all, and the reason a class nobody anticipated fails CLOSED.
    Every other check answers a question this module thought to ask; this one
    asks `check_path` itself, so a skip nobody here has heard of still answers.

    A TWIN path, not the candidate: the candidate exists, so asking about it
    directly could only ever return `ok`. The twin differs in the filename STEM
    alone — same directory, same extension — and is asked against the REAL repo
    root, so mkdocs.yml, .gitignore and git are the host's own. Reconstructing
    an absent WORLD instead (a scratch root plus copies of whichever files
    check_path happens to read) was rejected for failing open: the first file
    the copy list had not been told about would go missing, missing files
    produce MORE blocking, and more blocking is what this gate reads as
    "verified".

    Residual, accepted: a skip keyed on the exact filename stem evades the
    twin. Those are the enumerable kind — `lint.citation_exempt_tokens` is one
    — and they are named above it. In the other direction the twin can decline
    a candidate the linter would really verify: a `.gitignore` that ignores the
    directory and re-admits this one file by negation. That is a false decline,
    and a false decline leaves the page blocking, which is where it already was.
    """
    p = PurePosixPath(rel)
    twin = str(p.with_name(_ABSENT_TWIN_STEM + p.suffix))
    with tempfile.TemporaryDirectory() as scratch:
        probe = Path(scratch) / "absence_probe.md"
        probe.write_text(f"`{twin}`\n")
        ok, _detail = check_path(probe, repo_root, files, config)
    # The probe page carries that one citation and nothing else, so `not ok`
    # can only mean check_path reported it as a nonexistent path.
    return not ok


def _candidate_rejection(
    candidate: str, repo_root: Path, config: dict, files: set[str]
) -> str | None:
    """Why writing `candidate` into the page would not be verifiable, or None.

    THE GATE, and it is positive: a candidate is acceptable only if, once
    written into the page, `citation_exists` would both SEE it and verify it BY
    EXISTENCE — so that if the file it names ever goes away, the page blocks
    again. Anything else declines.

    This replaced a BLACKLIST of the classes check_path declines to check. A
    blacklist can only ever enumerate what someone thought of, and it missed a
    row twice with the same consequence both times: repair moved the citation
    into a region the linter does not verify, the page flipped from BLOCK to
    `ok`, and it was never checked again — `git rm` the target and check_path
    still answers `ok`. The two missed rows were a candidate the linter cannot
    PARSE (`app/(marketing)/guides/setup.md`) and a candidate under the mkdocs
    build dir, which `_resolves` returns True for with no existence test at
    all. Adding two more rows would have been the third and fourth attempt at
    the same enumeration.

    Checks run most specific first, and every one can only DECLINE:

    | reason                         | cause                                    |
    | ------------------------------ | ---------------------------------------- |
    | candidate_outside_repo         | `_relativize`: not a repo-relative path  |
    | candidate_exempt_token         | check_path's own skips — named, not      |
    | candidate_example_namespace    | probed, because they live in its branch  |
    | candidate_gitignored           | structure and each earns a digest reason |
    | candidate_unextractable        | the linter's extractor does not see it   |
    | candidate_unresolvable         | it does not resolve at all               |
    | candidate_unverified_namespace | resolves without its existence being     |
    |                                | tested (the build-dir arm, today)        |
    | candidate_unverified           | check_path would not report an absent    |
    |                                | file here; cause unknown, decline anyway |

    The last row is the fail-closed one: the six above it answer questions this
    module thought to ask, and it asks the linter. The four reasons that
    predate this gate are unchanged, so operator greps of the digest keep
    working.

    `candidate_unresolvable` is unreachable for a candidate that came from
    `suffix_candidates(rel, files)` — it is in `files`, so `_resolves` says
    yes. It is here because `files` is a PARAMETER of repair_text rather than
    git's output, and the positive form of this gate is "it resolves AND its
    resolution depends on its existence". Asserting only the second half would
    admit a path that resolves neither way.

    Config-derived values are re-derived here rather than threaded from
    repair_text. Each is pure or lru_cached, this runs only for the unique
    candidate of a citation that already failed to resolve, and a
    nine-parameter signature is an invitation to pass one mismatched piece.
    """
    rel = _relativize(candidate, repo_root)
    if rel is None:
        return "candidate_outside_repo"

    why = _excluded_reason(
        candidate, rel, repo_root, exempt_tokens(config), example_prefixes(config)
    )
    if why is not None:
        return f"candidate_{why}"

    if not _extractor_sees(candidate):
        return "candidate_unextractable"

    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    roots = source_roots(config)
    if not _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
        return "candidate_unresolvable"
    if _resolves_absent(rel, files, docs_dir, build_dir, roots):
        return "candidate_unverified_namespace"

    if not _linter_reports_an_absent_file(rel, repo_root, files, config):
        return "candidate_unverified"
    return None


def suffix_candidates(cited: str, files: set[str]) -> list[str]:
    """Tracked paths of which `cited` is a strict segment-boundary suffix.

    Segment boundaries are required, not substring matching:
    `references/checklist.md` matches
    `.claude/skills/connector-builder/references/checklist.md`, but
    `erences/checklist.md` matches nothing.

    `len(parts) > n` is what makes the shortening STRICT — it excludes the
    exact-match case, which is never a repair candidate because such a token
    already resolved.
    """
    segments = cited.split("/")
    n = len(segments)
    out = []
    for f in files:
        parts = f.split("/")
        if len(parts) > n and parts[-n:] == segments:
            out.append(f)
    return sorted(out)


# Index marker: a fixed-width binary code in LEADING WHITESPACE, tab=1 space=0.
_MARK_BITS = {" ": "0", "\t": "1"}


def _linter_dropped_lines(text: str) -> set[int]:
    r"""Indices of the lines `strip_fenced_blocks` REMOVES from `text`.

    Those are the lines the LINTER never reads, and therefore the only lines
    `rewrite_token` must leave alone. The invariant, asserted directly in the
    tests: repair rewrites a line IF AND ONLY IF the linter reads that line.

    Derived by RUNNING the linter's own function and reading back which source
    lines survived — not by re-deriving its bookkeeping. The mirror this
    replaces recorded only CLOSED fences, and was wrong in both directions on
    an unterminated one: strip_fenced_blocks DROPS the opener of a fence that
    never closes (it `continue`s past it before appending, so the
    `del out[fence_start:]` that would cut the body back out never runs, having
    nothing to cut), while the mirror reported nothing dropped there at all. A
    page opening ``~~~ see `refs/x.md``` is invisible to extract_citations and
    was still rewritten — a repair the page receives that the lint can never
    see, which is the report/apply divergence this module forbids, inverted.

    Reading the survivors back needs each line to be identifiable, and the tag
    that identifies it must not perturb the very function being measured. It is
    a fixed-width binary index code written in LEADING WHITESPACE — tab for 1,
    space for 0 — prepended to each line. strip_fenced_blocks computes
    `stripped = line.lstrip()` ONCE and every branch it takes reads only
    `stripped`, so leading whitespace is discarded before any decision is made:
    `(code + line).lstrip()` is `line.lstrip()`, character for character,
    whatever the line contains and whatever the fence rules become. Yet the
    function appends the ORIGINAL line to its output, so the code survives into
    the result and names the source index. A marker APPENDED to the line would
    read the same way today, but only because `fence` is `stripped[:3]`; the
    moment fence matching considered the whole opener — full info strings, say —
    an appended marker would silently stop two identical fences from matching.
    Neither tab nor space is a splitlines() boundary, so the code cannot forge
    a line break either.

    Two checks make the derivation self-verifying rather than merely
    well-argued, because a silent misalignment here reports repairs the page
    never received. Each survivor must decode to a well-formed index whose body
    is the source line, and the surviving BODIES, rejoined, must equal what
    strip_fenced_blocks returns for the UNMARKED text. The second is what
    catches a marker that has stopped being neutral: the two runs would keep
    different lines. Both raise rather than guess.

    Boundaries matter throughout because EIGHT characters survive
    Path.read_text()'s universal-newline translation yet ARE splitlines()
    boundaries — U+2028, U+2029, \x85, \x0b, \x0c, \x1c, \x1d, \x1e (\r is
    safe; read_text normalises it). Walking split("\n") instead would see a
    fence opener glued to the end of the preceding line and never open the
    fence, which is how the earlier mirror came to rewrite a deliberate fenced
    illustration. Line bodies come from text.splitlines() and so contain none
    of the eight, which is also why joining the marked lines with "\n" and
    letting strip_fenced_blocks re-split them round-trips exactly.

    Per-line rewriting stays equivalent to the linter's whole-document view
    because _INLINE_CODE_RE excludes newlines: no code span the linter sees can
    straddle a line. strip_fenced_blocks rejoins its survivors with "\n", so a
    span straddling one of the eight reads as containing a newline there too,
    and matches in neither place.

    Any future change to strip_fenced_blocks — a new fence syntax, a different
    unterminated policy — is inherited rather than re-implemented, so the two
    cannot drift apart again.
    """
    lines = text.splitlines()
    if not lines:
        return set()
    width = max(1, (len(lines) - 1).bit_length())
    marked = "\n".join(
        f"{i:0{width}b}".replace("0", " ").replace("1", "\t") + line
        for i, line in enumerate(lines)
    )
    kept: list[int] = []
    for survivor in strip_fenced_blocks(marked).splitlines():
        code = survivor[:width]
        if len(code) != width or not set(code) <= set(_MARK_BITS):
            raise RuntimeError(
                "strip_fenced_blocks no longer returns its input lines "
                f"verbatim: {survivor!r} carries no line marker"
            )
        i = int("".join(_MARK_BITS[c] for c in code), 2)
        if i >= len(lines) or survivor[width:] != lines[i]:
            raise RuntimeError(
                f"line marker {i} does not name its source line: "
                f"{survivor[width:]!r}"
            )
        kept.append(i)
    if "\n".join(lines[i] for i in kept) != strip_fenced_blocks(text):
        # The marked and unmarked runs kept DIFFERENT lines, so the marker has
        # stopped being neutral and the alignment is unknowable. Guessing it
        # would let repair_text report a rewrite the page never received, so
        # fail loudly instead — the same choice `_resolves` makes by refusing
        # to default its `roots` parameter.
        raise RuntimeError(
            "the line marker perturbs strip_fenced_blocks: the marked and "
            "unmarked runs of the same text keep different lines"
        )
    return set(range(len(lines))) - set(kept)


def rewrite_token(text: str, old: str, new: str) -> str:
    r"""Replace bare path `old` with `new` inside matching inline code spans.

    Matching is on the token's BARE path (suffix stripped) and on the STRIPPED
    token: extract_citations strips each span before matching, so
    `` ` refs/x.md ` `` IS a citation it reports, and an equality test that
    did not strip would leave that span alone while repair_text reported the
    repair — the page untouched, the digest claiming otherwise. The
    replacement happens inside the ORIGINAL token, so `path.py:Class.method`
    keeps its symbol and a padded span keeps its padding. Every other byte of
    the document is preserved — this must never reflow or normalise the
    author's prose.

    Lines come from splitlines(), which is what _linter_dropped_lines indexes
    and what strip_fenced_blocks iterates. They are rejoined by concatenating
    each line with its OWN terminator, taken from splitlines(keepends=True) —
    "\n".join() would be lossy, because splitlines() also splits on U+2028,
    U+2029, \x85, \x0b, \x0c, \x1c, \x1d and \x1e, and joining with "\n" would
    silently rewrite every one of those eight characters. A line this function
    does not rewrite is emitted verbatim, so byte identity holds for pages that
    contain them.
    """

    def _sub(match: re.Match[str]) -> str:
        token = match.group(1)
        if _SUFFIX_RE.sub("", token.strip()) != old:
            return match.group(0)
        return "`" + token.replace(old, new, 1) + "`"

    dropped = _linter_dropped_lines(text)
    bodies = text.splitlines()
    raws = text.splitlines(keepends=True)
    out: list[str] = []
    for i, body in enumerate(bodies):
        if i in dropped:
            out.append(raws[i])
            continue
        out.append(_INLINE_CODE_RE.sub(_sub, body) + raws[i][len(body) :])
    return "".join(out)


def repair_text(
    text: str,
    repo_root: Path,
    config: dict,
    files: set[str],
    corroborators: set[str],
) -> tuple[str, list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Repair shortened citations. Returns (new_text, repairs, declines).

    Corroboration is the ENTRY CONDITION, not an ambiguity tiebreak. A unique
    suffix match establishes only that the candidate exists — never that the
    cited token was a shortening of it, and the sole entry condition ("does
    not resolve") is exactly the confabulation population citation_exists
    exists to block. See the spec's "Why uniqueness is necessary but NOT
    sufficient".

    The invariant this delivers: repair never introduces a reference to a file
    the pipeline had not already accepted a reference to. The set of files the
    finished page points at is invariant under repair; only the spelling of an
    existing pointer changes.

    The skip order on the CITED side mirrors `citation_exists.check_path`
    deliberately. Every class it declines to check is a class repair must
    decline to touch: an exempt token, a reserved `example/` path, and a
    gitignored path are all unresolvable BY DESIGN, and "fixing" one would
    convert a deliberate illustration into a false claim about real code.

    The CANDIDATE side is not a mirror of that list but a positive gate — see
    `_candidate_rejection`. Testing the cited token alone let a repair MOVE a
    citation into a region the linter does not check rather than out of one,
    which is the same harm in the other direction; enumerating the regions let
    it happen twice more. The candidate must instead be one the linter would
    both SEE and verify BY EXISTENCE once written, and a cause nobody
    anticipated declines.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)

    repairs: list[tuple[str, str]] = []
    declines: list[tuple[str, str, str]] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
            continue
        if _excluded_reason(cited, rel, repo_root, exempt, prefixes) is not None:
            continue

        candidates = suffix_candidates(rel, files)
        if len(candidates) != 1:
            # Ambiguity and zero-match both fail closed. Corroboration narrows
            # the entry condition; it does not resolve ambiguity, so a second
            # candidate still leaves the page untouched and blocking.
            continue
        candidate = candidates[0]

        # The candidate must clear the verifiability gate. Testing only the
        # cited token let a repair MOVE a citation into a region the linter
        # does not check, rather than out of one — the same harm, in the other
        # direction, and a page that reads `ok` forever afterwards.
        why = _candidate_rejection(candidate, repo_root, config, files)
        if why is not None:
            declines.append((cited, candidate, why))
            continue

        if candidate not in corroborators:
            # Match the CANDIDATE, never the cited token: the token is what the
            # agent wrote, so corroborating it would be circular.
            declines.append((cited, candidate, "uncorroborated"))
            continue
        repairs.append((cited, candidate))

    new_text = text
    for old, new in repairs:
        new_text = rewrite_token(new_text, old, new)
    return new_text, repairs, declines
