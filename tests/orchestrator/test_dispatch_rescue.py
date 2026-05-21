"""CCE-15: _rescue_json_object — extract the first balanced JSON object
from prose-contaminated subagent stdout. Defense in depth for the
Mode 2 contamination class even after --bare (Task 1) closes the
SessionStart-hook pathway.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import orchestrator_runner as runner  # noqa: E402


def test_rescue_extracts_first_balanced_object_from_prose_prefix():
    """Mirrors CCE-14 Run 4: an '★ Insight' prose block followed by the
    canonical JSON. The rescue must locate the first '{', balance to
    the matching '}', and return the parsed dict.
    """
    contaminated = (
        "`★ Insight ─────────────────────────────────────`\n"
        "The CCE-14 prompt worked: I invoked gh pr list and identified PR #9.\n"
        "`─────────────────────────────────────────────────`\n\n"
        '{"prs":[{"number":9,"url":"https://example.com/9"}],"jira_issues":[]}'
    )
    assert runner._rescue_json_object(contaminated) == {
        "prs": [{"number": 9, "url": "https://example.com/9"}],
        "jira_issues": [],
    }


def test_rescue_extracts_json_with_braces_in_string_literals():
    """The brace-balanced scan must honor JSON string state. Braces
    inside string literals (e.g. {"body": "see {detail}"}) must not
    affect depth tracking. Escaped quotes inside strings must not
    close the string early.
    """
    text = 'preamble\n{"body": "see {detail} and \\"quoted\\" text", "n": 1}\ntrailing'
    assert runner._rescue_json_object(text) == {
        "body": 'see {detail} and "quoted" text',
        "n": 1,
    }


def test_rescue_returns_none_when_no_opening_brace():
    """All-prose output (no '{' anywhere) — rescue returns None so the
    caller falls through to the original failure path.
    """
    assert runner._rescue_json_object("nothing parseable here") is None
    assert runner._rescue_json_object("") is None


def test_rescue_returns_none_when_brace_extracted_object_does_not_parse():
    """A balanced brace pair whose contents aren't valid JSON (e.g.
    Python repr, malformed) — rescue returns None. Avoids accepting
    syntactically-balanced-but-semantically-broken pseudo-JSON.
    """
    text = "header\n{'not': 'json', invalid: True}\nfooter"
    assert runner._rescue_json_object(text) is None


def test_rescue_takes_first_object_when_multiple_present():
    """The agent's contract is 'the canonical JSON is the response'.
    If multiple JSON objects appear in contaminated output, treat the
    first as canonical and any later ones as decorative — matches
    existing parse semantics.
    """
    text = 'first {"a": 1}\nsecond {"b": 2}\nthird {"c": 3}'
    assert runner._rescue_json_object(text) == {"a": 1}


import subprocess
from types import SimpleNamespace


def _fake_run_capture(captured: dict, *, stdout: str = "{}", returncode: int = 0):
    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    return fake_run


def test_dispatch_subagent_appends_rescue_reason_to_out_reasons(monkeypatch):
    """When strict parse fails but rescue succeeds, dispatch_subagent
    returns the rescued dict AND appends a labeled partial reason to
    the caller's out_reasons list.
    """
    contaminated_stdout = (
        '`★ Insight ─`\nsome prose\n`─`\n\n{"prs": [], "jira_issues": []}'
    )
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout=contaminated_stdout)
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == ["prose_contamination_rescued: source-collector"]


def test_dispatch_subagent_out_reasons_stays_empty_on_clean_parse(monkeypatch):
    """The rescue path must be cold when strict parse succeeds. No
    rescue reason appended; out_reasons stays empty.
    """
    captured: dict = {}
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run_capture(captured, stdout='{"prs": [], "jira_issues": []}'),
    )

    reasons: list[str] = []
    result = runner.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )

    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_dispatch_subagent_out_reasons_optional_backward_compatible(monkeypatch):
    """Existing callers (18 sites in this repo) call dispatch_subagent
    without out_reasons. The parameter must default to None and the
    return type must remain dict | None for those callers.
    """
    captured: dict = {}
    monkeypatch.setattr(
        subprocess, "run", _fake_run_capture(captured, stdout='{"prs": []}')
    )

    # No out_reasons argument: existing signature contract.
    result = runner.dispatch_subagent("source-collector", {}, dry_run_dir=None)
    assert result == {"prs": []}
