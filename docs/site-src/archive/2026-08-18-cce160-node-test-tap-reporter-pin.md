---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/232
synthesized_into: []
doc_kind: decision
---

# CCE-160: pin `node:test` to the TAP reporter

`tests/templates/test_sdd_fidelity_gate_node.py` shells out to `node --test` to run the SDD fidelity-gate JS suite (`docs/superpowers/templates/sdd-fidelity-gate.mjs`) inside the integrated pytest run. The wrapper parses `node:test`'s stdout for summary counts — `pass N` / `fail N` — because a suite that runs nothing still exits 0, and a plain substring check for `"pass "` would false-pass on `"pass 0"`. The parser anchored its regexes to the start of a summary line to guard against that.

That anchoring is exactly what broke.

## What went wrong

`node:test`'s default reporter writes for humans, and it colourises its output whenever `FORCE_COLOR` is set. Agent sessions commonly export `FORCE_COLOR`, whether or not anything downstream will render the output as a terminal would. When that happens, node injects an ANSI (SGR) escape code between the start of the summary line and the token the anchored regex expected — `^\s*[ℹ#]\s*pass (\d+)\b` never matches the coloured line, even though the suite ran cleanly (`pass 53`, `fail 0`, `returncode == 0`).

The result: a genuinely green JS suite was reported to `pytest` as unparseable, which the wrapper treats as a hard failure. This surfaced while landing CCE-159, in a Claude Code agent session — the one environment where `FORCE_COLOR` is reliably set and CI is not.

The failure mode has an unusually bad visibility profile: it is deterministic for every agent-run invocation and invisible to both CI and a human terminal, because neither of those sets `FORCE_COLOR`. A fix that merely tolerates both the coloured and plain formats would let a later removal of whatever pins the format regress silently — green in CI, red only for agents.

Setting `NO_COLOR=1` does not fix it. Node gives `FORCE_COLOR` precedence over `NO_COLOR`, so the obvious-looking patch — export the "disable colour" variable everyone reaches for first — would have looked right, passed review, and changed nothing. That precedence rule is worth remembering on its own the next time a Node-ecosystem tool's coloured output breaks a parser.

## The fix

Pin the reporter explicitly rather than rely on node's default selection: `node --test --test-reporter=tap`. TAP's summary lines are a machine-readable contract (`# pass 53`, `# fail 0`), not human-facing prose, so they carry no colour regardless of `FORCE_COLOR` — verified on node v26.5.0, where `FORCE_COLOR=3 node --test --test-reporter=tap` emits zero escape bytes. `tests/templates/test_sdd_fidelity_gate_node.py` now builds its `node --test` invocation with `--test-reporter=tap` and matches the summary with the `#` prefix instead of the reporter-dependent `[ℹ#]` alternation the patterns previously carried. Because TAP's `#`-prefixed wording is what the `#` half of that alternation already matched, the whole fix is the one added argv entry — the parse patterns themselves don't change shape, only the reporter that produces the text they read.

That alternation collapsing to `#` alone is deliberate, not an oversight: keeping it as tolerance for both the coloured and plain reporter formats would let a later removal of `--test-reporter=tap` pass CI green and fail only inside agent sessions — reintroducing this exact bug silently. Matching `#` only makes deleting the flag fail everywhere at once instead of nowhere visible.

The suite also gained a regression test that sets `FORCE_COLOR` explicitly rather than relying on session inheritance — the pre-existing test alone only exercises the coloured path when the person running it happens to be in an agent session, and passes vacuously everywhere else.

## Why this matters beyond the one test

No production code changed — only `CHANGELOG.md` and `tests/templates/test_sdd_fidelity_gate_node.py`. But the underlying gotcha generalizes: any stdout-parsing test or script that pattern-matches CLI output line-anchored, without pinning a machine-readable output mode, is exposed to the same `FORCE_COLOR`-shaped blind spot in agent sessions. If you're writing a parser against `node:test`, `npm`, or any other Node-ecosystem tool's default output, prefer its explicit machine-readable mode (TAP, `--json`, etc.) over the human-facing default, and test the coloured path deliberately rather than trusting session inheritance to exercise it for you.

The scope of this fix was established, not assumed: it's exactly one test. All seven production stdout-parsing call sites in `scripts/` shell out to git (`rev-parse`, `ls-files`, `ls-remote`, `remote get-url`, `branch --show-current`) or to `gh --json` via `gh_client._run_json`, and neither tool shares node's exposure — git ignores `FORCE_COLOR` entirely (that's a Node-ecosystem convention, not a universal one) and defaults `color.ui=auto`, which is off whenever stdout isn't a TTY. So this class of bug is real, but it doesn't reach the orchestrator's own production parsing today — only the JS-suite test wrapper.
