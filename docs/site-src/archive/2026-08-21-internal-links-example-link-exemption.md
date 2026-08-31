---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/239
synthesized_into: []
doc_kind: decision
---

# internal_links now exempts example links quoted in prose (CCE-131 pattern, recurring)

## The problem

The `internal_links` Tier-1 lint rule (`scripts/lint/internal_links.py`) checks
every Markdown link in a page and blocks the build if a local target doesn't
resolve on disk. That's the right behavior for navigation links. It's the
wrong behavior for a link that appears purely as an *illustration* — a page
quoting link syntax to explain how a function parses links, not to point you
somewhere.

That distinction bit twice, on the same page, before this fix landed. A page
documenting `extractDocRefs` — a function whose entire job is parsing Markdown
links out of `CLAUDE.md` — was blocked on `broken internal link(s):
docs/runbook.md`, then again on `docs/foo.md`. Both strings came verbatim from
the source material the page was written from: the design spec writes the
syntax as `` `[x](docs/foo.md)` ``, and the unit test fixture contains the
literal text `Also [the runbook](docs/runbook.md).`. You can't document a
Markdown-link parser without showing a Markdown link. The page was correct;
the rule wasn't.

The cost of a false-positive block here isn't cosmetic. A blocked page is
dropped from the docs PR entirely, and post-CCE-140 the deferral-skip
machinery abandons a repeatedly-blocked PR and moves the baseline past it — so
the page is never written, and nothing stays red to tell you it's missing.

## The fix

`internal_links` now strips code before matching links, the same way
`citation_exists` has since CCE-110 ("fenced examples are legitimately
hypothetical"). Concretely, `check_path` runs `strip_code` over the file
before `LINK_RE` ever sees it, and `strip_code` does two things in sequence:

1. Strip fenced blocks by calling `strip_fenced_blocks`, **imported directly
   from `citation_exists`** rather than reimplemented. That's deliberate: the
   helper already carries the CCE-131 fail-closed behavior for an unterminated
   fence (an unclosed ` ``` ` doesn't swallow the rest of the file and silently
   disable the rule for everything after it), and a local copy would risk
   losing that.
2. Strip inline code spans with `CODE_SPAN_RE`, a regex matched *locally* to
   `internal_links` rather than shared. That's also deliberate, not an
   oversight: `citation_exists` can't strip inline spans the same way, because
   its citations — `` `path/to/file.py` `` and `` `path/to/file.py:symbol` ``
   — *are* inline code spans. The two rules read the same document through
   deliberately different filters.

`CODE_SPAN_RE` matches a run of backticks closed by an equal-length run, not a
single backtick. That matters for the actual failure mode here: the spec
itself writes examples like `` `[x](docs/foo.md)` `` — a span delimited by a
*double*-backtick run, because the example text contains a bare backtick. A
matcher that only recognized single backticks would miss the outer delimiters
and the link would leak straight back out to `LINK_RE`, reproducing the exact
bug this fix closes.

## What still blocks

This is not a blanket amnesty on link checking. A real broken link in prose,
sitting right next to an exempted example, still blocks — the fix strips code
spans and fences, nothing else. Links that survive a closed fence, or that
appear after a fence closes, are still checked normally. Two regression tests
in `tests/lint/test_internal_links.py` pin this directly: a genuine broken
link next to a fenced and an inline-span example still fails the build
(`test_real_broken_link_beside_an_example_still_blocks`), and a broken link
placed after a closed fence still fails too
(`test_broken_link_after_a_closed_fence_still_blocks`) — fence-stripping
resumes checking once the fence ends rather than staying off for the rest of
the file. A third test,
`test_unterminated_fence_fails_closed`, pins the CCE-131 fail-closed behavior
the imported `strip_fenced_blocks` carries: an unclosed fence must not
swallow the rest of the file and silently disable the rule.

One known limit is explicit in the module docstring: indented (4-space) code
blocks are not stripped. They're ambiguous with list continuation, and telling
the two apart needs a real Markdown parser — stripping them heuristically
risks silently skipping a genuinely broken link. An example link written in an
indented block therefore still blocks. That's read as the safe failure
direction: loud and visible, rather than a quiet false negative.

## Why this is a recurring pattern, not a one-off

This is the same pathology CCE-131 closed for `citation_exists` (the reserved
`example/` namespace and exempt-token allowlist for confabulated-looking but
intentional citations), showing up again in a sibling rule that didn't get the
same treatment the first time: a lint rule that can't tell an example quoted
in prose from a real reference will eventually block the exact page whose job
is to quote that example. Any future Tier-1 rule that matches on link-shaped
or citation-shaped text in prose should assume it needs the same code-aware
exemption from day one, rather than waiting for its own incident.

## Reference

Incident: 2026-08-21, `theoju/claude-code-self-assessment` runs `32460602658`
and `32495019606`. Fix: PR #239.
