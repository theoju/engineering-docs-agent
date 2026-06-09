from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import managed_block as mb  # noqa: E402


def test_append_when_absent_preserves_author_prose():
    existing = "---\ntitle: Architecture\n---\n\n# Architecture\n\nAuthor intro.\n"
    out = mb.upsert_managed_block(existing, "GENERATED")
    assert out.startswith(existing.rstrip("\n") + "\n\n")
    assert mb.START in out and mb.END in out
    assert "GENERATED" in out
    assert out.count(mb.START) == 1 and out.count(mb.END) == 1


def test_replace_preserves_prose_above_and_below():
    existing = f"# Title\n\nABOVE\n\n{mb.START}\nOLD BODY\n{mb.END}\n\nBELOW\n"
    out = mb.upsert_managed_block(existing, "NEW BODY")
    assert "ABOVE" in out and "BELOW" in out
    assert "OLD BODY" not in out
    assert "NEW BODY" in out
    assert out.startswith("# Title\n\nABOVE\n\n")
    assert out.rstrip("\n").endswith("BELOW")
    assert out.count(mb.START) == 1 and out.count(mb.END) == 1


def test_idempotent_same_body():
    existing = "# T\n\nintro\n"
    once = mb.upsert_managed_block(existing, "BODY")
    twice = mb.upsert_managed_block(once, "BODY")
    assert once == twice


def test_append_into_empty_text():
    out = mb.upsert_managed_block("", "BODY")
    assert out == f"{mb.START}\nBODY\n{mb.END}\n"


def test_double_start_raises():
    bad = f"{mb.START}\nx\n{mb.START}\ny\n{mb.END}\n"
    with pytest.raises(ValueError):
        mb.upsert_managed_block(bad, "BODY")


def test_end_before_start_raises():
    bad = f"{mb.END}\nstray\n{mb.START}\nbody\n"
    with pytest.raises(ValueError):
        mb.upsert_managed_block(bad, "BODY")
