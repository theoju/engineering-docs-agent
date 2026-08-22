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
block. The run-input set (`build_run_inputs`) is therefore reported as a
CONFIDENCE LABEL on the suggestion rather than as a gate on an action: nothing
acts, so there is nothing to gate.

WHAT EACH LABEL ESTABLISHES, AND WHAT IT DOES NOT. Read literally; every one
of them describes an OBSERVATION, never a verdict.

`candidate_in_run_inputs`
    ESTABLISHES: exactly one tracked file is a strict segment-suffix match for
    the cited tail, AND that file is named by an input to this run — a file
    the batch's PRs changed (rung 2), or a path the page's own prior commit
    already cited and the linter validated there (rung 1).
    DOES NOT ESTABLISH: that the cited token was ever a shortening of that
    file; that the page-author had that file in mind; or that repointing the
    citation at it would be right. Rung 2 admits the WHOLE
    `_pr_changed_files(batch_prs)` set, so a vendored dependency, a lockfile
    or an unrelated module that the batch happened to touch earns this label
    the moment it is the unique suffix match. It bounds a coincidence; it
    confirms nothing. This label was called `corroborated` until CCE-141
    round 5 — a name that read as "confirmed" and was granted by batch
    membership alone.

`suffix_match_only`
    ESTABLISHES: exactly one tracked file is a strict segment-suffix match,
    and nothing else points at it. (Formerly `uncorroborated`.)
    DOES NOT ESTABLISH: anything beyond the string match.

`ambiguous`
    ESTABLISHES: several tracked files end with the cited tail, listed up to
    `_AMBIGUITY_CAP`.
    DOES NOT ESTABLISH: that any of them is the intended one.

`no_candidate`
    ESTABLISHES: NO tracked file ends with the cited tail — the module looked
    and found nothing, so its own evidence says the token is not a shortening
    of anything in the repo.
    DOES NOT ESTABLISH: anything actionable. `diagnose` still RETURNS these to
    its caller, but the orchestrator deliberately keeps them out of the run
    digest: `lint_block` already names every one of those paths, with zero
    added information, and they are the dominant population — see
    `orchestrator_runner._diagnose_citation_paths` for the full reasoning.

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
    "build_run_inputs",
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


