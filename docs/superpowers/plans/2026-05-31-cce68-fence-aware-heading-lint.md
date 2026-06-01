# CCE-68 — Fence-aware heading hierarchy scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `markdown_hygiene_structure` from counting `#`-prefixed lines inside fenced code blocks as Markdown headings. Pair `FENCE_RE` matches greedily and mask any `HEADING_RE` match whose offset falls inside a pair.

**Architecture:** The rule's `check_path()` already runs `FENCE_RE.finditer` for the unpaired-fence check. Extend it to build a list of `(start, end)` pairs covering fenced regions, then skip `HEADING_RE` matches that fall inside one. Single function, no signature change, no new imports.

**Tech Stack:** Python stdlib (`re`), pytest with subprocess invocation. No new runtime deps.

**Test runner:** `python3 -m pytest`

**Commit trailer (required on every commit):** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

**Branch:** `fix/CCE-68-fence-aware-heading-lint` (already checked out off main `6e812a5`).

**Never use:** `-f`, `--force`, `--no-verify`, `--amend`.

**Spec:** `docs/superpowers/specs/2026-05-31-cce68-fence-aware-heading-lint.md`

---

### Task 1: Failing regression tests — heading inside fence must not be counted

**Files:**

- Modify: `tests/lint/test_markdown_hygiene_structure.py` (append two tests at EOF)

- [ ] **Step 1: Append the tests**

Append to `tests/lint/test_markdown_hygiene_structure.py`:

