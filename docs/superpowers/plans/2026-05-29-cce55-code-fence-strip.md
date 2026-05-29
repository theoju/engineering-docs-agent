# CCE-55 Code-Fence Strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a whole-string code-fence stripper to `scripts/orchestrator_runner.py` so subagent dispatches that wrap their JSON in ` ```json ... ``` ` parse cleanly without firing the `prose_contamination_rescued` partial banner. Preserve `_rescue_json_object` as fallback for anomalous contamination.

**Architecture:** New private helper `_strip_code_fence(text)` lives in `scripts/orchestrator_runner.py`. Pre-pass before `json.loads(canonical_text)` inside `dispatch_subagent`. Whole-string regex match on `^\s*```[A-Za-z0-9]*\s*\n(.*)\n```\s*$` with `DOTALL`. On match: strip. On miss: pass-through (no behavior change). Existing `_rescue_json_object` continues to handle non-fence contamination unchanged.

**Tech Stack:** Python 3.11+, stdlib `re` (no new dependencies). Tests use pytest + monkeypatch (same pattern as `tests/orchestrator/test_dispatch_rescue.py`).

---

## File structure

**Files to create:**

- `tests/orchestrator/test_strip_code_fence.py` — unit tests for `_strip_code_fence` helper (~8 tests).
- `tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt` — captured fence-wrapped output from PR #69's forensics (the 1640-byte sample), used as integration fixture.

**Files to modify:**

- `scripts/orchestrator_runner.py` — add `_strip_code_fence` helper (~10 lines after the existing `_rescue_json_object` at line 174); wire it into `dispatch_subagent` between `canonical_text` strip (line 470) and `json.loads(canonical_text)` (line 474).
- `tests/orchestrator/test_dispatch_rescue.py` — add 2 dispatch-pipeline integration tests at the end of the file.

**Files NOT changed:**

- `agents/pr-summarizer.md`, `agents/gap-detector.md`, `agents/source-collector.md` — instruction text already says "no markdown fences"; the model ignores it sometimes anyway.
- `agents/schemas/*.json` — no schema change.
- `scripts/contracts.py` — no dataclass change.
- `.github/workflows/*.yml` — no workflow change.

---

## Task 1: Capture the real-world fixture

**Files:**

- Create: `tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt`

- [ ] **Step 1: Copy the real PR #69 fence-wrapped capture into a stable fixture**

The PR #69 forensics artifact has been downloaded to `/tmp/cce55-fx-v2/`. Copy the smallest representative fence-wrapped sample so it lives in-tree as a regression fixture.

```bash
mkdir -p tests/fixtures/cce55
cp /tmp/cce55-fx-v2/20260529T155357-pr-summarizer.stdout.txt \
   tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt
```

Verify the fixture starts with ` ```json ` and ends with ` ``` `:

````bash
head -1 tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt
# Expected: ```json
tail -1 tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt
# Expected: ```
````

- [ ] **Step 2: Commit the fixture**

````bash
git add tests/fixtures/cce55/pr_summarizer_fence_wrap.stdout.txt
git commit -m "$(cat <<'EOF'
test(CCE-55): capture fence-wrapped pr-summarizer fixture from PR #69 forensics