def build_run_inputs(
    prior_text: str | None, source_paths: set[str], files: set[str]
) -> set[str]:
    """Tracked paths named by an input to this run that the page-author did not write.

    A CONFIDENCE LABEL, not a safety gate. This used to be the ENTRY CONDITION
    for rewriting a page: a candidate no independent source named was refused,
    because acting on it was dangerous. Nothing acts now. Membership here
    decides only how much an operator should trust the suggestion in the
    digest — `candidate_in_run_inputs` means some input other than the
    authoring agent already named that file during this run or on the prior
    commit; `suffix_match_only` means the suggestion rests on a suffix match
    alone. Behaviour is unchanged from when it was a gate; only its role and
    its name are.

    NAMED FOR WHAT IT MEASURES (CCE-141 round 5). It was `build_corroborators`
    and the label was `corroborated`, which reads as "confirmed". It is not:
    rung 2 admits the WHOLE batch-changed set, so any tracked file the batch
    happened to touch — a vendored dependency, a lockfile, an unrelated module
    — takes the top label the moment it is the unique suffix match. The
    evidence is "this run was already looking at that file", and the name now
    says exactly that and no more. The fix is a RENAME on purpose: adding a
    further check to try to earn the old name is the mechanism escalation this
    feature was already cut down for.

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
    acceptance, so counting it would raise a suggestion with no independent
    support at all to the top label. Calling extract_citations also inherits
    the linter's fence semantics for free, satisfying import-never-reimplement
    rather than straining it.

    Rung 2 (every authoring): the batch's source set — `grounding =
    _pr_changed_files(batch_prs)` inside the page-authoring loop of
    `orchestrator_runner.run`, carried per page in `grounding_by_path` and
    handed here as `source_paths`. Glob entries are excluded: expanding them
    would make the label ceremony. (Cross-references here name SYMBOLS, never
    line numbers — two line-pinned ones in this docstring had already rotted
    by one revision when CCE-141 round 5 checked them.)

    NOT "orchestrator-authoritative". `batch_prs` traces to
    `orchestrator_runner.run`'s `dispatch_validated("source-collector", …)`,
    and source-collector is itself an LLM subagent
    (`agents/source-collector.md`, `model: sonnet`). Its schema types `files`
    as a bare `{"type": "array"}` with no item shape
    (`agents/schemas/source_collector.schema.json`), and nothing under
    scripts/ checks `pr["files"]` against git. Rung 2's provenance is therefore
    A DIFFERENT AGENT, not the orchestrator.

    The doctrine still holds LITERALLY: source-collector is not the AUTHORING
    agent, so a page-author that confabulates a citation cannot also mint its
    own supporting input. The residual is that a confabulating source-collector
    can — an invented entry in `files[]` becomes a run input, widening the
    `candidate_in_run_inputs` label from a batch's true 5–15 files to any
    tracked file on the host. That residual cost a rewrite; it now costs an
    operator one over-confident digest line.

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


def _is_excluded(
    token: str,
    rel: str,
    repo_root: Path,
    exempt: set[str],
    prefixes: tuple[str, ...],
) -> bool:
    """True when `citation_exists.check_path` declines to CHECK this path at all.

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

    Returns a BOOL. It used to return which class matched, but the only caller
    tested that string against None and the class never reached a digest line
    or a test — a classification nobody read. Bool is the whole contract.
    """
    return (
        token in exempt
        or any(rel.startswith(p) for p in prefixes)
        or _is_gitignored(repo_root, rel)
    )


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
    run_inputs: set[str],
) -> list[tuple[str, str, str]]:
    """What each blocked citation was probably shortened from. Reports; never acts.

    Takes text and returns findings. It does NOT return a modified string and
    it does NOT accept a path to write to — see the module docstring for why
    the rewrite was deleted.

    Returns `[(cited, candidate, confidence)]` in document order, one entry per
    citation that does not resolve and is not in a class the linter declines to
    check. Four confidence labels, and every non-resolving citation gets
    exactly one of them:

    | confidence                | candidate field           | means                |
    | ------------------------- | ------------------------- | -------------------- |
    | `candidate_in_run_inputs` | the one candidate         | one strict suffix    |
    |                           |                           | match, and an input  |
    |                           |                           | to this run other    |
    |                           |                           | than the authoring   |
    |                           |                           | agent already named  |
    |                           |                           | that file            |
    | `suffix_match_only`       | the one candidate         | one strict suffix    |
    |                           |                           | match, resting on    |
    |                           |                           | the match alone      |
    | `ambiguous`               | the candidates, capped at | several tracked      |
    |                           | `_AMBIGUITY_CAP`, then    | files end with this  |
    |                           | `(+N more)`               | tail                 |
    | `no_candidate`            | `""`                      | no tracked file ends |
    |                           |                           | with this tail       |

    The module docstring states what each label does and does NOT establish;
    read it before acting on one.

    `suffix_match_only` findings are RETURNED, not withheld. The old code
    declined them because ACTING on them was dangerous; nothing acts now, and
    an operator reading the digest is better served by a labelled suggestion
    than by silence. The same reasoning covers the last two rows: `ambiguous`
    and `no_candidate` used to `continue` silently, so a page that blocked
    because two candidates matched produced no line at all while the
    single-candidate case was loud. That inconsistency was the whole reason
    the digest could not be trusted as a census of blocked citations.

    This function returns ALL FOUR classes. What reaches the run digest is the
    ORCHESTRATOR's decision, and it drops `no_candidate` — that population is
    already named path-for-path by `lint_block`, and its own evidence says the
    token is not a shortening. See `orchestrator_runner._diagnose_citation_paths`.

    The skip order mirrors `citation_exists.check_path` deliberately. A token
    that resolves needs no diagnosis; an absolute path outside the repo is an
    environment reference the linter does not treat as a repo citation; and
    every class `_is_excluded` covers is unresolvable by design, so a
    finding there would be noise rather than signal.
    """
    docs_dir = _docs_dir(config)
    build_dir = _build_dir(repo_root)
    prefixes = example_prefixes(config)
    exempt = exempt_tokens(config)
    roots = source_roots(config)

    findings: list[tuple[str, str, str]] = []
    for cited in extract_citations(text)["paths"]:
        try:
            rel = _relativize(cited, repo_root)
            if rel is None:
                continue
            if _resolves(rel, repo_root, files, docs_dir, build_dir, roots):
                continue
            if _is_excluded(cited, rel, repo_root, exempt, prefixes):
                continue

            candidates = suffix_candidates(rel, files)
        except OSError:
            # One pathological token costs only itself. `_resolves` reaches
            # `(repo_root / rel).exists()` and pathlib RE-RAISES OSError for
            # errno values outside its ignored set — ENAMETOOLONG among them —
            # so a single 3000-char token propagated out of this function and
            # discarded `findings` wholesale, losing every good finding that
            # appeared EARLIER on the same page. Skipping just this token is
            # safe for the same reason the caller drops `no_candidate`: the
            # token does not resolve, so `citation_exists` blocks the page and
            # `lint_block` names this exact path, with severity.
            continue

        if not candidates:
            findings.append((cited, "", "no_candidate"))
        elif len(candidates) > 1:
            findings.append((cited, _summarize(candidates), "ambiguous"))
        elif candidates[0] in run_inputs:
            # Match the CANDIDATE, never the cited token: the token is what the
            # authoring agent wrote, so matching it would be circular.
            findings.append((cited, candidates[0], "candidate_in_run_inputs"))
        else:
            findings.append((cited, candidates[0], "suffix_match_only"))
    return findings
