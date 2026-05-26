from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from source_map import _glob_to_regex  # noqa: E402


def _m(glob: str, path: str) -> bool:
    return _glob_to_regex(glob).fullmatch(path) is not None


def test_star_is_single_segment():
    assert _m("scripts/*.py", "scripts/a.py")
    assert not _m("scripts/*.py", "scripts/sub/a.py")


def test_double_star_slash_spans_segments():
    assert _m("scripts/**/*.py", "scripts/a.py")
    assert _m("scripts/**/*.py", "scripts/sub/deep/a.py")
    assert _m("**/test_*.py", "test_x.py")
    assert _m("**/test_*.py", "a/b/test_x.py")
    assert not _m("**/test_*.py", "a/b/test_x.py.bak")


def test_trailing_double_star_matches_subtree():
    assert _m("src/auth/**", "src/auth/x.py")
    assert _m("src/auth/**", "src/auth/a/b.py")


def test_question_mark_is_one_non_slash():
    assert _m("a?.py", "ab.py")
    assert not _m("a?.py", "a/.py")


def test_literals_are_escaped():
    assert _m("a.b", "a.b")
    assert not _m("a.b", "axb")
    assert _m("scripts/orchestrator_runner.py", "scripts/orchestrator_runner.py")
    assert not _m("scripts/orchestrator_runner.py", "scripts/orchestrator_runnerXpy")
    assert not _m("a+b", "aab")


def test_no_partial_match():
    assert not _m("scripts/*.py", "x/scripts/a.py")
    assert not _m("scripts/*.py", "scripts/a.py.bak")
