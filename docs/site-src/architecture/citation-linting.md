---
description: 'Documents architecture citation linting: Fixes three defects in the citation extraction/relativization layer of the Tier-1 `citation_exists` block rule in `scripts/lint/citation_exists.py`: an unguarded `OSError` in the blocking-loop existence check (the diagnostic loop already had a guard, per CCE-141 round 6), bare filenames that were never actually checked for existence, and relative paths that were used unnormalized before comparison/lookup.'
source_files:
  - scripts/lint/citation_exists.py
  - tests/lint/test_citation_exists.py
last_reviewed: '2026-10-01'
status: draft
---
# Citation linting

`citation_exists` is a Tier-1 **block** rule in `scripts/lint/citation_exists.py`. It reads the inline code spans in a page's prose and fails the page when a cited repo path, test name, or `path:symbol` does not exist. It exists to stop confabulated citations from shipping.

This page covers how citations are extracted and normalized, and the three hardening fixes from CCE-171 (PR #263).

## What gets checked

`extract_citations` strips fenced code blocks first, then looks at inline code spans. Fenced examples are treated as hypothetical and never checked. Each span becomes one of:

- a test identifier (`test_` followed by snake case), checked by `cited_test_exists`;
- a repo path with a directory separator, with any `:line`, `:start-end` or `:symbol` suffix stripped;
- nothing, when the span is a placeholder (contains `<`, `>`, `*`, `{`, `}`, `YYYY`, `...`, starts with `~` or `$`, or is a URL).

`check_path` then resolves each path through `_resolves`: build output, tracked or on-disk file, `docs_dir`, then declared `lint.citation_source_roots`. Reserved example prefixes and exempt tokens are skipped. Paths a host's `.gitignore` excludes are downgraded to an advisory note.

If the config does not live in a git repo, every path passes. The rule cannot verify, so it never blocks.

## CCE-171: three hardening fixes

### Relative paths are normalized

`_relativize` used to return every non-absolute token verbatim. The character class in `_REPO_PATH_RE` admits `..`, and pathlib's `/` operator never collapses it. So `repo_root / rel` reached the kernel with the `..` intact, and the kernel walked the path out of the repo. A page could cite a file in a sibling checkout and pass, even though no CI checkout or reader can see that file.

The relative branch now runs `os.path.normpath` and returns `None` when the result is `..` or starts with `../`. `None` means "not a repo citation", and the callers skip it.

Containment is the rule, not a ban on `..`. A token such as `docs/../<dir>/<file>.py` normalizes to `<dir>/<file>.py` and resolves as usual.

The code uses `normpath` and not `Path.resolve`. The token is a repo-relative string, and resolving it would anchor it to the process working directory. The verdict would then depend on where the linter ran. Symlinks are not followed, for the same reason.

The fix lives in `_relativize` and not in `_resolves`. Three `.exists()` arms in `_resolves` were exposed, and so was `resolve_cited_sources`, which feeds the fact-checker's admission gate. One change covers every call site.

### Escaping tokens are skipped, not blocked

This is surprising. A `..` token that escapes the repo root is not reported as a failure. `_relativize` returns `None` and the loop silently skips it. Do not describe the linter as blocking such a token.

### Bare filenames are out of scope

A citation must carry a directory separator to be verified. A lone filename passes unchecked. Resolving it against the tracked-file list would be basename matching, which is suffix matching under another name. Suffix matching admits the confabulated paths this rule blocks. `source_roots` drops multi-segment entries for the same reason.

The `citation_line_free` rule reports a bare filename that pins a `:line` suffix, as advisory. A bare filename with no suffix is reported by nothing. That gap is known and accepted.

### OSError is guarded in the blocking loop

`_resolves` reaches `(repo_root / rel).exists()`. Pathlib re-raises `OSError` for errno values outside its ignored set, and `ENAMETOOLONG` is one of them. `_REPO_PATH_RE` constrains the shape of a token and not its length, so an over-long LLM-authored token could raise.

Before the fix, one such token propagated out of `check_path` and discarded every finding already made on that page. The diagnostic path in `scripts/citation_repair.py` already had this guard from CCE-141 round 6. The blocking loop did not.

The paths loop in `check_path` now wraps each token's body in `try/except OSError`. A failing token is **reported**, as `cites unusable path '<token>': <strerror>`. It is not skipped, because this is the blocking rule. A token the filesystem cannot name does not name a real file, so failing closed is accurate.

`_truncate` elides reported tokens past 80 characters. Lint messages reach the docs PR body, and GitHub caps that at 65,536 bytes.

The `path:symbol` loop handles the same error differently. It skips the token with `continue`, because the paths loop has already named it and a second line would be noise.

## Keeping this module out of its own way

This module's source is an input to the pages that document it. `page-author` reads it and quotes back what it finds. A concrete example path in a docstring that does not resolve becomes a blocking citation on the page about the rule (CCE-195).

Write every example path in `scripts/lint/citation_exists.py` as a placeholder form. `DEFAULT_EXEMPT_TOKENS` holds only exact tokens that must stay verbatim.

### Why the allowlist alone could not fix it

PR #302 exempted the three grammar examples that blocked this page on nightly 36245832365: `dir/file.ext`, `scripts/x.py` and `docs/../scripts/x.py`. They are exact tokens in `DEFAULT_EXEMPT_TOKENS`, not a prefix, so an invented neighbour of any of them still blocks. The same PR exempted the three CCE-141 shortening-evidence paths in the host's `lint.citation_exempt_tokens` list, because that story cannot be told without naming paths that must not resolve.

The PR's own explanatory comment then spelled out a concrete sibling of the first example. That minted a fourth blocking token and re-blocked this page on nightly 36722383698. PR #263 lost its page to `deferral_skip` after three deferrals. Seven more concrete examples sat unfired in the same file.

Widening the allowlist cannot converge: each new entry arrives with prose that mints the next token. PR #305 removed the generator instead.

### Three cases for an example path in linter source

When a path in a docstring or comment would not resolve, decide which case it is:

1. **Arbitrary illustration.** Any name would do. Reword it into a form `_PLACEHOLDER_MARKERS` already skips, such as `scripts/<name>.py`. Never write a concrete sibling.
2. **Measured record.** The exact spelling is the evidence, such as the two links that blocked real host runs. Rewording would make the sentence claim something that did not happen, so exempt the token in host config.
3. **Tested contract.** The token is supposed to block. `scripts/external_refs.py` quotes a transcript of its renderer declining a token, and `test_a_declined_token_reverts_to_being_blocked_by_the_linter` requires the linter to block it. You can neither reword nor exempt it. The file is excluded from the sweep instead.

### The sweep guard

`tests/lint/test_citation_exists.py` runs the production rule over the source an authored page quotes: `scripts/*.py`, `scripts/lint/*.py` and `agents/*.md`. It loads this repo's real host config, because the plugin documents itself and the nightly's config is that file.

- `test_this_modules_own_source_mints_no_blocking_token` checks `scripts/lint/citation_exists.py` alone.
- `test_no_plugin_source_file_mints_a_blocking_token` checks the whole sweep and names every offender.
- `test_the_sweep_exclusions_are_each_load_bearing` fails when an excluded file no longer has an unresolvable token. The exclusion set is a contract, not a waiver list.
- `test_the_guard_rejects_a_concrete_example_path` builds its offending token from string pieces. Writing it literally would mint the citation the guard exists to stop.

If the sweep fails, check the module the blocked page documents before adding an exemption. The token is probably in a docstring, and the fix is upstream of the allowlist.
