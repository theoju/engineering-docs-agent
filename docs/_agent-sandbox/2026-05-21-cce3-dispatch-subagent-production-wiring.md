---
status: draft
sources:
  - https://github.com/theoju/engineering-docs-agent/pull/3
synthesized_into: []
---

# CCE-3: `dispatch_subagent` Production Wiring

**PR #3** completed the production wiring of `dispatch_subagent` by resolving three compounding failures at the subprocess dispatch boundary. All three shared the same root cause: the Claude CLI invocation was treated as a fire-and-forget shell command rather than a configured agent dispatch.

## What broke and why

The first live Mode B smoke run against ADIS exposed the failures. Without the fixes, the LLM returned markdown clarifying questions instead of JSON output, loaded the wrong `CLAUDE.md` from a different repo, and could not resolve or execute any declared agent tools non-interactively.

## Fix A: Prompt framing

Payloads are now wrapped in `<inputs>...</inputs>` markers. The wrapper includes pinned execution instructions: `Execute the Job`, `Return ONLY`, `no prose`, `no markdown fences`, `no clarifying questions`.

Without this framing, the LLM analyzed the JSON payload rather than executing the agent job. The markers shift the model into execution mode.

## Fix B: CWD propagation

`subprocess.run()` now accepts a `cwd: Path | None = None` parameter. All nine call sites in `orchestrator_runner.py` and `verify_runner.py` thread `repo_root` through so each agent subprocess starts with the correct working directory.

This matters because the Claude CLI loads `CLAUDE.md` relative to the working directory. Running without an explicit `cwd` caused agents to pick up the wrong project's instructions — confirmed by the smoke run referencing files from a different repo.

## Fix C: Plugin discovery and tool permissions

The `argv` list now includes two additional flags:

- `--plugin-dir` — auto-resolved via `Path(__file__).resolve().parent.parent`, so the plugin is always found regardless of whether it is user-installed.
- `--allowedTools` — set to the full union of declared agent tools: `Bash Read Write Edit WebFetch`.

Without `--plugin-dir`, agents only resolved if the plugin happened to be user-installed globally. Without `--allowedTools`, non-interactive dispatch silently dropped tool calls, leaving agents unable to read or write files.

## Updated dispatch contract

After this PR, every `dispatch_subagent` call carries:

| Parameter | Value |
|---|---|
| `cwd` | `repo_root` (forwarded from caller) |
| `--plugin-dir` | `Path(__file__).resolve().parent.parent` |
| `--allowedTools` | `Bash Read Write Edit WebFetch` |
| Prompt wrapping | `<inputs>…</inputs>` + pinned execution instructions |

## Deferred items

The following were noted in the PR body and are not addressed here:

- Strict output-schema enforcement (validate agent JSON before passing downstream).
- Per-agent tool narrowing (grant only the tools each agent declares, not the full union).
- `partial_reasons` hygiene (consistent structure across all failure paths).
- A `--live` pytest gate with CI cost controls for end-to-end dispatch tests.

## Stack note

This PR was stacked on CCE-2 (`fix/CCE-2-dispatch-cli-surface`). Merge order matters — CCE-2 must land before CCE-3 for the combined CLI surface to be correct.
