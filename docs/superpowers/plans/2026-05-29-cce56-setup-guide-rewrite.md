# CCE-56 Setup Guide Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Single coordinator pass — this is a prose rewrite with known drift items, not a TDD code change. Each task below is a contiguous Edit on docs/setup-guide.md or README.md, then verify.

**Goal:** Fix 6 substantive + 3 tone drifts in the stashed setup-guide draft, add a README cross-link, trim README's duplicated install content. Ship a doc that accurately reflects main as of CCE-55 + CCE-59 merge.

**Architecture:** Doc-only delta. No code changes. Each task is one Edit call.

**Tech Stack:** Markdown.

---

## File structure

**Files to modify:**

- `docs/setup-guide.md` — substantive drift fixes (D1, D2, D3, D4, D5) + tone fixes (D7, D8, D9)
- `README.md` — add cross-link to setup guide (D6); collapse duplicated install section to quickstart (D10)

**Files NOT changed:**

- `scripts/`, `agents/`, `.github/workflows/`, `agents/schemas/`, `tests/`
- The setup-guide's 7-part structure (intact)

---

## Task 1: D1 — actionlint YAML in Part 5

**Files:** `docs/setup-guide.md`, the actionlint code block in Part 5

- [ ] Locate the embedded `actionlint.yml` example in Part 5 (around lines 236-265). It has:

```yaml
on:
  pull_request:
    branches: [main]
    paths:
      - ".github/workflows/**"
      - ".github/actionlint.yml"
  push:
    branches: [main]
    paths:
      - ".github/workflows/**"
      - ".github/actionlint.yml"
```

- [ ] Replace with the post-CCE-59 form:

```yaml
on:
  pull_request:
    # actionlint is a required status check; if it doesn't run, GitHub
    # treats the check as "not yet passing" and blocks merge on every
    # non-workflow PR. No paths filter — actionlint runs ~5s, cheap enough
    # to gate every PR. See CCE-59.
    branches: [main]
  push:
    # post-merge runs on main only when workflows actually change
    branches: [main]
    paths:
      - ".github/workflows/**"
      - ".github/actionlint.yml"
```

- [ ] Verify by diff: the only difference is the removal of the `pull_request paths:` block and the addition of the comment.

---

## Task 2: D2 — remove docs-agent-verify.yml reference

**Files:** `docs/setup-guide.md`, Part 2.2 outputs list

- [ ] Find the line in Part 2.2 that lists `.github/workflows/docs-agent-verify.yml` as a setup-skill output.

- [ ] Delete that single bullet. The remaining bullet (`docs-agent-nightly.yml — the cron workflow`) stays.

- [ ] If there's surrounding prose that depends on the docs-agent-verify reference, simplify so it reads cleanly without it.

---

## Task 3: D3 — `prose_contamination_rescued` description in Part 6

**Files:** `docs/setup-guide.md`, Part 6 troubleshooting

- [ ] Locate the `prose_contamination_rescued` symptom block in Part 6.

- [ ] Replace the "Status: tracked as CCE-55, not yet fixed. Content is safe to merge; banner is signal-noise until the upstream fix lands." with:

> **Status (post-CCE-55):** Pure markdown code-fence wraps (the most common contamination class) are now stripped at parse time and don't trigger the banner. If this banner now appears on a docs-agent PR, the contamination is genuinely anomalous — investigate the per-dispatch forensics artifact uploaded by the nightly workflow (CCE-41).

- [ ] Update the "Root cause" line to reflect that fence wraps are no longer the cause. The genuine cause is now: prose preambles, trailing prose, or other shapes that the whole-string fence strip doesn't normalize away.

---

## Task 4: D4 + D5 — Reference section CCE-55 status + add CCE-59

**Files:** `docs/setup-guide.md`, Reference section near end

- [ ] Find the line `- **CCE-55**: \`prose_contamination_rescued\` (open).`

- [ ] Replace with: `- **CCE-55**: Strip benign markdown fence wraps before strict JSON parse (Done).`

- [ ] Add immediately after the CCE-55 line:

```
- **CCE-59**: Remove `pull_request` paths filter on actionlint workflow — required-check footgun fix (Done).
```

- [ ] Verify the rest of the list is unchanged.

---

## Task 5: D7, D8, D9 — Part 4 tone fixes

**Files:** `docs/setup-guide.md`, Part 4 Python hosts

- [ ] Replace "Voice samples load from `CLAUDE.md` (per `scripts/state_io.py`)" with "Voice samples load from `voice.sample_paths` in config, with `CLAUDE.md` appended when present (per `scripts/state_io.py`)".

- [ ] Replace "The orchestrator is stdlib-first" with "The orchestrator prefers stdlib where feasible (PyYAML is the one external runtime dep)".

- [ ] Prefix the pytest/test-runner sentence with "On this dogfood host:" so the claim is scoped, not implied universal.

---

## Task 6: D6 + D10 — README.md cross-link + install trim

**Files:** `README.md`

- [ ] Read the current `## Install` (or equivalent) section.

- [ ] Replace it with:

```markdown
## Install

1. `claude plugin marketplace add <this-repo>`
2. `claude plugin install engineering-docs-agent@engineering-docs-agent-marketplace`
3. `claude /engineering-docs-agent-setup` in the host repo

For per-host setup (GitHub App registration, secrets, branch protection, validation, troubleshooting), see [docs/setup-guide.md](docs/setup-guide.md).
```

- [ ] Verify the secrets table that previously lived in README is now gone (the setup guide already has it in Part 2.4).

- [ ] If the README has other sections after Install that are not affected by the trim (Self-hosting, Architecture, etc.), leave them as-is.

---

## Task 7: Validate

- [ ] `python3 -m pytest -q` → expect 635 passed, 3 skipped (unchanged baseline).

- [ ] Visually scan the rendered markdown for: unpaired code fences, broken cross-links, heading-level jumps. Specifically check:
  - The actionlint YAML block in Part 5 closes its fence cleanly.
  - The new CCE-59 bullet in Reference doesn't break the list.
  - The README → setup-guide link uses the relative path `docs/setup-guide.md`.

- [ ] Quick grep for stale references: `grep -n "docs-agent-verify\|(open)\|prose_contamination_rescued.*not yet fixed" docs/setup-guide.md` — expect 0 matches.

---

## Task 8: Ship via /ship

- [ ] Commit spec + plan first (similar to CCE-55 pattern).
- [ ] Commit the doc changes.
- [ ] Invoke `/ship` for the standard pipeline: pre-flight → test → verify-agent → simplify (skip — prose) → code-review → push + PR → jira.

If the in-flight nightly run completes during this work and produces a PR that touches `docs/setup-guide.md`, decide merge order at that point. Otherwise ship clean and let the nightly base-branch-sync if needed.
