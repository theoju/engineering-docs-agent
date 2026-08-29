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

The result: a genuinely green JS suite was reported to `pytest` as unparseable, which the wrapper treats as a hard failure. This surfaced while landing CCE-159, in a Claude Code agent session — the one environment where `FORCE_COLOR` is reliably set and CI is not, and the failure was misdiagnosed twice in that session because the assertion message named the parse, not the bytes.

The failure mode has an unusually bad visibility profile: it is deterministic for every agent-run invocation and invisible to both CI and a human terminal, because neither of those sets `FORCE_COLOR`. A fix that merely tolerates both the coloured and plain formats would let a later removal of whatever pins the format regress silently — green in CI, red only for agents.

The obvious first patch — setting `NO_COLOR=1` alongside `FORCE_COLOR` — does not work: node gives `FORCE_COLOR` precedence over `NO_COLOR`, so that patch would have looked right, passed review, and changed nothing.

## The fix

Pin the reporter explicitly rather than rely on node's default selection: `node --test --test-reporter=tap`. TAP's summary lines are a machine-readable contract (`# pass 53`, `# fail 0`), not human-facing prose, so they carry no colour regardless of `FORCE_COLOR` — verified on node v26.5.0, where `FORCE_COLOR=3 node --test --test-reporter=tap` emits zero escape bytes. `tests/templates/test_sdd_fidelity_gate_node.py` now builds its `node --test` invocation with `--test-reporter=tap` and matches the summary with the `#` prefix only, instead of the reporter-dependent `[ℹ#]` alternation that used to tolerate both the TAP and default-reporter forms.

That narrowing to `#` alone is deliberate, not incidental. The old `[ℹ#]` alternation existed to tolerate the default reporter's own uncoloured form, which prefixes summary lines with `ℹ`. Keeping that tolerance around would let a later removal of `--test-reporter=tap` pass CI green — CI never sets `FORCE_COLOR`, so the default reporter's uncoloured `ℹ` line would still match the alternation there — and fail only inside agent sessions, silently reintroducing this exact bug. Matching `#` only, TAP's token and TAP's alone, makes deleting the flag fail everywhere at once, which is the point: the test can no longer pass by accident on an environment that happens not to colourise.

An alternative was considered and rejected: stripping ANSI escape codes from the captured stdout before parsing, rather than pinning the reporter. It was evaluated against a throwaway state model (on a prototype branch, never merged) that ran candidate mechanisms over several situations, and it ties with pinning on the cases both handle — but loses on the one case pinning survives and stripping cannot: a withdrawn or renamed reporter produces no output to strip in the first place, so stripping has no fallback for that failure mode while pinning fails loudly and immediately.

The suite also gained a regression test that sets `FORCE_COLOR` explicitly rather than relying on session inheritance (`test_the_gate_survives_an_environment_that_forces_colour` in `tests/templates/test_sdd_fidelity_gate_node.py`) — the pre-existing test alone only exercises the coloured path when the person running it happens to be in an agent session, and passes vacuously everywhere else. And the wrapper's unparseable-summary assertion message now renders stdout via `repr()` instead of printing it raw: control characters (like a stray SGR escape) render invisibly in a terminal, so a raw print of an unparseable summary looks perfectly readable and sends the reader chasing their own diff instead of the actual bytes — which is exactly what happened during the misdiagnosis this ticket traces back to.

## Why this matters beyond the one test

No production code changed — only `CHANGELOG.md` and `tests/templates/test_sdd_fidelity_gate_node.py`. But the underlying gotcha generalizes: any stdout-parsing test or script that pattern-matches CLI output line-anchored, without pinning a machine-readable output mode, is exposed to the same `FORCE_COLOR`-shaped blind spot in agent sessions. If you're writing a parser against `node:test`, `npm`, or any other Node-ecosystem tool's default output, prefer its explicit machine-readable mode (TAP, `--json`, etc.) over the human-facing default, and test the coloured path deliberately rather than trusting session inheritance to exercise it for you.

Scope was measured rather than assumed before treating this as a one-off: the repo's other production stdout-parsing call sites in `scripts/` parse `git` subprocess output (`rev-parse`, `ls-files`, `ls-remote`, `remote get-url`, `branch --show-current`) plus `gh_client._run_json` reading `gh --json`. Neither is exposed to this class of bug — `git` ignores `FORCE_COLOR` entirely (it's a Node-ecosystem convention, not a general one) and defaults `color.ui=auto`, which is off whenever stdout isn't a TTY, as it never is under `subprocess.run`. So the fix is scoped to the one Node-ecosystem parser this codebase has.
