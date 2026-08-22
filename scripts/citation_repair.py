"""Detection of shortened citation paths (CCE-141). DETECTION ONLY.

`page-author` sometimes emits a citation as a bare relative path — the
committed page cited
`.claude/skills/connector-builder/references/checklist.md` at three sites and
the rewrite shortened it to `references/checklist.md`. `citation_exists`
correctly finds nothing at the repo root and blocks the page; post-CCE-140 the
deferral skip then abandons the PR, so the page is silently never written.

This module REPORTS the tracked file such a citation was most likely shortened
from, and stops. IT NEVER TOUCHES A PAGE. There is no `Path.write_text` here,
no rewriting, and there must never be one.

Why the rewrite is gone. A deterministic repair was built for exactly this
defect, and across four adversarial review rounds it produced four Criticals —
every one the same class in a new disguise: the repair moved a citation into a
region `citation_exists` does not verify, so a BLOCK became a silent PASS and
the pointer stopped being checked even after the file it named was deleted.
(Round 1: uniqueness does not imply the token was ever a shortening. Round 2:
the corroborator's raw scan counted fenced/URL/comment mentions the linter
never validated. Round 3: the candidate blacklist missed unparseable tokens
and the mkdocs build dir. Round 4: the gate's own absence probe emptied the
repo root and blinded the on-disk half of every resolution arm.) Meanwhile the
measured production value of the rewrite, across the whole archived record
(19 PRs, 15 blocked citations), was that it fired ZERO times.

A page that is never rewritten cannot be corrupted that way. Deleting the
rewrite deleted the entire defect class and kept the one thing four rounds
actually produced: the diagnosis.

Nothing here is correct, let alone provably so — that claim is retired.
A suffix match is a SUGGESTION for a human reading the run digest. Uniqueness
establishes only that exactly one tracked file ends with the cited tail; it
never establishes that the cited token was a shortening of it, and "does not
resolve" is precisely the confabulation population `citation_exists` exists to
block. Corroboration (`build_corroborators`) is therefore reported as a
CONFIDENCE LABEL on the suggestion rather than as a gate on an action: nothing
acts, so there is nothing to gate.

Spec: docs/superpowers/specs/2026-08-21-cce141-citation-path-repair-design.md
"""

from __future__ import annotations

import sys
from pathlib import Path

_LINT_DIR = str(Path(__file__).resolve().parent / "lint")
if _LINT_DIR not in sys.path:
    sys.path.append(_LINT_DIR)

# Imported, never reimplemented: citation_exists declares these a shared-helper
# contract. Detection must agree with check_path on what a citation IS and what
# resolves, or the two drift and this module starts reporting tokens the linter
# deliberately skips.
from citation_exists import (  # noqa: E402
    _build_dir,
    _docs_dir,
    _is_gitignored,
    _relativize,
    _resolves,
    example_prefixes,
    exempt_tokens,
    extract_citations,
    source_roots,
    tracked_files,
)

__all__ = [
    "build_corroborators",
    "diagnose",
    "suffix_candidates",
    "tracked_files",
]


_GLOB_CHARS = ("*", "?", "[", "{")

# How many candidates an `ambiguous` finding names before it stops listing and
# says how many it withheld. A digest line is read by a human; an unbounded
# join of a one-segment tail's matches would be hundreds of paths long on a
# real host and would drown every other reason in the run.
_AMBIGUITY_CAP = 5


def build_corroborators(
    prior_text: str | None, source_paths: set[str], files: set[str]
) -> set[str]:
    """Tracked paths vouched for by a source the authoring agent did not write.

    A CONFIDENCE LABEL, not a safety gate. This used to be the ENTRY CONDITION
    for rewriting a page: a candidate no independent source vouched for was
    refused, because acting on it was dangerous. Nothing acts now. Membership
    here decides only how much an operator should trust the suggestion in the
    digest — `corroborated` means some source outside the authoring agent
    already pointed at that file during this run or on the prior commit;
    `uncorroborated` means the suggestion rests on a suffix match alone.
    Behaviour is unchanged from when it was a gate; only its role is.

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
    acceptance, so counting it would stamp `corroborated` on a suggestion with
    no independent support at all. Calling extract_citations also inherits the
    linter's fence semantics for free, satisfying import-never-reimplement
    rather than straining it.

    Rung 2 (every authoring): the batch's source set — `grounding =
    _pr_changed_files(batch_prs)` (orchestrator_runner.py:2372), handed here as
    `source_paths`. Glob entries are excluded: expanding them would make the
    label ceremony.

    NOT "orchestrator-authoritative". `batch_prs` traces to
    `dispatch_validated("source-collector", …)`
    (orchestrator_runner.py:2048-2050), and source-collector is itself an LLM
    subagent (`agents/source-collector.md`, `model: sonnet`). Its schema types
    `files` as a bare `{"type": "array"}` with no item shape
    (agents/schemas/source_collector.schema.json:22), and nothing under
    scripts/ checks `pr["files"]` against git. Rung 2's provenance is therefore
    A DIFFERENT AGENT, not the orchestrator.

    The doctrine still holds LITERALLY: source-collector is not the AUTHORING
    agent, so a page-author that confabulates a citation cannot also mint its
    own corroborator. The residual is that a confabulating source-collector
    can — an invented entry in `files[]` becomes a corroborator, widening the
    `corroborated` label from a batch's true 5–15 files to any tracked file on
    the host. That residual cost a rewrite; it now costs an operator one
    over-confident digest line.

    `p in files` and `suffix_candidates` iterating `files` both bound this to
    the tracked set (`files` is `git ls-files` via
    `citation_exists.tracked_files`), so a label can never be pinned on a path
    that is not in the repo.

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
    reserved `example/` prefix, a gitignored path. Every class here is
    unresolvable BY DESIGN, so a non-resolving token in one of them is not a
    defect and reporting a candidate for it would be pure noise in the digest:
    an `example/` path is fictional on purpose, an exempt token was declared
    unverifiable on purpose, and a gitignored path is expected to be absent
    from a fresh checkout.

    Applied to the CITED token only. There is no candidate side any more —
    the candidate-side gate existed to make a page rewrite safe, and it went
    with the rewrite.

    `_resolves` is deliberately not one of these classes: it is the entry
    condition (a token that resolves needs no diagnosis), and the caller
    applies it itself.

    Ordering: this runs AFTER `_resolves`, so the `_is_gitignored` subprocess
    is only paid for paths that do not resolve.
    """
    if token in exempt:
        return "exempt_token"
    if any(rel.startswith(p) for p in prefixes):
        return "example_namespace"
    if _is_gitignored(repo_root, rel):
        return "gitignored"
    return None


