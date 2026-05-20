# voice_consistency rule

**Tier:** 2 (opt-in)
**Severity:** block

## What it checks

Page prose must match the voice samples provided by the orchestrator. The `content-validator` subagent receives the page text and a bundle of voice samples (recent pages from the same lens, plus optional `docs-agent-voice.md`). It evaluates:

- Tone and register (formal vs casual, technical vs prose)
- Person (consistent first/second/third)
- Average sentence length distribution
- Paragraph structure
- Typical openers and connectors

## Failure conditions

- Page drifts substantially in any of the above dimensions compared to samples.
- Message format: `"voice mismatch: <dimension>: <specifics>"`

## Why no script

Voice comparison requires LLM judgment over prose features that defy regex. The lint_runner skips this rule when invoked standalone; the subagent layer handles it.
