# CCE-56 — Comprehensive setup-guide rewrite

## Background

`docs/setup-guide.md` was a 46-line stub. Earlier in this session I drafted a 367-line comprehensive replacement (7-part structure: prereqs → one-time → per-host → validate → per-language notes → add-ons → troubleshooting → checklist + reference). The draft was written from working session memory, then stashed (uncommitted) before pivoting to CCE-55 + CCE-59. After those merged today, main diverged from the draft assumptions.

## Problem

Shipping the draft as-is would land stale claims in main's permanent doc tree:

1. Part 5 (actionlint pre-merge gate) embeds the pre-CCE-59 workflow YAML with a `pull_request paths:` filter — CCE-59 just removed that filter to unblock non-workflow PRs.
2. Part 2.2 lists `.github/workflows/docs-agent-verify.yml` as a setup-skill output — the file doesn't exist on main.
3. Part 6 troubleshooting describes `prose_contamination_rescued` as firing on subagent output-discipline failures — after CCE-55 it only fires on genuinely anomalous contamination (not fence wraps).
4. Reference section lists CCE-55 as `(open)` — it's now Done.
5. Reference section omits CCE-59 — operationally critical for setup (actionlint required-check + path-filter footgun).
6. README.md has no cross-link to the setup guide, and its install section duplicates content the guide owns.

Plus three tone/precision drifts (voice-sample loading path, "stdlib-first" claim, pytest dogfood-host scoping).

## Goal

Ship a docs/setup-guide.md and README.md that accurately reflect main as of the merge. Establish setup-guide.md as the canonical onboarding doc; reduce README to quickstart + link.

## Non-goals

- Re-architecting the 7-part structure. The structure is sound; only content needs corrections.
- Validating the guide by walking a fresh host end-to-end. That's CCE-57 (claude-code-self-assessment) and CCE-58 (advanced-data-import-system) — the guide gets exercised through those onboarding flows.
- Touching scripts/, agents/, or workflows. CCE-56 is doc-only.

## Design

### Substantive drift fixes (D1–D6)

| ID  | Section                | Current                                                                                         | Target                                                                                                 |
| --- | ---------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| D1  | Part 5 actionlint YAML | `pull_request: { branches: [main], paths: [".github/workflows/**", ".github/actionlint.yml"] }` | `pull_request: { branches: [main] }` — no paths filter; reference CCE-59                               |
| D2  | Part 2.2 outputs list  | Lists `docs-agent-verify.yml` as committed                                                      | Remove (file isn't shipped on main yet)                                                                |
| D3  | Part 6 troubleshooting | Describes `prose_contamination_rescued` as firing on every fence wrap                           | Update: post-CCE-55, fence wraps strip cleanly; banner only fires on genuinely anomalous contamination |
| D4  | Reference              | `CCE-55 (open)`                                                                                 | `CCE-55: code-fence strip (Done)`                                                                      |
| D5  | Reference              | CCE-59 missing                                                                                  | Add: `CCE-59: actionlint pull_request paths-filter removal`                                            |
| D6  | README cross-link      | None                                                                                            | Add a "Detailed setup" link to docs/setup-guide.md right after the intro                               |

### Tone/precision fixes (D7–D9, optional)

| ID  | Section       | Current                                                                                            | Target                                                                                                                       |
| --- | ------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| D7  | Part 4 Python | "Voice samples load from `CLAUDE.md` (per `scripts/state_io.py`)"                                  | "Voice samples load from `voice.sample_paths` in config, with `CLAUDE.md` appended when present (per `scripts/state_io.py`)" |
| D8  | Part 4 Python | "The orchestrator is stdlib-first"                                                                 | "The orchestrator prefers stdlib where feasible (PyYAML is the one external runtime dep)"                                    |
| D9  | Part 4 Python | "Test runner is pytest. Workflows that gate on `pytest (3.11)` + `pytest (3.12)` cover the matrix" | Same, prefixed with "On this dogfood host:" to scope the claim                                                               |

### README.md changes (D10)

Replace the current ~15-line `## Install` section with:

```markdown
## Install

1. `claude plugin marketplace add <this-repo>`
2. `claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace`
3. `claude /engineering-docs-agent-setup` in the host repo

For per-host setup (GitHub App registration, secrets, branch protection, validation, troubleshooting), see [docs/setup-guide.md](docs/setup-guide.md).
```

The secret table moves out of README and lives only in the setup guide.

## Test plan

- `python3 -m pytest -q` — full suite (sanity, no regressions). Expected: 635 passed, 3 skipped (unchanged from main; doc-only changes shouldn't affect tests).
- Markdown hygiene block-tier lint — manual check by reading the rendered file. Specifically: no unpaired code fences, no heading jumps.
- Code-reviewer subagent pass on the diff — same Stage 4 verification used for CCE-55.

## Files changed

- `docs/setup-guide.md` — substantive drift fixes + tone fixes (~30-50 line delta).
- `README.md` — cross-link + install-section trim (~10-15 line delta).
- `docs/superpowers/specs/2026-05-29-cce56-setup-guide-rewrite-design.md` (this file) — spec.
- `docs/superpowers/plans/2026-05-29-cce56-setup-guide-rewrite.md` — plan.

## Risk

- **Race with the in-flight clean-replay nightly run (26660051279)**: if the nightly's page-author writes to `docs/setup-guide.md`, the resulting PR will conflict. Mitigation: ship CCE-56 before the nightly PR opens, or merge in sequence after manually resolving. If the nightly doesn't touch setup-guide.md, no conflict.
- **README change might bleed into other doc paths**: low risk, README only owns the quickstart now; per-host content is unambiguously in the guide.

## Out of scope

- `docs-agent-verify.yml` implementation. Filed/tracked separately; CCE-56 just removes the false reference to it.
- Per-language host validation (JS/TS, hybrid CI). Covered by CCE-57 and CCE-58.
- Telemetry on doc-guide reads (e.g., "how often does the guide get followed"). Not a v1 concern.
