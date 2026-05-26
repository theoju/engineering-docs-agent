# engineering-docs-agent — agent guidelines

A Claude Code plugin: seven specialized subagents turn merged PRs, commits, and Jira issues into a single nightly docs-update PR — voice-matched authoring, tiered linting, gap detection, and post-merge publish verification.

## Generic plugin — runs on ANY host repo (critical)

This repo ships a Claude Code **plugin**, not a one-off tool. Its skills — `/engineering-docs-agent:engineering-docs-agent` (the nightly docs-PR runner) and `/engineering-docs-agent:engineering-docs-agent-setup` (scaffolds the docs site) — run against **arbitrary host repositories**. This repo is simultaneously the plugin's source _and_ one dogfood host; never conflate the two.

Design every capability (S/D/API/M/C and the orchestrator) **generic-first, convention-optimized**:

- **Behavior is driven by detection and config, never by hardcoded paths.** `scripts/`, `agents/schemas/`, `docs/superpowers/{specs,plans}` are _this host's_ layout — they are examples in fixtures and defaults, never assumptions baked into capability code. Read inputs from the `site:` config block (`sources`, `extractors`, `docs_dir`) and from `setup_discover.py` detection.
- **Degrade gracefully.** When a host lacks a convention (no specs/plans, no Python package, no OpenAPI schema, no decision sources), the affected capability **skips or falls back cleanly** — it never errors and never emits an empty artifact. Detection drives the path taken.
- **Markedly better on Claude Code / superpowers repos** that carry `docs/superpowers/{specs,plans}`, but **nothing hard-requires that convention.**
- **Tests use fixtures that represent arbitrary hosts**, not this repo's tree. A capability that only works because it found this repo's own directories is a bug.

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
- Merge on a green _integrated_ suite, never on GitHub's "mergeable" flag (that only means no textual conflict). Before merging, merge the target branch into yours locally and run the full `python3 -m pytest` against the combined tree. With stacked branches, land the base first, then siblings one at a time, re-testing between each (`git fetch` before verifying — `origin/main` goes stale after an API-side merge).
- Shared helpers are contracts. Before changing the signature or behavior of a cross-capability helper (`archive_indexes.parse_frontmatter`, anything in `state_io.py`, `contracts.py`), `grep -rn` its callers repo-wide and update them in the same change; never let two branches refactor the same helper in different directions.
- Python: stdlib-first. New runtime deps require explicit justification in the spec.
- Tests: pytest. TDD for new behavior (failing test → implementation → green). All tests use the fixture-driven dry-run path; the production Claude CLI dispatch is monkeypatched in unit tests.
- Subagent contracts: each agent's `.md` file in `agents/` defines the canonical input/output shape. JSON schemas in `agents/schemas/` codify the output shape. Dataclasses in `scripts/contracts.py` provide the typed view.
- Linting: the host repo's `lint.tier1: default` setting enables all 7 Tier-1 rules. Tier-2 and Tier-3 are opt-in per rule.
- Config invariant: every `docs.lens_paths` entry must be covered by at least one `docs.agent_editable_paths` glob (validated at load by `_validate_lens_paths_are_editable`). The editable glob may be narrower than the lens path (e.g., a sandbox sub-path of a top-level lens).