def suffix_candidates(cited: str, files: set[str]) -> list[str]:
    """Tracked paths of which `cited` is a strict segment-boundary suffix.

    Segment boundaries are required, not substring matching:
    `references/checklist.md` matches
    `.claude/skills/connector-builder/references/checklist.md`, but
    `erences/checklist.md` matches nothing.

    `len(parts) > n` is what makes the shortening STRICT — it excludes the
    exact-match case, which is never a candidate because such a token already
    resolved.
    """
    segments = cited.split("/")
    n = len(segments)
    out = []
    for f in files:
        parts = f.split("/")
        if len(parts) > n and parts[-n:] == segments:
            out.append(f)
    return sorted(out)


def _summarize(candidates: list[str]) -> str:
    """The `ambiguous` finding's candidate list, capped and honest about it.

    `suffix_candidates` returns sorted output, so which candidates survive the
    cap is deterministic rather than set-iteration-order roulette.
    """
    withheld = len(candidates) - _AMBIGUITY_CAP
    shown = ", ".join(candidates[:_AMBIGUITY_CAP])
    return f"{shown} (+{withheld} more)" if withheld > 0 else shown


def diagnose(
    text: str,
    repo_root: Path,
    config: dict,
    files: set[str],
    corroborators: set[str],
) -> list[tuple[str, str, str]]:
    """What each blocked citation was probably shortened from. Reports; never acts.

    Takes text and returns findings. It does NOT return a modified string and
    it does NOT accept a path to write to — see the module docstring for why
    the rewrite was deleted.

    Returns `[(cited, candidate, confidence)]` in document order, one entry per
    citation that does not resolve and is not in a class the linter declines to
    check. Four confidence labels, and every non-resolving citation gets
    exactly one of them:

    | confidence       | candidate field            | means                    |
    | ---------------- | -------------------------- | ------------------------ |
    | `corroborated`   | the one candidate          | one strict suffix match, |
    |                  |                            | and some source outside  |
    |                  |                            | the authoring agent      |
    |                  |                            | already pointed at it    |
    | `uncorroborated` | the one candidate          | one strict suffix match, |
    |                  |                            | resting on the match     |
    |                  |                            | alone                    |
    | `ambiguous`      | the candidates, capped at  | several tracked files    |
    |                  | `_AMBIGUITY_CAP`, then     | end with this tail       |
    |                  | `(+N more)`                |                          |
    | `no_candidate`   | `""`                       | no tracked file ends     |
    |                  |                            | with this tail at all    |

    Uncorroborated findings are REPORTED, not withheld. The old code declined
    them because ACTING on them was dangerous; nothing acts now, and an
    operator reading the digest is better served by a labelled suggestion than
    by silence. The same reasoning covers the last two rows: `ambiguous` and
    `no_candidate` used to `continue` silently, so a page that blocked because
    two candidates matched produced no digest line at all while the
    single-candidate case was loud. That inconsistency was the whole reason
    the digest could not be trusted as a census of blocked citations. Now it
    can: every non-excluded, non-resolving citation appears.

    A `corroborated` label is not a claim of correctness. Corroboration bounds
    the surface — the candidate is a tracked file some other source already
    pointed at — and nothing more.

    The skip order mirrors `citation_exists.check_path` deliberately. A token
    that resolves needs no diagnosis; an absolute path outside the repo is an
    environment reference the linter does not treat as a repo citation; and
    every class `_excluded_reason` names is unresolvable by design, so a
    finding there would be noise rather than signal.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)

    findings: list[tuple[str, str, str]] = []
    for cited in extract_citations(text)["paths"]:
        rel = _relativize(cited, repo_root)
        if rel is None:
            continue
        if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
            continue
        if _excluded_reason(cited, rel, repo_root, exempt, prefixes) is not None:
            continue

        candidates = suffix_candidates(rel, files)
        if not candidates:
            findings.append((cited, "", "no_candidate"))
        elif len(candidates) > 1:
            findings.append((cited, _summarize(candidates), "ambiguous"))
        elif candidates[0] in corroborators:
            # Match the CANDIDATE, never the cited token: the token is what the
            # authoring agent wrote, so corroborating it would be circular.
            findings.append((cited, candidates[0], "corroborated"))
        else:
            findings.append((cited, candidates[0], "uncorroborated"))
    return findings
