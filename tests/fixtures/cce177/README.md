# CCE-177 — real Claude CLI event streams

Trimmed captures of production `docs-agent-nightly` runs on
`theoju/engineering-docs-agent`, taken from the per-run
`docs-agent-subagent-forensics-<run-id>-1` artifacts while they were still
downloadable. **They are not synthetic.**

They exist because every other test of `_detect_output_token_limit_split`
(`scripts/orchestrator_runner.py`) builds its own `isSynthetic` dicts. Those
dicts agree with each other about a shape that had never been checked against
the CLI's actual output, so a field rename or a reworded resume prompt would
leave the whole suite green while the detector silently stopped firing. These
fixtures are the "verify against the actual consumer" rule applied to a data
format — the consumer being the CLI event stream.

Consumed by `tests/orchestrator/test_output_token_limit_real_streams.py`.

## The three runs

| File                                                 | Run ID        | Date  | Outcome | What it pins                                                                  |
| ---------------------------------------------------- | ------------- | ----- | ------- | ----------------------------------------------------------------------------- |
| `run-35862057776-fail-marker-last.stream.jsonl`      | `35862057776` | 09-23 | FAIL    | Marker between the final two text-carrying turns; no `tool_use` after it      |
| `run-35343242932-fail-marker-midstream.stream.jsonl` | `35343242932` | 09-18 | FAIL    | Marker with **four** real `tool_use` blocks after it (Bash, Bash, Read, Read) |
| `run-35727627405-pass-no-marker.stream.jsonl`        | `35727627405` | 09-22 | PASS    | Negative control — no synthetic turn anywhere                                 |

The 09-18 capture is the hard case and the reason a proposed refinement
("only count a marker that appears after the last `tool_use`") was rejected:
that predicate would have accepted a night whose entire `prs` array sat in the
discarded head half. See the "Measured findings" subsection of
`docs/superpowers/specs/2026-09-23-cce177-source-collector-output-ceiling-design.md`.

The 09-22 control carries **more than one** assistant turn with text, so it is
False on the marker's absence alone and not on a degenerate shape.

## Provenance

| Run           | Source artifact file                            | Original                | Kept                |
| ------------- | ----------------------------------------------- | ----------------------- | ------------------- |
| `35862057776` | `20260923T125923-source-collector.stream.jsonl` | 207 events, 1,203,745 B | 19 events, 19,875 B |
| `35343242932` | `20260918T122139-source-collector.stream.jsonl` | 175 events, 1,042,394 B | 27 events, 27,867 B |
| `35727627405` | `20260922T123452-source-collector.stream.jsonl` | 120 events, 591,799 B   | 19 events, 20,769 B |

Source path, while the artifacts lived:
`docs-agent-subagent-forensics-<run-id>-1/<timestamp>-source-collector.stream.jsonl`.
The forensics artifacts expire 14 days after each run — 09-18's around
**2026-10-02**. After that these files are the only surviving capture of the
event shape.

## How they were trimmed

Two operations, and nothing else.

**1. Events dropped.** A subset of each stream's events was kept, in original
order, by index. Nothing was reordered, synthesized or edited into place.

| Run           | Kept event indices (0-based, into the original stream)   |
| ------------- | -------------------------------------------------------- |
| `35862057776` | 0-1, 3-6, 12-14, 79-80, 195-198, 203-206                 |
| `35343242932` | 0-2, 4-6, 10-12, 115-117, 156-158, 160-161, 163, 166-174 |
| `35727627405` | 0-1, 3-6, 10-12, 27-29, 62-63, 115-119                   |

What was dropped is the repetitive middle: long runs of `Bash`/`Read`
tool-call round trips and their `system: thinking_tokens` events. What was
kept is the `system: init` header, at least one `rate_limit_event`, a
representative early tool-call round trip, the turns immediately around the
split (or around the final answer, for the control), and the terminating
`result` event.

Because events were dropped, per-run counts in a fixture are **lower** than
the production counts quoted in the spec. Assistant-turns-carrying-text:
13 → 3 (09-23), 9 → 4 (09-18), 8 → 3 (09-22). Each is still greater than one,
so the detector's second condition is satisfied exactly as it was in
production.

**2. Long strings truncated.** Every string value longer than **200
characters**, anywhere in a kept event, was cut to its first 200 characters.
No marker was appended — a truncated value is simply 200 characters long.
The final answers were 159,475 / 161,217 / 36,316 characters; this is where
the ~50x size reduction comes from.

**The one exception: the synthetic marker event is kept complete and
byte-unmodified.** Its text is 183 characters and it is the exact string
`_detect_output_token_limit_split` matches on, so truncating it would defeat
the purpose of the fixture.
`test_the_real_resume_prompt_still_starts_with_the_matched_prefix` asserts its
length is 183 to keep it that way.

Everything else is verbatim: `type`, `isSynthetic`, `subtype`, `message.role`,
`message.content` block shapes and `content[].type`, plus the surrounding
`uuid` / `session_id` / `parent_tool_use_id` / `usage` / `timestamp` fields.
That fidelity is the entire point of the fixtures.

## Secrets

Scanned before committing for GitHub/AWS/Atlassian/Slack/Anthropic/OpenAI
token shapes, JWTs, private-key headers, `Authorization:` and
`user:password@host` URLs, and `key|secret|token|password = <value>`
assignments. Clean.

What remains and is intentionally kept: session and message UUIDs, GitHub
Actions runner paths under `/home/runner/work/...`, the CLI version, and
`"apiKeySource": "none"`. None is a credential.
