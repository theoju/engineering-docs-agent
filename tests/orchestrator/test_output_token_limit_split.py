"""CCE-177: an answer split by the CLI's output-token ceiling is detected
and refused.

When a subagent's JSON payload is large enough to hit the CLI's
maxOutputTokens ceiling mid-object, the CLI injects a synthetic user turn
("Output token limit hit. Resume directly...") and the model finishes the
JSON in a SECOND assistant message. `_extract_final_assistant_text` keeps
only the LAST assistant message, so the half carrying `{"prs": [` is
discarded and the orchestrator parses a fragment.

Detection names what happened; the `return None` is the load-bearing half.
A tail fragment that *happens* to parse must never be accepted as the whole
answer — the run would advance the watermark past PRs it never documented
(the CCE-151 class).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import orchestrator_runner as orun  # noqa: E402

# The real CLI marker, verbatim from the 2026-09-18/20/23 forensics streams.
_LIMIT_TEXT = "Output token limit hit. Resume directly — no apology, no recap."


# --------------------------------------------------------------------------
# Stream builders
# --------------------------------------------------------------------------


def _assistant(*texts: str, tool_use: bool = False) -> dict:
    content: list[dict] = [{"type": "text", "text": t} for t in texts]
    if tool_use:
        content.insert(
            1 if len(content) > 1 else 0,
            {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {}},
        )
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _limit_turn(text: str = _LIMIT_TEXT) -> dict:
    return {
        "type": "user",
        "isSynthetic": True,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _tool_result_turn() -> dict:
    """An ordinary (non-synthetic) user turn carrying a tool result."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "[]"}
            ],
        },
    }


def _ndjson(events: list[dict]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


class _FakeCompleted:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _dispatch(monkeypatch, debug_dir: Path, events: list[dict]) -> tuple:
    """Run dispatch_subagent against a faked CLI emitting `events`."""
    monkeypatch.setattr(
        orun.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=_ndjson(events)),
    )
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(debug_dir))
    reasons: list[str] = []
    result = orun.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )
    return result, reasons


# --------------------------------------------------------------------------
# The detector itself
# --------------------------------------------------------------------------


def test_detector_fires_on_two_assistant_turns_around_the_synthetic_marker():
    events = [
        _assistant('{"prs": [{"number": 1, "url": "u"}],'),
        _limit_turn(),
        _assistant(' "jira_issues": []}'),
    ]
    assert orun._detect_output_token_limit_split(events) is True


def test_detector_matches_the_marker_case_insensitively_after_stripping():
    events = [
        _assistant("head"),
        _limit_turn("  OUTPUT TOKEN LIMIT HIT. Resume directly.  "),
        _assistant("tail"),
    ]
    assert orun._detect_output_token_limit_split(events) is True


def test_detector_reads_a_synthetic_turn_whose_content_is_a_plain_string():
    """The CLI normally emits a block list; a bare string must still match."""
    marker = {"type": "user", "isSynthetic": True, "message": {"content": _LIMIT_TEXT}}
    assert (
        orun._detect_output_token_limit_split(
            [_assistant("head"), marker, _assistant("tail")]
        )
        is True
    )


def test_detector_ignores_a_non_synthetic_user_turn_with_the_same_text():
    """Only the CLI's own synthetic resume turn counts. A model or tool that
    echoes the phrase must not fabricate a truncation."""
    echo = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": _LIMIT_TEXT}]},
    }
    assert (
        orun._detect_output_token_limit_split(
            [_assistant("head"), echo, _assistant("tail")]
        )
        is False
    )


def test_detector_needs_more_than_one_assistant_turn_with_text():
    """The marker alone is not enough: with a single assistant text turn there
    is no split half to have been discarded. Pins the AND, so dropping the
    assistant-count condition is caught here."""
    events = [_assistant("only answer"), _limit_turn(), _assistant(tool_use=True)]
    assert orun._detect_output_token_limit_split(events) is False


def test_detector_ignores_a_synthetic_turn_carrying_other_text():
    events = [
        _assistant("head"),
        {
            "type": "user",
            "isSynthetic": True,
            "message": {"content": [{"type": "text", "text": "Please continue."}]},
        },
        _assistant("tail"),
    ]
    assert orun._detect_output_token_limit_split(events) is False


# --------------------------------------------------------------------------
# dispatch_subagent wiring
# --------------------------------------------------------------------------


def test_split_answer_returns_none_and_names_the_agent(tmp_path, monkeypatch):
    """Spec test 1 — the observed production shape."""
    result, reasons = _dispatch(
        monkeypatch,
        tmp_path,
        [
            _assistant('{"prs": [{"number": 221, "url": "https://x/221"}],'),
            _limit_turn(),
            _assistant(' "jira_issues": [{"key": "CCE-101"}]}'),
        ],
    )
    assert result is None
    assert reasons == ["output_token_limit_truncated: source-collector"]


def test_split_answer_still_leaves_its_forensics_stream_on_disk(tmp_path, monkeypatch):
    """Placement guard: the refusal sits AFTER the forensics write, so the
    run that needs diagnosing most still has its .stream.jsonl."""
    events = [_assistant('{"prs": ['), _limit_turn(), _assistant("]}")]
    result, _reasons = _dispatch(monkeypatch, tmp_path, events)

    assert result is None
    stream = next(p for p in tmp_path.iterdir() if p.name.endswith(".stream.jsonl"))
    assert stream.read_text() == _ndjson(events)


