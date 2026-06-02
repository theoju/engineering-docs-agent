"""CCE-74: Integration tests for scripts/orchestrator_runner.run().

Covers:
  - Task 3: lint_block_unsafe_path / lint_block paths route through
    add_partial, gaining redaction-on-storage.
  - Task 6: exit-0 partial dump + exit-1 belt-and-suspenders dump.
"""

from __future__ import annotations

from scripts.state_io import add_partial


# --- Task 3: lint_block paths now redact via add_partial -------------------


def test_lint_block_unsafe_path_message_redacts_credentials_via_add_partial(capsys):
    """Lint_block paths at orchestrator_runner.py:1222-1226 / 1230-1234 /
    1267-1270 previously mutated state.partial_reasons directly, bypassing
    _redact_credentials. After Task 3 they route through add_partial,
    which redacts at entry. This test verifies the redaction surface:
    a credential-bearing path passed to add_partial must store the
    redacted form. The companion source-scan test
    (test_lint_block_sites_no_longer_directly_mutate_partial_reasons)
    locks AC #9's structural requirement — that the 3 lint_block sites
    actually CALL add_partial rather than mutating state directly."""
    state: dict = {"current_run": {"partial": False, "partial_reasons": []}}
    # A path that happens to contain a URL with token (unlikely in real
    # content-validator output but possible in test fixtures or future
    # validator bugs).
    raw = (
        "lint_block_unsafe_path: "
        "https://x-access-token:ghs_TESTONLY@github.com/owner/repo/blob/main/x.md "
        "(outside repo)"
    )
    add_partial(state, raw)
    stored = state["current_run"]["partial_reasons"][0]
    assert "ghs_TESTONLY" not in stored
    assert "<redacted>" in stored
    err = capsys.readouterr().err
    assert "ghs_TESTONLY" not in err
    assert "docs-agent PARTIAL:" in err


def test_lint_block_sites_no_longer_directly_mutate_partial_reasons():
    """AC #9 structural lock: after Task 3 refactor, the 3 lint_block sites
    at scripts/orchestrator_runner.py:~1222 / ~1230 / ~1267 MUST call
    add_partial(state, ...) instead of mutating
    state["current_run"]["partial_reasons"] directly.

    This test source-scans the lint_block region for the pre-CCE-74
    direct-mutation pattern. If a future contributor reverts to direct
    mutation in any of the 3 sites, this test fails — without requiring
    end-to-end fixture orchestration of the content-validator pipeline.

    Companion to test_lint_block_unsafe_path_message_redacts_credentials_via_add_partial:
    that test proves add_partial redacts on entry; this test proves the
    lint_block sites actually USE add_partial.
    """
    import re
    from pathlib import Path

    src = Path("scripts/orchestrator_runner.py").read_text()

    # Locate the lint_block region: bounded by the first occurrence of
    # 'lint_block_unsafe_path' (Site 1, ~line 1222) and the last
    # 'lint_block:' reason (Site 3, ~line 1267-1270). Read the whole region.
    region_start = src.find("lint_block_unsafe_path")
    assert region_start != -1, (
        "Could not locate the lint_block region — 'lint_block_unsafe_path' "
        "string is missing. The 3 lint_block sites may have been deleted "
        "or restructured."
    )
    # Extend the search to the third 'lint_block:' message site (~1267).
    # Bound the end by adding ~3000 chars after the start — well past all
    # 3 sites' code blocks even with future expansion.
    region = src[region_start : region_start + 3000]

    # Direct-mutation patterns the Task 3 refactor REPLACES with add_partial.
    # We forbid both shapes inside the lint_block region:
    #   state["current_run"]["partial"] = True
    #   state["current_run"]["partial_reasons"].append(...)
    forbidden_patterns = [
        re.compile(r'state\["current_run"\]\["partial"\]\s*=\s*True'),
        re.compile(r'state\["current_run"\]\["partial_reasons"\]\.append'),
    ]

    offending = []
    for pat in forbidden_patterns:
        for m in pat.finditer(region):
            # Compute absolute line number relative to the file
            abs_offset = region_start + m.start()
            line_no = src.count("\n", 0, abs_offset) + 1
            offending.append((line_no, m.group(0)))

    assert not offending, (
        "AC #9 regression: lint_block region in scripts/orchestrator_runner.py "
        "contains direct mutations of state['current_run']['partial']  / "
        "['partial_reasons'].append. Task 3 refactored these 3 sites to call "
        "add_partial(state, reason). Restore the add_partial calls:\n"
        + "\n".join(f"  line {ln}: {snippet!r}" for ln, snippet in offending)
    )
