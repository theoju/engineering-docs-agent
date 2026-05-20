# Changelog

## v0.1.0 — 2026-05-19

Initial release.

### Plugin

- 7 specialized subagents (source-collector, pr-summarizer, gap-detector, page-author, content-validator, publish-verifier, notifier).
- Orchestrator skill + setup skill.
- Main authoring workflow + post-merge verify workflow.

### Lint

- Tier 1 (default-on, block): frontmatter_schema, internal_links, markdown_hygiene, footnotes, diagrams, framework_build, stub_redirect.
- Tier 2 (opt-in, block): banned_phrases, ai_tells, voice_consistency (LLM-based), terminology, second_person, paragraph_length.
- Tier 3 (advisory, warn): reading_grade, sentence_variance, duplicate_content (placeholder).

### Verification

- Tests for every lint rule (good + bad fixtures).
- Orchestrator integration tests using fake subagent outputs.
- E2E main-pipeline test with a fixture host repo.
- JSON schemas for config and state with validation tests.
