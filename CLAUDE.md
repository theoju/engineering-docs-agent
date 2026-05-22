# engineering-docs-agent — agent guidelines

A Claude Code plugin: seven specialized subagents turn merged PRs, commits, and Jira issues into a single nightly docs-update PR — voice-matched authoring, tiered linting, gap detection, and post-merge publish verification.

## Jira context

All Jira work for this project lives in:

- **Instance:** `https://designitright.atlassian.net`
- **Project:** Claude-Code-Extensions
- **Key prefix:** `CCE`

Every branch and PR for this repo should reference a CCE issue:

- **Branch naming:** `<type>/CCE-<number>-<short-slug>` (e.g. `feat/CCE-12-jira-input-wiring`, `fix/CCE-7-empty-path-guard`)
- **Commit messages:** include `CCE-<number>` in the subject line or trailer when the change implements a specific ticket. Hardening / refactor commits that close multiple tickets may list them in the body.
- **PR titles:** prefix or include `CCE-<number>` so the Atlassian GitHub integration auto-links.

The `/ship` skill's Jira stage uses `extract-jira-key.sh` to pull the key from the branch name or the first commit subject. Keep the format above so it lands automatically.

## Voice & style

This file is read by the docs-agent's `load_voice_samples` helper (per `scripts/state_io.py`). Keep prose:

- Direct and concrete. Avoid hedging ("perhaps", "might consider", "it could be argued").
- Second person ("you", "your") when addressing the reader. Third person ("the orchestrator", "the runner") when describing system behavior.
- Short paragraphs. One idea per paragraph.
- Code names match `file_path:line_number` for navigability.

## Plugin conventions

- All work happens on a feature branch off `main`. Direct commits to `main` are not allowed.
- Python: stdlib-first. New runtime deps require explicit justification in the spec.
- Tests: pytest. TDD for new behavior (failing test → implementation → green). All tests use the fixture-driven dry-run path; the production Claude CLI dispatch is monkeypatched in unit tests.
- Subagent contracts: each agent's `.md` file in `agents/` defines the canonical input/output shape. JSON schemas in `agents/schemas/` codify the output shape. Dataclasses in `scripts/contracts.py` provide the typed view.
- Linting: the host repo's `lint.tier1: default` setting enables all 7 Tier-1 rules. Tier-2 and Tier-3 are opt-in per rule.
- Config invariant: every `docs.lens_paths` entry must be covered by at least one `docs.agent_editable_paths` glob (validated at load by `_validate_lens_paths_are_editable`). The editable glob may be narrower than the lens path (e.g., a sandbox sub-path of a top-level lens).