Lifted from /tmp/cce55-fx-v2/20260529T155357-pr-summarizer.stdout.txt
(workflow run 26647051715, the run that produced PR #69). This is the
canonical "subagent wraps JSON in ```json fence" failure mode that
CCE-55 will normalize at parse time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

## Task 2: TDD — `_strip_code_fence` unit tests (RED)

**Files:**

- Create: `tests/orchestrator/test_strip_code_fence.py`

- [ ] **Step 1: Write all 8 failing tests**

````python
"""CCE-55: _strip_code_fence — normalize the markdown code-fence wrap
the LLM emits ~19% of the time despite explicit "no fences" instructions.

Whole-string match only. Any contamination that isn't exactly a fence
wrap falls through to _rescue_json_object unchanged.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_strip_unwraps_json_lang_fence():
    """The most common observed case: ```json\\n<obj>\\n```."""
    text = '```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_no_lang_fence():
    """No language tag — bare triple-backtick fence."""
    text = '```\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_trailing_whitespace():
    """Trailing newlines/spaces after the closing fence — common in
    LLM output that adds a final newline.
    """
    text = '```json\n{"a": 1}\n```\n\n  '
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_unwraps_leading_whitespace():
    """Leading whitespace before the opening fence."""
    text = '\n  ```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text) == '{"a": 1}'


def test_strip_preserves_clean_json():
    """Already-clean JSON is returned unchanged (pure pass-through)."""
    text = '{"a": 1, "b": [2, 3]}'
    assert runner._strip_code_fence(text) == text


def test_strip_does_not_match_prose_around_fence():
    """Prose before OR after the fence breaks the whole-string match.
    These cases fall through to _rescue_json_object as anomalous
    contamination (and still emit prose_contamination_rescued).
    """
    text_prefix = 'preamble\n```json\n{"a": 1}\n```'
    assert runner._strip_code_fence(text_prefix) == text_prefix
    text_suffix = '```json\n{"a": 1}\n```\nepilogue'
    assert runner._strip_code_fence(text_suffix) == text_suffix


def test_strip_does_not_match_mid_string_backticks():
    """Stray backticks inside a string literal aren't a fence wrap."""
    text = '{"note": "see `code` block"}'
    assert runner._strip_code_fence(text) == text


def test_strip_real_pr69_fixture_round_trips_to_valid_pr_summarizer_json():
    """Integration check: the actual fence-wrapped output captured from
    PR #69's forensics strips cleanly AND the result is valid JSON
    matching the pr-summarizer schema's required top-level keys.
    """
    fixture = (
        Path(__file__).parent.parent / "fixtures" / "cce55"
        / "pr_summarizer_fence_wrap.stdout.txt"
    )
    raw = fixture.read_text()
    stripped = runner._strip_code_fence(raw)
    assert stripped != raw, "strip should have removed the fence wrap"
    parsed = json.loads(stripped)
    assert "pr_number" in parsed
    assert "doc_targets" in parsed
````

- [ ] **Step 2: Run the test file — confirm RED**

```bash
python3 -m pytest tests/orchestrator/test_strip_code_fence.py -v
```

Expected: 8 errors — `AttributeError: module 'orchestrator_runner' has no attribute '_strip_code_fence'`.

---

## Task 3: GREEN — implement `_strip_code_fence`

**Files:**

- Modify: `scripts/orchestrator_runner.py` (insert helper after line 174, the existing `_rescue_json_object`)

- [ ] **Step 1: Add the import**

Find the existing `import` block near the top of `scripts/orchestrator_runner.py` and confirm `import re` is present. If not, add it alphabetically among the stdlib imports.

- [ ] **Step 2: Add the helper after `_rescue_json_object`**

Insert this function immediately after the closing of `_rescue_json_object` (after line 174):

````python
# CCE-55: whole-string match for the most common LLM contamination —
# the model wraps its JSON in a markdown code fence despite explicit
# "no fences" instructions in both the agent contract and the
# orchestrator's execution-framing prompt. Observed rate on the
# 2026-05-29 docs-agent-nightly run that produced PR #69: ~19%
# (3 of 16 schema-bearing dispatches). The fence content is byte-equal
# to the JSON the model intended, so stripping here lets the strict
# json.loads in dispatch_subagent succeed without triggering the
# rescue path's prose_contamination_rescued partial reason.
_FENCE_RE = re.compile(
    r"\A\s*```[A-Za-z0-9]*\s*\n(.*)\n```\s*\Z",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """If text is exactly a markdown code-fence wrap, return the inner
    content. Otherwise return text unchanged.

    The match is whole-string (\\A ... \\Z). Any prose before or after
    the fence breaks the match and the original text is returned so the
    caller falls through to _rescue_json_object for anomalous
    contamination handling.
    """
    m = _FENCE_RE.match(text)
    if m is None:
        return text
    return m.group(1)
````

- [ ] **Step 3: Run the unit tests — confirm GREEN**

```bash
python3 -m pytest tests/orchestrator/test_strip_code_fence.py -v
```

Expected: 8 passed.

- [ ] **Step 4: Commit**

````bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_strip_code_fence.py
git commit -m "$(cat <<'EOF'
feat(CCE-55): add _strip_code_fence helper for benign markdown-wrap normalization

Subagents wrap JSON in ```json ... ``` ~19% of the time despite explicit
"no markdown fences" instructions in both the agent contracts (e.g.
agents/pr-summarizer.md:71, :159) and the orchestrator's execution-framing
prompt (scripts/orchestrator_runner.py:119-126). The fence contents are
byte-equal to the intended JSON.

_strip_code_fence does a whole-string regex match (\A ... \Z) against
the fence pattern. On match: strip. On miss: return unchanged so the
existing _rescue_json_object path handles anomalous contamination.

8 unit tests cover: json-lang fence, no-lang fence, trailing whitespace,
leading whitespace, clean-JSON pass-through, prose-around-fence
non-match, mid-string backticks non-match, and a real-world fixture
round-trip from PR #69's forensics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

## Task 4: TDD — dispatch-pipeline integration tests (RED)

**Files:**

- Modify: `tests/orchestrator/test_dispatch_rescue.py` (append at end of file)

- [ ] **Step 1: Add 2 integration tests at the end of the file**

````python
def test_dispatch_subagent_fence_wrapped_no_partial_reason(monkeypatch):
    """CCE-55: when the subagent wraps its JSON in a ```json``` markdown
    fence (the most common benign contamination), dispatch_subagent
    strips the wrap, json.loads succeeds, and out_reasons stays empty.
    No prose_contamination_rescued partial banner for this class.
    """
    fence_wrapped_stdout = '```json\n{"prs": [], "jira_issues": []}\n```'
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout=fence_wrapped_stdout)
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == [], "fence wrap is benign; rescue banner must not fire"


def test_dispatch_subagent_prose_with_embedded_fence_still_emits_rescue(monkeypatch):
    """CCE-55 regression guard: prose surrounding a code fence (i.e.
    actually anomalous contamination, not a clean wrap) must still flow
    through _rescue_json_object and emit prose_contamination_rescued.
    The whole-string fence match doesn't apply when prose is on either
    side — that's the existing rescue path's responsibility.
    """
    anomalous_stdout = (
        '`★ Insight ─`\nprose preamble\n`─`\n\n'
        '```json\n{"prs": [], "jira_issues": []}\n```\n'
        'trailing prose'
    )
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout=anomalous_stdout)
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == ["prose_contamination_rescued: source-collector"]
````

