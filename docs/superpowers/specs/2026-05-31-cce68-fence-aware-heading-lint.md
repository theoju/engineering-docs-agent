---
status: draft
ticket: CCE-68
related: CCE-57, CCE-67
created: 2026-05-31
---

# CCE-68 — Fence-aware heading hierarchy scan in `markdown_hygiene_structure`

## Goal

Stop the `markdown_hygiene_structure` lint rule from counting `#`-prefixed lines INSIDE fenced code blocks as Markdown headings. Today those lines participate in the heading-hierarchy check and cause false-positive `lint_block` rejections of structurally-correct documents.

## Background

The CCE-67 smoke test on CCSA opened partial PR #105 with `partial_reasons` containing:

```
lint_block: docs/2026-05-31-engineering-docs-agent-bootstrap.md
  markdown_hygiene_structure: heading hierarchy jumps from h1 to h3
```

Inspection of the file: page-author wrote correct markdown — `# H1` → `## H2` → `### H3`. Between the H2 and the H3, a fenced YAML block contained:

```
# lens and page mappings (this is a YAML comment, not a heading)
```

The lint rule's `HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)` matches that YAML comment as an `h1`. The heading sequence as the rule perceives it becomes `h1 → h2 → h1 → h3`, and the last transition flags as a jump.

The fix lives in the lint rule, not in page-author. The rule already detects fences (via `FENCE_RE` for the unpaired-fence check); extending it to mask fenced regions from the heading scan is small, local, and lossless.

## Approach

Pair `FENCE_RE` matches greedily (matches[0]+matches[1], matches[2]+matches[3], …) to produce a list of `(start_offset, end_offset)` ranges representing fenced regions. When iterating `HEADING_RE`, skip any match whose `.start()` falls inside one of those ranges.

If fences are unpaired (odd count), keep the existing "unpaired code fence" `problems` entry AND still mask any pair-wise regions we did identify. Headings outside all detected pairs are still checked. This degrades cleanly on broken input — better than ignoring all hierarchy when fences look wrong.

Rejected alternatives:

- **Pre-strip fences from `text` then re-run `HEADING_RE` on the stripped text.** Cleaner conceptually, but loses offset alignment for any future feature that wants to report headings with their original line numbers. The masking approach keeps the original `text` intact.
- **Add a tokenizer.** Overengineered. The rule is a 50-line regex scanner; preserving that shape is correct.
- **Update page-author to avoid `# ` comments in YAML examples.** Wrong layer — the bug is in the lint, not the output. Demonstrative YAML/shell examples should be allowed to contain comments.

## What changes

### 1. Lint rule — `scripts/lint/markdown_hygiene_structure.py`

In `check_path()`, after `fences = list(FENCE_RE.finditer(text))` (current line ~37):

```python
fenced_regions = [
    (fences[i].start(), fences[i + 1].end())
    for i in range(0, len(fences) - 1, 2)
]

def _in_fence(offset: int) -> bool:
    return any(start <= offset < end for start, end in fenced_regions)
```

Then in the existing `for m in HEADING_RE.finditer(text)` loop:

```python
for m in HEADING_RE.finditer(text):
    if _in_fence(m.start()):
        continue
    level = len(m.group(1))
    ...
```

No signature change. No new imports. The unpaired-fence detection stays identical.

### 2. Regression tests — `tests/lint/test_markdown_hygiene_structure.py`

Append two tests:

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

## What does NOT change

- The rule's name, severity (`block`), command-line interface, or output schema.
- The unpaired-fence detection (`if len(fences) % 2 != 0`).
- The heading-hierarchy detection logic itself — only the input set it operates on shrinks.
- Other lint rules in `scripts/lint/`. The `markdown_hygiene_lang` sibling rule has its own logic and isn't affected.
- Existing tests in `test_markdown_hygiene_structure.py` (`test_good`, `test_hierarchy`, `test_unpaired_fence_detected`, etc.) must continue to pass.

## Error handling

- **Unpaired fences (odd count)**: the existing `problems.append("unpaired code fence ...")` fires. We still mask whatever pairs we found (pair-wise iteration stops at `len(fences) - 1`). Headings inside any matched pair are masked; headings outside any pair are scanned normally. No silent failure.
- **A heading inside a fence is followed by a heading outside**: `prev_level` correctly resumes from the last NON-MASKED heading, so the hierarchy gap calculation continues seamlessly. Tests cover this.
- **No fences in the document**: `fenced_regions == []`, `_in_fence` returns False for every offset, behavior is identical to today.

## Testing

1. New tests in `tests/lint/test_markdown_hygiene_structure.py` (two functions).
2. All existing `tests/lint/test_markdown_hygiene_structure.py` tests must remain green.
3. `python3 -m pytest` must stay green overall.
4. Post-merge: re-trigger docs-agent-nightly on CCSA. Confirm the bootstrap page (or its replacement) does not lint-block on `markdown_hygiene_structure` for a fence-internal `#` line.

## Migration

None. The rule's contract is identical; only false-positive frequency drops. Existing fixtures keep their semantics.

## Out of scope

- Adding a CommonMark/markdown-it style tokenizer.
- Other lint-rule false-positives that may exist on the same fixtures.
- Updating page-author's prompt — page-author's output was correct.

## Risks

- **Indented fences**: the `FENCE_RE = re.compile(r"^```(\S*)\s*$", re.MULTILINE)` only matches column-zero fences. Indented code blocks (4-space prefix) are not captured, and headings inside them would not be masked. The lint's current behavior for indented blocks is the same — out of scope. Accept current limitation; document in a follow-up if it surfaces.
- **Mixed fence styles (``` and ~~~)**: only backtick fences are recognized by `FENCE_RE`. Out of scope; consistent with current behavior.

## Success criteria

1. The two new tests fail without the fix and pass with it.
2. All existing tests in `test_markdown_hygiene_structure.py` remain green.
3. The CCSA scheduled nightly produces a non-partial PR for a document containing a fenced YAML/code block with `# `-prefixed lines.

## References

- `scripts/lint/markdown_hygiene_structure.py:32-44` — `check_path()` to extend
- `scripts/lint/markdown_hygiene_structure.py:20-21` — `FENCE_RE`, `HEADING_RE`
- `tests/lint/test_markdown_hygiene_structure.py` — pattern for new tests
- CCSA partial PR #105 (closed; preserved in workflow run forensics artifact `docs-agent-subagent-forensics-26728572465`)
- CCE-67 — content-validator path fix that made this lint behavior visible
