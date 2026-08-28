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

The obvious patch — set `NO_COLOR=1` alongside `FORCE_COLOR` — does not work. Node gives `FORCE_COLOR` precedence over `NO_COLOR`, so a caller can't override the colourisation from the outside; anything that respects both env vars still colourises when `FORCE_COLOR` is set. That patch would have looked right, passed review, and changed nothing.

## The fix

Pin the reporter explicitly rather than rely on node's default selection: `node --test --test-reporter=tap`. TAP's summary lines are a machine-readable contract (`# pass 53`, `# fail 0`), not human-facing prose, so they carry no colour regardless of `FORCE_COLOR`. `tests/templates/test_sdd_fidelity_gate_node.py` now builds its `node --test` invocation with `--test-reporter=tap` and matches the summary with the `#` prefix instead of the reporter-dependent `[ℹ#]` alternation.

Stripping ANSI escape codes from the captured output before parsing was considered and rejected. It ties with pinning the reporter on the cases both can handle, but it can't rescue the one case pinning is designed for: a reporter that gets withdrawn or renamed produces no output to strip in the first place, so escape-stripping alone leaves the parser exposed to the next default-reporter change. Pinning the reporter removes the dependency on the default entirely, rather than tolerating whatever the default currently emits.

The suite also gained a regression test that sets `FORCE_COLOR` explicitly rather than relying on session inheritance — the pre-existing test alone only exercises the coloured path when the person running it happens to be in an agent session, and passes vacuously everywhere else.

## Why this matters beyond the one test

No production code changed — only `CHANGELOG.md` and `tests/templates/test_sdd_fidelity_gate_node.py`. But the underlying gotcha generalizes: any stdout-parsing test or script that pattern-matches CLI output line-anchored, without pinning a machine-readable output mode, is exposed to the same `FORCE_COLOR`-shaped blind spot in agent sessions. If you're writing a parser against `node:test`, `npm`, or any other Node-ecosystem tool's default output, prefer its explicit machine-readable mode (TAP, `--json`, etc.) over the human-facing default, and test the coloured path deliberately rather than trusting session inheritance to exercise it for you.