- [ ] **Step 2: Run the new tests — confirm RED**

```bash
python3 -m pytest tests/orchestrator/test_dispatch_rescue.py::test_dispatch_subagent_fence_wrapped_no_partial_reason -v
```

Expected: FAIL — `assert reasons == []` fails because the current code path emits `prose_contamination_rescued`.

```bash
python3 -m pytest tests/orchestrator/test_dispatch_rescue.py::test_dispatch_subagent_prose_with_embedded_fence_still_emits_rescue -v
```

Expected: this one may PASS already (anomalous text falls through the strip and hits rescue). Document if so; this is a regression guard, not a new behavior.

---

## Task 5: GREEN — wire `_strip_code_fence` into `dispatch_subagent`

**Files:**

- Modify: `scripts/orchestrator_runner.py:470-485`

- [ ] **Step 1: Re-read the existing block before editing**

The relevant block currently lives at `scripts/orchestrator_runner.py:470-485`:

```python
    canonical_text = canonical_text.strip()
    if not canonical_text:
        return None
    try:
        return json.loads(canonical_text)
    except json.JSONDecodeError:
        # CCE-15: strict parse failed. Try prose-tolerant rescue. If we
        # extract a valid object, surface the rescue event via
        # out_reasons so dispatch_validated can roll it into the
        # pipeline's partial_reasons summary.
        rescued = _rescue_json_object(canonical_text)
        if rescued is not None:
            if out_reasons is not None:
                out_reasons.append(f"prose_contamination_rescued: {name}")
            return rescued
        return None
```

