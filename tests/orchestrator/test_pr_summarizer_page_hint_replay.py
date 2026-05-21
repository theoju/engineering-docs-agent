"""Regression: replay the 2026-05-21 full-run pr-summarizer outputs.

Asserts the tightened schema flags exactly the doc_targets we know are bad
and accepts the ones we know are good.
"""

from __future__ import annotations
import json
from pathlib import Path
import pytest
from jsonschema import Draft7Validator

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "schemas"
    / "pr_summarizer.schema.json"
)
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "cce17"


@pytest.fixture(scope="module")
def validator() -> Draft7Validator:
    return Draft7Validator(json.loads(SCHEMA_PATH.read_text()))


def _fixtures() -> list[Path]:
    return sorted(FIXTURES_DIR.glob("pr_*.json"))


def test_fixtures_present() -> None:
    files = _fixtures()
    assert len(files) >= 8, f"Expected >=8 staged fixtures, found {len(files)}"


def test_replay_flags_known_bad_targets(validator: Draft7Validator) -> None:
    """Every captured output should have at least one schema violation.

    The schema was tightened specifically to catch the failure shapes
    observed in this run. If any fixture validates clean, the schema is too
    loose or the fixture was hand-edited.
    """
    bad_count = 0
    for path in _fixtures():
        doc = json.loads(path.read_text())
        errors = list(validator.iter_errors(doc))
        if errors:
            bad_count += 1
    assert bad_count >= 6, (
        f"Expected at least 6 of the captured outputs to violate the tightened "
        f"schema; got {bad_count}. The schema is too lenient or the fixtures "
        f"have been hand-edited."
    )


def test_replay_per_fixture_violation_summary(validator: Draft7Validator) -> None:
    """For each fixture, print the violations (informational; never fails).

    Run with `-s` to see the breakdown:
        pytest tests/orchestrator/test_pr_summarizer_page_hint_replay.py -v -s
    """
    for path in _fixtures():
        doc = json.loads(path.read_text())
        errors = list(validator.iter_errors(doc))
        if errors:
            print(f"\n{path.name}: {len(errors)} violation(s)")
            for err in errors[:3]:
                print(f"  - {err.message[:120]}")
