"""CCE-122: the fact-checker contract must scope verdicts to behavioral truth
and explicitly exclude citation line/location precision (owned by the
citation_exists lint now)."""

from pathlib import Path

_CONTRACT = (
    Path(__file__).parent.parent.parent / "agents" / "fact-checker.md"
).read_text()


def test_contract_excludes_location_precision():
    lowered = _CONTRACT.lower()
    # Anchor on the load-bearing instruction; deleting it must break this test.
    assert "do not" in lowered and "line number" in lowered
    assert "location precision" in lowered
    assert "citation_exists" in _CONTRACT  # names the lint that owns existence
    # Behavioral checking must remain the job.
    assert "behavioral claim" in lowered