- [ ] **Step 2: Edit the block to strip the fence first**

Replace the block above with:

```python
    canonical_text = canonical_text.strip()
    if not canonical_text:
        return None
    # CCE-55: strip the markdown code-fence wrap if present. This is a
    # whole-string match — fence-only inputs strip to clean JSON and
    # parse without firing the rescue partial banner. Anything that
    # isn't a pure fence wrap passes through unchanged so the existing
    # _rescue_json_object path still handles anomalous contamination.
    parse_text = _strip_code_fence(canonical_text)
    try:
        return json.loads(parse_text)
    except json.JSONDecodeError:
        # CCE-15: strict parse failed. Try prose-tolerant rescue against
        # the ORIGINAL canonical_text (not the strip output) — if the
        # strip didn't change anything, both are identical; if it did,
        # we still want the rescue to see the full text in case the
        # contamination is more complex than a simple fence wrap.
        rescued = _rescue_json_object(canonical_text)
        if rescued is not None:
            if out_reasons is not None:
                out_reasons.append(f"prose_contamination_rescued: {name}")
            return rescued
        return None
```

- [ ] **Step 3: Run the integration tests — confirm GREEN**

```bash
python3 -m pytest tests/orchestrator/test_dispatch_rescue.py -v
```

Expected: all tests pass, including the 2 new ones.

- [ ] **Step 4: Run the full suite**

```bash
python3 -m pytest -q
```

Expected: 626 passed, 3 skipped (was 624 passed before this change; +2 from the new dispatch tests). The 8 strip-helper tests added in Task 3 push the count to 634 passed.

Adjust expected count if the file structure dictates otherwise — the key invariant is **no test that was passing before this change starts failing**, and **all new tests pass**.

- [ ] **Step 5: Commit**

````bash
git add scripts/orchestrator_runner.py tests/orchestrator/test_dispatch_rescue.py
git commit -m "$(cat <<'EOF'
feat(CCE-55): wire _strip_code_fence into dispatch_subagent pre-parse

When a subagent wraps its JSON in a ```json fence, the strip
normalizes it before strict json.loads, and the parse succeeds without
flowing through _rescue_json_object. No partial_reasons banner fires
for this benign class.

When the contamination is anomalous (prose around a fence, ★ Insight
preamble, etc.), the whole-string strip is a no-op and the original
canonical_text falls through to _rescue_json_object as before. The
prose_contamination_rescued banner still fires for those cases — the
banner now signals genuine contamination, not decorative whitespace.

PR #69 forensics (workflow run 26647051715) showed 3 fence-wrapped
dispatches out of 16 (~19%). After this change, those would be silent
clean parses; the banner would only fire on the residual anomalous
class.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
````

---

## Task 6: Final verification

- [ ] **Step 1: Run the full suite from a clean state**

```bash
python3 -m pytest -q 2>&1 | tail -5
```

Expected: `634 passed, 3 skipped` (or equivalent — see Task 5 step 4 note on counting).

- [ ] **Step 2: Replay the PR #69 forensics fixture through the pipeline mentally**

Verify (no command required) that for each of the 3 contaminated samples in `/tmp/cce55-fx-v2/`:

- `20260529T155357-pr-summarizer.stdout.txt` — starts ` ```json `, ends ` ``` ` → after strip, parses to a 7-key pr-summarizer dict → schema valid → no partial reason.
- `20260529T155629-pr-summarizer.stdout.txt` — same shape → strip + parse → no partial reason.
- `20260529T160611-gap-detector.stdout.txt` — same shape → strip + parse → no partial reason.

If we re-ran the same nightly today against the same input PRs, `partial_reasons` would be empty.

- [ ] **Step 3: Hand off to /ship**

The plan controller will invoke `/ship` next. No additional manual steps before that.
