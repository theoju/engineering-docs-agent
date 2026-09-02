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

The obvious-looking counter-patch doesn't work, either: `NO_COLOR=1` does not suppress the escape codes here, because node gives `FORCE_COLOR` precedence over it. That patch would look right, pass review, and change nothing — the failure mode this ticket closes would have shipped again under a different diagnosis.

## The fix

Pin the reporter explicitly rather than rely on node's default selection: `node --test --test-reporter=tap`. TAP's summary lines are a machine-readable contract (`# pass 53`, `# fail 0`), not human-facing prose, so they carry no colour regardless of `FORCE_COLOR`. `tests/templates/test_sdd_fidelity_gate_node.py` now builds its `node --test` invocation with `--test-reporter=tap` and matches the summary with the `#` prefix instead of the reporter-dependent `[ℹ#]` alternation. Verified directly on node v26.5.0: `FORCE_COLOR=3 node --test --test-reporter=tap` emits zero escape bytes.

That collapse from `[ℹ#]` to `#` alone is deliberate, not incidental tightening: keeping both branches as tolerance would let a later removal of `--test-reporter=tap` pass CI green and fail only inside agent sessions — the exact bug this closes, reintroduced silently. Matching `#` only makes deleting the flag fail everywhere at once instead of nowhere visible.

The unparseable-summary assertion also now `repr()`s stdout rather than printing it raw. An unparseable summary usually carries control characters, which a terminal renders invisibly — printing raw output that looks perfectly readable sends the reader chasing their own diff instead of the bytes actually returned.

The suite also gained a regression test that sets `FORCE_COLOR` explicitly rather than relying on session inheritance — the pre-existing test alone only exercises the coloured path when the person running it happens to be in an agent session, and passes vacuously everywhere else.

## Why the fix is a reporter pin, not escape-stripping

Pinning the reporter was chosen over the belt-and-braces alternative of stripping ANSI escapes from whatever reporter's output before parsing it. Stripping ties with pinning on every case it can handle, but it cannot rescue the one case where pinning would also fail: a reporter that is withdrawn or renamed produces no matching output to strip in the first place. Pinning to a machine-readable contract (TAP) sidesteps that failure mode instead of adding a layer to compensate for it.

## Why this matters beyond the one test

No production code changed — only `CHANGELOG.md` and `tests/templates/test_sdd_fidelity_gate_node.py`. The scope of the underlying gotcha was established rather than assumed: none of this plugin's production stdout-parsing sites in `scripts/` share the exposure. Every one of them shells out to `git` (`rev-parse`, `ls-files`, `ls-remote`, `remote get-url`, `branch --show-current`) or to `gh --json` via `gh_client._run_json`, and `git` ignores `FORCE_COLOR` entirely — that's a Node-ecosystem convention, not a universal one — defaulting instead to `color.ui=auto`, which is off whenever stdout isn't a TTY (as it never is under `subprocess.run`).

That scoping is the generalizable lesson: any stdout-parsing test or script that pattern-matches CLI output line-anchored, without pinning a machine-readable output mode, is exposed to the same `FORCE_COLOR`-shaped blind spot in agent sessions — but only if the tool it's parsing actually honors `FORCE_COLOR` in the first place. If you're writing a parser against `node:test`, `npm`, or any other Node-ecosystem tool's default output, prefer its explicit machine-readable mode (TAP, `--json`, etc.) over the human-facing default, and test the coloured path deliberately rather than trusting session inheritance to exercise it for you. Before assuming the same fix is needed elsewhere, check whether the tool you're wrapping honors `FORCE_COLOR` at all — `git`, notably, does not.