````python
def test_fenced_yaml_comment_does_not_trigger_hierarchy_jump(tmp_path):
    """CCE-68: a `# ` comment inside a fenced code block must not be
    counted as a heading. The bootstrap-style pattern is real h1 → h2 →
    fenced YAML with `# comment` → real h3. Without fence-aware scanning,
    the YAML comment counts as h1 and the real h3 reads as an h1→h3 jump."""
    p = tmp_path / "fenced.md"
    p.write_text(
        "# Real H1\n\nintro prose\n\n## Real H2\n\nconfig example:\n\n"
        "```yaml\n"
        "# lens and page mappings (this is a YAML comment, not a heading)\n"
        "key: value\n"
        "```\n\n"
        "### Real H3\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0, f"fence-aware scanning should not flag this; got {out}"
    assert out["results"][0]["ok"] is True


def test_heading_inside_fenced_block_is_ignored(tmp_path):
    """CCE-68 (variant): a literal `###` line inside a fenced markdown
    example must not contribute to hierarchy tracking. Demonstrative
    snippets are valid."""
    p = tmp_path / "fenced-heading.md"
    p.write_text(
        "# Real H1\n\n## Real H2\n\nAn example structure:\n\n"
        "```markdown\n### Section title\nSome content\n```\n\n"
        "### Real H3\n"
    )
    cfg = tmp_path / "c.yml"
    cfg.write_text("{}")
    rc, out = _run([p], cfg)
    assert rc == 0
````

- [ ] **Step 2: Run the tests — confirm BOTH FAIL**

Run: `python3 -m pytest tests/lint/test_markdown_hygiene_structure.py -v 2>&1 | tail -15`

Expected: the two new tests FAIL (with `rc=1` and `hierarchy jumps from h1 to h3` message); existing tests continue to PASS.

- [ ] **Step 3: Commit the failing tests**

````bash
git add tests/lint/test_markdown_hygiene_structure.py
git commit -m "$(cat <<'EOF'
test(CCE-68): failing regression for fence-aware heading lint

Two appended tests: (1) a YAML comment inside ```yaml ... ``` must not
count as h1 (the exact CCSA bootstrap-page pattern that triggered the
false positive on PR #105); (2) a `### Section title` inside ```markdown
... ``` must not contribute to hierarchy tracking. Both currently fail —
`HEADING_RE` matches `#`-prefixed lines anywhere in the file including
inside fences. Task 2 introduces fence-aware filtering.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

### Task 2: Lint rule — mask fenced regions before heading scan

**Files:**

- Modify: `scripts/lint/markdown_hygiene_structure.py` — extend `check_path()`.

- [ ] **Step 1: Add fenced-region mask**

In `scripts/lint/markdown_hygiene_structure.py:check_path()`, locate (current lines ~37-44):

```python
    fences = list(FENCE_RE.finditer(text))
    if len(fences) % 2 != 0:
        problems.append(f"unpaired code fence (count={len(fences)})")
    prev_level = 0
    for m in HEADING_RE.finditer(text):
        level = len(m.group(1))
        if prev_level and level > prev_level + 1:
            problems.append(f"heading hierarchy jumps from h{prev_level} to h{level}")
        prev_level = level
```

Replace with:

````python
    fences = list(FENCE_RE.finditer(text))
    if len(fences) % 2 != 0:
        problems.append(f"unpaired code fence (count={len(fences)})")
    # CCE-68: pair fences greedily and mask headings inside them. A `#`
    # line inside ```yaml``` (or any fenced block) is a code comment, not
    # a Markdown heading. Without masking, false-positive hierarchy
    # jumps fire on structurally-correct documents.
    fenced_regions = [
        (fences[i].start(), fences[i + 1].end())
        for i in range(0, len(fences) - 1, 2)
    ]

    def _in_fence(offset: int) -> bool:
        return any(start <= offset < end for start, end in fenced_regions)

    prev_level = 0
    for m in HEADING_RE.finditer(text):
        if _in_fence(m.start()):
            continue
        level = len(m.group(1))
        if prev_level and level > prev_level + 1:
            problems.append(f"heading hierarchy jumps from h{prev_level} to h{level}")
        prev_level = level
````

- [ ] **Step 2: Run Task 1's tests — confirm BOTH PASS**

Run: `python3 -m pytest tests/lint/test_markdown_hygiene_structure.py -v 2>&1 | tail -15`

Expected: all tests PASS (the two new ones, plus the four existing ones).

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest 2>&1 | tail -5`

Expected: 669 passed, 3 skipped (was 667 after CCE-70 branch; +2 from the two new tests; no regressions).

- [ ] **Step 4: Commit the lint-rule fix**

````bash
git add scripts/lint/markdown_hygiene_structure.py
git commit -m "$(cat <<'EOF'
fix(CCE-68): markdown_hygiene_structure masks headings inside fenced code

The rule's HEADING_RE = r"^(#{1,6})\s+\S" with re.MULTILINE matches `#`-
prefixed lines anywhere in the file, including inside ```fenced``` blocks.
A YAML comment like `# lens and page mappings` was counted as h1, making
the next real h3 look like an h1→h3 jump.

Fix: pair FENCE_RE matches greedily into (start, end) ranges; skip any
HEADING_RE match whose offset falls inside a range. The unpaired-fence
detection is unchanged. No signature change, no new imports.

Caught by CCE-67's smoke test on CCSA (partial PR #105, closed). Mistakenly
filed initially as a page-author bug; root cause is in the lint rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

### Task 3: Full pytest verification

**Files:** (none — verification only)

- [ ] **Step 1: Run full pytest suite**

Run: `python3 -m pytest -v 2>&1 | tail -20`

Expected: all tests pass (669+ / 3 skipped). Pay particular attention to:

- `tests/lint/test_markdown_hygiene_structure.py` — 4 existing + 2 new tests
- `tests/lint/test_markdown_hygiene_lang.py` — sibling rule unaffected
- `tests/lint/test_lint_runner.py` — overall runner contract unchanged

- [ ] **Step 2: Verify branch state**

```bash
git log --oneline main..HEAD
git status --short
```

Expected: 3 commits ahead of main (spec+plan, failing tests, lint fix). Clean working tree.

- [ ] **Step 3: No commit — hand off to /ship**

---

## Out of scope

- CommonMark tokenizer adoption.
- Indented-fence support.
- Other lint-rule false-positives.
- Updating page-author's prompt (page-author's output was correct).

## After Task 3 — handoff

Surface ship-readiness. Controller invokes `/ship` separately.
