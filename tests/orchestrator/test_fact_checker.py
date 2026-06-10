from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from contracts import validate_and_parse  # noqa: E402

SCHEMAS = Path(__file__).parent.parent.parent / "agents" / "schemas"


def test_fact_checker_contradiction_output_validates():
    raw = {
        "ok": True,
        "verdict": "contradiction",
        "page": "docs/site-src/core/page.md",
        "findings": [
            {
                "claim": "page says partial runs never advance the baseline",
                "source_path": "scripts/runner.py",
                "evidence": "advance happens unconditionally at save_state()",
            }
        ],
    }
    parsed, reasons = validate_and_parse("fact-checker", raw)
    assert reasons == []
    assert parsed.verdict == "contradiction"
    assert parsed.findings[0]["source_path"] == "scripts/runner.py"


def test_fact_checker_minimal_output_validates_with_empty_findings():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "consistent"}
    )
    assert reasons == []
    assert parsed.findings == []


def test_fact_checker_bad_verdict_rejected():
    parsed, reasons = validate_and_parse(
        "fact-checker", {"ok": True, "verdict": "maybe"}
    )
    assert parsed is None
    assert any("schema_invalid" in r for r in reasons)
