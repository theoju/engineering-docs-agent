from __future__ import annotations
import json
import sys
from pathlib import Path

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

FAKES = Path(__file__).parent.parent / "orchestrator" / "fakes"


def test_source_collector_validates_and_parses():
    from contracts import validate_and_parse, SourceCollectorResult

    raw = json.loads((FAKES / "fake_source_collector.json").read_text())
    result, errors = validate_and_parse("source-collector", raw)
    assert errors == []
    assert isinstance(result, SourceCollectorResult)
    assert len(result.prs) == 1
    assert result.partial is False


def test_source_collector_rejects_malformed():
    from contracts import validate_and_parse

    raw = {"prs": "not-a-list", "jira_issues": []}
    result, errors = validate_and_parse("source-collector", raw)
    assert result is None
    assert errors
    assert "schema_invalid" in errors[0]


def test_pr_summarizer_validates_and_parses():
    from contracts import validate_and_parse, PrSummary

    raw = json.loads((FAKES / "fake_pr_summarizer.json").read_text())
    result, errors = validate_and_parse("pr-summarizer", raw)
    assert errors == []
    assert isinstance(result, PrSummary)
    assert result.pr_number == 1
    assert result.error is None


def test_page_author_validates_and_parses():
    from contracts import validate_and_parse, PageAuthorResult

    raw = json.loads((FAKES / "fake_page_author.json").read_text())
    result, errors = validate_and_parse("page-author", raw)
    assert errors == []
    assert isinstance(result, PageAuthorResult)
    assert result.ok is True
