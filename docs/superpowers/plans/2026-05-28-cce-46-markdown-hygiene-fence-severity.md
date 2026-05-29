# CCE-46 plan — markdown_hygiene fence severity split

**Spec:** `docs/superpowers/specs/2026-05-28-cce-46-markdown-hygiene-fence-severity.md`

Three-line code change; two test surfaces. TDD: failing test → run → expect fail → minimal implementation → run → expect pass → full suite → commit.

## Task 1 — new warn-severity rule for missing language tags

**Failing test.** Create `tests/lint/test_markdown_hygiene_lang.py` with three tests:

- `test_warns_on_missing_lang_tag`: invokes `scripts/lint/markdown_hygiene_lang.py` against `tests/fixtures/markdown_hygiene/bad_no_lang.md`; expects rc=1, `out["rule"] == "markdown_hygiene_lang"`, `out["severity"] == "warn"`, message contains `"language"`.
- `test_good_passes`: same script against `good.md`; expects rc=0.
- `test_does_not_flag_structural_defect`: writes a tmp_path file with an unpaired but language-tagged fence (`"# x\n\n```python\ncode\n```\n\n```ruby\nmore\n"`); expects rc=0 from the lang rule (structure is the other rule's job).

**Run.** `python3 -m pytest tests/lint/test_markdown_hygiene_lang.py -xvs` — expect import or path failure (script does not exist).

**Implement.** Create `scripts/lint/markdown_hygiene_lang.py` with `RULE_NAME = "markdown_hygiene_lang"`, `SEVERITY = "warn"`, and a `check_path` that only flags fences without a language tag (no unpaired-fence, no heading detection).

**Run.** `python3 -m pytest tests/lint/test_markdown_hygiene_lang.py -xvs` — expect pass.

**Full suite.** `python3 -m pytest` — expect green (existing markdown_hygiene tests still pass against the unchanged-as-of-now `markdown_hygiene.py`).

**Commit.** `fix(CCE-46): add warn-severity markdown_hygiene_lang rule`.

## Task 2 — convert markdown_hygiene to structure-only

**Failing test.** Update `tests/lint/test_markdown_hygiene.py`:

- Add assertion `out["rule"] == "markdown_hygiene_structure"` and `out["severity"] == "block"` to `test_good`, `test_hierarchy`, `test_unpaired_fence_detected`.
- Move `test_no_lang` out (already moved to the lang test file in Task 1; delete here) — OR replace it with a `test_does_not_flag_missing_lang_tag` that asserts rc=0 when the only defect is a missing language tag.

**Run.** `python3 -m pytest tests/lint/test_markdown_hygiene.py -xvs` — expect fail (rule name still `markdown_hygiene`; still flags missing language).

**Implement.** In `scripts/lint/markdown_hygiene.py`:

- Change `RULE_NAME` to `"markdown_hygiene_structure"`.
- Delete the fence-language-detection loop (the block that walks `fences[::2]` and appends `"code fence at offset N has no language"`).
- Keep unpaired-fence check and heading-hierarchy check.

**Run.** `python3 -m pytest tests/lint/test_markdown_hygiene.py -xvs` — expect pass.

**Full suite.** `python3 -m pytest` — expect one failure in `test_lint_runner.py::test_runs_tier1_default` because `markdown_hygiene` no longer matches. Defer that to Task 3.

**Commit.** `fix(CCE-46): convert markdown_hygiene to structure-only block rule`.

## Task 3 — register both rules in TIER1_DEFAULT

**Failing test.** Update `tests/lint/test_lint_runner.py::test_runs_tier1_default`:

- Replace `assert "markdown_hygiene" in rules_run` with two asserts: `assert "markdown_hygiene_lang" in rules_run` and `assert "markdown_hygiene_structure" in rules_run`.

**Run.** `python3 -m pytest tests/lint/test_lint_runner.py::test_runs_tier1_default -xvs` — expect fail (TIER1_DEFAULT still has the old name).

**Implement.** In `scripts/lint/lint_runner.py:21-30`, replace `"markdown_hygiene"` with the two new names. Order: keep alphabetical-ish per existing grouping.

**Run.** `python3 -m pytest tests/lint/test_lint_runner.py::test_runs_tier1_default -xvs` — expect pass.

**Full suite.** `python3 -m pytest` — expect green.

**Commit.** `fix(CCE-46): register split markdown_hygiene rules in TIER1_DEFAULT`.

## Verification

After Task 3, `python3 -m pytest` runs end-to-end green. The orchestrator's drop path is unchanged but now receives `severity: "warn"` for missing-language findings, so the page survives. No further code changes needed.