def test_a_parseable_tail_fragment_is_still_refused(tmp_path, monkeypatch):
    """Spec test 2 — the silent-corruption guard.

    The tail is valid, schema-satisfying JSON on its own, so every layer
    below dispatch would wave it through as the whole answer while the PRs
    named in the discarded head go undocumented. This test is what fails if
    the `return None` is ever deleted.
    """
    tail = '{"prs": [], "jira_issues": []}'
    assert json.loads(tail) == {"prs": [], "jira_issues": []}, "fixture sanity"

    result, reasons = _dispatch(
        monkeypatch,
        tmp_path,
        [
            _assistant('{"prs": [{"number": 221, "url": "https://x/221"}], "jira'),
            _limit_turn(),
            _assistant(tail),
        ],
    )
    assert result is None, "a tail that parses is still only the tail"
    assert reasons == ["output_token_limit_truncated: source-collector"]


def test_a_clean_single_message_run_is_unaffected(tmp_path, monkeypatch):
    """Spec test 3 — the detector must be cold on a normal run."""
    result, reasons = _dispatch(
        monkeypatch, tmp_path, [_assistant('{"prs": [], "jira_issues": []}')]
    )
    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_one_message_with_several_text_blocks_does_not_trip(tmp_path, monkeypatch):
    """Spec test 4 — the CCE-14 interleaved-tool_use shape. One assistant
    message whose text is split around a tool_use block is normal, and
    `_extract_final_assistant_text` already concatenates it correctly."""
    result, reasons = _dispatch(
        monkeypatch,
        tmp_path,
        [
            _assistant('{"prs": [],', ' "jira_issues": []}', tool_use=True),
        ],
    )
    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_a_multi_turn_tool_using_run_does_not_trip(tmp_path, monkeypatch):
    """Two assistant turns with text, but no synthetic marker — an ordinary
    tool-using conversation. Only the LAST turn is the answer, as before."""
    result, reasons = _dispatch(
        monkeypatch,
        tmp_path,
        [
            _assistant("Let me list the PRs.", tool_use=True),
            _tool_result_turn(),
            _assistant('{"prs": [], "jira_issues": []}'),
        ],
    )
    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


def test_simple_print_mode_has_no_events_and_is_untouched(tmp_path, monkeypatch):
    """B's scope, stated in the spec: with DOCS_AGENT_DEBUG_DIR unset there
    is no event stream, so behaviour is exactly what it was."""
    monkeypatch.setattr(
        orun.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout='{"prs": [], "jira_issues": []}'),
    )
    monkeypatch.delenv("DOCS_AGENT_DEBUG_DIR", raising=False)

    reasons: list[str] = []
    result = orun.dispatch_subagent(
        "source-collector", {}, dry_run_dir=None, out_reasons=reasons
    )
    assert result == {"prs": [], "jira_issues": []}
    assert reasons == []


# --------------------------------------------------------------------------
# Spec test 5 — the reason inherits the call site's CCE-144 classification
# --------------------------------------------------------------------------


def test_the_reason_is_blind_at_the_source_collector_call_site():
    """`_record_dispatch_reasons(..., ok=False)` is what the source-collector
    call site runs, and it classifies blocking reasons blind by default. No
    new classification code exists for CCE-177, so this is the whole of its
    classification contract."""
    state: dict = {}
    orun._record_dispatch_reasons(
        state, ["output_token_limit_truncated: source-collector"], ok=False
    )
    cr = state["current_run"]
    assert cr["partial"] is True
    assert cr["blind"] is True
    assert cr["blind_reasons"] == ["output_token_limit_truncated: source-collector"]
    assert "output_token_limit_truncated: source-collector" in cr["partial_reasons"]


def test_a_truncated_source_collector_run_exits_1_and_freezes_the_watermark(
    tmp_path, init_host, monkeypatch
):
    """The same reason driven through the real `run()`, end to end: the split
    stream reaches `dispatch_validated`, the refusal lands in
    `partial_reasons`, `blind` flips, the exit code is 1 and the baseline
    does not move."""
    repo = tmp_path
    state_path = init_host({"version": "1", "last_successful_run": {}})

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    base = _git("rev-parse", "HEAD")
    (repo / "f.txt").write_text("c1")
    _git("add", ".")
    _git("commit", "-q", "-m", "c1")
    state_path.write_text(
        json.dumps({"version": "1", "last_successful_run": {"head_sha": base}})
    )

    split_stream = _ndjson(
        [
            _assistant('{"prs": [{"number": 1, "url": "https://x/1"}],'),
            _limit_turn(),
            _assistant(' "jira_issues": []}'),
        ]
    )
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        if list(argv)[:1] == ["claude"]:
            return _FakeCompleted(stdout=split_stream)
        return real_run(argv, **kwargs)

    monkeypatch.setattr(orun.subprocess, "run", fake_run)
    monkeypatch.setenv("DOCS_AGENT_DEBUG_DIR", str(tmp_path.parent / "debug"))

    rc = orun.run(repo, dry_run_dir=None, no_pr=True)

    assert rc == 1, "a source-collector truncation is blind; the run must exit 1"
    cr = json.loads(
        (repo / ".engineering-docs-agent" / "current_run.json").read_text()
    )["current_run"]
    assert cr["blind"] is True, cr
    assert "output_token_limit_truncated: source-collector" in cr["partial_reasons"], cr
    assert "output_token_limit_truncated: source-collector" in cr["blind_reasons"], cr
    written = json.loads(state_path.read_text())
    assert written["last_successful_run"]["head_sha"] == base, written
