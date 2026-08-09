---
status: draft
sources:
- https://github.com/theoju/engineering-docs-agent/pull/202
synthesized_into: []
doc_kind: decision
---

# CCE-134: Citation Exempt Token, Not Example Prefix

## Problem

Nightly run 31275900434 went `partial`. `citation_exists` (Tier-1, block)
rejected `docs/site-src/architecture/cce-capability-c2-canonical-core-authoring.md`
on two cited tokens, but only one of them was a real defect:

- CCE-132 — a genuine confabulation, a citation naming something that was
  never written.
- CCE-134 — `path/to/file.py`, the metasyntactic placeholder from the
  CCE-122 citation grammar. The plugin ships that exact string in
  `agents/page-author.md` and `CLAUDE.md` as the illustrative shape of a
  citation, so it propagates verbatim into authored prose on every host —
  and then fails the Tier-1 block rule it exists to document.

`path/to/file.py` matched neither of the two existing escape hatches in
`scripts/lint/citation_exists.py`: it isn't a placeholder by the
`_is_placeholder` heuristic (no `<`, `>`, `*`, `{`, `}`, `YYYY`, or `...`
marker), and it doesn't fall under the reserved `example/` illustrative
namespace (`DEFAULT_EXAMPLE_PREFIXES`, CCE-131).

## Decision

Add `path/to/file.py` to `DEFAULT_EXEMPT_TOKENS`
(`scripts/lint/citation_exists.py`) as an **exact-match token**:

```text
test_snake_case
path/to/file.py
```

`exempt_tokens()` unions the plugin defaults with the host's
`lint.citation_exempt_tokens`, so the entry ships to every host without
per-host config. `check_path` already reports drift on a listed token that
starts resolving (`stale exemption: '<token>' now resolves`), so the
mechanism is self-healing rather than a silent permanent hole.

The obvious-looking alternative — reserving `path/to/` as a whole entry in
`DEFAULT_EXAMPLE_PREFIXES` alongside `example/` — was considered and
rejected.

## Why a token, not a prefix

The prefix branch in `check_path` is a silent, unconditional `continue`:
once a cited path's relativized form starts with a reserved prefix, nothing
downstream is checked — no path-existence check, no symbol check, no drift
report. Reserving `path/to/` fails open on three independent grounds:

1. **It swallows genuine confabulations under the same subtree.** A
   citation like `path/to/genuinely_missing.py`, or an invented `:symbol`
   attributed to a real file such as `path/to/real_module.py`, would pass
   silently — the exact CCE-122 authoritative-looking-but-wrong hazard the
   `:symbol` grammar was built to catch. An exact token only ever matches
   the one string; a confabulated sibling still resolves through the normal
   existence check and still blocks.
2. **It does not survive host config overrides.** `example_prefixes()`
   *replaces* `DEFAULT_EXAMPLE_PREFIXES` when a host sets
   `lint.citation_example_prefixes` (deliberately — CCE-131 made this a
   namespace choice, so a host with a real `example/` directory picks a
   different word instead of keeping a shadowed default). Any host that
   configured its own prefix would silently lose the `path/to/` reservation
   and start failing on pages the plugin itself authored. `exempt_tokens()`
   unions instead of replacing, so the entry survives every host
   configuration.
3. **It has no stale-exemption drift detection.** The exempt-token branch in
   `check_path` reports `stale exemption: '<token>' now resolves` the moment
   a listed token starts pointing at something real. The prefix branch's
   bare `continue` never reports anything — a `path/to/file.py` that someday
   becomes a real file would pass forever with no signal that the exemption
   is now moot.

## Behavior by case

| Cited token | Under a `path/to/` prefix reservation (rejected) | Under an exact exempt token (shipped) |
| --- | --- | --- |
| `path/to/file.py` | passes | passes |
| `path/to/file.py:symbol` / `path/to/file.py:line` | passes (suffix strips to the same reserved prefix) | passes (suffix strips to the same exempt token) |
| `path/to/genuinely_missing.py` | passes silently — fails open | blocks: `cites nonexistent path 'path/to/genuinely_missing.py'` |
| `path/to/real_module.py:totally_invented_symbol` | passes silently — authoritative-looking false claim | blocks: `cites nonexistent symbol 'totally_invented_symbol' in 'path/to/real_module.py'` |
| Host sets `lint.citation_example_prefixes` | plugin's `path/to/` reservation is silently lost (replace semantics) | `path/to/file.py` still passes (union semantics) |
| `path/to/file.py` later becomes a real file | passes forever, no signal | passes, with an explicit `stale exemption` note |

## Test coverage

Six discriminating tests in `tests/lint/test_citation_exists.py` pin the
token-vs-prefix choice:

- `test_plugin_default_exempts_the_citation_grammar_placeholder` — the bare
  placeholder passes with no host config.
- `test_grammar_placeholder_suffix_variants_are_exempt` — `:symbol` and
  `:line` suffixes strip to the same exempt bare path, including in the
  symbol-existence loop.
- `test_grammar_placeholder_survives_a_host_example_prefix_override` — a
  host that reconfigures `citation_example_prefixes` does not lose the
  exempt token.
- `test_confabulated_sibling_under_path_to_still_blocks` — an invented
  sibling path under `path/to/` still blocks; only the exact token is
  exempt.
- `test_confabulated_symbol_in_a_real_path_to_file_still_blocks` — an
  invented `:symbol` on a real file under `path/to/` still blocks, the
  worst case a prefix reservation would have hidden.
- `test_grammar_placeholder_reports_drift_once_it_resolves` — once
  `path/to/file.py` resolves to a real file, the result carries a `stale
  exemption` note instead of passing silently.

All pre-existing CCE-132 confabulation regression tests still fail as
expected — the fix does not weaken any other guard.

## Corpus scan

A scan across the 106 published pages confirmed the fix closed exactly the
one false positive and opened nothing else: block-failure count held at 12
(`docs/site-src/whats-new.md` still fails on nine unrelated tokens) and one
archive-lens `warn` page cleared. No page was newly unblocked by relaxing
the gate — the exempt-token route removes the false positive at the
resolver without widening what the rule tolerates.
